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

from freshmaker.security_data import SecurityDataAPI
from tests import helpers


class TestSecurityDataAPI(helpers.FreshmakerTestCase):

    @patch("freshmaker.security_data.requests.get")
    def test_get_highest_threat_severity(self, requests_get):
        severities = ["Low", "Moderate", "Important", "Critical"]
        sec_data = SecurityDataAPI()
        for num_of_cves in range(1, 4):
            requests_get.return_value.json.side_effect = [
                {"threat_severity": severity} for severity in severities]
            ret = sec_data.get_highest_threat_severity(["CVE-1"] * num_of_cves)
            self.assertEqual(ret, severities[num_of_cves - 1].lower())

    @patch("freshmaker.security_data.requests.get")
    def test_get_highest_threat_severity_empty_list(self, requests_get):
        sec_data = SecurityDataAPI()
        ret = sec_data.get_highest_threat_severity([])
        self.assertEqual(ret, None)
        requests_get.assert_not_called()

    @patch("freshmaker.security_data.requests.get")
    def test_get_highest_threat_severity_unknown_severity(self, requests_get):
        severities = ["Low", "unknown"]
        requests_get.return_value.json.side_effect = [
            {"threat_severity": severity} for severity in severities]
        sec_data = SecurityDataAPI()
        ret = sec_data.get_highest_threat_severity(["CVE-1", "CVE-2"])
        self.assertEqual(ret, "low")
