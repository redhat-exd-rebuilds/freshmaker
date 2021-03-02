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

from freshmaker import db
from freshmaker.models import (
    ArtifactBuild, ArtifactBuildState, Compose, ArtifactBuildCompose)
from freshmaker.handlers import (
    ContainerBuildHandler, fail_event_on_handler_exception)
from freshmaker.events import ODCSComposeStateChangeEvent

from odcs.common.types import COMPOSE_STATES

__all__ = ('RebuildImagesOnODCSComposeDone',)


class RebuildImagesOnODCSComposeDone(ContainerBuildHandler):
    """Start image rebuild with this compose containing included packages"""

    def can_handle(self, event):
        if not isinstance(event, ODCSComposeStateChangeEvent):
            return False
        return event.compose['state'] == COMPOSE_STATES['done']

    @fail_event_on_handler_exception
    def handle(self, event):
        if event.dry_run:
            self.force_dry_run()

        builds_ready_to_rebuild = db.session.query(ArtifactBuild).join(
            ArtifactBuildCompose).join(Compose)
        # Get all the builds waiting for this compose in PLANNED state ...
        builds_ready_to_rebuild = builds_ready_to_rebuild.filter(
            ArtifactBuild.state == ArtifactBuildState.PLANNED.value,
            Compose.odcs_compose_id == event.compose['id'],
            ArtifactBuildCompose.compose_id == Compose.id)

        if builds_ready_to_rebuild:
            self.log_info('ODCS compose %s finished', event.compose['id'])

        # ... and depending on DONE parent image or parent image which is
        # not planned to be built in this Event (dep_on == None).
        builds_ready_to_rebuild = [
            b for b in builds_ready_to_rebuild if
            b.dep_on is None or b.dep_on.state == ArtifactBuildState.DONE.value
        ]

        if not self.dry_run:
            # In non-dry-run mode, check that all the composes are ready.
            # In dry-run mode, the composes are fake, so they are always ready.
            builds_ready_to_rebuild = filter(
                lambda build: build.composes_ready, builds_ready_to_rebuild)

        # Start the rebuild.
        self.start_to_build_images(builds_ready_to_rebuild)
