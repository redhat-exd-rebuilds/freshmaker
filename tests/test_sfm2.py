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

from unittest.mock import patch, MagicMock

from freshmaker.sfm2 import SFM2API
from tests import helpers
from requests.exceptions import HTTPError


class MockResponse(object):
    def __init__(self, text):
        self.text = text

    def json(self):
        return self.text

    def raise_for_status(self):
        pass


class TestSFM2API(helpers.FreshmakerTestCase):

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata(self, requests_get):
        impacts = ["low", "moderate", "important", "critical"]
        sfm2 = SFM2API()
        for num_of_cves in range(1, 4):
            requests_get.side_effect = [MockResponse([{'affects': [], 'impact': impacts[num_of_cves - 1]}])]
            highest_cve_severity, _ = sfm2.fetch_cve_metadata(["CVE-%s" % num_of_cves])
            self.assertEqual(highest_cve_severity, impacts[num_of_cves - 1].lower())

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_empty_list(self, requests_get):
        sfm2 = SFM2API()
        highest_cve_severity, _ = sfm2.fetch_cve_metadata([])
        self.assertEqual(highest_cve_severity, None)
        requests_get.assert_not_called()

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_empty_affects_and_impact(self, requests_get):
        sfm2 = SFM2API()
        requests_get.return_value = MockResponse([{'affects': [], 'impact': None}])
        highest_cve_severity, affected_pkgs = sfm2.fetch_cve_metadata(["CVE-1"])
        self.assertEqual(highest_cve_severity, None)
        self.assertEqual(affected_pkgs, [])

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_unspecified_impact(self, requests_get):
        impacts = ["low", "unspecified", "none"]
        requests_get.side_effect = [MockResponse([{'affects': [], 'impact': impact}]) for impact in impacts]
        sfm2 = SFM2API()
        highest_cve_severity, _ = sfm2.fetch_cve_metadata(["CVE-1", "CVE-2"])
        self.assertEqual(highest_cve_severity, "low")

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_unspecified_impact_only(self, requests_get):
        impacts = ["unspecified", "none"]
        requests_get.side_effect = [MockResponse([{'affects': [], 'impact': impact}]) for impact in impacts]
        sfm2 = SFM2API()
        highest_cve_severity, _ = sfm2.fetch_cve_metadata(["CVE-1", "CVE-2"])
        self.assertEqual(highest_cve_severity, None)

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_with_affected_pkgs(self, requests_get):
        response_impact_and_affected_pkgs = [{'affects': [{
            'affected': 'affected',
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'openssl',
            'ps_module': 'rhel-6',
            'resolution': 'fix'
        }, {
            'affected': 'affected',
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'openssl',
            'ps_module': 'rhel-7.1.z',
            'resolution': 'fix'
        }, {
            'affected': None,
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'openssl097a',
            'ps_module': 'rhel-5',
            'resolution': 'wontfix'
        }, {
            'affected': 'notaffected',
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'nss',
            'ps_module': 'rhel-5',
            'resolution': None
        }], 'impact': 'important'}]
        requests_get.side_effect = [MockResponse(response_impact_and_affected_pkgs)]
        sfm2 = SFM2API()
        highest_cve_severity, affected_pkgs = sfm2.fetch_cve_metadata(["CVE-1"])
        self.assertEqual(highest_cve_severity, "important")
        self.assertEqual(affected_pkgs[0]['product'], 'rhel-6')
        self.assertEqual(affected_pkgs[0]['pkg_name'], 'openssl')
        self.assertEqual(affected_pkgs[1]['product'], 'rhel-7.1.z')
        self.assertEqual(len(affected_pkgs), 2)

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_with_not_affected_pkgs(self, requests_get):
        response_impact_and_affected_pkgs = [{'affects': [{
            'affected': None,
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'openssl097a',
            'ps_module': 'rhel-5',
            'resolution': 'wontfix'
        }, {
            'affected': 'notaffected',
            'cvss2': None,
            'cvss3': None,
            'impact': None,
            'ps_component': 'nss',
            'ps_module': 'rhel-5',
            'resolution': None
        }], 'impact': 'important'}]
        requests_get.side_effect = [MockResponse(response_impact_and_affected_pkgs)]
        sfm2 = SFM2API()
        highest_cve_severity, affected_pkgs = sfm2.fetch_cve_metadata(["CVE-1"])
        self.assertEqual(highest_cve_severity, "important")
        self.assertEqual(affected_pkgs, [])

    @patch("freshmaker.sfm2.requests.get")
    def test_fetch_cve_metadata_with_error(self, requests_get):
        for status_code in [400, 500]:
            error_response = MagicMock()
            error_response.status_code = status_code
            error_response.raise_for_status.side_effect = HTTPError(
                "Expected exception", response=error_response)
            sfm2 = SFM2API()
            highest_cve_severity, affected_pkgs = sfm2.fetch_cve_metadata(["CVE-1"])
            self.assertEqual(highest_cve_severity, None)
            self.assertEqual(affected_pkgs, [])
