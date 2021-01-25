# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

from freshmaker import db
from freshmaker.models import (
    Event, EventState, EVENT_TYPES,
    ArtifactBuild, ArtifactType, ArtifactBuildState, ArtifactBuildCompose,
    Compose
)
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers.internal import UpdateDBOnODCSComposeFail
from freshmaker.events import ODCSComposeStateChangeEvent
from tests import helpers
from odcs.common.types import COMPOSE_STATES


class TestUpdateDBOnODCSComposeFail(helpers.ModelsTestCase):

    def setUp(self):
        super(TestUpdateDBOnODCSComposeFail, self).setUp()
        self.db_event = self._create_test_event(
            "msg-1", "search-key-1", "build-1", 1)
        # Create another DB event, build and compose just to have more data
        # in database.
        self.db_event_2 = self._create_test_event(
            "msg-2", "search-key-2", "another-build-1", 2)

    def _create_test_event(self, event_id, search_key, build_name, compose_id):
        db_event = Event.create(
            db.session, "handler", event_id, search_key,
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.INITIALIZED,
            released=False)
        build_1 = ArtifactBuild.create(
            db.session, db_event, build_name, ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED)
        compose_1 = Compose(odcs_compose_id=compose_id)
        db.session.add(compose_1)
        db.session.commit()
        db.session.add(ArtifactBuildCompose(
            build_id=build_1.id, compose_id=compose_1.id))
        db.session.commit()
        return db_event

    def test_cannot_handle_if_compose_is_not_failed(self):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': COMPOSE_STATES["done"]}
        )
        handler = UpdateDBOnODCSComposeFail()
        can_handle = handler.can_handle(event)
        self.assertFalse(can_handle)

    def test_can_handle(self):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': COMPOSE_STATES["failed"]}
        )
        handler = UpdateDBOnODCSComposeFail()
        can_handle = handler.can_handle(event)
        self.assertTrue(can_handle)

    def test_handle_mark_build_as_failed(self):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': COMPOSE_STATES["failed"]}
        )
        handler = UpdateDBOnODCSComposeFail()
        handler.handle(event)

        db.session.refresh(self.db_event)
        build = self.db_event.builds[0]
        self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
        self.assertEqual(build.state_reason,
                         "ODCS compose 1 is in failed state.")

        db.session.refresh(self.db_event_2)
        build = self.db_event_2.builds[0]
        self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)
