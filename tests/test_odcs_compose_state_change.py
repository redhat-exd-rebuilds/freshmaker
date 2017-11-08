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

import unittest

from mock import call, patch

from freshmaker import db
from freshmaker.models import Event
from freshmaker.models import EVENT_TYPES
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.events import KojiTaskStateChangeEvent
from freshmaker.handlers.odcs import ComposeStateChangeHandler
from freshmaker.events import ODCSComposeStateChangeEvent


class TestComposeStateChangeHandler(unittest.TestCase):
    """Test ODCSComposeStateChangeHandler"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.adv_signed_event1 = Event.get_or_create(
            db.session, 'msg-id-1', 'msg-id-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        self.adv_signed_event2 = Event.get_or_create(
            db.session, 'msg-id-2', 'msg-id-2',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        self.unrelated_event = Event.get_or_create(
            db.session, 'msg-id-3', 'msg-id-3',
            EVENT_TYPES[KojiTaskStateChangeEvent])

        self.adv_signed_event1.compose_id = 1
        self.adv_signed_event2.compose_id = 1
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_cannot_handle_if_compose_is_not_done(self):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': 'generating'}
        )
        handler = ComposeStateChangeHandler()
        can_handle = handler.can_handle(event)
        self.assertFalse(can_handle)

    @patch('freshmaker.handlers.ContainerBuildHandler._build_first_batch')
    @patch('freshmaker.handlers.ContainerBuildHandler.set_context')
    def test_start_to_build(self, set_context, build_first_batch):
        event = ODCSComposeStateChangeEvent(
            'msg-id', {'id': 1, 'state': 'done'}
        )
        handler = ComposeStateChangeHandler()
        handler.handle(event)
        build_first_batch.assert_has_calls([
            call(self.adv_signed_event1),
            call(self.adv_signed_event2),
        ])

        set_context.assert_has_calls([
            call(self.adv_signed_event1),
            call(self.adv_signed_event2)
        ])
