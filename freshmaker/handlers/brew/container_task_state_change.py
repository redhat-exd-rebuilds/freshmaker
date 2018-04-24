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

from kobo import rpmlib

from freshmaker import conf
from freshmaker import log
from freshmaker import db
from freshmaker.errata import Errata
from freshmaker.events import (
    BrewContainerTaskStateChangeEvent, ErrataAdvisoryRPMsSignedEvent)
from freshmaker.models import ArtifactBuild, EVENT_TYPES
from freshmaker.handlers import (
    ContainerBuildHandler, fail_event_on_handler_exception)
from freshmaker.kojiservice import koji_service
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState


class BrewContainerTaskStateChangeHandler(ContainerBuildHandler):
    """Rebuild container when a dependecy container is built in Brew"""

    name = 'BrewContainerTaskStateChangeHandler'

    def can_handle(self, event):
        return isinstance(event, BrewContainerTaskStateChangeEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        When build container task state changed in brew, update build state in
        db and rebuild containers depend on the success build as necessary.
        """
        if event.dry_run:
            self.force_dry_run()

        build_id = event.task_id

        # check db to see whether this build exists in db
        found_build = db.session.query(ArtifactBuild).filter_by(
            type=ArtifactType.IMAGE.value,
            build_id=build_id
        ).first()

        if found_build is not None:
            self.set_context(found_build)
            # update build state in db
            if event.new_state == 'CLOSED':
                # if build is triggered by an advisory, verify the container
                # contains latest RPMs from the advisory
                if found_build.event.event_type_id == EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent]:
                    errata_id = found_build.event.search_key
                    # build_id is actually task id in build system, find out the actual build first
                    with koji_service(
                            conf.koji_profile, log, login=False,
                            dry_run=self.dry_run) as session:
                        container_build_id = session.get_container_build_id_from_task(build_id)

                    ret, msg = self._verify_advisory_rpms_in_container_build(errata_id, container_build_id)
                    if ret:
                        found_build.transition(ArtifactBuildState.DONE.value, "Built successfully.")
                    else:
                        found_build.transition(ArtifactBuildState.FAILED.value, msg)

                # for other builds, mark them as DONE
                else:
                    found_build.transition(ArtifactBuildState.DONE.value, "Built successfully.")
            if event.new_state == 'FAILED':
                found_build.transition(
                    ArtifactBuildState.FAILED.value,
                    "Failed to build in Koji.")
            db.session.commit()

            if found_build.state == ArtifactBuildState.DONE.value:
                # check db to see whether there is any planned image build
                # depends on this build
                planned_builds = db.session.query(ArtifactBuild).filter_by(
                    type=ArtifactType.IMAGE.value,
                    state=ArtifactBuildState.PLANNED.value,
                    dep_on=found_build
                ).all()

                log.info("Found following PLANNED builds to rebuild that "
                         "depends on %r", found_build)
                for build in planned_builds:
                    log.info("  %r", build)

                self.start_to_build_images(planned_builds)

            # Finally, we check if all builds scheduled by event
            # found_build.event (ErrataAdvisoryRPMsSignedEvent) have been
            # switched to FAILED or COMPLETE. If yes, mark the event COMPLETE.
            self._mark_event_complete_when_all_builds_done(found_build.event)

    def _mark_event_complete_when_all_builds_done(self, db_event):
        """Mark ErrataAdvisoryRPMsSignedEvent COMPLETE

        As we know that docker images are scheduled to be rebuilt by hanlding
        event ErrataAdvisoryRPMsSignedEvent. When all those builds are done,
        the event should be marked as COMPLETE accordingly. If not all finish,
        nothing change to the state.

        :param Event db_event: instance of Event that represents an event
            ErrataAdvisoryRPMsSignedEvent.
        """
        num_failed = 0
        for build in db_event.builds:
            if build.state == ArtifactBuildState.FAILED.value:
                num_failed += 1
            elif build.state != ArtifactBuildState.DONE.value:
                # Return when build is not DONE and also not FAILED, it means
                # it's still building.
                return

        if num_failed:
            db_event.transition(
                EventState.COMPLETE,
                '%d of %d container image(s) failed to rebuild.' % (
                    num_failed, len(db_event.builds),))
        else:
            db_event.transition(
                EventState.COMPLETE,
                'All %s container images have been rebuilt.' % (
                    len(db_event.builds),))

    def _verify_advisory_rpms_in_container_build(self, errata_id, container_build_id):
        """
        verify container built on brew has the latest rpms from an advisory
        """
        if self.dry_run:
            return (True, '')

        # Get rpms in advisory. There can be multiple versions of RPMs with
        # the same name, so we group them by a name in `advisory_rpms_by_name`
        # and use set of the nvrs as a value.
        advisory_rpms_by_name = {}
        e = Errata()
        build_nvrs = e.get_builds(errata_id)
        if build_nvrs:
            with koji_service(
                    conf.koji_profile, log, login=False,
                    dry_run=self.dry_run) as session:
                for build_nvr in build_nvrs:
                    build_rpms = session.get_build_rpms(build_nvr)
                    for rpm in build_rpms:
                        if rpm['name'] not in advisory_rpms_by_name:
                            advisory_rpms_by_name[rpm['name']] = set()
                        advisory_rpms_by_name[rpm['name']].add(rpm['nvr'])

        # get rpms in container
        with koji_service(
                conf.koji_profile, log, login=False,
                dry_run=self.dry_run) as session:
            container_rpms = session.get_rpms_in_container(container_build_id)
            container_rpms_by_name = {
                rpmlib.parse_nvr(x)['name']: x for x in container_rpms}

        # For each RPM name in advisory, check that the RPM exists in the
        # built container and its version is the same as one RPM in the
        # advisory.
        unmatched_rpms = []
        for rpm_name, nvrs in advisory_rpms_by_name.items():
            if rpm_name not in container_rpms_by_name:
                continue
            container_rpm_nvr = container_rpms_by_name[rpm_name]
            if container_rpm_nvr not in nvrs:
                unmatched_rpms.append(rpm_name)

        if unmatched_rpms:
            msg = ("The following RPMs in container build (%s) do not match "
                   "with the latest RPMs in advisory (%s):\n%s" %
                   (container_build_id, errata_id, unmatched_rpms))
            return (False, msg)
        return (True, "")
