# -*- coding: utf-8 -*-
# Copyright (c) 2020  Red Hat, Inc.
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

from freshmaker.events import (
    BotasErrataShippedEvent,
    ManualRebuildWithAdvisoryEvent,
    ErrataAdvisoryRPMsSignedEvent)
from freshmaker.handlers.botas import HandleBotasAdvisory
from freshmaker.errata import ErrataAdvisory
from tests import helpers


class TestBotasShippedAdvisory(helpers.ModelsTestCase):

    def setUp(self):
        super(TestBotasShippedAdvisory, self).setUp()

        # Each time when recording a build into database, freshmaker has to
        # request a pulp repo from ODCS. This is not necessary for running
        # tests.
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.botas.botas_shipped_advisory.')

        # We do not want to send messages to message bus while running tests
        self.mock_messaging_publish = self.patcher.patch(
            'freshmaker.messaging.publish')

        self.botas_advisory = ErrataAdvisory(
            123, "RHBA-2020", "SHIPPED_LIVE", ['docker'])
        self.botas_advisory._reporter = "botas/pnt-devops-jenkins@REDHAT.COM"
        self.rhba_event = ErrataAdvisoryRPMsSignedEvent(
            "123", self.botas_advisory)

    def tearDown(self):
        super(TestBotasShippedAdvisory, self).tearDown()
        self.patcher.unpatch_all()

    def test_can_handle_botas_adisory(self):
        event = BotasErrataShippedEvent("123", self.botas_advisory)
        handler = HandleBotasAdvisory()
        self.assertTrue(handler.can_handle(event))

    def test_can_handle_manual_rebuild_with_advisory(self):
        event = ManualRebuildWithAdvisoryEvent("123", self.botas_advisory, [])
        handler = HandleBotasAdvisory()
        self.assertFalse(handler.can_handle(event))
