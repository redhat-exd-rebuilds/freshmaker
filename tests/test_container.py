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

import os
from flexmock import flexmock
from gql import Client
from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse

from freshmaker.pyxis_gql import PyxisGQL
from freshmaker.container import ContainerAPI


def test_find_auto_rebuild_containers_with_older_rpms():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

    results = [
        {
            "find_repositories": {
                "data": [
                    {
                        "auto_rebuild_tags": ["v0.12", "v0.13"],
                        "registry": "registry.example.com",
                        "release_categories": ["Generally Available"],
                        "repository": "dummy/foobar-rhel8",
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 1,
            }
        },
        {
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
                    {
                        "architecture": "arm64",
                        "brew": {"build": "foobar-container-v0.12.2-5"},
                        "content_sets": ["rhel-8-for-aarch64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-100.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-100.el8.src",
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
                                "tags": [{"name": "v0.12"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "foobar-container-v0.12.2-5"},
                        "content_sets": ["rhel-8-for-x86_64-baseos-rpms"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "foo",
                                            "nvra": "foo-10-123.el8.noarch",
                                            "srpm_name": "foo",
                                            "srpm_nevra": "foo-10-100.el8.src",
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
                                "tags": [{"name": "v0.12"}],
                            }
                        ],
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 50,
                "total": 4,
            }
        },
    ]

    flexmock(Client).should_receive("execute").and_return(results).one_by_one()

    rpm_nvrs = ["foo-10-123.el8"]
    content_sets = ["rhel-8-for-x86_64-baseos-rpms", "rhel-8-for-aarch64-baseos-rpms"]

    container_api = ContainerAPI(
        pyxis_graphql_url="graphql.pyxis.local", pyxis_cert=("/path/to/crt", "/path/to/key")
    )
    containers = container_api.find_auto_rebuild_containers_with_older_rpms(
        rpm_nvrs=rpm_nvrs, content_sets=content_sets, published=True
    )
    assert len(containers) == 1
    assert containers[0].nvr == "foobar-container-v0.12.2-5"
