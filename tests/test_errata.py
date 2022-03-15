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
from requests_kerberos.exceptions import MutualAuthenticationError
from requests.exceptions import HTTPError

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
            },
            "people": {
                "reporter": "botas/dev-jenkins.some.strange.letters.redhat.com@REDHAT.COM"
            },
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

        self.builds_by_cve = {
            "CVE-2020-12345": {
                "PRODUCT1": {
                    "name": "PRODUCT1",
                    "description": "PRODUCT Version 1",
                    "builds": [
                        {
                            "libntirpc-1.4.3-4.el6rhs": {
                                "nvr": "libntirpc-1.4.3-4.el6rhs",
                                "nevr": "libntirpc-0:1.4.3-4.el6rhs",
                                "id": 1220279,
                                "is_module": False,
                                "variant_arch": {
                                    "PRODUCT1": {
                                        "x86_64": [
                                            "libntirpc-1.4.3-4.el6rhs.x86_64.rpm"
                                        ],
                                        "ppc64le": [
                                            "libntirpc-1.4.3-4.el6rhs.ppc64le.rpm"
                                        ],
                                        "s390x": ["libntirpc-1.4.3-4.el6rhs.s390x.rpm"],
                                        "aarch64": [
                                            "libntirpc-1.4.3-4.el6rhs.aarch64.rpm"
                                        ],
                                        "SRPMS": ["libntirpc-1.4.3-4.el6rhs.src.rpm"],
                                    },
                                    "PRODUCT2": {
                                        "x86_64": [
                                            "libntirpc-1.4.3-4.el6rhs.x86_64.rpm"
                                        ],
                                        "ppc64le": [
                                            "libntirpc-1.4.3-4.el6rhs.ppc64le.rpm"
                                        ],
                                        "s390x": ["libntirpc-1.4.3-4.el6rhs.s390x.rpm"],
                                        "aarch64": [
                                            "libntirpc-1.4.3-4.el6rhs.aarch64.rpm"
                                        ],
                                        "SRPMS": ["libntirpc-1.4.3-4.el6rhs.src.rpm"],
                                    },
                                },
                            }
                        }
                    ],
                }
            }
        }

        self.builds_list_with_sig_key = {
            "PRODUCT1": {
                "name": "PRODUCT1",
                "description": "Product 1",
                "builds": [
                    {
                        "pkg1-4.18.0-305.10.2.rt7.83.el8_4": {
                            "nvr": "pkg1-4.18.0-305.10.2.rt7.83.el8_4",
                            "nevr": "pkg1-0:4.18.0-305.10.2.rt7.83.el8_4",
                            "id": 1000,
                            "is_module": False,
                            "is_signed": True
                        },
                        "pkg2-4.18.0-305.10.2.rt7.83.el8_4": {
                            "nvr": "pkg2-4.18.0-305.10.2.rt7.83.el8_4",
                            "nevr": "pkg2-0:4.18.0-305.10.2.rt7.83.el8_4",
                            "id": 1001,
                            "is_module": False,
                            "is_signed": True
                        }
                    }
                ],
                "sig_key": {
                    "name": "releasekey",
                    "keyid": "abcdef01"
                },
                "container_sig_key": {
                    "name": "releasekey",
                    "keyid": "abcdef01"
                }
            }
        }

        self.blocking_errata_for = ["28484"]

    def errata_rest_get(self, endpoint):
        if endpoint.find("build/") != -1:
            nvr = endpoint.split("/")[-1]
            return self.builds[nvr]
        elif endpoint.find("builds_by_cve") != -1:
            return self.builds_by_cve
        elif endpoint.endswith("builds_list?with_sig_key=1"):
            return self.builds_list_with_sig_key
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
        elif endpoint.startswith("errata/blocking_errata_for/"):
            return self.blocking_errata_for


