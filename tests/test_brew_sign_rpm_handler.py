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

from mock import patch, MagicMock, PropertyMock

from freshmaker.handlers.brew.sign_rpm import BrewSignRPMHandler
from freshmaker.errata import ErrataAdvisory
from tests import helpers


class TestBrewSignHandler(helpers.ModelsTestCase):
    """Test BrewSignRPMHandler.handle"""

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_return_value(self, handler_build_whitelist, builds_signed,
                          advisories_from_event):
        """
        Tests that handle method returns ErrataAdvisoryRPMsSignedEvent.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"])]
        builds_signed.return_value = True

        event = MagicMock()
        event.msg_id = "msg_123"
        handler = BrewSignRPMHandler()
        ret = handler.handle(event)

        self.assertTrue(len(ret), 1)
        self.assertEqual(ret[0].advisory.name, "RHSA-2017")
        self.assertEqual(ret[0].advisory.errata_id, 123)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "global": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_false_global(self, handler_build_whitelist,
                                      builds_signed, advisories_from_event):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", ["rpm"])]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        ret = handler.handle(event)

        self.assertTrue(not ret)
        builds_signed.assert_not_called()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "global": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_true_global(self, handler_build_whitelist,
                                     builds_signed, advisories_from_event):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"])]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        handler.handle(event)

        builds_signed.assert_called_once()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_false(self, handler_build_whitelist, builds_signed,
                               advisories_from_event):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", ["rpm"])]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        ret = handler.handle(event)

        self.assertTrue(not ret)
        builds_signed.assert_not_called()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_true(self, handler_build_whitelist, builds_signed,
                              advisories_from_event):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"])]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        handler.handle(event)

        builds_signed.assert_called_once()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "BrewSignRPMHandler": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }
            }
        })
    def test_allow_security_impact_important_true(
            self, handler_build_whitelist, builds_signed,
            advisories_from_event):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_security_impact.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"], "Important")]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        handler.handle(event)

        builds_signed.assert_called_once()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "BrewSignRPMHandler": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }
            }
        })
    def test_allow_security_impact_important_false(
            self, handler_build_whitelist, builds_signed,
            advisories_from_event):
        """
        Tests that allow_build dost filter out advisories based on
        advisory_security_impact.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"], "None")]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHandler()
        handler.handle(event)

        builds_signed.assert_not_called()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_do_not_create_already_handled_event(
            self, handler_build_whitelist, builds_signed,
            advisories_from_event):
        """
        Tests that BrewSignRPMHandler don't return Event which already exists
        in Freshmaker DB.
        """
        builds_signed.return_value = True
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", ["rpm"])]

        event = MagicMock()
        event.msg_id = "msg_123"
        handler = BrewSignRPMHandler()
        handler.handle(event)

        builds_signed.assert_called_once()
        builds_signed.reset_mock()

        handler.handle(event)
        builds_signed.assert_not_called()
