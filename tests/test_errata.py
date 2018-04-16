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

from freshmaker.errata import Errata, ErrataAdvisory
from freshmaker.events import (
    BrewSignRPMEvent, GitRPMSpecChangeEvent, ErrataAdvisoryStateChangedEvent)
from tests import helpers


class MockedErrataAPI(object):
    """
    Class mocking methods accessing Errata API in Errata class.
    """
    def __init__(self, errata_rest_get, errata_http_get=None):
        errata_rest_get.side_effect = (self.errata_rest_get)
        if errata_http_get:
            errata_http_get.side_effect = self.errata_http_get

        self.builds_json = {
            "PRODUCT1": [
                {
                    "libntirpc-1.4.3-4.el6rhs":
                    {
                        "PRODUCT1-3.2-NFS":
                            {"x86_64": ["libntirpc-devel-1.4.3-4.el6rhs.x86_64.rpm"],
                             "SRPMS": ["libntirpc-1.4.3-4.el6rhs.src.rpm"]}
                    }
                }
            ],
            "PRODUCT2": [
                {
                    "libntirpc-1.4.3-4.el7rhgs":
                    {
                        "PRODUCT2-3.2-NFS":
                            {"x86_64": ["libntirpc-devel-1.4.3-4.el7rhgs.x86_64.rpm"],
                             "SRPMS": ["libntirpc-1.4.3-4.el7rhgs.src.rpm"]}
                    }
                }
            ]
        }

        self.builds = {}
        self.builds["libntirpc-1.4.3-4.el6rhs"] = {
            "all_errata": [{"id": 28484, "name": "RHSA-2017:28484", "status": "QE"}],
            "rpms_signed": True}
        self.builds["libntirpc-1.4.3-4.el7rhgs"] = {
            "all_errata": [{"id": 28484, "name": "RHSA-2017:28484", "status": "QE"}],
            "rpms_signed": True}

        self.advisory_json = {
            "id": 28484,
            "advisory_name": "RHSA-2017:28484",
            "status": "QE",
            "content_types": ["rpm"],
            "security_impact": "Important",
            "product": {
                "id": 89,
                "short_name": "product",
            }
        }

        self.advisory_rest_json = {
            "errata": {
                "rhsa": {
                    "id": 28484,
                    "fulladvisory": "RHSA-2017:28484",
                    "status": "QE",
                    "content_types": ["rpm"],
                    "security_impact": "Important",
                    "product_id": 89,
                }
            },
            "content": {
                "content": {
                    "cve": "CVE-2015-3253 CVE-2016-6814",
                }
            }
        }

        self.bugs = [
            {
                "id": 1519778,
                "is_security": True,
                "alias": "CVE-2017-5753",
                "flags": "hightouch+,requires_doc_text+,rhsa_sla+",
            },
            {
                "id": 1519780,
                "is_security": True,
                "alias": "CVE-2017-5715",
                "flags": "hightouch+,requires_doc_text+,rhsa_sla+",
            },
        ]

        self.products = {}
        self.products[89] = {"product": {"short_name": "product"}}

        self.product_versions_json = [
            {"product_version": {"name": "PRODUCT1-3.0-NFS", "id": 1}},
            {"product_version": {"name": "PRODUCT1-3.1-NFS", "id": 2}},
            {"product_version": {"name": "PRODUCT1-3.2-NFS", "id": 3}},
            {"product_version": {"name": "PRODUCT1", "id": 3}},
            {"product_version": {"name": "PRODUCT2-3.2-NFS", "id": 4}},
            {"product_version": {"name": "PRODUCT2", "id": 4}},
        ]

        self.product_versions = {}
        self.product_versions[3] = {"rhel_release": {"name": "RHEL-6-foobar"}}
        self.product_versions[4] = {"rhel_release": {"name": "RHEL-7-foobar"}}

    def errata_rest_get(self, endpoint):
        if endpoint.find("build/") != -1:
            nvr = endpoint.split("/")[-1]
            return self.builds[nvr]
        elif endpoint.find("erratum/") != -1:
            return self.advisory_rest_json

    def errata_http_get(self, endpoint):
        if endpoint.endswith("builds.json"):
            return self.builds_json
        elif endpoint.endswith("bugs.json"):
            return self.bugs
        elif endpoint.startswith("advisory/"):
            return self.advisory_json
        elif endpoint.startswith("products/"):
            if endpoint.endswith("product_versions.json"):
                return self.product_versions_json
            elif endpoint.find("/product_versions/") != -1:
                id = int(endpoint.split("/")[-1].replace(".json", ""))
                return self.product_versions[id]
            else:
                id = int(endpoint.split("/")[-1].replace(".json", ""))
                return self.products[id]


