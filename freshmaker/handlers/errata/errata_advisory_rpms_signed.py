# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Chenxiong Qi <cqi@redhat.com>
# Written by Jan Kaluza <jkaluza@redhat.com>

import json
import koji
import requests
import yaml
import os

from six.moves import cStringIO
from six.moves import configparser

from freshmaker import conf, db, log
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.events import ODCSComposeStateChangeEvent
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState
from freshmaker.models import Event, Compose
from freshmaker.consumer import work_queue_put
from freshmaker.utils import (
    krb_context, retry, get_rebuilt_nvr, temp_dir, clone_distgit_repo)
from freshmaker.odcsclient import create_odcs_client

from odcs.common.types import COMPOSE_STATES


class ErrataAdvisoryRPMsSignedHandler(ContainerBuildHandler):
    """
    Rebuilds all Docker images which contain packages from the Errata
    advisory.
    """

    name = 'ErrataAdvisoryRPMsSignedHandler'

    # Used to generate incremental compose id in dry run mode.
    _FAKE_COMPOSE_ID = 0

    def can_handle(self, event):
        return isinstance(event, ErrataAdvisoryRPMsSignedEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        Rebuilds all Docker images which contain packages from the Errata
        advisory.
        """

        if event.dry_run:
            self.force_dry_run()

        # In case we run in DRY_RUN mode, we need to initialize
        # FAKE_COMPOSE_ID to the id of last ODCS compose to give the IDs
        # increasing and unique even between Freshmaker restarts.
        if self.dry_run:
            ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID = \
                Compose.get_lowest_compose_id(db.session) - 1
            if ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID >= 0:
                ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID = -1

        self.event = event

        # Generate the Database representation of `event`, it can be
        # triggered by user, we want to track what happened

        db_event = Event.get_or_create(
            db.session, event.msg_id, event.search_key, event.__class__,
            released=False, manual=event.manual)
        db.session.commit()
        self.set_context(db_event)

        # Check if we are allowed to build this advisory.
        if not event.manual and not self.allow_build(
                ArtifactType.IMAGE,
                advisory_name=event.advisory.name,
                advisory_security_impact=event.advisory.security_impact,
                advisory_highest_cve_severity=event.advisory.highest_cve_severity,
                advisory_product_short_name=event.advisory.product_short_name,
                dry_run=self.dry_run):
            msg = ("Errata advisory {0} is not allowed by internal policy "
                   "to trigger rebuilds.".format(event.advisory.errata_id))
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        # Get and record all images to rebuild based on the current
        # ErrataAdvisoryRPMsSignedEvent event.
        batches = self._find_images_to_rebuild(db_event.search_key)
        builds = self._record_batches(batches, event)

        if not builds:
            msg = 'No container images to rebuild for advisory %r' % event.advisory.name
            self.log_info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

        if all([build.state == ArtifactBuildState.FAILED.value
                for build in builds.values()]):
            db_event.transition(
                EventState.COMPLETE,
                "No container images to rebuild, all are in failed state.")
            db.session.commit()
            return []

        if event.advisory.state != 'SHIPPED_LIVE':
            # If freshmaker is configured to rebuild images only when advisory
            # moves to SHIPPED_LIVE state, there is no need to generate new
            # composes for rebuild as all signed RPMs should already be
            # available from official YUM repositories.
            #
            # Generate the ODCS compose with RPMs from the current advisory.
            repo_urls = self._prepare_yum_repos_for_rebuilds(db_event)
            self.log_info(
                "Following repositories will be used for the rebuild:")
            for url in repo_urls:
                self.log_info("   - %s", url)

        # Log what we are going to rebuild
        self._check_images_to_rebuild(db_event, builds)

        if event.advisory.state == 'SHIPPED_LIVE':
            # As mentioned above, no need to wait for the event of new compose
            # is generated in ODCS, so we can start to rebuild the first batch
            # from here immediately.
            self.start_to_build_images(
                db_event.get_image_builds_in_first_batch(db.session))

        if event.manual:
            msg = 'Base images are scheduled to be rebuilt due to manual rebuild.'
        else:
            msg = ('Waiting for composes to finish in order to start to '
                   'schedule base images for rebuild.')
        db_event.transition(EventState.BUILDING, msg)

        return []

    def _should_generate_yum_repourls(self, repository, branch, commit):
        """
        Returns False if Koji/OSBS can build container without Freshmaker
        generating yum_repourls for content sets.

        This returns False if both content_sets.yml and container.yaml exists
        and the "pulp_repos" in container.yaml is set to True.
        """
        if "/" in repository:
            namespace, name = repository.split("/")
        else:
            namespace = "rpms"
            name = repository

        prefix = "freshmaker-%s-%s-%s" % (namespace, name, commit)
        with temp_dir(prefix=prefix) as repodir:
            clone_distgit_repo(namespace, name, repodir, commit=commit,
                               ssh=False, logger=log)

            content_sets_path = os.path.join(repodir, "content_sets.yml")
            if not os.path.exists(content_sets_path):
                self.log_debug("Should generate Pulp repo, %s does not exist.",
                               content_sets_path)
                return True

            container_path = os.path.join(repodir, "container.yaml")
            if not os.path.exists(container_path):
                self.log_debug("Should generate Pulp repo, %s does not exist.",
                               container_path)
                return True

            with open(container_path, 'r') as f:
                container_yaml = yaml.load(f)

            if ("compose" not in container_yaml or
                    "pulp_repos" not in container_yaml["compose"] or
                    not container_yaml["compose"]["pulp_repos"]):
                self.log_debug(
                    "Should generate Pulp repo, pulp_repos not enabled in %s.",
                    container_path)
                return True

            return False

    def _fake_odcs_new_compose(
            self, compose_source, tag, packages=None, results=[]):
        """
        Fake KojiSession.buildContainer method used dry run mode.

        Logs the arguments and emits ErrataAdvisoryRPMsSignedHandler of
        "done" state.

        :rtype: dict
        :return: Fake odcs.new_compose dict.
        """
        self.log_info("DRY RUN: Calling fake odcs.new_compose with args: %r",
                      (compose_source, tag, packages, results))

        # Generate the new_compose dict.
        ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID -= 1
        new_compose = {}
        new_compose['id'] = ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID
        new_compose['result_repofile'] = "http://localhost/%d.repo" % (
            new_compose['id'])
        new_compose['state'] = COMPOSE_STATES['done']
        if results:
            new_compose['results'] = ['boot.iso']

        # Generate and inject the ODCSComposeStateChangeEvent event.
        event = ODCSComposeStateChangeEvent(
            "fake_compose_msg", new_compose)
        event.dry_run = True
        self.log_info("Injecting fake event: %r", event)
        work_queue_put(event)

        return new_compose

    def _prepare_yum_repos_for_rebuilds(self, db_event):
        repo_urls = []
        db_composes = []

        compose = self._prepare_yum_repo(db_event)
        db_composes.append(Compose(odcs_compose_id=compose['id']))
        db.session.add(db_composes[-1])
        repo_urls.append(compose['result_repofile'])

        for dep_event in db_event.find_dependent_events():
            compose = self._prepare_yum_repo(dep_event)
            db_composes.append(Compose(odcs_compose_id=compose['id']))
            db.session.add(db_composes[-1])
            repo_urls.append(compose['result_repofile'])

        # commit all new composes
        db.session.commit()

        for build in db_event.builds:
            build.add_composes(db.session, db_composes)
        db.session.commit()

        # Remove duplicates from repo_urls.
        return list(set(repo_urls))

    def _prepare_yum_repo(self, db_event):
        """
        Request a compose from ODCS for builds included in Errata advisory

        Run a compose in ODCS to contain required RPMs for rebuilding images
        later.

        :param Event db_event: current event being handled that contains errata
            advisory to get builds containing updated RPMs.
        :return: a mapping returned from ODCS that represents the request
            compose.
        :rtype: dict
        """
        errata_id = int(db_event.search_key)

        packages = []
        errata = Errata()
        builds = errata.get_builds(errata_id)
        compose_source = None
        for nvr in builds:
            packages += self._get_packages_for_compose(nvr)
            source = self._get_compose_source(nvr)
            if compose_source and compose_source != source:
                # TODO: Handle this by generating two ODCS composes
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value, "Packages for errata "
                    "advisory %d found in multiple different tags."
                    % (errata_id))
                return
            else:
                compose_source = source

        if compose_source is None:
            db_event.builds_transition(
                ArtifactBuildState.FAILED.value, 'None of builds %s of '
                'advisory %d is the latest build in its candidate tag.'
                % (builds, errata_id))
            return

        self.log_info('Generating new compose for rebuild: '
                      'source: %s, source type: %s, packages: %s',
                      compose_source, 'tag', packages)

        if not self.dry_run:
            with krb_context():
                new_compose = create_odcs_client().new_compose(
                    compose_source, 'tag', packages=packages,
                    sigkeys=conf.odcs_sigkeys, flags=["no_deps"])
        else:
            new_compose = self._fake_odcs_new_compose(
                compose_source, 'tag', packages=packages)

        return new_compose

    def _prepare_pulp_repo(self, db_event, content_sets):
        """
        Prepares .repo file containing the repositories matching
        the content_sets by creating new ODCS compose of PULP type.

        This currently blocks until the compose is done or failed.

        :param db_event: models.Event instance associated with this build.
        :param list content_sets: List of content sets.
        :rtype: dict
        :return: ODCS compose dictionary.
        """
        self.log_info('Generating new PULP type compose for content_sets: %r',
                      content_sets)

        odcs = create_odcs_client()
        if not self.dry_run:
            with krb_context():
                new_compose = odcs.new_compose(
                    ' '.join(content_sets), 'pulp')

                # Pulp composes in ODCS takes just few seconds, because ODCS
                # only generates the .repo file after single query to Pulp.
                # TODO: Freshmaker is currently not designed to handle
                # multiple ODCS composes per rebuild Event and since these
                # composes are done in no-time normally, it is OK here to
                # block. It would still be nice to redesign that part of
                # Freshmaker to do things "right".
                # This is tracked here: https://pagure.io/freshmaker/issue/114
                @retry(timeout=60, interval=2)
                def wait_for_compose(compose_id):
                    ret = odcs.get_compose(compose_id)
                    if ret["state_name"] == "done":
                        return True
                    elif ret["state_name"] == "failed":
                        return False
                    self.log_info("Waiting for Pulp compose to finish: %r",
                                  ret)
                    raise Exception("ODCS compose not finished.")

                done = wait_for_compose(new_compose["id"])
                if not done:
                    db_event.builds_transition(
                        ArtifactBuildState.FAILED.value, "Cannot generate "
                        "ODCS PULP compose for content_sets %r"
                        % (content_sets))
        else:
            new_compose = self._fake_odcs_new_compose(
                content_sets, 'pulp')

        return new_compose

    def _get_base_image_build_target(self, image):
        dockerfile = image.dockerfile
        image_build_conf_url = dockerfile['content_url'].replace(
            dockerfile['filename'], 'image-build.conf')
        response = requests.get(image_build_conf_url)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            log.error(
                'Cannot get image-build.conf from %s.', image_build_conf_url)
            log.exception('Server response: %s', e)
            return None
        config_buf = cStringIO(response.content)
        config = configparser.RawConfigParser()
        try:
            config.readfp(config_buf)
        except configparser.MissingSectionHeaderError:
            return None
        finally:
            config_buf.close()
        try:
            return config.get('image-build', 'target')
        except (configparser.NoOptionError, configparser.NoSectionError):
            log.exception('image-build.conf does not have option target.')
            return None

    def _get_base_image_build_tag(self, build_target):
        with koji_service(
                conf.koji_profile, log, dry_run=self.dry_run) as session:
            target_info = session.get_build_target(build_target)
            if target_info is None:
                return target_info
            else:
                return target_info['build_tag_name']

    def _request_boot_iso_compose(self, image):
        """Request boot.iso compose for base image"""
        target = self._get_base_image_build_target(image)
        if not target:
            return None
        build_tag = self._get_base_image_build_tag(target)
        if not build_tag:
            return None

        if self.dry_run:
            new_compose = self._fake_odcs_new_compose(
                build_tag, 'tag', results=['boot.iso'])
        else:
            with krb_context():
                new_compose = create_odcs_client().new_compose(
                    build_tag, 'tag', results=['boot.iso'])
        return new_compose

    def _get_packages_for_compose(self, nvr):
        """Get RPMs of current build NVR

        :param str nvr: build NVR.
        :return: list of RPM names built from given build.
        :rtype: list
        """
        with koji_service(
                conf.koji_profile, log, dry_run=self.dry_run) as session:
            rpms = session.get_build_rpms(nvr)
        return list(set([rpm['name'] for rpm in rpms]))

    def _get_compose_source(self, nvr):
        """Get tag from which to collect packages to compose
        :param str nvr: build NVR used to find correct tag.
        :return: found tag. None is returned if build is not the latest build
            of found tag.
        :rtype: str
        """
        with koji_service(
                conf.koji_profile, log, dry_run=self.dry_run) as service:
            # Get the list of *-candidate tags, because packages added into
            # Errata should be tagged into -candidate tag.
            tags = service.session.listTags(nvr)
            candidate_tags = [tag['name'] for tag in tags
                              if tag['name'].endswith('-candidate')]

            # Candidate tags may include unsigned packages and ODCS won't
            # allow generating compose from them, so try to find out final
            # version of candidate tag (without the "-candidate" suffix).
            final_tags = []
            for candidate_tag in candidate_tags:
                final = candidate_tag[:-len("-candidate")]
                final_tags += [tag['name'] for tag in tags
                               if tag['name'] == final]

            # Prefer final tags over candidate tags.
            tags_to_try = final_tags + candidate_tags
            for tag in tags_to_try:
                latest_build = service.session.listTagged(
                    tag,
                    latest=True,
                    package=koji.parse_NVR(nvr)['name'])
                if latest_build and latest_build[0]['nvr'] == nvr:
                    self.log_info("Package %r is latest version in tag %r, "
                                  "will use this tag", nvr, tag)
                    return tag
                elif not latest_build:
                    self.log_info("Could not find package %r in tag %r, "
                                  "skipping this tag", nvr, tag)
                else:
                    self.log_info("Package %r is not he latest in the tag %r ("
                                  "latest is %r), skipping this tag",
                                  nvr, tag, latest_build[0]['nvr'])

    def _check_images_to_rebuild(self, db_event, builds):
        """
        Checks the images to rebuild and logs them using self.log_info(...).
        :param Event db_event: Database Event associated with images.
        :param builds dict: list of docker images to build as returned by
            _find_images_to_rebuild(...).
        """
        self.log_info('Found container images to rebuild in following order:')
        batch = 0
        printed = []
        while (len(printed) != len(builds.values()) or
               len(printed) != len(db_event.builds)):
            self.log_info('   Batch %d:', batch)
            old_printed_count = len(printed)
            for build in builds.values():
                # Print build only if:
                # a) It depends on other build, but this dependency has not
                #    been printed yet or ...
                # b) ... it does not depend on other build and we are printing
                #   batch 0 - this handles the base images
                # In call cases, print only builds which have not been printed
                # so far.
                if (build.original_nvr not in printed and
                        ((build.dep_on and build.dep_on.original_nvr in printed) or
                         (not build.dep_on and batch == 0))):
                    args = json.loads(build.build_args)
                    based_on = "based on %s" % args["parent"] \
                        if args["parent"] else "base image"
                    self.log_info(
                        '      - %s#%s (%s)' %
                        (args["repository"], args["commit"], based_on))
                    printed.append(build.original_nvr)

            # Nothing has been printed, that means the dependencies between
            # images are not OK and we would loop forever. Instead of that,
            # print error and stop the rebuild.
            if old_printed_count == len(printed):
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value,
                    "No image to be built in batch %d." % (batch))
                self.log_error("Dumping the builds:")
                for build in builds.values():
                    self.log_error("   %r", build.original_nvr)
                self.log_error("Printed ones:")
                for p in printed:
                    self.log_error("   %r", p)
                break

            batch += 1

    def _record_batches(self, batches, event, builds=None):
        """
        Records the images from batches to database.

        :param batches list: Output of LightBlue._find_images_to_rebuild(...).
        :param event ErrataAdvisoryRPMsSignedEvent: The event this handler
            is currently handling.
        :param builds dict: mappings from docker image build NVR to
            corresponding ArtifactBuild object, e.g.
            ``{brew_build_nvr: ArtifactBuild, ...}``. Previous builds returned
            from this method can be passed to this call to be extended by
            adding a new mappings after docker image is stored into database.
            For the first time to call this method, builds could be None.
        :return: a mapping between docker image build NVR and
            corresponding ArtifactBuild object representing a future rebuild of
            that docker image. It is extended by including those docker images
            stored into database.
        :rtype: dict
        """
        # Used as tmp dict with {brew_build_nvr: ArtifactBuild, ...} mapping.
        builds = builds or {}

        for batch in batches:
            for image in batch:
                nvr = image["brew"]["build"]
                if nvr in builds:
                    self.log_debug("Skipping recording build %s, "
                                   "it is already in db", nvr)
                    continue
                self.log_debug("Recording %s", nvr)
                parent_nvr = image["parent"]["brew"]["build"] \
                    if "parent" in image and image["parent"] else None
                dep_on = builds[parent_nvr] if parent_nvr in builds else None

                # If this container image depends on another container image
                # we are going to rebuild, use the new NVR of that image
                # as a dependency instead of the original one.
                if dep_on:
                    parent_nvr = dep_on.rebuilt_nvr

                if "error" in image and image["error"]:
                    state_reason = image["error"]
                    state = ArtifactBuildState.FAILED.value
                elif dep_on and dep_on.state == ArtifactBuildState.FAILED.value:
                    # If this artifact build depends on a build which cannot
                    # be built by Freshmaker, mark this one as failed too.
                    state_reason = "Cannot build artifact, because its " \
                        "dependency cannot be built."
                    state = ArtifactBuildState.FAILED.value
                else:
                    state_reason = ""
                    state = ArtifactBuildState.PLANNED.value

                rebuilt_nvr = get_rebuilt_nvr(ArtifactType.IMAGE.value, nvr)
                image_name = koji.parse_NVR(image["brew"]["build"])["name"]

                build = self.record_build(
                    event, image_name, ArtifactType.IMAGE,
                    dep_on=dep_on,
                    state=ArtifactBuildState.PLANNED.value,
                    original_nvr=nvr,
                    rebuilt_nvr=rebuilt_nvr)

                build.transition(state, state_reason)

                build_args = {}
                build_args["repository"] = image["repository"]
                build_args["commit"] = image["commit"]
                build_args["parent"] = parent_nvr
                build_args["target"] = image["target"]
                build_args["branch"] = image["git_branch"]
                build.build_args = json.dumps(build_args)

                db.session.commit()

                if state != ArtifactBuildState.FAILED.value:
                    # Store odcs pulp compose to build
                    build_pulp_compose = self._should_generate_yum_repourls(
                        image["repository"], image["git_branch"], image["commit"])
                    if build_pulp_compose:
                        compose = self._prepare_pulp_repo(
                            build.event, image["content_sets"])
                        db_compose = Compose(odcs_compose_id=compose['id'])
                        db.session.add(db_compose)
                        db.session.commit()
                        build.add_composes(db.session, [db_compose])

                    # TODO: uncomment following code after boot.iso compose is
                    # deployed in ODCS server.
#                    if image.is_base_image:
#                        compose = self._request_boot_iso_compose(image)
#                        if compose is None:
#                            log.error(
#                                'Failed to request boot.iso compose for base '
#                                'image %s.', nvr)
#                            build.transition(
#                                ArtifactBuildState.FAILED.value,
#                                'Cannot rebuild this base image because failed to '
#                                'requeset boot.iso compose.')
#                            # FIXME: mark all builds associated with build.event FAILED?
#                        else:
#                            db_compose = Compose(odcs_compose_id=compose['id'])
#                            db.session.add(db_compose)
#                            db.session.commit()
#                            build.add_composes(db.session, [db_compose])

                builds[nvr] = build

        return builds

    def _filter_out_not_allowed_builds(self, image):
        """
        Helper method for _find_images_to_rebuild(...) to filter
        out all images which are not allowed to build by configuration.

        :param ContainerImage image: Image to be checked.
        :rtype: bool
        :return: True when image should be filtered out.
        """

        image_name = koji.parse_NVR(image["brew"]["build"])['name']

        if not self.event.manual and not self.allow_build(
                ArtifactType.IMAGE, image_name=image_name):
            self.log_info("Skipping rebuild of image %s, not allowed by "
                          "configuration", image_name)
            return True
        return False

    def _find_images_to_rebuild(self, errata_id):
        """
        Finds docker rebuild images from each build added to specific Errata
        advisory.

        Found images are yielded in proper rebuild order from base images to
        leaf images through the docker build dependnecy chain.

        :param int errata_id: Errata ID.
        """
        errata = Errata()
        errata_id = int(errata_id)

        # Use the errata_id to find out Pulp repository IDs from Errata Tool
        # and furthermore get content_sets from Pulp where signed RPM will end
        # up eventually when advisories are shipped.
        pulp_repo_ids = list(set(errata.get_pulp_repository_ids(errata_id)))

        pulp = Pulp(server_url=conf.pulp_server_url,
                    username=conf.pulp_username,
                    password=conf.pulp_password)
        content_sets = pulp.get_content_set_by_repo_ids(pulp_repo_ids)

        self.log_info('RPMs from advisory ends up in following content sets: '
                      '%s', content_sets)

        # Query images from LightBlue by signed RPM's srpm name and found
        # content sets
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key)

        # Check if we are allowed to rebuild unpublished images and clear
        # published and release_category if so.
        if self.allow_build(
                ArtifactType.IMAGE, advisory_name=self.event.advisory.name,
                advisory_security_impact=self.event.advisory.security_impact,
                advisory_highest_cve_severity=self.event.advisory.highest_cve_severity,
                advisory_product_short_name=self.event.advisory.product_short_name,
                published=True, dry_run=self.dry_run):
            published = True
            release_category = "Generally Available"
        else:
            published = None
            release_category = None

        # For each RPM package in Errata advisory, find the SRPM package name.
        srpm_names = set()
        nvrs = errata.get_builds(errata_id)
        for nvr in nvrs:
            srpm_name = koji.parse_NVR(nvr)['name']
            srpm_names.add(srpm_name)

        # For each SRPM name, find out all the containers which include
        # this SRPM name.
        self.log_info(
            "Going to find all the container images to rebuild as "
            "result of %r update.", srpm_names)
        batches = lb.find_images_to_rebuild(
            srpm_names, content_sets,
            filter_fnc=self._filter_out_not_allowed_builds,
            published=published, release_category=release_category)
        return batches

    def _find_build_srpm_name(self, build_nvr):
        """Find srpm name from a build"""
        with koji_service(
                conf.koji_profile, log, dry_run=self.dry_run) as session:
            rpm_infos = session.get_build_rpms(build_nvr, arches='src')
            if not rpm_infos:
                raise ValueError(
                    'Build {} does not have a SRPM, although this should not '
                    'happen in practice.'.format(build_nvr))
            return rpm_infos[0]['name']
