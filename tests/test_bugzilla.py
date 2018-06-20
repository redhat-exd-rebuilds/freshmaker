# -*- coding: utf-8 -*-
#
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

from mock import patch

from freshmaker.bugzilla import BugzillaAPI
from tests import helpers


class MockResponse(object):
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


xml_with_status = """
<bugzilla><bug>
<status_whiteboard>impact={impact}</status_whiteboard>
</bug></bugzilla>
"""

xml_with_empty_status = """
<bugzilla><bug>
<status_whiteboard></status_whiteboard>
</bug></bugzilla>
"""
xml_without_status = """<bugzilla><bug></bug></bugzilla>"""
xml_with_empty_bug = """<bugzilla></bugzilla>"""


class TestBugzillaAPI(helpers.FreshmakerTestCase):

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact(self, requests_get):
        impacts = ["Low", "Moderate", "Important", "Critical"]
        bugzilla = BugzillaAPI()
        for num_of_cves in range(1, 4):
            requests_get.side_effect = [
                MockResponse(xml_with_status.format(impact=impact))
                for impact in impacts]
            ret = bugzilla.get_highest_impact(["CVE-1"] * num_of_cves)
            self.assertEqual(ret, impacts[num_of_cves - 1].lower())

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact_empty_list(self, requests_get):
        bugzilla = BugzillaAPI()
        ret = bugzilla.get_highest_impact([])
        self.assertEqual(ret, None)
        requests_get.assert_not_called()

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact_no_status(self, requests_get):
        bugzilla = BugzillaAPI()
        requests_get.return_value = MockResponse(xml_without_status)
        ret = bugzilla.get_highest_impact(["CVE-1"])
        self.assertEqual(ret, None)

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact_empty_status(self, requests_get):
        bugzilla = BugzillaAPI()
        requests_get.return_value = MockResponse(xml_with_empty_status)
        ret = bugzilla.get_highest_impact(["CVE-1"])
        self.assertEqual(ret, None)

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact_empty_bug(self, requests_get):
        bugzilla = BugzillaAPI()
        requests_get.return_value = MockResponse(xml_with_empty_bug)
        ret = bugzilla.get_highest_impact(["CVE-1"])
        self.assertEqual(ret, None)

    @patch("freshmaker.bugzilla.requests.get")
    def test_get_highest_impact_unknown_impact(self, requests_get):
        impacts = ["Low", "unknown"]
        requests_get.side_effect = [
            MockResponse(xml_with_status.format(impact=impact))
            for impact in impacts]
        bugzilla = BugzillaAPI()
        ret = bugzilla.get_highest_impact(["CVE-1", "CVE-2"])
        self.assertEqual(ret, "low")
