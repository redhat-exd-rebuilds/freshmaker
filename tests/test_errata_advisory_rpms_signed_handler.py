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

import unittest

from mock import patch

from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent

from freshmaker import db
from freshmaker.models import Event
from freshmaker.types import EventState


class TestErrataAdvisoryRPMsSignedHandler(unittest.TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler._find_images_to_rebuild")
    def test_event_state_updated_when_no_images_to_rebuild(self, mock_find_images):
        mock_find_images.return_value = []
        event = ErrataAdvisoryRPMsSignedEvent("123", "RHBA-2017", 123, "")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(db_event.state_reason, "No container images to rebuild for advisory 'RHBA-2017'")
