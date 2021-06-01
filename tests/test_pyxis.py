# -*- coding: utf-8 -*-
#
# Copyright (c) 2020  Red Hat, Inc.
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

import requests
import requests_mock

from datetime import datetime
from freezegun import freeze_time
from http import HTTPStatus
from copy import deepcopy
from unittest.mock import call, patch, create_autospec, Mock

from freshmaker import conf
from freshmaker.pyxis import Pyxis, PyxisRequestError

from tests import helpers


class TestQueryPyxis(helpers.FreshmakerTestCase):
    def setUp(self):
        super().setUp()

        self.patcher = helpers.Patcher(
            'freshmaker.pyxis.')

        self.fake_server_url = 'https://pyxis.localhost/'
        self.px = Pyxis(self.fake_server_url)
        self.response = create_autospec(requests.Response)
        self.response.status_code = HTTPStatus.OK
        self.bad_requests_response = {
            "detail": [
                "Unable to parse the filter from URL.",
                "Please verify the 'Field Name' in the RSQL Expression.",
                "Please visit the following end-point for more details:",
                "    /v1/docs/filtering-language"
            ],
            "status": 400,
            "title": "Bad Request",
            "type": "about:blank"
        }

        self.empty_response_page = {
            "data": [],
            "page": 0,
            "page_size": 100,
            "total": 0
        }

        self.indices = [
            {
                "_id": "1",
                "created_by": "meteor",
                "creation_date": "2020-01-01T09:32:31.692000+00:00",
                "last_update_date": "2020-01-01T09:32:31.692000+00:00",
                "last_updated_by": "meteor",
                "ocp_version": "4.5",
                "organization": "org",
                "path": "path/to/registry:v4.5"
            },
            {
                "_id": "2",
                "created_by": "meteor",
                "creation_date": "2020-01-01T09:32:38.486000+00:00",
                "last_update_date": "2020-01-01T09:32:38.486000+00:00",
                "last_updated_by": "meteor",
                "ocp_version": "4.6",
                "organization": "org",
                "path": "path/to/registry:v4.6"
            },
            {
                "_id": "2",
                "created_by": "meteor",
                "creation_date": "2020-01-01T09:32:38.486000+00:00",
                "last_update_date": "2020-01-01T09:32:38.486000+00:00",
                "last_updated_by": "meteor",
                "ocp_version": "4.6",
                "organization": "org",
                "path": ""
            }
        ]

        self.bundles = [
            {
                "channel_name": "streams-1.5.x",
                "related_images": [
                    {
                        "image": "registry/amq7/amq-streams-r-operator@sha256:111",
                        "name": "strimzi-cluster-operator",
                        "digest": "sha256:111"
                    },
                    {
                        "image": "registry/amq7/amq-streams-kafka-24-r@sha256:222",
                        "name": "strimzi-kafka-24",
                        "digest": "sha256:222"
                    },
                    {
                        "image": "registry/amq7/amq-streams-kafka-25-r@sha256:333",
                        "name": "strimzi-kafka-25",
                        "digest": "sha256:333"
                    },
                    {
                        "image": "registry/amq7/amq-streams-bridge-r@sha256:444",
                        "name": "strimzi-bridge",
                        "digest": "sha256:444"
                    }
                ],
                "version": "1.5.3"
            },
            {
                "channel_name": "streams-1.5.x",
                "related_images": [
                    {
                        "image": "registry/amq7/amq-streams-r-operator@sha256:555",
                        "name": "strimzi-cluster-operator",
                        "digest": "sha256:555"
                    },
                    {
                        "image": "registry/amq7/amq-streams-kafka-24-r@sha256:666",
                        "name": "strimzi-kafka-24",
                        "digest": "sha256:666"
                    },
                    {
                        "image": "registry/amq7/amq-streams-kafka-25-r@sha256:777",
                        "name": "strimzi-kafka-25",
                        "digest": "sha256:777"
                    },
                    {
                        "image": "registry/amq7/amq-streams-bridge-r@sha256:888",
                        "name": "strimzi-bridge",
                        "digest": "sha256:888"
                    }
                ],
                "version": "1.5.4"
            },
            {
                "channel_name": "stable",
                "related_images": [
                    {
                        "image": "registry/amq7/amq--operator@sha256:999",
                        "name": "strimzi-cluster-operator",
                        "digest": "sha256:999"
                    },
                    {
                        "image": "registry/amq7/kafka-24-r@sha256:aaa",
                        "name": "strimzi-kafka-24",
                        "digest": "sha256:aaa"
                    },
                    {
                        "image": "registry/amq7/kafka-25-r@sha256:bbb",
                        "name": "strimzi-kafka-25",
                        "digest": "sha256:bbb"
                    },
                    {
                        "image": "registry/amq7/amq-streams-bridge-r@sha256:ccc",
                        "name": "strimzi-bridge",
                        "digest": "sha256:ccc"
                    }
                ],
                "version": "1.5.3"
            },
            {
                "channel_name": "stable",
                "related_images": [
                    {
                        "image": "registry/tracing/j-operator:1.13.2",
                        "name": "j-1.13.2-annotation",
                        "digest": "sha256:fff"
                    },
                    {
                        "image": "registry/tracing/j-operator:1.13.2",
                        "name": "j-operator",
                        "digest": "sha256:ffff"
                    }
                ],
                "version": "1.5.2"
            },
            {
                "channel_name": "quay-v3.3",
                "related_images": [
                    {
                        "image": "registry/quay/quay-operator@sha256:ddd",
                        "name": "quay-operator-annotation",
                        "digest": "sha256:ddd"
                    },
                    {
                        "image": "registry/quay/quay-security-r-operator@sha256:eee",
                        "name": "container-security-operator",
                        "digest": "sha256:eee"
                    }
                ],
                "version": "3.3.1"
            },
        ]

        self.images = [
            {
                "brew": {
                    "build": "s2i-1-2",
                    "completion_date": "2020-08-12T11:31:39+00:00",
                    "nvra": "s2i-1-2.ppc64le",
                    "package": "s2i-core-container"
                },
                "repositories": [
                    {
                        "manifest_list_digest": "sha256:1111",
                        "published": False,
                        "registry": "reg1",
                        "repository": "repo1",
                        "tags": [{"name": "tag0"}]
                    },
                    {
                        "manifest_list_digest": "sha256:1112",
                        "published": True,
                        "registry": "reg2",
                        "repository": "repo2",
                        "tags": [{"name": "tag1"}, {"name": "tag2"}]
                    }
                ]
            },
            {
                "brew": {
                    "build": "s2i-1-2",
                    "completion_date": "2020-08-12T11:31:39+00:00",
                    "nvra": "s2i-1-2.s390x",
                    "package": "s2i-core-container"
                },
                "repositories": [
                    {
                        "manifest_list_digest": "sha256:2222",
                        "published": True,
                        "registry": "reg2",
                        "repository": "repo2",
                        "tags": [{"name": "tag2"}]
                    }
                ]
            },
            {
                "brew": {
                    "build": "s2i-1-2",
                    "completion_date": "2020-08-12T11:31:39+00:00",
                    "nvra": "s2i-1-2.amd64",
                    "package": "s2i-core-container"
                },
                "repositories": [
                    {
                        "manifest_list_digest": "sha256:3333",
                        "published": True,
                        "registry": "reg3",
                        "repository": "repo3",
                        "tags": [{"name": "latest"}]
                    }
                ]
            },
            {
                "brew": {
                    "build": "s2i-1-2",
                    "completion_date": "2020-08-12T11:31:39+00:00",
                    "nvra": "s2i-1-2.arm64",
                    "package": "s2i-core-container"
                },
                "repositories": [
                    {
                        "manifest_list_digest": "sha256:4444",
                        "published": True,
                        "registry": "reg4",
                        "repository": "repo4",
                        "tags": [{"name": "tag1"}]
                    }
                ]
            }
        ]

    def tearDown(self):
        super().tearDown()
        self.patcher.unpatch_all()

    @staticmethod
    def copy_call_args(mock):
        """
        Copy args of Mock to another Mock so we can check call args if we call
        mock with mutable args and change it between calls
        """
        new_mock = Mock()

        def side_effect(*args, **kwargs):
            args = deepcopy(args)
            kwargs = deepcopy(kwargs)
            return new_mock(*args, **kwargs)
        mock.side_effect = side_effect
        return new_mock

    @patch('freshmaker.pyxis.HTTPKerberosAuth')
    @patch('freshmaker.pyxis.requests.get')
    def test_make_request(self, get, auth):
        get.return_value = self.response
        test_params = {'key1': 'val1'}
        self.px._make_request('test', test_params)

        get_url = self.fake_server_url + 'v1/test'
        self.response.json.assert_called_once()
        test_params['page_size'] = "100"
        get.assert_called_once_with(get_url, params=test_params, auth=auth(),
                                    timeout=conf.net_timeout)

    @patch('freshmaker.pyxis.HTTPKerberosAuth')
    @patch('freshmaker.pyxis.requests.get')
    def test_make_request_error(self, get, auth):
        get.return_value = self.response
        self.response.ok = False
        self.response.json.side_effect = ValueError
        self.response.json.text = 'test message'
        self.response.request = Mock()
        self.response.request.url = 'test/url'

        with self.assertRaises(PyxisRequestError, msg='test message'):
            self.px._make_request('test', {})

    @patch('freshmaker.pyxis.HTTPKerberosAuth')
    @patch('freshmaker.pyxis.Pyxis._make_request')
    def test_pagination(self, request, auth):
        my_request = self.copy_call_args(request)
        my_request.side_effect = [
            {"page": 0, "data": ["fake_data1"]},
            {"page": 1, "data": ["fake_data2"]},
            {"page": 2, "data": []}
        ]
        test_params = {'include': ['total', 'field1']}
        entity = 'test'
        auth.return_value = 1
        self.px._pagination(entity, test_params)

        self.assertEqual(request.call_count, 3)
        default_params = {'page_size': '100', 'include': ['total', 'field1']}
        calls = [call('test', params={**default_params, 'page': 0}),
                 call('test', params={**default_params, 'page': 1}),
                 call('test', params={**default_params, 'page': 2})
                 ]
        my_request.assert_has_calls(calls)

    @patch.object(conf, 'pyxis_index_image_organizations', new=['org1', 'org2'])
    @patch('freshmaker.pyxis.Pyxis._pagination')
    def test_get_operator_indices(self, page):
        self.px.get_operator_indices()
        page.assert_called_once_with(
            'operators/indices', {'filter': 'organization==org1 or organization==org2'})

    @patch.object(conf, "product_pages_api_url", new="http://pp.example.com/api")
    @patch("freshmaker.pyxis.Pyxis._pagination")
    def test_get_operator_indices_with_unreleased_filtered_out(self, page):
        pp_mock_data = [
            {
                "url": "http://pp.example.com/api/releases/openshift-4.5/schedule-tasks",
                "json": [{"name": "GA", "date_finish": "2020-02-05"}]
            },
            {
                "url": "http://pp.example.com/api/releases/openshift-4.6/schedule-tasks",
                "json": [{"name": "GA", "date_finish": "2020-05-23"}]
            },
            {
                "url": "http://pp.example.com/api/releases/openshift-4.8/schedule-tasks",
                "json": [{"name": "GA", "date_finish": "2021-08-12"}]
            }
        ]
        page.return_value = self.indices + [
            {
                "_id": "3",
                "created_by": "meteor",
                "creation_date": "2020-11-01T08:23:28.253000+00:00",
                "last_update_date": "2020-11-01T08:23:28.253000+00:00",
                "last_updated_by": "meteor",
                "ocp_version": "4.8",
                "organization": "org",
                "path": ""
            }
        ]
        now = datetime(year=2020, month=12, day=15, hour=0, minute=0, second=0)

        with requests_mock.Mocker() as http:
            for data in pp_mock_data:
                http.get(data["url"], json=data["json"])

            with freeze_time(now):
                indices = self.px.get_operator_indices()

        assert len(indices) == 3
        assert "4.8" not in [i["ocp_version"] for i in indices]

    @patch('freshmaker.pyxis.Pyxis._pagination')
    def test_get_latest_bundles(self, page):
        page_copy = self.copy_call_args(page)
        # Ensure this one is ignored
        bad_version_bundle = {
            "channel_name": "test-v2.3",
            "related_images": [
                {
                    "image": "registry/quay/quay-operator@sha256:ddd",
                    "name": "quay-operator-annotation",
                    "digest": "sha256:ddd"
                },
                {
                    "image": "registry/quay/quay-security-r-operator@sha256:eee",
                    "name": "container-security-operator",
                    "digest": "sha256:eee"
                }
            ],
            "version": "version_me"
        }
        page_copy.side_effect = [self.bundles[:3] + [bad_version_bundle], []]

        out = self.px.get_latest_bundles(self.indices)
        expected_out = self.bundles[:3]

        self.assertEqual(out, expected_out)
        page_copy.assert_has_calls([
            call('operators/bundles',
                 {'include': 'data.channel_name,data.version,'
                             'data.related_images,data.bundle_path_digest,'
                             'data.bundle_path,data.csv_name',
                  'filter': 'latest_in_channel==true and '
                            'source_index_container_path==path/to/registry:v4.5'}),
            call('operators/bundles',
                 {'include': 'data.channel_name,data.version,'
                             'data.related_images,data.bundle_path_digest,'
                             'data.bundle_path,data.csv_name',
                  'filter': 'latest_in_channel==true and '
                            'source_index_container_path==path/to/registry:v4.6'}),
        ])

    @patch.object(conf, 'image_build_repository_registries', new=['reg1'])
    @patch('freshmaker.pyxis.Pyxis._pagination')
    def test_get_manifest_list_digest_by_nvr(self, page):
        page.return_value = self.images
        digest = self.px.get_manifest_list_digest_by_nvr('s2i-1-2')

        expected_digest = 'sha256:1112'
        self.assertEqual(digest, expected_digest)
        page.assert_called_once_with(
            'images/nvr/s2i-1-2',
            {'include': 'data.brew,data.repositories'}
        )

    def test_get_bundles_by_related_image_digest(self):
        digest = 'sha256:111'
        new_bundles = self.px.get_bundles_by_related_image_digest(
            digest, self.bundles)

        expected_bundles = [self.bundles[0]]
        self.assertListEqual(new_bundles, expected_bundles)

    @patch('freshmaker.pyxis.Pyxis._pagination')
    def test_get_bundles_by_digest(self, page):
        page.return_value = {"some_bundle"}
        digest = "some_digest"

        self.px.get_bundles_by_digest(digest)

        page.assert_called_once_with("operators/bundles", {
            "include": "data.version,data.csv_name",
            "filter": "bundle_path_digest==some_digest"
        })

    @patch('freshmaker.pyxis.requests.get')
    def test_get_images_by_digest(self, mock_get):
        image_1 = {
            'brew': {
                'build': 'foo-operator-2.1-2',
                'nvra': 'foo-operator-2.1-2.amd64',
                'package': 'foo',
            },
            'repositories': [
                {
                    'content_advisory_ids': [],
                    'manifest_list_digest': 'sha256:12345',
                    'manifest_schema2_digest': 'sha256:23456',
                    'published': True,
                    'registry': 'registry.example.com',
                    'repository': 'foo/foo-operator-bundle',
                    'tags': [{'name': '2'}, {'name': '2.1'}],
                }
            ],
        }
        fake_responses = [Mock(ok=True), Mock(ok=True)]
        fake_responses[0].json.return_value = {'data': [image_1]}
        fake_responses[1].json.return_value = {'data': []}
        mock_get.side_effect = fake_responses

        digest = 'sha256:23456'
        images = self.px.get_images_by_digest(digest)
        self.assertListEqual(images, [image_1])

    @patch('freshmaker.pyxis.requests.get')
    def test_get_auto_rebuild_tags(self, mock_get):
        mock_get.return_value = Mock(ok=True)
        mock_get.return_value.json.return_value = {
            '_links': {},
            'auto_rebuild_tags': [
                '2.3',
                'latest'
            ]
        }

        tags = self.px.get_auto_rebuild_tags('registry.example.com', 'foo/foo-operator-bundle')
        self.assertListEqual(tags, ['2.3', 'latest'])
