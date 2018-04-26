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

import six

from freshmaker import db
from freshmaker.models import ArtifactBuild, ArtifactBuildState, Compose
from freshmaker.handlers import (
    ContainerBuildHandler, fail_event_on_handler_exception)
from freshmaker.events import ODCSComposeStateChangeEvent

from odcs.common.types import COMPOSE_STATES

__all__ = ('ComposeStateChangeHandler',)


class ComposeStateChangeHandler(ContainerBuildHandler):
    """Start image rebuild with this compose containing included packages"""

    def can_handle(self, event):
        if not isinstance(event, ODCSComposeStateChangeEvent):
            return False
        return event.compose['state'] == COMPOSE_STATES['done']

    @fail_event_on_handler_exception
    def handle(self, event):
        if event.dry_run:
            self.force_dry_run()

        query = db.session.query(ArtifactBuild).join('composes')
        first_batch_builds = query.filter(
            ArtifactBuild.dep_on == None,  # noqa
            ArtifactBuild.state == ArtifactBuildState.PLANNED.value,
            Compose.odcs_compose_id == event.compose['id'])
        if self.dry_run:
            builds_ready_to_rebuild = first_batch_builds
        else:
            builds_ready_to_rebuild = six.moves.filter(
                lambda build: build.composes_ready, first_batch_builds)
        self.start_to_build_images(builds_ready_to_rebuild)
