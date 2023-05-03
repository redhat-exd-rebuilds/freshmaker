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
from copy import deepcopy
import os
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from flexmock import flexmock
from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse, GraphQLSchema

from freshmaker.pyxis_gql_async import PyxisAsyncGQL


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


async def async_run_twice(f, *args, **kwargs) -> list[Any]:
    task1 = asyncio.create_task(f(*args, **kwargs))
    task2 = asyncio.create_task(f(*args, **kwargs))
    results = await asyncio.gather(task1, task2)
    return results


def check_asyncness(f, *args, **kwargs) -> tuple[Any, Any, Any]:
    """Checks if execution time of function f is compatible with an assynchronous implementation.

    This function will:
        - make a first run of the function f and collect the execution time
        - call f two times assynchronously, and collect the combined execution time
        - check if the combined time is less than twice the individual execution time

    This check is important to make sure no blocking calls are stopping a function that is
    intended to be assynchronous.
    """
    from time import perf_counter

    # let's use a high tolerance (almost 2s) since we will be returning in cpu-bound regime,
    # instead of io-bound, when we mock things in the unit tests below
    tolerance_multiplier = 1.9

    t0 = perf_counter()
    res1 = asyncio.run(f(*args, **kwargs))
    t1 = perf_counter()
    T = t1 - t0

    t2 = perf_counter()
    [res2, res3] = asyncio.run(async_run_twice(f, *args, **kwargs))
    t3 = perf_counter()

    dt = t3 - t2
    assert (
        dt < tolerance_multiplier * T
    ), f"Async call too slow, did you call everything asynchronously? dt={dt}, T={T}"
    return res1, res2, res3


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
        fake_query = ds.Query.find_repositories(
            page=0,
            page_size=2,
            filter={},
        ).select(
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
        expected = {"fake_query": {"data": ["fake_data"]}}
        mock_gql_client.return_value.__aenter__.return_value.execute.return_value = deepcopy(
            expected
        )

        (result, _, _) = check_asyncness(self.pyxis_gql_async.query, fake_query)

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

        (repositories, _, _) = check_asyncness(self.pyxis_gql_async.find_repositories)

        assert repositories == result["find_repositories"]["data"]

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

        (repository, _, _) = check_asyncness(
            self.pyxis_gql_async.get_repository_by_registry_path,
            "foobar/foobar-operator",
            "registry.example.com",
        )

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
        (images, _, _) = check_asyncness(
            self.pyxis_gql_async.find_images_by_nvr, "foobar-container-v0.13.0-12.1582340001"
        )

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
        (images, _, _) = check_asyncness(
            self.pyxis_gql_async.find_images_by_nvrs, nvrs, include_rpms=True
        )

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
        (images, _, _) = check_asyncness(
            self.pyxis_gql_async.find_images_by_installed_rpms,
            rpm_names,
            content_sets=content_sets,
            repositories=repositories,
            tags=tags,
        )

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

        (images, _, _) = check_asyncness(
            self.pyxis_gql_async.find_images_by_names, ["foobar-container"]
        )

        assert images == result["find_images"]["data"]
