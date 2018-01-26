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
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
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

from mock import patch, PropertyMock

from freshmaker import db
from freshmaker.models import (
    Event, EventState, EVENT_TYPES,
    ArtifactBuild, ArtifactType, ArtifactBuildState, ArtifactBuildCompose,
    Compose
)
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers.odcs import ComposeStateChangeHandler
from freshmaker.events import ODCSComposeStateChangeEvent
from tests import helpers


class TestComposeStateChangeHandler(helpers.ModelsTestCase):
    """Test ODCSComposeStateChangeHandler"""

    def setUp(self):
        super(TestComposeStateChangeHandler, self).setUp()

        # Test data
        # (Inner build depends on outer build)
        # Event (ErrataAdvisoryRPMsSignedEvent):
        #     build 1: [compose 1, pulp compose 1]
        #         build 2: [compose 1, pulp compose 2]
        #     build 3: [compose 1, pulp compose 3]
        #         build 4: [compose 1, pulp compose 4]
        #         build 5: [compose 1, pulp compose 5]
        #     build 6 (not planned): [compose 1, pulp compose 6]

        self.db_event = Event.create(
            db.session, 'msg-1', 'search-key-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.INITIALIZED,
            released=False)

        self.build_1 = ArtifactBuild.create(
            db.session, self.db_event, 'build-1', ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED)
        self.build_2 = ArtifactBuild.create(
            db.session, self.db_event, 'build-2', ArtifactType.IMAGE,
            dep_on=self.build_1,
            state=ArtifactBuildState.PLANNED)

        self.build_3 = ArtifactBuild.create(
            db.session, self.db_event, 'build-3', ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED)
        self.build_4 = ArtifactBuild.create(
            db.session, self.db_event, 'build-4', ArtifactType.IMAGE,
            dep_on=self.build_3,
            state=ArtifactBuildState.PLANNED)
        self.build_5 = ArtifactBuild.create(
            db.session, self.db_event, 'build-5', ArtifactType.IMAGE,
            dep_on=self.build_3,
            state=ArtifactBuildState.PLANNED)

        self.build_6 = ArtifactBuild.create(
            db.session, self.db_event, 'build-6', ArtifactType.IMAGE,
            state=ArtifactBuildState.BUILD)

        self.compose_1 = Compose(odcs_compose_id=1)
        db.session.add(self.compose_1)
        db.session.commit()

        builds = [self.build_1, self.build_2, self.build_3,
                  self.build_4, self.build_5, self.build_6]
        composes = [self.compose_1] * 6
        for build, compose in six.moves.zip(builds, composes):
            db.session.add(ArtifactBuildCompose(
                build_id=build.id, compose_id=compose.id))
        db.session.commit()

    def test_cannot_handle_if_compose_is_not_done(self):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': 'generating'}
        )
        handler = ComposeStateChangeHandler()
        can_handle = handler.can_handle(event)
        self.assertFalse(can_handle)

    @patch('freshmaker.models.ArtifactBuild.composes_ready',
           new_callable=PropertyMock)
    @patch('freshmaker.handlers.ContainerBuildHandler.start_to_build_images')
    def test_start_to_build(self, start_to_build_images, composes_ready):
        composes_ready.return_value = True

        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': self.compose_1.id, 'state': 'done'}
        )

        handler = ComposeStateChangeHandler()
        handler.handle(event)

        args, kwargs = start_to_build_images.call_args
        passed_builds = sorted(args[0], key=lambda build: build.id)
        self.assertEqual([self.build_1, self.build_3], passed_builds)
