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

from freshmaker import log
from freshmaker import db
from freshmaker.events import BrewContainerTaskStateChangeEvent
from freshmaker.models import ArtifactBuild
from freshmaker.handlers import (
    ContainerBuildHandler, fail_event_on_handler_exception)
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
                found_build.transition(
                    ArtifactBuildState.DONE.value,
                    "Built successfully.")
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
        build_complete_states = (
            ArtifactBuildState.FAILED.value,
            ArtifactBuildState.DONE.value
        )
        all_builds_done = all((build.state in build_complete_states
                               for build in db_event.builds))
        if all_builds_done:
            db_event.transition(
                EventState.COMPLETE, 'All docker images have been rebuilt.')
