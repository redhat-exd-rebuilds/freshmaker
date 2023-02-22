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
from flexmock import flexmock
from gql import Client
from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse

from freshmaker.container import Container, ContainerAPI
from freshmaker.kojiservice import KojiService
from freshmaker.odcsclient import RetryingODCS
from freshmaker.pyxis_gql import PyxisGQL


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

    container_api = ContainerAPI(pyxis_graphql_url="graphql.pyxis.local")
    containers = container_api.find_auto_rebuild_containers_with_older_rpms(
        rpm_nvrs=rpm_nvrs, content_sets=content_sets, published=True
    )
    assert len(containers) == 1
    assert containers[0].nvr == "foobar-container-v0.12.2-5"


def test_resolve_image_build_metadata():
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
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    buildinfo = {
        "build_id": 212121,
        "cg_id": 1,
        "cg_name": "atomic-reactor",
        "epoch": None,
        "extra": {
            "container_koji_task_id": 23232323,
            "image": {
                "autorebuild": False,
                "help": None,
                "isolated": True,
                "odcs": {
                    "compose_ids": [123, 124, 125, 126],
                    "signing_intent": "release",
                    "signing_intent_overridden": False,
                },
                "parent_build_id": 202020,
                "parent_image_builds": {
                    "registry.example.com/ubi8/ubi-minimal:8.6-100": {
                        "id": 202020,
                        "nvr": "ubi8-minimal-container-8.6-100",
                    },
                },
                "parent_images": [
                    "registry.example.com/ubi8/ubi-minimal:8.6-100",
                ],
                "remote_sources": [
                    {
                        "name": None,
                        "url": "https://cachito.engineering.redhat.com/api/v1/requests/427897",
                    }
                ],
            },
        },
        "id": 212121,
        "name": "foobar-container",
        "nvr": "foobar-container-v0.13.0-12.1582340001",
        "package_id": 123,
        "package_name": "foobar-container",
        "release": "12.1582340001",
        "source": "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "state": 1,
        "task_id": None,
        "version": "v0.13.0",
        "volume_id": 0,
        "volume_name": "DEFAULT",
    }
    flexmock(KojiService).should_receive("get_build").and_return(buildinfo)

    task_params = [
        "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "foobar-rhel-8-containers-candidate",
        {
            "arch_override": "aarch64 x86_64",
            "compose_ids": [123, 124, 125, 126],
            "git_branch": "foobar-rhel-8",
            "isolated": True,
            "koji_parent_build": "ubi8-minimal-container-8.6-100",
            "release": "12.1582340001",
            "scratch": False,
        },
    ]
    flexmock(KojiService).should_receive("get_task_request").and_return(task_params)

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local")

    images = pyxis_gql.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
    container = Container.load(images[0])
    for img in images[1:]:
        container.add_arch(img)

    koji_session = KojiService()
    container.resolve_build_metadata(koji_session)

    assert container.build_metadata["commit"] == "5cb45172e9108e894bb43cbc76b74ed159594f66"
    assert container.build_metadata["git_branch"] == "foobar-rhel-8"
    assert container.build_metadata["parent_build_id"] == 202020
    assert container.build_metadata["repository"] == "containers/foobar"
    assert container.build_metadata["target"] == "foobar-rhel-8-containers-candidate"
    assert sorted(container.build_metadata["odcs_compose_ids"]) == [123, 124, 125, 126]


def test_resolve_image_compose_sources():
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
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    buildinfo = {
        "build_id": 212121,
        "cg_id": 1,
        "cg_name": "atomic-reactor",
        "epoch": None,
        "extra": {
            "container_koji_task_id": 23232323,
            "image": {
                "autorebuild": False,
                "help": None,
                "isolated": True,
                "odcs": {
                    "compose_ids": [123, 124],
                    "signing_intent": "release",
                    "signing_intent_overridden": False,
                },
                "parent_build_id": 202020,
                "parent_image_builds": {
                    "registry.example.com/ubi8/ubi-minimal:8.6-100": {
                        "id": 202020,
                        "nvr": "ubi8-minimal-container-8.6-100",
                    },
                },
                "parent_images": [
                    "registry.example.com/ubi8/ubi-minimal:8.6-100",
                ],
            },
        },
        "id": 212121,
        "name": "foobar-container",
        "nvr": "foobar-container-v0.13.0-12.1582340001",
        "package_id": 123,
        "package_name": "foobar-container",
        "release": "12.1582340001",
        "source": "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "state": 1,
        "task_id": None,
        "version": "v0.13.0",
        "volume_id": 0,
        "volume_name": "DEFAULT",
    }
    flexmock(KojiService).should_receive("get_build").and_return(buildinfo)

    task_params = [
        "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "foobar-rhel-8-containers-candidate",
        {
            "arch_override": "aarch64 x86_64",
            "compose_ids": [123],
            "git_branch": "foobar-rhel-8",
            "isolated": True,
            "koji_parent_build": "ubi8-minimal-container-8.6-100",
            "release": "12.1582340001",
            "scratch": False,
        },
    ]
    flexmock(KojiService).should_receive("get_task_request").and_return(task_params)

    odcs_composes = [
        {
            "arches": "aarch64",
            "id": 123,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-x86_64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-1449617",
        },
        {
            "arches": "x86_64",
            "id": 124,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-aarch64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-124",
        },
    ]
    flexmock(RetryingODCS).should_receive("get_compose").and_return(odcs_composes).one_by_one()

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local")

    images = pyxis_gql.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
    container = Container.load(images[0])
    for img in images[1:]:
        container.add_arch(img)

    koji_session = KojiService()
    container.resolve_build_metadata(koji_session)
    container.resolve_compose_sources()
    assert sorted(container.compose_sources) == [
        "rhel-8-for-aarch64-baseos-rpms",
        "rhel-8-for-x86_64-baseos-rpms",
    ]


