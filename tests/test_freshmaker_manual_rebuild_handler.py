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

from mock import patch

from freshmaker.handlers.internal import FreshmakerManualRebuildHandler
from freshmaker.events import (
    FreshmakerManualRebuildEvent, ErrataAdvisoryRPMsSignedEvent)

from freshmaker.errata import ErrataAdvisory
from freshmaker import db
from freshmaker.models import Event


class TestFreshmakerManualRebuildHandler(unittest.TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists(self, advisories_from_event):
        handler = FreshmakerManualRebuildHandler()

        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", "Critical")]
        ev = FreshmakerManualRebuildEvent("msg123", errata_id=123)
        ret = handler.handle(ev)

        self.assertEqual(len(ret), 1)
        self.assertEqual(ret[0].errata_id, 123)
        self.assertEqual(ret[0].security_impact, "Critical")
        self.assertEqual(ret[0].errata_name, "RHSA-2017")

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists_already_exists(
            self, advisories_from_event):
        handler = FreshmakerManualRebuildHandler()

        Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent)
        db.session.commit()

        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", "Critical")]
        ev = FreshmakerManualRebuildEvent("msg123", errata_id=123)
        ret = handler.handle(ev)

        self.assertEqual(len(ret), 0)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists_unknown_errata_id(
            self, advisories_from_event):
        advisories_from_event.return_value = []
        handler = FreshmakerManualRebuildHandler()

        ev = FreshmakerManualRebuildEvent("msg123", errata_id=123)
        ret = handler.handle(ev)

        self.assertEqual(len(ret), 0)
