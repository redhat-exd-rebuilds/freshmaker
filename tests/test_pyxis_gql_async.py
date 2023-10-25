# -*- coding: utf-8 -*-
#
# Copyright (c) 2022  Red Hat, Inc.
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

import asyncio
import os
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from flexmock import flexmock
from gql.dsl import DSLSchema
from graphql import GraphQLSchema, build_ast_schema, parse

from freshmaker.pyxis_gql_async import PyxisAsyncGQL, PyxisGQLRequestError


def load_schema() -> GraphQLSchema:
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)
    return schema


# this mock is replicated in all test functions inside this class
@patch("freshmaker.pyxis_gql_async.Client", autospec=True)
class TestPyxisAsyncGQL(TestCase):
    @patch("freshmaker.pyxis_gql_async.ssl.SSLContext.load_cert_chain")
    def setUp(self, mock_load_cert):
        self.schema = load_schema()
        flexmock(PyxisAsyncGQL).should_receive("dsl_schema").and_return(DSLSchema(self.schema))
        self.pyxis_gql_async = PyxisAsyncGQL(
            url="https://graphql.pyxis.local", certpath="", keypath=""
        )

    def test_query(self, mock_gql_client):
        ds = self.pyxis_gql_async.dsl_schema
        fake_query = ds.Query.find_repositories(page=0, page_size=2, filter={}).select(
            ds.ContainerRepositoryPaginatedResponse.error.select(
                ds.ResponseError.status,
                ds.ResponseError.detail,
            ),
            ds.ContainerRepositoryPaginatedResponse.page,
            ds.ContainerRepositoryPaginatedResponse.page_size,
            ds.ContainerRepositoryPaginatedResponse.total,
            ds.ContainerRepositoryPaginatedResponse.data.select(
                *self.pyxis_gql_async._get_repo_projection()
            ),
        )
        expected = {"find_repositories": {"data": ["fake_data"], "error": None}}
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(
            expected
        )

        result = asyncio.run(self.pyxis_gql_async.query(fake_query))

        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert result == expected

    def test_find_repositories(self, mock_gql_client):
        result = {
            "find_repositories": {
                "data": [
                    {
                        "auto_rebuild_tags": ["latest"],
                        "registry": "registry.example.com",
                        "release_categories": ["Generally Available"],
                        "repository": "foobar/foo",
                    },
                    {
                        "auto_rebuild_tags": ["latest"],
                        "registry": "registry.example.com",
                        "release_categories": ["Generally Available"],
                        "repository": "foobar/bar",
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 2,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        repositories = asyncio.run(self.pyxis_gql_async.find_repositories())

        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert repositories == result["find_repositories"]["data"]

    def test_find_repositories_by_repo_name(self, mock_gql_client):
        result = {
            "find_repositories": {
                "data": [{"foo": "bar"}],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 1,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        repositories = asyncio.run(
            self.pyxis_gql_async.find_repositories_by_repository_name(repository="foo")
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert repositories == result["find_repositories"]["data"]

    def test_find_repositories_by_registry_paths(self, mock_gql_client):
        result = {
            "find_repositories": {
                "data": [{"foo": "bar"}],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 1,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        repository = asyncio.run(
            self.pyxis_gql_async.find_repositories_by_registry_paths(
                [{"registry": "foo-registry", "repository": "foobar"}]
            )
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert repository == result["find_repositories"]["data"]

    def test_get_repository_by_registry_path(self, mock_gql_client):
        result = {
            "get_repository_by_registry_path": {
                "data": {
                    "auto_rebuild_tags": ["1.0", "1.1"],
                    "registry": "registry.example.com",
                    "release_categories": ["Generally " "Available"],
                    "repository": "foobar/foobar-operator",
                },
                "error": None,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        repository = asyncio.run(
            self.pyxis_gql_async.get_repository_by_registry_path(
                "foobar/foobar-operator", "registry.example.com"
            )
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert repository == result["get_repository_by_registry_path"]["data"]

    def test_find_images_by_nvr(self, mock_gql_client):
        result = {
            "find_images_by_nvr": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        },
                                        {
                                            "name": "bar",
                                            "nvra": "bar-20-220.el8.noarch",
                                            "srpm_name": "bar",
                                            "srpm_nevra": "bar-20-220.el8.src",
                                        },
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                    {
                        "architecture": "arm64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-aarch64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        },
                                        {
                                            "name": "bar",
                                            "nvra": "bar-20-220.el8.noarch",
                                            "srpm_name": "bar",
                                            "srpm_nevra": "bar-20-220.el8.src",
                                        },
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 2,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        images = asyncio.run(
            self.pyxis_gql_async.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert images == result["find_images_by_nvr"]["data"]

    def test_find_images_by_nvrs(self, mock_gql_client):
        result = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        }
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                    {
                        "architecture": "arm64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-aarch64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        }
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 2,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        nvrs = ["foobar-container-v0.13.0-12.1582340001"]
        images = asyncio.run(self.pyxis_gql_async.find_images_by_nvrs(nvrs, include_rpms=True))
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        expected = deepcopy(result["find_images"]["data"])
        assert images == expected

    def test_find_images_by_installed_rpms(self, mock_gql_client):
        result = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        },
                                        {
                                            "name": "bar",
                                            "nvra": "bar-20-220.el8.noarch",
                                            "srpm_name": "bar",
                                            "srpm_nevra": "bar-20-220.el8.src",
                                        },
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                    {
                        "architecture": "arm64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-aarch64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-123.el8.src",
                                        },
                                        {
                                            "name": "bar",
                                            "nvra": "bar-20-220.el8.noarch",
                                            "srpm_name": "bar",
                                            "srpm_nevra": "bar-20-220.el8.src",
                                        },
                                    ]
                                }
                            }
                        },
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 2,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        rpm_names = ["foo"]
        content_sets = ["rhel-8-for-x86_64-baseos-rpms"]
        repositories = ["dummy/foobar-rhel8"]
        tags = ["v0.13"]
        images = asyncio.run(
            self.pyxis_gql_async.find_images_by_installed_rpms(
                rpm_names,
                content_sets=content_sets,
                repositories=repositories,
                tags=tags,
            )
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        expected = deepcopy(result["find_images"]["data"])
        for image in expected:
            # Expect the unmatched rpms to be removed from rpm_manifest data
            rpms = image["edges"]["rpm_manifest"]["data"]["rpms"]
            image["edges"]["rpm_manifest"]["data"]["rpms"] = [
                x for x in rpms if x["name"] in rpm_names
            ]
        assert images == expected

    def test_find_images_by_names(self, mock_gql_client):
        result = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                    {
                        "architecture": "arm64",
                        "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                        "content_sets": ["rhel-8-for-aarch64-baseos-rpms"],
                        "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                        "parsed_data": {},
                        "repositories": [
                            {
                                "published": True,
                                "registry": "registry.example.com",
                                "repository": "dummy/foobar-rhel8",
                                "tags": [{"name": "v0.13"}],
                            }
                        ],
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 2,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        images = asyncio.run(self.pyxis_gql_async.find_images_by_names(["foobar-container"]))
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert images == result["find_images"]["data"]

    def test_find_images_by_repository(self, mock_gql_client):
        result = {
            "find_images": {
                "data": [{"foo": "bar"}],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 1,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        images = asyncio.run(
            self.pyxis_gql_async.find_images_by_repository(
                repository="foo-repo", auto_rebuild_tags=["foo-tag"]
            )
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert images == result["find_images"]["data"]

    def test_find_latest_images_by_name_version(self, mock_gql_client):
        result = {
            "find_images": {
                "data": [{"foo": "bar"}],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 1,
            }
        }
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        images = asyncio.run(
            self.pyxis_gql_async.find_latest_images_by_name_version(name="foo-repo", version="1.23")
        )
        mock_gql_client.return_value.__aenter__.return_value.execute.assert_awaited()
        assert images == result["find_images"]["data"]

    @patch("freshmaker.pyxis_gql.RequestsHTTPTransport", autospec=True)
    def test_log_trace_id(self, mock_transport, mock_gql_client):
        result = {
            "find_images": {
                "data": [],
                "error": ["something went wrong"],
                "page": 0,
                "page_size": 250,
                "total": 2,
            }
        }

        mock_transport.return_value.response_headers = {"trace_id": "123"}
        mock_gql_client.return_value.__aenter__.return_value.transport = mock_transport.return_value
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(result)

        with self.assertRaises(PyxisGQLRequestError) as cm:
            asyncio.run(
                self.pyxis_gql_async.find_latest_images_by_name_version(
                    name="foo-repo", version="1.23"
                )
            )
        exception = cm.exception
        self.assertEqual(exception.error, str(result["find_images"]["error"]))
        self.assertEqual(
            exception.trace_id, mock_transport.return_value.response_headers["trace_id"]
        )
