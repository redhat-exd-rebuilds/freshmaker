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

from freshmaker import db
from freshmaker.events import ODCSComposeStateChangeEvent
from freshmaker.models import ArtifactBuild, ArtifactBuildCompose, Compose
from freshmaker.handlers import BaseHandler, fail_event_on_handler_exception
from freshmaker.types import ArtifactBuildState
from odcs.common.types import COMPOSE_STATES


class UpdateDBOnODCSComposeFail(BaseHandler):
    """
    Marks the ArtifactBuild as FAILED in case the ODCS compose on which the
    ArtifactBuild depends is moved to "failed" state.
    """

    name = "UpdateDBOnODCSComposeFail"
    order = 0

    def can_handle(self, event):
        if not isinstance(event, ODCSComposeStateChangeEvent):
            return False
        return event.compose["state"] == COMPOSE_STATES["failed"]

    @fail_event_on_handler_exception
    def handle(self, event):
        # Get all the builds waiting for this compose.
        builds_with_compose = db.session.query(ArtifactBuild).join(
            ArtifactBuildCompose).join(Compose)
        builds_with_compose = builds_with_compose.filter(
            Compose.odcs_compose_id == event.compose["id"],
            ArtifactBuildCompose.compose_id == Compose.id)

        for build in builds_with_compose:
            build.transition(
                ArtifactBuildState.FAILED.value,
                "ODCS compose %r is in failed state." % event.compose["id"])
