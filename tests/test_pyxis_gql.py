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

import copy
import os
from unittest.mock import patch

from flexmock import flexmock
from gql import Client
from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse

from freshmaker.pyxis_gql import PyxisGQL, PyxisGQLRequestError


def test_pyxis_graphql_find_repositories():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

    result = {
        "find_repositories": {
            "data": [
                {
                    "auto_rebuild_tags": ["latest"],
                    "published": True,
                    "release_categories": ["Generally Available"],
                    "repository": "foobar/foo",
                },
                {
                    "auto_rebuild_tags": ["latest"],
                    "published": True,
                    "release_categories": ["Generally Available"],
                    "repository": "foobar/bar",
                },
            ],
            "error": None,
            "page": 0,
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    repositories = pyxis_gql.find_repositories()

    assert repositories == result["find_repositories"]["data"]


def test_pyxis_graphql_get_repository_by_registry_path():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

    result = {
        "get_repository_by_registry_path": {
            "data": {
                "auto_rebuild_tags": ["1.0", "1.1"],
                "published": True,
                "release_categories": ["Generally " "Available"],
                "repository": "foobar/foobar-operator",
            },
            "error": None,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    repository = pyxis_gql.get_repository_by_registry_path(
        "foobar/foobar-operator", "registry.example.com"
    )

    assert repository == result["get_repository_by_registry_path"]["data"]


def test_pyxis_graphql_find_images_by_installed_rpms():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

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
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    rpm_names = ["foo"]
    content_sets = ["rhel-8-for-x86_64-baseos-rpms"]
    repositories = ["dummy/foobar-rhel8"]
    tags = ["v0.13"]

    images = pyxis_gql.find_images_by_installed_rpms(
        rpm_names, content_sets=content_sets, repositories=repositories, tags=tags
    )
    expected = copy.deepcopy(result["find_images"]["data"])
    for image in expected:
        # Expect the unmatched rpms to be removed from rpm_manifest data
        rpms = image["edges"]["rpm_manifest"]["data"]["rpms"]
        image["edges"]["rpm_manifest"]["data"]["rpms"] = [x for x in rpms if x["name"] in rpm_names]
    assert images == expected


def test_pyxis_graphql_find_images_by_nvr():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

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
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    images = pyxis_gql.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
    assert images == result["find_images_by_nvr"]["data"]


def test_pyxis_graphql_find_images_by_nvrs():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

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
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    nvrs = ["foobar-container-v0.13.0-12.1582340001"]
    images = pyxis_gql.find_images_by_nvrs(nvrs, include_rpms=True)
    expected = copy.deepcopy(result["find_images"]["data"])

    assert images == expected


def test_pyxis_graphql_find_images_by_names():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

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
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    images = pyxis_gql.find_images_by_names(["foobar-container"])
    assert images == result["find_images"]["data"]


def test_pyxis_graphql_find_latest_images_by_name_version():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

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
                            "tags": [{"name": "v0.13.0"}],
                        }
                    ],
                },
                {
                    "architecture": "arm64",
                    "brew": {"build": "foobar-container-v0.13.0-12.1582340001"},
                    "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                    "parent_brew_build": "ubi8-minimal-container-8.6-100.1582220001",
                    "parsed_data": {},
                    "repositories": [
                        {
                            "published": True,
                            "registry": "registry.example.com",
                            "repository": "dummy/foobar-rhel8",
                            "tags": [{"name": "v0.13.0"}],
                        }
                    ],
                },
            ],
            "error": None,
            "page": 0,
            "page_size": 250,
            "total": 2,
        }
    }

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    images = pyxis_gql.find_latest_images_by_name_version(
        "foobar-container",
        "v0.13.0",
        published=True,
        content_sets=["rhel-8-for-x86_64-baseos-rpms"],
    )
    assert images == result["find_images"]["data"]


def test_pyxis_graphql_find_latest_images_by_name_version_empty():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

    result = {
        "find_images": {
            "data": [],
            "error": None,
            "page": 0,
            "page_size": 250,
            "total": 0,
        }
    }
    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    images = pyxis_gql.find_latest_images_by_name_version(
        "foobar-container",
        "v0.13.0",
        published=True,
        content_sets=["rhel-8-for-x86_64-baseos-rpms"],
    )
    assert not images


@patch("freshmaker.pyxis_gql.RequestsHTTPTransport", autospec=True)
@patch("freshmaker.pyxis_gql.Client", autospec=True)
def test_log_trace_id(mock_client, mock_transport):
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    result = {
        "find_images": {
            "data": [],
            "error": {"status": 500, "detail": "something went wrong"},
            "page": 0,
            "page_size": 250,
            "total": 2,
        }
    }

    mock_transport.return_value.response_headers = {"trace_id": "123"}
    mock_client.return_value.transport = mock_transport.return_value
    mock_client.return_value.execute.return_value = copy.deepcopy(result)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))
    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert="/path/to/cert")

    try:
        pyxis_gql.find_latest_images_by_name_version(
            "foobar-container",
            "v0.13.0",
            published=True,
            content_sets=["rhel-8-for-x86_64-baseos-rpms"],
        )
    except PyxisGQLRequestError as e:
        assert e.error == str(result["find_images"]["error"])
        assert e.trace_id == mock_transport.return_value.response_headers["trace_id"]
