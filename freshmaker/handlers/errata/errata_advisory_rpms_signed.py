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
import time

from itertools import chain

from freshmaker import conf
from freshmaker import log
from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import BaseHandler
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.models import Event

from odcs.client.odcs import ODCS
from odcs.client.odcs import AuthMech


class ErrataAdvisoryRPMsSignedHandler(BaseHandler):
    """
    Rebuilds all Docker images which contain packages from the Errata
    advisory.
    """

    name = 'ErrataAdvisoryRPMsSignedHandler'

    def can_handle(self, event):
        return isinstance(event, ErrataAdvisoryRPMsSignedEvent)

    def handle(self, event):
        """
        Rebuilds all Docker images which contain packages from the Errata
        advisory.
        """

        # Check if we are allowed to build this advisory.
        if not self.allow_build(
                ArtifactType.IMAGE, advisory_name=event.errata_name,
                advisory_security_impact=event.security_impact):
            log.info("Errata advisory %s not allowed to trigger rebuilds.",
                     event.errata_name)
            return []

        # Generate the Database representation of `event`.
        db_event = Event.get_or_create(
            db.session, event.msg_id, event.search_key, event.__class__,
            released=False)
        db.session.commit()

        # Get and record all images to rebuild based on the current
        # ErrataAdvisoryRPMsSignedEvent event.
        builds = self._record_images_to_rebuild(db_event, event)
        if not builds:
            log.info('Not found docker images to rebuild.')
            return []

        # Generate the ODCS compose with RPMs from the current advisory.
        repo_urls = []
        repo_urls.append(self._prepare_yum_repo(event))  # noqa

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
                builds = self._record_images_to_rebuild(ev, event, builds)
                repo_urls.append(self._prepare_yum_repo(ev))

        # Remove duplicates from repo_urls.
        repo_urls = list(set(repo_urls))

        # Log what we are going to rebuild
        self._log_images_to_rebuild(builds)
        log.info("Following repositories will be used for the rebuild:")
        for url in repo_urls:
            log.info("   - %s", url)

        # TODO: Rebuild first batch.

        return []

    def _prepare_yum_repo(self, db_event):
        """
        Prepare a yum repo for rebuild

        Run a compose in ODCS to contain required RPMs for rebuilding images
        later.
        """

        errata_id = int(db_event.search_key)

        packages = []
        errata = Errata(conf.errata_tool_server_url)
        builds = errata.get_builds(errata_id)
        compose_source = None
        for nvr in builds:
            packages += self._get_packages_for_compose(nvr)
            source = self._get_compose_source(nvr)
            if compose_source and compose_source != source:
                # TODO: Handle this by generating two ODCS composes
                log.error("Packages for errata advisory %d found in multiple "
                          "different tags", errata_id)
                return
            else:
                compose_source = source

        odcs = ODCS(conf.odcs_server_url, auth_mech=AuthMech.Kerberos,
                    verify_ssl=conf.odcs_verify_ssl)

        if compose_source is None:
            log.error('Builds for errata %d are not the latest build in its '
                      'all tags.', errata_id)
            return

        log.info('Generate new compose for rebuild: '
                 'source: %s, source type: %s, packages: %s',
                 compose_source, 'tag', packages)

        new_compose = odcs.new_compose(compose_source,
                                       'tag',
                                       packages=packages)
        compose_id = new_compose['id']

        log.info('Waiting for ODCS to finish the compose: %d', compose_id)

        while True:
            time.sleep(1)

            new_compose = odcs.get_compose(compose_id)
            state = new_compose['state']
            if state == 0:  # waiting for generating compose
                log.info('Waiting for generating new compose')
            elif state == 1:  # generating in progress
                log.info('ODCS is generating the compose')
            elif state == 4:  # Failed to generate compose
                log.error('ODCS fails to generate compose: %d', compose_id)
                log.error('Please consult ODCS to see what is wrong with it')
                return
            elif state == 2:  # Succeed to generate compose
                log.info('ODCS has finished to generate compose. Continue to rebuild')
                break
            else:
                log.error('Got unexpected compose state {0} from ODCS.'.format(state))
                return

        log.info('Repo URL containing packages used to rebuild container: %s',
                 new_compose['result_repo'])

        return new_compose['result_repo']

    def _get_packages_for_compose(self, nvr):
        """Get RPMs of current build NVR"""
        with koji_service(conf.koji_profile, log) as session:
            rpms = session.get_build_rpms(nvr)
        return list(set([rpm['name'] for rpm in rpms]))

    def _get_compose_source(self, nvr):
        """Get tag from which to collect packages to compose"""
        with koji_service(conf.koji_profile, log) as service:
            tag = [tag['name'] for tag in service.session.listTags(nvr)
                   if tag['name'].endswith('-candidate')][0]
            latest_build = service.session.listTagged(
                tag,
                latest=True,
                package=koji.parse_NVR(nvr)['name'])
            if latest_build and latest_build[0]['nvr'] == nvr:
                return tag

    def _log_images_to_rebuild(self, builds):
        """
        Logs the information about images to rebuilt using log.info(...).
        :param builds dict: list of docker images to build as returned by
            _record_images_to_rebuild(...).
        """
        log.info('Found docker images to rebuild in following order:')
        batch = 0
        printed = []
        while len(printed) != len(builds.values()):
            log.info('   Batch %d:', batch)
            for build in builds.values():
                if (((build.dep_on and build.dep_on.name in printed)
                        or (not build.dep_on and batch == 0))
                        and not build.name in printed):
                    args = json.loads(build.build_args)
                    based_on = "based on %s" % args["parent"] \
                        if args["parent"] else "base image"
                    log.info('      - %s#%s (%s)' %
                            (args["repository"], args["commit"], based_on))
                    printed.append(build.name)

            batch += 1

    def _find_events_to_include(self, db_event, builds):
        """
        Find out all unreleased events which built some image which is also
        planned to be build as part of current image rebuild.

        :param db_event Event: Database representation of
            ErrataAdvisoryRPMsSignedEvent.
        :param builds dict: list of docker images to build as returned by
            _record_images_to_rebuild(...).
        """
        events_to_include = []
        for ev in Event.get_unreleased(db.session):
            for build in ev.builds:
                # Skip non IMAGE builds
                if (build.type != ArtifactType.IMAGE.value
                        or ev.message_id == db_event.message_id):
                    continue

                if build.name in builds:
                    events_to_include.append(ev)
                    break

        return events_to_include

    def _record_batches(self, batches, event, builds=None):
        """
        Records the images from batches to database.
        :param batches list: Output of _find_images_to_rebuild(...).
        :param event ErrataAdvisoryRPMsSignedEvent: The main event this handler
            is currently handling.
        :param builds dict: list of docker images to build as returned by
            _record_images_to_rebuild(...).
        """

        # Used as tmp dict with {brew_buil_id: ArtifactBuild, ...} mapping.
        builds = builds or {}

        for batch in batches:
            for image in batch:
                name = image["brew"]["build"]
                if name in builds:
                    log.debug("Skipping recording build %s, "
                              "it is already in db", name)
                    continue
                log.debug("Recording %s", name)
                parent_name = image["parent"]["brew"]["build"] \
                    if image["parent"] else None
                dep_on = builds[parent_name] if parent_name in builds else None
                build = self.record_build(
                    event, name, ArtifactType.IMAGE, 0, dep_on,
                    ArtifactBuildState.PLANNED.value)

                build_args = {}
                build_args["repository"] = image["repository"]
                build_args["commit"] = image["commit"]
                build_args["parent"] = parent_name
                build.build_args = json.dumps(build_args)
                db.session.commit()

                builds[name] = build

        return builds

    def _record_images_to_rebuild(self, db_event, event, builds=None):
        """
        Finds and records to DB the list of Docker images to rebuild based
        on the particular ErrataAdvisoryRPMsSignedEvent.

        :param db_event Event: Database representation of
            ErrataAdvisoryRPMsSignedEvent.
        :param event ErrataAdvisoryRPMsSignedEvent: The main event this handler
            is currently handling.
        :param builds dict: list of docker images to build as returned by
            previous calls of _record_images_to_rebuild(...).
        """

        errata = Errata(conf.errata_tool_server_url)
        errata_id = int(db_event.search_key)

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

        # For each RPM build in Errata advisory, find the list of Docker
        # images containing this RPM and record it to DB.
        builds = builds or {}
        nvrs = errata.get_builds(errata_id)
        for nvr in nvrs:
            srpm_name = self._find_build_srpm_name(nvr)
            batches = lb.find_images_to_rebuild(srpm_name, content_sets)
            builds = self._record_batches(batches, event, builds)
        return builds

    def _find_build_srpm_name(self, build_nvr):
        """Find srpm name from a build"""
        with koji_service(conf.koji_profile, log) as session:
            rpm_infos = session.get_build_rpms(build_nvr, arches='src')
            if not rpm_infos:
                raise ValueError(
                    'Build {} does not have a SRPM, although this should not '
                    'happen in practice.'.format(build_nvr))
            return rpm_infos[0]['name']