class TestErrata(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestErrata, self).setUp()
        self.errata = Errata("https://localhost/")

    def tearDown(self):
        super(TestErrata, self).tearDown()

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
        self.assertEqual(advisories[0].security_impact, "important")
        self.assertEqual(advisories[0].product_short_name, "product")
        self.assertEqual(advisories[0].cve_list,
                         ["CVE-2015-3253", "CVE-2016-6814"])
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
        builds = mocked_errata.builds_list_with_sig_key["PRODUCT1"]["builds"][0]
        builds["pkg1-4.18.0-305.10.2.rt7.83.el8_4"]["is_signed"] = False
        self.assertFalse(self.errata.builds_signed(28484))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_builds_signed_missing_data(self, errata_http_get, errata_rest_get):
        mocked_errata = MockedErrataAPI(errata_rest_get, errata_http_get)
        builds = mocked_errata.builds_list_with_sig_key["PRODUCT1"]["builds"][0]
        builds["pkg1-4.18.0-305.10.2.rt7.83.el8_4"] = {}
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
    def test_get_nvrs(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        srpms = self.errata.get_srpm_nvrs(28484, "")
        binary_rpms = self.errata.get_binary_rpm_nvrs(28484)
        self.assertEqual(set(srpms), set(['libntirpc-1.4.3-4.el7rhgs',
                                          'libntirpc-1.4.3-4.el6rhs']))
        self.assertEqual(set(binary_rpms), set(['libntirpc-devel-1.4.3-4.el6rhs',
                                                'libntirpc-devel-1.4.3-4.el7rhgs']))

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_binary_rpms_rhel_7(
            self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        ret = self.errata.get_binary_rpm_nvrs(28484, "RHEL-7")
        self.assertEqual(ret, ['libntirpc-devel-1.4.3-4.el7rhgs'])

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_srpm_nvrs_empty(
            self, errata_http_get, errata_rest_get):
        api = MockedErrataAPI(errata_rest_get, errata_http_get)
        api.builds_json = {
            "PRODUCT1": [
                {
                    "libntirpc-1.4.3-4.el7rhgs":
                    {
                        "PRODUCT2-3.2-NFS":
                            {"x86_64": ["libntirpc-devel-1.4.3-4.el7rhgs.x86_64.rpm"]}
                    }
                }
            ]
        }
        ret = self.errata.get_srpm_nvrs(28484, "")
        self.assertEqual(ret, [])

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_binary_nvrs_empty(
            self, errata_http_get, errata_rest_get):
        api = MockedErrataAPI(errata_rest_get, errata_http_get)
        api.builds_json = {
            "PRODUCT1": [
                {
                    "libntirpc-1.4.3-4.el7rhgs":
                        {
                            "PRODUCT2-3.2-NFS":
                                {"SRPMS": [
                                    "libntirpc-devel-1.4.3-4.el7rhgs.x86_64.rpm"]}
                        }
                }
            ]
        }
        ret = self.errata.get_binary_rpm_nvrs(28484, "")
        self.assertEqual(ret, [])

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_get_attached_build_nvrs(
            self, errata_http_get, errata_rest_get):
        api = MockedErrataAPI(errata_rest_get, errata_http_get)
        api.builds_json = {
            "PRODUCT1": [
                {
                    "libreoffice-flatpak-8050020220215203934.84f422e1":
                    {
                        "Hidden-PRODUCT2":
                            {"x86_64": ["libfontenc-1.1.3-8.module+el8.5.0+12446+59af0ebd.x86_64.rpm"]}
                    }
                }
            ]
        }
        ret = self.errata.get_attached_build_nvrs(28484)
        self.assertEqual(ret, {"libreoffice-flatpak-8050020220215203934.84f422e1"})

    @patch.object(Errata, "_errata_rest_get")
    @patch.object(Errata, "_errata_http_get")
    def test_errata_get_cve_affected_rpm_nvrs(self, errata_http_get, errata_rest_get):
        MockedErrataAPI(errata_rest_get, errata_http_get)
        ret = self.errata.get_cve_affected_rpm_nvrs(28484)
        self.assertEqual(ret, ['libntirpc-1.4.3-4.el6rhs'])

    def test_get_docker_repo_tags(self):
        with patch.object(self.errata, "xmlrpc") as xmlrpc:
            xmlrpc.get_advisory_cdn_docker_file_list.return_value = {
                'foo-container-1-1': {
                    'docker': {
                        'target': {
                            'external_repos': {
                                'foo-526': {'tags': ['5.26', 'latest']}
                            }
                        }
                    }
                }
            }
            repo_tags = self.errata.get_docker_repo_tags(28484)

            expected = {'foo-526': ['5.26', 'latest']}
            self.assertEqual(repo_tags, expected)

        with patch.object(self.errata, "xmlrpc") as xmlrpc:
            xmlrpc.get_advisory_cdn_docker_file_list.return_value = {
                'foo-container-1-1': {
                    'docker': {
                        'target': {
                            'external_repos': {
                                'foo-526': {'tags': ['5.26', 'latest']}
                            }
                        }
                    }
                },
                'bar-container-1-1': {
                    'docker': {
                        'target': {
                            'external_repos': {
                                'bar-526': {'tags': ['5.27', 'latest']}
                            }
                        }
                    }
                }
            }
            repo_tags = self.errata.get_docker_repo_tags(28484)

            expected = {'bar-526': ['5.27', 'latest'], 'foo-526': ['5.26', 'latest']}
            self.assertEqual(repo_tags, expected)

    def test_get_docker_repo_tags_xmlrpc_exception(self):
        with patch.object(self.errata, "xmlrpc") as xmlrpc:
            xmlrpc.get_advisory_cdn_docker_file_list.side_effect = ValueError(
                "Expected XMLRPC test exception")
            repo_tags = self.errata.get_docker_repo_tags(28484)
            self.assertEqual(repo_tags, None)

    def test_get_docker_repo_tags_xmlrpc_non_returned(self):
        with patch.object(self.errata, "xmlrpc") as xmlrpc:
            xmlrpc.get_advisory_cdn_docker_file_list.return_value = None
            repo_tags = self.errata.get_docker_repo_tags(28484)
            self.assertEqual(repo_tags, None)

    @patch.object(Errata, "_get_attached_builds")
    @patch.object(Errata, "_get_blocking_advisories")
    def test_get_blocking_advisories_builds(self, get_blocks, get_builds):
        get_builds.return_value = {"product3": [{"nvr1": "some_info"},
                                                {"nvr2": "some_info"}]}
        get_blocks.side_effect = [["28484"], []]

        builds = self.errata.get_blocking_advisories_builds("123")

        self.assertSetEqual(builds, {"nvr1", "nvr2"})
        get_builds.assert_called_once_with("28484")

    @patch.object(Errata, "_get_attached_builds")
    @patch.object(Errata, "_get_blocking_advisories")
    def test_get_recursive_blocking_advisories_builds(self, get_blocks,
                                                      get_builds):
        get_blocks.side_effect = [["12:34"], ["56:78"], []]
        get_builds.side_effect = [{"product1": [{"nvr1": "some_info",
                                                 "nvr2": "some_info"}],
                                  "product2": [{"nvr3": "some_info",
                                                "nvr4": "some_info"}]
                                   },
                                  {"product3": [{"nvr5": "some_info"}]}
                                  ]

        builds = self.errata.get_blocking_advisories_builds("123")

        self.assertSetEqual(builds, {"nvr1", "nvr2", "nvr3", "nvr4", "nvr5"})
        self.assertEqual(get_blocks.call_count, 3)


class TestErrataAuthorizedGet(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestErrataAuthorizedGet, self).setUp()
        self.errata = Errata("https://localhost/")

        self.patcher = helpers.Patcher(
            'freshmaker.errata.')
        self.requests_get = self.patcher.patch("requests.get")
        self.response = MagicMock()
        self.response.json.return_value = {"foo": "bar"}
        self.unlink = self.patcher.patch("os.unlink")

    def tearDown(self):
        super(TestErrataAuthorizedGet, self).tearDown()
        self.patcher.unpatch_all()

    def test_errata_authorized_get(self):
        self.requests_get.return_value = self.response
        data = self.errata._errata_authorized_get("http://localhost/test")
        self.assertEqual(data, {"foo": "bar"})

    def test_errata_authorized_get_kerberos_exception(self):
        # Test that MutualAuthenticationError is retried.
        self.requests_get.side_effect = [MutualAuthenticationError, self.response]

        data = self.errata._errata_authorized_get("http://localhost/test")

        self.assertEqual(data, {"foo": "bar"})
        self.assertEqual(len(self.requests_get.mock_calls), 2)

    def test_errata_authorized_get_kerberos_exception_401(self):
        # Test that 401 error response is retried with kerberos ccache file
        # removed.
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.raise_for_status.side_effect = HTTPError(
            "Expected exception", response=error_response)
        self.requests_get.side_effect = [error_response, self.response]

        data = self.errata._errata_authorized_get("http://localhost/test")

        self.assertEqual(data, {"foo": "bar"})
        self.assertEqual(len(self.requests_get.mock_calls), 2)
        self.unlink.assert_called_once_with(helpers.AnyStringWith("freshmaker_cc"))