def test_resolve_content_sets():
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
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    buildinfo = {
        "build_id": 212121,
        "cg_id": 1,
        "cg_name": "atomic-reactor",
        "epoch": None,
        "extra": {
            "container_koji_task_id": 23232323,
            "image": {
                "autorebuild": False,
                "help": None,
                "isolated": True,
                "odcs": {
                    "compose_ids": [123, 124],
                    "signing_intent": "release",
                    "signing_intent_overridden": False,
                },
                "parent_build_id": 202020,
                "parent_image_builds": {
                    "registry.example.com/ubi8/ubi-minimal:8.6-100": {
                        "id": 202020,
                        "nvr": "ubi8-minimal-container-8.6-100",
                    },
                },
                "parent_images": [
                    "registry.example.com/ubi8/ubi-minimal:8.6-100",
                ],
            },
        },
        "id": 212121,
        "name": "foobar-container",
        "nvr": "foobar-container-v0.13.0-12.1582340001",
        "package_id": 123,
        "package_name": "foobar-container",
        "release": "12.1582340001",
        "source": "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "state": 1,
        "task_id": None,
        "version": "v0.13.0",
        "volume_id": 0,
        "volume_name": "DEFAULT",
    }
    flexmock(KojiService).should_receive("get_build").and_return(buildinfo)

    task_params = [
        "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "foobar-rhel-8-containers-candidate",
        {
            "arch_override": "aarch64 x86_64",
            "compose_ids": [123],
            "git_branch": "foobar-rhel-8",
            "isolated": True,
            "koji_parent_build": "ubi8-minimal-container-8.6-100",
            "release": "12.1582340001",
            "scratch": False,
        },
    ]
    flexmock(KojiService).should_receive("get_task_request").and_return(task_params)

    odcs_composes = [
        {
            "arches": "aarch64",
            "id": 123,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-x86_64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-1449617",
        },
        {
            "arches": "x86_64",
            "id": 124,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-aarch64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-124",
        },
    ]
    flexmock(RetryingODCS).should_receive("get_compose").and_return(
        odcs_composes
    ).one_by_one()

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local")

    images = pyxis_gql.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
    container = Container.load(images[0])
    for img in images[1:]:
        container.add_arch(img)

    koji_session = KojiService()
    container.resolve_build_metadata(koji_session)
    container.resolve_compose_sources()
    container.resolve_content_sets(pyxis_gql, koji_session)
    assert container.content_sets_by_arch == {
        "amd64": ["rhel-8-for-x86_64-baseos-rpms"],
        "arm64": ["rhel-8-for-aarch64-baseos-rpms"],
    }


def test_resolve_published():
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
    flexmock(Client).should_receive("execute").and_return(copy.deepcopy(result))

    buildinfo = {
        "build_id": 212121,
        "cg_id": 1,
        "cg_name": "atomic-reactor",
        "epoch": None,
        "extra": {
            "container_koji_task_id": 23232323,
            "image": {
                "autorebuild": False,
                "help": None,
                "isolated": True,
                "odcs": {
                    "compose_ids": [123, 124],
                    "signing_intent": "release",
                    "signing_intent_overridden": False,
                },
                "parent_build_id": 202020,
                "parent_image_builds": {
                    "registry.example.com/ubi8/ubi-minimal:8.6-100": {
                        "id": 202020,
                        "nvr": "ubi8-minimal-container-8.6-100",
                    },
                },
                "parent_images": [
                    "registry.example.com/ubi8/ubi-minimal:8.6-100",
                ],
            },
        },
        "id": 212121,
        "name": "foobar-container",
        "nvr": "foobar-container-v0.13.0-12.1582340001",
        "package_id": 123,
        "package_name": "foobar-container",
        "release": "12.1582340001",
        "source": "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "state": 1,
        "task_id": None,
        "version": "v0.13.0",
        "volume_id": 0,
        "volume_name": "DEFAULT",
    }
    flexmock(KojiService).should_receive("get_build").and_return(buildinfo)

    task_params = [
        "git://pkgs.example.com/containers/foobar#5cb45172e9108e894bb43cbc76b74ed159594f66",
        "foobar-rhel-8-containers-candidate",
        {
            "arch_override": "aarch64 x86_64",
            "compose_ids": [123],
            "git_branch": "foobar-rhel-8",
            "isolated": True,
            "koji_parent_build": "ubi8-minimal-container-8.6-100",
            "release": "12.1582340001",
            "scratch": False,
        },
    ]
    flexmock(KojiService).should_receive("get_task_request").and_return(task_params)

    odcs_composes = [
        {
            "arches": "aarch64",
            "id": 123,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-x86_64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-1449617",
        },
        {
            "arches": "x86_64",
            "id": 124,
            "sigkeys": "FD431D51",
            "source": "rhel-8-for-aarch64-baseos-rpms",
            "source_type": 4,
            "state": 3,
            "state_name": "removed",
            "toplevel_url": "http://download.example.com/odcs/prod/odcs-124",
        },
    ]
    flexmock(RetryingODCS).should_receive("get_compose").and_return(
        odcs_composes
    ).one_by_one()

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local")

    images = pyxis_gql.find_images_by_nvr("foobar-container-v0.13.0-12.1582340001")
    container = Container.load(images[0])
    for img in images[1:]:
        container.add_arch(img)

    koji_session = KojiService()
    container.resolve_build_metadata(koji_session)
    container.resolve_compose_sources()
    container.resolve_published(pyxis_gql)
    assert container.published is True