class TestErrata(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestErrata, self).setUp()
        self.errata = Errata("https://localhost/")

        self.patcher = helpers.Patcher(
            'freshmaker.errata.SecurityDataAPI.')
        self.patcher.patch("get_highest_threat_severity",
                           return_value="moderate")

    def tearDown(self):
        super(TestErrata, self).tearDown()
        self.patcher.unpatch_all()

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event(self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        event = BrewSignRPMEvent("msgid", "libntirpc-1.4.3-4.el7rhgs")
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].errata_id, 28484)
        self.assertEqual(advisories[0].name, "RHSA-2017:28484")
        self.assertEqual(advisories[0].state, "QE")
        self.assertEqual(advisories[0].content_types, ["rpm"])
        self.assertEqual(advisories[0].security_impact, "Important")
        self.assertEqual(advisories[0].product_short_name, "product")
        self.assertEqual(advisories[0].cve_list,
                         ["CVE-2015-3253", "CVE-2016-6814"])
        self.assertEqual(advisories[0].highest_cve_severity, "moderate")
        self.assertEqual(advisories[0].has_hightouch_bug, True)

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event_empty_cve(
            self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        mocked_errata.advisory_rest_json["content"]["content"]["cve"] = ""
        event = BrewSignRPMEvent("msgid", "libntirpc-1.4.3-4.el7rhgs")
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].cve_list, [])

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event_no_bugs(
            self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        mocked_errata.bugs = []
        event = BrewSignRPMEvent("msgid", "libntirpc-1.4.3-4.el7rhgs")
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].has_hightouch_bug, False)

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event_empty_bug_flags(
            self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        for bug in mocked_errata.bugs:
            bug["flags"] = ""
        event = BrewSignRPMEvent("msgid", "libntirpc-1.4.3-4.el7rhgs")
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].has_hightouch_bug, False)

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event_missing_all_errata(self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        del mocked_errata.builds["libntirpc-1.4.3-4.el7rhgs"]["all_errata"]

        event = BrewSignRPMEvent("msgid", "libntirpc-1.4.3-4.el7rhgs")
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 0)

    def test_advisories_from_event_unsupported_event(self):
        event = GitRPMSpecChangeEvent("msgid", "libntirpc", "master", "foo")
        with self.assertRaises(ValueError):
            self.errata.advisories_from_event(event)

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_advisories_from_event_errata_state_change_event(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        event = ErrataAdvisoryStateChangedEvent(
            "msgid", ErrataAdvisory(28484, "name", "SHIPPED_LIVE", ['rpm']))
        advisories = self.errata.advisories_from_event(event)
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].errata_id, 28484)

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_builds_signed_all_signed(self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        self.assertTrue(self.errata.builds_signed(28484))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_builds_signed_some_unsigned(self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        mocked_errata.builds["libntirpc-1.4.3-4.el7rhgs"]["rpms_signed"] = False
        self.assertFalse(self.errata.builds_signed(28484))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_builds_signed_missing_data(self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        mocked_errata.builds["libntirpc-1.4.3-4.el7rhgs"] = {}
        self.assertFalse(self.errata.builds_signed(28484))

    @patch('freshmaker.errata.requests.get')
    def test_get_errata_repo_ids(self, get):
        get.return_value.json.return_value = {
            'rhel-6-server-eus-source-rpms__6_DOT_7__x86_64': [
            ],
            'rhel-6-server-eus-optional-debug-rpms__6_DOT_7__i386': [
                '/path/to/package.rpm',
                '/path/to/package1.rpm',
                '/path/to/package2.rpm',
            ],
            'rhel-6-server-eus-rpms__6_DOT_7__x86_64': [
            ],
        }

        repo_ids = self.errata.get_pulp_repository_ids(25718)

        self.assertEqual(set(['rhel-6-server-eus-source-rpms__6_DOT_7__x86_64',
                              'rhel-6-server-eus-optional-debug-rpms__6_DOT_7__i386',
                              'rhel-6-server-eus-rpms__6_DOT_7__x86_64']),
                         set(repo_ids))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_rhel_release_from_product_version(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        ret = self.errata._rhel_release_from_product_version(
            28484, "PRODUCT1-3.2-NFS")
        self.assertEqual(ret, "RHEL-6-foobar")

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_rhel_release_from_product_version_unknown_product_ver(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        with self.assertRaises(ValueError):
            self.errata._rhel_release_from_product_version(
                28484, "PRODUCT1-2.9-NFS")

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_builds(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        ret = self.errata.get_builds(28484, "")
        self.assertEqual(ret, set(['libntirpc-1.4.3-4.el7rhgs',
                                  'libntirpc-1.4.3-4.el6rhs']))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_builds_rhel_7(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        ret = self.errata.get_builds(28484, "RHEL-7")
        self.assertEqual(ret, set(['libntirpc-1.4.3-4.el7rhgs']))
