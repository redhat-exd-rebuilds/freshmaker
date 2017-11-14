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

from freshmaker import conf, db, log
from freshmaker import messaging
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.events import ODCSComposeStateChangeEvent
from freshmaker.handlers import BaseHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.models import Event
from freshmaker.consumer import work_queue_put
from freshmaker.utils import krb_context, retry, get_rebuilt_nvr

from odcs.client.odcs import ODCS
from odcs.client.odcs import AuthMech
from odcs.common.types import COMPOSE_STATES


class ErrataAdvisoryRPMsSignedHandler(BaseHandler):
    """
    Rebuilds all Docker images which contain packages from the Errata
    advisory.
    """

    name = 'ErrataAdvisoryRPMsSignedHandler'

    # Used to generate incremental compose id in dry run mode.
    _FAKE_COMPOSE_ID = 1

    def can_handle(self, event):
        return isinstance(event, ErrataAdvisoryRPMsSignedEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        Rebuilds all Docker images which contain packages from the Errata
        advisory.
        """

        self.event = event

        # Check if we are allowed to build this advisory.
        if not event.manual and not self.allow_build(
                ArtifactType.IMAGE, advisory_name=event.errata_name,
                advisory_security_impact=event.security_impact):
            msg = 'Errata advisory {0} not allowed to trigger ' \
                  'rebuilds.'.format(event.errata_id)
            log.info(msg)
            return []

        # Generate the Database representation of `event`.
        db_event = Event.get_or_create(
            db.session, event.msg_id, event.search_key, event.__class__,
            released=False, manual=event.manual)
        db.session.commit()
        self.set_context(db_event)

        # Get and record all images to rebuild based on the current
        # ErrataAdvisoryRPMsSignedEvent event.
        builds = {}
        for batches in self._find_images_to_rebuild(db_event.search_key):
            builds = self._record_batches(batches, event, builds)

        if not builds:
            log.info('No container images to rebuild for advisory %r',
                     event.errata_name)
            return []

        # Generate the ODCS compose with RPMs from the current advisory.
        repo_urls = []
        repo_urls.append(self._prepare_yum_repo(db_event))  # noqa

        # Find out extra events we want to include. These are advisories
        # which are not released yet and touches some Docker images which
        # are shared with the initial list of docker images we are going to
        # rebuild.
        # If we For example have NSS Errata advisory and httpd advisory, we
        # need to rebuild some Docker images with both NSS and httpd
        # advisories.
        # We also want to search for extra events recursively, because there
        # might for example be zlib advisory, and we want to include this zlib
        # advisory when rebuilding NSS when rebuilding httpd... :)
        prev_builds_count = 0
        seen_extra_events = []

        # We stop when we did not find more docker images to rebuild and
        # therefore cannot find more extra events.
        while prev_builds_count != len(builds):
            prev_builds_count = len(builds)
            extra_events = self._find_events_to_include(db_event, builds)
            log.info("Extra events: %r", extra_events)
            for ev in extra_events:
                if ev in seen_extra_events:
                    continue
                seen_extra_events.append(ev)
                db_event.add_event_dependency(db.session, ev)
                for batches in self._find_images_to_rebuild(ev.search_key):
                    builds = self._record_batches(batches, event, builds)
                repo_urls.append(self._prepare_yum_repo(ev))

        db.session.commit()
        # Remove duplicates from repo_urls.
        repo_urls = list(set(repo_urls))

        # Log what we are going to rebuild
        self._check_images_to_rebuild(db_event, builds)
        log.info("Following repositories will be used for the rebuild:")
        for url in repo_urls:
            log.info("   - %s", url)

        # TODO: Once https://pagure.io/freshmaker/issue/137 is fixed, this
        # should be moved to models.Event.transition().
        messaging.publish('event.state.changed', db_event.json())

        return []

    def _fake_odcs_new_compose(self, compose_source, tag, packages=None):
        """
        Fake KojiSession.buildContainer method used dry run mode.

        Logs the arguments and emits ErrataAdvisoryRPMsSignedHandler of
        "done" state.

        :rtype: dict
        :return: Fake odcs.new_compose dict.
        """
        log.info("DRY RUN: Calling fake odcs.new_compose with args: %r",
                 (compose_source, tag, packages))

        # Generate the new_compose dict.
        ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID += 1
        new_compose = {}
        new_compose['id'] = ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID
        new_compose['result_repofile'] = "http://localhost/%d.repo" % (
            new_compose['id'])
        new_compose['state'] = COMPOSE_STATES['done']

        # Generate and inject the ODCSComposeStateChangeEvent event.
        event = ODCSComposeStateChangeEvent(
            "fake_compose_msg", new_compose)
        log.info("Injecting fake event: %r", event)
        work_queue_put(event)

        return new_compose

    def _prepare_yum_repo(self, db_event):
        """
        Prepare a yum repo for rebuild

        Run a compose in ODCS to contain required RPMs for rebuilding images
        later.
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

        log.info('Generate new compose for rebuild: '
                 'source: %s, source type: %s, packages: %s',
                 compose_source, 'tag', packages)

        odcs = ODCS(conf.odcs_server_url, auth_mech=AuthMech.Kerberos,
                    verify_ssl=conf.odcs_verify_ssl)
        if not conf.dry_run:
            with krb_context():
                new_compose = odcs.new_compose(
                    compose_source, 'tag', packages=packages,
                    sigkeys=conf.odcs_sigkeys, flags=["no_deps"])
        else:
            new_compose = self._fake_odcs_new_compose(
                compose_source, 'tag', packages=packages)

        compose_id = new_compose['id']
        yum_repourl = new_compose['result_repofile']

        rebuild_event = Event.get(db.session, db_event.message_id)
        rebuild_event.compose_id = compose_id
        db.session.commit()

        return yum_repourl

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
        log.info('Generating new PULP type compose for content_sets: %r',
                 content_sets)

        odcs = ODCS(conf.odcs_server_url, auth_mech=AuthMech.Kerberos,
                    verify_ssl=conf.odcs_verify_ssl)
        if not conf.dry_run:
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
                    log.info("Waiting for Pulp compose to finish: %r", ret)
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

    def _get_packages_for_compose(self, nvr):
        """Get RPMs of current build NVR

        :param str nvr: build NVR.
        :return: list of RPM names built from given build.
        :rtype: list
        """
        with koji_service(conf.koji_profile, log) as session:
            rpms = session.get_build_rpms(nvr)
        return list(set([rpm['name'] for rpm in rpms]))

    def _get_compose_source(self, nvr):
        """Get tag from which to collect packages to compose
        :param str nvr: build NVR used to find correct tag.
        :return: found tag. None is returned if build is not the latest build
            of found tag.
        :rtype: str
        """
        with koji_service(conf.koji_profile, log) as service:
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
                    log.info("Package %r is latest version in tag %r, "
                             "will use this tag", nvr, tag)
                    return tag
                elif not latest_build:
                    log.info("Could not find package %r in tag %r, "
                             "skipping this tag", nvr, tag)
                else:
                    log.info("Package %r is not he latest in the tag %r ("
                             "latest is %r), skipping this tag", nvr, tag,
                             latest_build[0]['nvr'])

    def _check_images_to_rebuild(self, db_event, builds):
        """
        Checks the images to rebuild and logs them using log.info(...).
        :param Event db_event: Database Event associated with images.
        :param builds dict: list of docker images to build as returned by
            _find_images_to_rebuild(...).
        """
        log.info('Found docker images to rebuild in following order:')
        batch = 0
        printed = []
        while (len(printed) != len(builds.values()) or
               len(printed) != len(db_event.builds)):
            log.info('   Batch %d:', batch)
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
                    log.info('      - %s#%s (%s)' %
                             (args["repository"], args["commit"], based_on))
                    printed.append(build.original_nvr)

            # Nothing has been printed, that means the dependencies between
            # images are not OK and we would loop forever. Instead of that,
            # print error and stop the rebuild.
            if old_printed_count == len(printed):
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value,
                    "No image to be built in batch %d." % (batch))
                log.error("Dumping the builds:")
                for build in builds.values():
                    log.error("   %r", build.original_nvr)
                log.error("Printed ones:")
                for p in printed:
                    log.error("   %r", p)
                break

            batch += 1

    def _find_events_to_include(self, db_event, builds):
        """
        Find out all unreleased events which built some image which is also
        planned to be built as part of current image rebuild.

        :param db_event Event: Database representation of
            ErrataAdvisoryRPMsSignedEvent.
        :param builds dict: list of docker images to build as returned by
            _find_images_to_rebuild(...).
        """
        events_to_include = []
        for ev in Event.get_unreleased(db.session):
            for build in ev.builds:
                # Skip non IMAGE builds
                if (build.type != ArtifactType.IMAGE.value or
                        ev.message_id == db_event.message_id):
                    continue

                if build.name in builds:
                    events_to_include.append(ev)
                    break

        return events_to_include

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
                    log.debug("Skipping recording build %s, "
                              "it is already in db", nvr)
                    continue
                log.debug("Recording %s", nvr)
                parent_nvr = image["parent"]["brew"]["build"] \
                    if image["parent"] else None
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

                compose = self._prepare_pulp_repo(event, image["content_sets"])

                build_args = {}
                build_args["repository"] = image["repository"]
                build_args["commit"] = image["commit"]
                build_args["parent"] = parent_nvr
                build_args["target"] = image["target"]
                build_args["branch"] = image["git_branch"]
                build_args["odcs_pulp_compose_id"] = compose["id"]
                build.build_args = json.dumps(build_args)
                db.session.commit()

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
            log.info("Skipping rebuild of image %s, not allowed by "
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

        log.info('RPM will end up within content sets %s', content_sets)

        # Query images from LightBlue by signed RPM's srpm name and found
        # content sets
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key)

        # For each RPM package in Errata advisory, find Docker images
        # containing this package and record those images into database.
        nvrs = errata.get_builds(errata_id)
        for nvr in nvrs:
            # Container images builds end with ".tar.gz", so do not treat
            # them as RPMs here.
            if not nvr.endswith(".tar.gz"):
                srpm_name = self._find_build_srpm_name(nvr)
                batches = lb.find_images_to_rebuild(
                    srpm_name, content_sets,
                    filter_fnc=self._filter_out_not_allowed_builds)
                yield batches
            else:
                log.info("Skipping unsupported Errata build type: %s.", nvr)

    def _find_build_srpm_name(self, build_nvr):
        """Find srpm name from a build"""
        with koji_service(conf.koji_profile, log) as session:
            rpm_infos = session.get_build_rpms(build_nvr, arches='src')
            if not rpm_infos:
                raise ValueError(
                    'Build {} does not have a SRPM, although this should not '
                    'happen in practice.'.format(build_nvr))
            return rpm_infos[0]['name']
