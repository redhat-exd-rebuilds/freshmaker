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
import pytest
import unittest

from mock import patch, MagicMock, PropertyMock

from freshmaker.handlers.brew.sign_rpm import BrewSignRPMHanlder
from freshmaker.errata import ErrataAdvisory


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestFindBuildSrpmName(unittest.TestCase):
    """Test BrewSignRPMHanlder._find_build_srpm_name"""

    @patch('koji.ClientSession')
    def test_find_srpm_name(self, ClientSession):
        session = ClientSession.return_value
        session.getBuild.return_value = {
            'build_id': 439408,
            'id': 439408,
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }
        session.listRPMs.return_value = [{
            'arch': 'src',
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }]

        handler = BrewSignRPMHanlder()
        srpm_name = handler._find_build_srpm_name('bind-dyndb-ldap-2.3-8.el6')

        session.getBuild.assert_called_once_with('bind-dyndb-ldap-2.3-8.el6')
        session.listRPMs.assert_called_once_with(buildID=439408, arches='src')
        self.assertEqual('bind-dyndb-ldap', srpm_name)

    @patch('koji.ClientSession')
    def test_error_if_no_srpm_in_build(self, ClientSession):
        session = ClientSession.return_value
        session.getBuild.return_value = {
            'build_id': 439408,
            'id': 439408,
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }
        session.listRPMs.return_value = []

        handler = BrewSignRPMHanlder()

        self.assertRaisesRegexp(
            ValueError,
            'Build bind-dyndb-ldap-2.3-8.el6 does not have a SRPM',
            handler._find_build_srpm_name,
            'bind-dyndb-ldap-2.3-8.el6',
        )

        session.getBuild.assert_called_once_with('bind-dyndb-ldap-2.3-8.el6')
        session.listRPMs.assert_called_once_with(buildID=439408, arches='src')


class TestAllowBuild(unittest.TestCase):
    """Test BrewSignRPMHanlder.allow_build"""

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": [{"advisory_name": "RHSA-.*"}]}})
    def test_allow_build_false(self, handler_build_whitelist, builds_signed,
                               advisories_from_event):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP")]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHanlder()
        handler.handle(event)

        builds_signed.assert_not_called()

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch('freshmaker.errata.Errata.builds_signed')
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "BrewSignRPMHandler": {"image": [{"advisory_name": "RHSA-.*"}]}})
    def test_allow_build_true(self, handler_build_whitelist, builds_signed,
                              advisories_from_event):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        advisories_from_event.return_value = [
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP")]
        builds_signed.return_value = False

        event = MagicMock()
        handler = BrewSignRPMHanlder()
        handler.handle(event)

        builds_signed.assert_called_once()
