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

import copy
import pytest

from unittest import mock
from unittest.mock import patch, Mock

import freshmaker

from freshmaker.image import (
    ContainerImage,
    ContainerRepository,
    ExtraRepoNotConfiguredError,
    ImageGroup,
    PyxisAPI,
)
from freshmaker.utils import sorted_by_nvr
from tests.test_handler import MyHandler
from tests import helpers


class TestContainerImageObject(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestContainerImageObject, self).setUp()

        self.koji_read_config_patcher = patch(
            "koji.read_config", return_value={"server": "http://localhost/"}
        )
        self.koji_read_config_patcher.start()

        self.patcher = helpers.Patcher("freshmaker.image.")

        self.dummy_image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-1-4-12.10",
                    "package": "package-name-1",
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-0:1.2.3-1.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.3-1.amd64",
                            },
                            {
                                "srpm_name": "tespackage",
                                "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                "name": "tespackage",
                                "nvra": "testpackage-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            }
        )

    def tearDown(self):
        super(TestContainerImageObject, self).tearDown()
        self.patcher.unpatch_all()
        self.koji_read_config_patcher.stop()

    def test_create(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "completion_date": "20151210T10:09:35.000-0500",
                    "build": "jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6",
                    "package": "jboss-webserver-3-webserver30-tomcat7-openshift-docker",
                },
            }
        )

        self.assertEqual("1233829", image["_id"])
        self.assertEqual("20151210T10:09:35.000-0500", image["brew"]["completion_date"])

    def test_update_multi_arch(self):
        rpm_manifest_x86_64 = [{"rpms": [{"name": "spam"}]}]
        image_x86_64 = ContainerImage.create(
            {
                "_id": "1233829",
                "architecture": "amd64",
                "brew": {
                    "completion_date": "20151210T10:09:35.000-0500",
                    "build": "jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6",
                    "package": "jboss-webserver-3-webserver30-tomcat7-openshift-docker",
                },
                "rpm_manifest": rpm_manifest_x86_64,
            }
        )

        rpm_manifest_s390x = [{"rpms": [{"name": "maps"}]}]
        image_s390x = ContainerImage.create(
            {
                "_id": "1233829",
                "architecture": "s390x",
                "brew": {
                    "completion_date": "20151210T10:09:35.000-0500",
                    "build": "jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6",
                    "package": "jboss-webserver-3-webserver30-tomcat7-openshift-docker",
                },
                "rpm_manifest": rpm_manifest_s390x,
            }
        )

        self.assertEqual(image_x86_64["rpm_manifest"], rpm_manifest_x86_64)
        self.assertEqual(image_x86_64["multi_arch_rpm_manifest"], {"amd64": rpm_manifest_x86_64})
        self.assertEqual(image_s390x["rpm_manifest"], rpm_manifest_s390x)
        self.assertEqual(image_s390x["multi_arch_rpm_manifest"], {"s390x": rpm_manifest_s390x})

        image_x86_64.update_multi_arch(image_s390x)
        self.assertEqual(image_x86_64["rpm_manifest"], rpm_manifest_x86_64)
        self.assertEqual(
            image_x86_64["multi_arch_rpm_manifest"],
            {"amd64": rpm_manifest_x86_64, "s390x": rpm_manifest_s390x},
        )
        self.assertEqual(image_s390x["rpm_manifest"], rpm_manifest_s390x)
        self.assertEqual(image_s390x["multi_arch_rpm_manifest"], {"s390x": rpm_manifest_s390x})

        image_s390x.update_multi_arch(image_x86_64)
        self.assertEqual(image_x86_64["rpm_manifest"], rpm_manifest_x86_64)
        self.assertEqual(
            image_x86_64["multi_arch_rpm_manifest"],
            {"amd64": rpm_manifest_x86_64, "s390x": rpm_manifest_s390x},
        )
        self.assertEqual(image_s390x["rpm_manifest"], rpm_manifest_s390x)
        self.assertEqual(
            image_s390x["multi_arch_rpm_manifest"],
            {"amd64": rpm_manifest_x86_64, "s390x": rpm_manifest_s390x},
        )

    def test_log_error(self):
        image = ContainerImage.create(
            {
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
            }
        )

        image.log_error("foo")
        self.assertEqual(image["error"], "foo")

        image.log_error("bar")
        self.assertEqual(image["error"], "foo; bar")

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_commit_koji_fallback(self, get_task_request, get_build):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#commit_hash1",
            "target1",
            {},
        ]

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_commit_no_koji_build(self, get_task_request, get_build):
        get_build.return_value = {}

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], None)
        self.assertEqual(self.dummy_image["commit"], None)
        self.assertEqual(self.dummy_image["target"], None)
        self.assertTrue(
            "Cannot find Koji build with nvr package-name-1-4-12.10 in Koji"
            in self.dummy_image["error"]
        )

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_commit_no_task_id(self, get_task_request, get_build):
        get_build.return_value = {"task_id": None}

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], None)
        self.assertEqual(self.dummy_image["commit"], None)
        self.assertEqual(self.dummy_image["target"], None)
        self.assertTrue(
            "Cannot find task_id or container_koji_task_id in the Koji build {'task_id': None}"
            in self.dummy_image["error"]
        )

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_commit_flatpak(self, get_task_request, get_build):
        get_build.return_value = {
            "task_id": 123456,
            "extra": {"image": {"flatpak": True, "isolated": False}},
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#commit_hash1",
            "target1",
            {},
        ]

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image.get("flatpak"), True)
        self.assertEqual(self.dummy_image.get("isolated"), None)

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    @patch("freshmaker.kojiservice.KojiService.list_archives")
    def test_resolve_commit_prefer_build_source(self, list_archives, get_task_request, get_build):
        get_build.return_value = {
            "build_id": 67890,
            "task_id": 123456,
            "source": "git://example.com/rpms/repo-1?#commit_hash1",
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master",
            "target1",
            {},
        ]
        list_archives.return_value = [
            {"btype": "image", "extra": {"image": {"arch": "ppc64le"}}},
            {"btype": "image", "extra": {"image": {"arch": "s390x"}}},
        ]

        with patch.object(freshmaker.conf, "supply_arch_overrides", new=True):
            self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")
        self.assertEqual(self.dummy_image["arches"], "ppc64le s390x")

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    @patch("freshmaker.kojiservice.KojiService.list_archives")
    def test_resolve_commit_no_extra_repo(self, list_archives, get_task_request, get_build):
        get_build.return_value = {
            "build_id": 67890,
            "task_id": 123456,
            "source": "git://example.com/rpms/repo-1?#commit_hash1",
            "extra": {"filesystem_koji_task_id": 12345},
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master",
            "target1",
            {},
        ]
        list_archives.return_value = []

        self.assertRaises(
            ExtraRepoNotConfiguredError,
            self.dummy_image.get_additional_data_from_koji,
            self.dummy_image.nvr,
        )

        with patch.object(freshmaker.conf, "image_extra_repo", new={"package-name-1-4": ""}):
            self.dummy_image.get_additional_data_from_koji(self.dummy_image.nvr)

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_commit_invalid_hash(self, get_task_request, get_build):
        get_build.return_value = {"task_id": 123456, "source": "git://example.com/rpms/repo-1"}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master",
            "target1",
            {},
        ]

        self.dummy_image.resolve_commit()
        self.assertTrue(
            self.dummy_image["error"].find("Cannot find valid source of Koji build") != -1
        )

    @patch("freshmaker.image.ContainerImage.resolve_commit")
    def test_resolve_commit_exception(self, resolve_commit):
        resolve_commit.side_effect = ValueError("Expected exception.")
        self.dummy_image.resolve(None)
        self.assertEqual(
            self.dummy_image["error"], "Cannot resolve the container image: Expected exception."
        )

    def test_resolve_content_sets_already_included_in_pyxis_response(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repository": "foo",
                "git_branch": "branch",
                "commit": "commithash",
                "content_sets": ["dummy-contentset"],
            }
        )

        pyxis = Mock()
        image.resolve_content_sets(pyxis)
        self.assertEqual(image["content_sets"], ["dummy-contentset"])
        self.assertEqual(image["content_sets_source"], "pyxis_container_image")

    def test_resolve_content_sets_no_repositories(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repository": "foo",
                "git_branch": "branch",
                "commit": "commithash",
            }
        )
        self.assertTrue("content_sets" not in image)

        pyxis = Mock()
        image.resolve_content_sets(pyxis)
        self.assertEqual(image["content_sets"], [])

    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_resolve_content_sets_no_repositories_children_set(self, get_task_request, get_build):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repository": "foo",
                "git_branch": "branch",
                "commit": "commithash",
            }
        )
        self.assertTrue("content_sets" not in image)

        child1 = ContainerImage.create(
            {
                "_id": "1233828",
                "brew": {
                    "build": "child1-name-1-4-12.10",
                },
            }
        )

        child2 = ContainerImage.create(
            {
                "_id": "1233828",
                "brew": {
                    "build": "child2-name-1-4-12.10",
                },
                "content_sets": ["foo", "bar"],
            }
        )

        pyxis = Mock()
        image.resolve_content_sets(pyxis, children=[child1, child2])
        self.assertEqual(image["content_sets"], ["foo", "bar"])

    def test_resolve_content_sets_empty_repositories(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repositories": [],
                "repository": "foo",
                "git_branch": "branch",
                "commit": "commithash",
            }
        )
        self.assertTrue("content_sets" not in image)

        pyxis = Mock()
        image.resolve_content_sets(pyxis)
        self.assertEqual(image["content_sets"], [])

    def test_resolve_published(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repositories": [
                    {"published": True}
                ],
            }
        )

        pyxis = Mock()
        pyxis.find_images_by_nvr.return_value = [image]
        image.resolve_published(pyxis)
        self.assertEqual(image["published"], True)
        pyxis.find_images_by_nvr.assert_called_once_with("package-name-1-4-12.10")

    def test_resolve_published_unpublished(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
                "repositories": [
                    {"published": False}
                ],
                "edges": {"rpm_manifest": {"data": {"rpms": [{"name": "foobar"}]}}}
            }
        )

        pyxis = Mock()
        pyxis.find_images_by_nvr.return_value = [image]
        image.resolve_published(pyxis)
        self.assertEqual(image["published"], False)
        pyxis.find_images_by_nvr.assert_called_once_with("package-name-1-4-12.10")
        self.assertEqual(image["rpm_manifest"][0], {"rpms": [{'name': 'foobar'}]})

    def test_resolve_published_not_image_in_pyxis(self):
        image = ContainerImage.create(
            {
                "_id": "1233829",
                "brew": {
                    "build": "package-name-1-4-12.10",
                },
            }
        )

        pyxis = Mock()
        pyxis.find_images_by_nvr.return_value = []
        image.resolve_published(pyxis)


class TestContainerRepository(helpers.FreshmakerTestCase):
    def test_create(self):
        image = ContainerRepository.create(
            {
                "creationDate": "20160927T11:14:56.420-0400",
                "metrics": {
                    "pulls_in_last_30_days": 0,
                    "last_update_date": "20170223T08:28:40.913-0500",
                },
            }
        )

        self.assertEqual("20160927T11:14:56.420-0400", image["creationDate"])
        self.assertEqual(0, image["metrics"]["pulls_in_last_30_days"])
        self.assertEqual("20170223T08:28:40.913-0500", image["metrics"]["last_update_date"])


@pytest.mark.usefixtures("pyxis_graphql_schema")
class TestQueryFromPyxis(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestQueryFromPyxis, self).setUp()
        # Clear the ContainerImage Koji cache.
        ContainerImage.KOJI_BUILDS_CACHE = {}

        self.koji_read_config_patcher = patch(
            "koji.read_config", return_value={"server": "http://locahost/"}
        )
        self.koji_read_config_patcher.start()

        self.patcher = helpers.Patcher("freshmaker.image.")

        self.fake_server_url = "pyxis.localhost"
        self.fake_repositories_with_content_sets = [
            {
                "repository": "product/repo1",
                "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                "auto_rebuild_tags": ["latest", "tag1"],
                "release_categories": ["Generally Available"],
                "published": "true",
            },
            {
                "repository": "product2/repo2",
                "content_sets": ["dummy-content-set-1"],
                "auto_rebuild_tags": ["latest", "tag2"],
                "release_categories": ["Generally Available"],
                "published": "true",
            },
        ]

        self.fake_pyxis_find_repos = {
            "find_repositories": {
                "data": [
                    {
                        "repository": "product/repo1",
                        "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                        "auto_rebuild_tags": ["latest", "tag1"],
                        "release_categories": ["Generally Available"],
                        "published": "true",
                    },
                    {
                        "repository": "product2/repo2",
                        "content_sets": ["dummy-content-set-1"],
                        "auto_rebuild_tags": ["latest", "tag2"],
                        "release_categories": ["Generally Available"],
                        "published": "true",
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 250,
                "total": 2,
            }
        }

        foo_image_1_20_data = [
            {
                "architecture": "amd64",
                "brew": {"build": "foo-container-1-20"},
                "content_sets": ["foo-content-set-x86_64"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.x86_64",
                                },
                                {
                                    "srpm_name": "tespackage",
                                    "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                    "name": "tespackage",
                                    "nvra": "testpackage-1.2.3-1.x86_64",
                                },
                            ]
                        }
                    }
                },
                "parent_brew_build": "foo-parent-container-2-130",
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/foo-container/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/foo",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
            {
                "architecture": "ppc64le",
                "brew": {"build": "foo-container-1-20"},
                "content_sets": ["foo-content-set-ppc64le"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.ppc64le",
                                },
                                {
                                    "srpm_name": "tespackage",
                                    "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                    "name": "tespackage",
                                    "nvra": "testpackage-1.2.3-1.ppc64le",
                                },
                            ]
                        }
                    }
                },
                "parent_brew_build": "foo-parent-container-2-130",
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/foo-container/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/foo",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
        ]

        foo_parent_image_2_130_data = [
            {
                "architecture": "amd64",
                "brew": {"build": "foo-parent-container-2-130"},
                "content_sets": ["foo-content-set-x86_64"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.x86_64",
                                }
                            ]
                        }
                    }
                },
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/foo-parent-container/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/foo-parent",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
            {
                "architecture": "ppc64le",
                "brew": {"build": "foo-parent-container-2-130"},
                "content_sets": ["foo-content-set-ppc64le"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.ppc64le",
                                }
                            ]
                        }
                    }
                },
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/foo-parent-container/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/foo-parent",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
        ]

        bar_image_2_30_data = [
            {
                "architecture": "amd64",
                "brew": {"build": "bar-container-2-30"},
                "content_sets": ["bar-content-set-x86_64"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.x86_64",
                                },
                                {
                                    "srpm_name": "tespackage",
                                    "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                    "name": "tespackage",
                                    "nvra": "testpackage-1.2.3-1.x86_64",
                                },
                            ]
                        }
                    }
                },
                "parent_brew_build": "bar-parent-container-1-10",
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/bar-container/plain/Dockerfile?id=commit_hash2",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/bar",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
            {
                "architecture": "ppc64le",
                "brew": {"build": "bar-container-2-30"},
                "content_sets": ["bar-content-set-ppc64le"],
                "edges": {
                    "rpm_manifest": {
                        "data": {
                            "rpms": [
                                {
                                    "srpm_name": "openssl",
                                    "srpm_nevra": "openssl-0:1.2.3-1.src",
                                    "name": "openssl",
                                    "nvra": "openssl-1.2.3-1.ppc64le",
                                },
                                {
                                    "srpm_name": "tespackage",
                                    "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                    "name": "tespackage",
                                    "nvra": "testpackage-1.2.3-1.ppc64le",
                                },
                            ]
                        }
                    }
                },
                "parent_brew_build": "bar-parent-container-1-10",
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/bar-container/plain/Dockerfile?id=commit_hash2",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "repositories": [
                    {
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foobar-product/bar",
                        "tags": [{"name": "latest"}],
                    }
                ],
            },
        ]

        self.fake_pyxis_find_images_by_nvr = {
            "find_images_by_nvr": {
                "data": foo_image_1_20_data,
                "error": None,
                "page": 0,
                "page_size": 250,
                "total": 2,
            }
        }

        self.fake_pyxis_find_images_by_nvr_parent = {
            "find_images_by_nvr": {
                "data": foo_parent_image_2_130_data,
                "error": None,
                "page": 0,
                "page_size": 250,
                "total": 2,
            }
        }

        self.fake_pyxis_find_images_by_nvrs = {
            "find_images": {
                "data": foo_image_1_20_data + bar_image_2_30_data,
                "error": None,
                "page": 0,
                "page_size": 250,
                "total": 4,
            }
        }

        self.fake_images_with_parsed_data = [
            {
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-1-4-12.10",
                    "package": "package-name-1",
                },
                "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                "parent_brew_build": "some-original-nvr-7.6-252.1561619826",
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "repository": "product1/repo1",
                        "published": True,
                        "tags": [{"name": "latest"}],
                    }
                ],
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-0:1.2.3-1.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.3-1.amd64",
                            },
                            {
                                "srpm_name": "tespackage",
                                "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                "name": "tespackage",
                                "nvra": "testpackage-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            },
            {
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-2-4-12.10",
                    "package": "package-name-2",
                },
                "content_sets": ["dummy-content-set-1"],
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "repository": "product2/repo2",
                        "published": True,
                        "tags": [{"name": "latest"}],
                    }
                ],
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/repo-2/plain/Dockerfile?id=commit_hash2",
                            "filename": "Dockerfile",
                        },
                        {
                            "key": "bogusfile",
                            "content_url": "bogus_test_url",
                            "filename": "bogus.file",
                        },
                    ],
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-1:1.2.3-1.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.3-1.amd64",
                            },
                            {
                                "srpm_name": "tespackage2",
                                "srpm_nevra": "testpackage2-10:1.2.3-1.src",
                                "name": "tespackage2",
                                "nvra": "testpackage2-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            },
        ]

        self.fake_images_with_parsed_data_floating_tag = [
            {
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-3-4-12.10",
                    "package": "package-name-1",
                },
                "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "repository": "product2/repo2",
                        "published": True,
                        "tags": [{"name": "tag2"}],
                    }
                ],
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-0:1.2.3-1.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.3-1.amd64",
                            },
                            {
                                "srpm_name": "tespackage",
                                "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                "name": "tespackage",
                                "nvra": "testpackage-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            },
        ]

        self.fake_images_with_modules = [
            {
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-3-4-12.10",
                    "package": "package-name-1",
                },
                "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "repository": "product2/repo2",
                        "published": True,
                        "tags": [{"name": "tag2"}],
                    }
                ],
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-1.2.1-2.module+el8.0.0+3248+9d514f3b.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.1-2.module+el8.0.0+3248+9d514f3b.amd64",
                            },
                            {
                                "srpm_name": "tespackage",
                                "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                "name": "tespackage",
                                "nvra": "testpackage-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            },
        ]

        self.fake_images_with_parent_brew_build = [
            {
                "brew": {
                    "completion_date": "20170421T04:27:51.000-0400",
                    "build": "package-name-1-4-12.10",
                    "package": "package-name-1",
                },
                "content_sets": ["dummy-content-set-1", "dummy-content-set-2"],
                "parent_brew_build": "some-original-nvr-7.6-252.1561619826",
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "repository": "product1/repo1",
                        "published": True,
                        "tags": [{"name": "latest"}],
                    }
                ],
                "parsed_data": {
                    "files": [
                        {
                            "key": "buildfile",
                            "content_url": "http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1",
                            "filename": "Dockerfile",
                        }
                    ],
                },
                "rpm_manifest": [
                    {
                        "rpms": [
                            {
                                "srpm_name": "openssl",
                                "srpm_nevra": "openssl-0:1.2.3-1.src",
                                "name": "openssl",
                                "nvra": "openssl-1.2.3-1.amd64",
                            },
                            {
                                "srpm_name": "tespackage",
                                "srpm_nevra": "testpackage-10:1.2.3-1.src",
                                "name": "tespackage",
                                "nvra": "testpackage-1.2.3-1.amd64",
                            },
                        ]
                    }
                ],
            }
        ]

        self.fake_container_images = [
            ContainerImage.create(data) for data in self.fake_images_with_parsed_data
        ]

        self.fake_container_images_floating_tag = [
            ContainerImage.create(data) for data in self.fake_images_with_parsed_data_floating_tag
        ]

        self.fake_images_with_modules = [
            ContainerImage.create(data) for data in self.fake_images_with_modules
        ]

        self.fake_container_images_with_parent_brew_build = [
            ContainerImage.create(data) for data in self.fake_images_with_parent_brew_build
        ]

        self.fake_koji_builds = [{"task_id": 654321}, {"task_id": 123456}]
        self.fake_koji_task_requests = [
            [
                "git://pkgs.devel.redhat.com/rpms/repo-2#commit_hash2",
                "target2",
                {"git_branch": "mybranch"},
            ],
            [
                "git://pkgs.devel.redhat.com/rpms/repo-1#commit_hash1",
                "target1",
                {"git_branch": "mybranch"},
            ],
        ]
        self.current_db_event_id = MyHandler.current_db_event_id

    def tearDown(self):
        super(TestQueryFromPyxis, self).tearDown()
        self.patcher.unpatch_all()
        self.koji_read_config_patcher.stop()

    @patch.object(
        freshmaker.conf,
        "unpublished_exceptions",
        new=[{"repository": "some_repo", "registry": "some_registry"}],
    )
    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_find_all_repositories(self, exists, gql_client):
        exists.return_value = True
        gql_client.return_value.execute.return_value = self.fake_pyxis_find_repos
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_repositories()

        expected_ret = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }
        self.assertEqual(ret, expected_ret)

    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_find_images_with_included_rpm(self, exists, mocked_client):
        mocked_client.return_value.execute.return_value = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-2"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.el8.x86_64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.el8.src",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-3"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.x86_64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.x86_64",
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
                                "repository": "product2/repo2",
                                "tags": [{"name": "latest"}],
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
        exists.return_value = True
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        repositories = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }

        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1"], ["openssl-1.2.3-3"], repositories
        )
        self.assertEqual(len(ret), 2)
        self.assertEqual(["parent-1-2", "parent-1-3"], sorted([x.nvr for x in ret]))

    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_images_with_included_srpm_floating_tag(self, exists, mocked_client):
        mocked_client.return_value.execute.return_value = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-2"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-3"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
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
        exists.return_value = True
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        repositories = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }
        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.4-2"], repositories
        )

        self.assertEqual([image.nvr for image in ret], ["parent-1-3", "parent-1-2"])

    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_images_with_included_newer_srpm(self, exists, mocked_client):
        mocked_client.return_value.execute.return_value = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-2"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-3"},
                        "content_sets": ["dummy-content-set-2"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
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

        exists.return_value = True
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        repositories = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }
        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-1"], repositories
        )
        self.assertEqual(ret, [])

    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_images_with_included_newer_srpm_multilpe_nvrs(self, exists, mocked_client):
        mocked_client.return_value.execute.return_value = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-2"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-3"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.amd64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.amd64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
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
        exists.return_value = True
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        repositories = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }
        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1"], ["openssl-1.2.4-2"], repositories
        )
        self.assertEqual([image.nvr for image in ret], ["parent-1-3", "parent-1-2"])

    def _filter_fnc(self, image):
        return image.nvr.startswith("filtered_")

    @patch("freshmaker.pyxis_gql.Client")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    @patch("os.path.exists")
    def test_images_with_content_set_packages_filter_func(
        self, exists, koji_task_request, koji_get_build, gql_client
    ):
        exists.return_value = True
        gql_client.return_value.execute.return_value = self.fake_pyxis_find_repos

        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        # "filtered_x-1-23" image will be filtered by filter_fnc.
        filtered_images = [
            ContainerImage.create(
                {
                    "content_sets": ["dummy-content-set-1"],
                    "brew": {"build": "filtered_x-1-23"},
                    "repositories": [
                        {
                            "registry": "registry.example.com",
                            "repository": "product/repo1",
                            "published": True,
                            "tags": [{"name": "latest"}],
                        }
                    ],
                }
            )
        ]
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        pyxis.find_images_with_included_rpms = mock.Mock()
        pyxis.find_images_with_included_rpms.return_value = (
            self.fake_container_images + filtered_images
        )

        ret = pyxis.find_images_with_packages_from_content_set(
            set(["openssl-1.2.3-3"]), ["dummy-content-set-1"], filter_fnc=self._filter_fnc
        )

        # The "filtered_x-1-23" build should be filtered out
        self.assertEqual(2, len(ret))
        ret_nvrs = [x["brew"]["build"] for x in ret]
        self.assertTrue("package-name-1-4-12.10" in ret_nvrs)
        self.assertTrue("package-name-2-4-12.10" in ret_nvrs)
        self.assertTrue("filtered_x-1-23" not in ret_nvrs)

    @patch("freshmaker.image.ContainerImage.resolve_published")
    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package(
        self, get_task_request, get_build, exists, gql_client, resolve_published
    ):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1",
            "target1",
            {},
        ]
        exists.return_value = True

        gql_client.return_value.execute.return_value = self.fake_pyxis_find_images_by_nvr_parent

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_parent_images_with_package(self.fake_container_images[0], "openssl")

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["build"], "foo-parent-container-2-130")
        self.assertEqual(
            set(ret[0]["content_sets"]), set(["foo-content-set-x86_64", "foo-content-set-ppc64le"])
        )

    @patch("freshmaker.image.ContainerImage.resolve_published")
    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package_last_parent_content_sets(
        self, get_task_request, get_build, exists, gql_client, resolve_published
    ):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1",
            "target1",
            {},
        ]
        exists.return_value = True

        gql_client.return_value.execute.side_effect = [
            self.fake_pyxis_find_images_by_nvr,
            self.fake_pyxis_find_images_by_nvr_parent,
        ]

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_parent_images_with_package(self.fake_container_images[0], "openssl", [])

        self.assertEqual(2, len(ret))
        self.assertEqual(ret[0]["brew"]["build"], "foo-container-1-20")
        self.assertEqual(ret[1]["brew"]["build"], "foo-parent-container-2-130")
        self.assertEqual(
            set(ret[0]["content_sets"]), set(["foo-content-set-x86_64", "foo-content-set-ppc64le"])
        )
        self.assertEqual(
            set(ret[1]["content_sets"]), set(["foo-content-set-x86_64", "foo-content-set-ppc64le"])
        )

    @patch("freshmaker.image.PyxisAPI.find_images_with_packages_from_content_set")
    @patch("freshmaker.image.PyxisAPI.find_parent_images_with_package")
    @patch("freshmaker.image.PyxisAPI._filter_out_already_fixed_published_images")
    @patch("os.path.exists")
    def test_images_to_rebuild(
        self,
        exists,
        _filter_out_already_fixed_published_images,
        find_parent_images_with_package,
        find_images_with_packages_from_content_set,
    ):
        exists.return_value = True

        image_a = ContainerImage.create(
            {
                "brew": {"package": "image-a", "build": "image-a-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-a-commit",
            }
        )
        image_b = ContainerImage.create(
            {
                "brew": {"package": "image-b", "build": "image-b-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-b-commit",
                "parent": image_a,
            }
        )
        image_c = ContainerImage.create(
            {
                "brew": {"package": "image-c", "build": "image-c-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-c-commit",
                "parent": image_b,
            }
        )
        image_e = ContainerImage.create(
            {
                "brew": {"package": "image-e", "build": "image-e-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-e-commit",
                "parent": image_a,
            }
        )
        image_d = ContainerImage.create(
            {
                "brew": {"package": "image-d", "build": "image-d-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-d-commit",
                "parent": image_e,
            }
        )
        image_j = ContainerImage.create(
            {
                "brew": {"package": "image-j", "build": "image-j-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-j-commit",
                "parent": image_e,
            }
        )
        image_k = ContainerImage.create(
            {
                "brew": {"package": "image-k", "build": "image-k-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-k-commit",
                "parent": image_j,
            }
        )
        image_g = ContainerImage.create(
            {
                "brew": {"package": "image-g", "build": "image-g-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-g-commit",
                "parent": None,
            }
        )
        image_f = ContainerImage.create(
            {
                "brew": {"package": "image-f", "build": "image-f-v-r1"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-f-commit",
                "parent": image_g,
            }
        )

        leaf_image1 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-1-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image1-commit",
            }
        )
        leaf_image2 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-2-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image2-commit",
            }
        )
        leaf_image3 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-3-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image3-commit",
            }
        )
        leaf_image4 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-4-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image4-commit",
            }
        )
        leaf_image5 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-5-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image5-commit",
            }
        )
        leaf_image6 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-6-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image6-commit",
            }
        )
        leaf_image7 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-7-1"},
                "parsed_data": {
                    "labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image7-commit",
            }
        )
        images = [
            leaf_image1,
            leaf_image2,
            leaf_image3,
            leaf_image4,
            leaf_image5,
            leaf_image6,
            leaf_image7,
        ]

        for image in images:
            image["rpm_manifest"] = [{"rpms": [{"name": "dummy"}]}]
            image["directly_affected"] = True

        find_images_with_packages_from_content_set.return_value = images

        leaf_image6_as_parent = copy.deepcopy(leaf_image6)
        leaf_image6_as_parent["parent"] = image_f
        # When the image is a parent, directly_affected is not set
        del leaf_image6_as_parent["directly_affected"]
        find_parent_images_with_package.side_effect = [
            [image_b, image_a],  # parents of leaf_image1
            [image_c, image_b, image_a],  # parents of leaf_image2
            [image_k, image_j, image_e, image_a],  # parents of leaf_image3
            [image_d, image_e, image_a],  # parents of leaf_image4
            [image_a],  # parents of leaf_image5
            [image_f, image_g],  # parents of leaf_image6
            [leaf_image6_as_parent, image_f, image_g],  # parents of leaf_image7
        ]
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        batches = pyxis.find_images_to_rebuild(["dummy-1-1"], ["dummy"])

        # Each of batch is sorted for assertion easily
        expected_batches = [
            [image_a, image_g],
            [image_b, image_e, image_f, leaf_image5],
            [image_c, image_d, image_j, leaf_image1, leaf_image6],
            [image_k, leaf_image2, leaf_image4, leaf_image7],
            [leaf_image3],
        ]
        expected_batches_nvrs = [{image.nvr for image in batch} for batch in expected_batches]

        returned_batches_nvrs = [{image.nvr for image in batch} for batch in batches]

        self.assertEqual(expected_batches_nvrs, returned_batches_nvrs)
        # This verifies that Freshmaker recognizes that the parent of leaf_image7 that gets put
        # into one of the batches is directly affected because the same image was returned in
        # find_images_with_packages_from_content_set.
        for batch in batches:
            for image in batch:
                if image.nvr == "leaf-image-6-1":
                    self.assertTrue(leaf_image6_as_parent["directly_affected"])
                    break
        expected_directly_affected_nvrs = {
            "leaf-image-5-1",
            "leaf-image-1-1",
            "leaf-image-3-1",
            "leaf-image-6-1",
            "leaf-image-7-1",
            "leaf-image-4-1",
            "leaf-image-2-1",
        }

        _filter_out_already_fixed_published_images.assert_called_once_with(
            mock.ANY, expected_directly_affected_nvrs, ["dummy-1-1"], ["dummy"]
        )

    @patch("freshmaker.image.PyxisAPI.find_images_with_packages_from_content_set")
    @patch("freshmaker.image.PyxisAPI.find_parent_images_with_package")
    @patch("freshmaker.image.PyxisAPI._filter_out_already_fixed_published_images")
    @patch("os.path.exists")
    def test_skip_nvrs_when_find_rebuild_images(
        self,
        exists,
        _filter_out_already_fixed_published_images,
        find_parent_images_with_package,
        find_images_with_packages_from_content_set,
    ):
        exists.return_value = True

        image_a = ContainerImage.create(
            {
                "brew": {"package": "image-a", "build": "image-a-v-r1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-a-commit",
            }
        )
        image_b = ContainerImage.create(
            {
                "brew": {"package": "image-b", "build": "image-b-v-r1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-b-commit",
                "parent": image_a,
            }
        )
        image_c = ContainerImage.create(
            {
                "brew": {"package": "image-c", "build": "image-c-v-r1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "image-c-commit",
                "parent": image_b,
            }
        )

        leaf_image1 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-1-1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image1-commit",
            }
        )
        leaf_image2 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-2-1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image2-commit",
            }
        )
        leaf_image3 = ContainerImage.create(
            {
                "brew": {"build": "leaf-image-3-1"},
                "parsed_data": {
                    "labels": [
                        {"name": "not_com.redhat.hotfix", "value": "v4.6"},
                    ],
                    "layers": ["fake layer"],
                },
                "repositories": [{"repository": "foo/bar"}],
                "repository": "repo-1",
                "commit": "leaf-image3-commit",
            }
        )
        images = [leaf_image1, leaf_image2, leaf_image3]

        for image in images:
            image["rpm_manifest"] = [{"rpms": [{"name": "dummy"}]}]
            image["directly_affected"] = True

        find_images_with_packages_from_content_set.return_value = images

        find_parent_images_with_package.side_effect = [
            [image_a],  # parents of leaf_image1
            [image_b, image_a],  # parents of leaf_image2
            [image_c, image_a],  # parents of leaf_image3
        ]
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        batches = pyxis.find_images_to_rebuild(
            ["dummy-1-1"], ["dummy"], skip_nvrs=["leaf-image-3-1"]
        )

        # Each of batch is sorted for assertion easily
        expected_batches = [[image_a], [leaf_image1, image_b], [leaf_image2]]

        expected_batches_nvrs = [{image.nvr for image in batch} for batch in expected_batches]
        returned_batches_nvrs = [{image.nvr for image in batch} for batch in batches]

        self.assertEqual(expected_batches_nvrs, returned_batches_nvrs)
        expected_directly_affected_nvrs = {"leaf-image-1-1", "leaf-image-2-1"}

        _filter_out_already_fixed_published_images.assert_called_once_with(
            mock.ANY, expected_directly_affected_nvrs, ["dummy-1-1"], ["dummy"]
        )

    @patch("freshmaker.image.ContainerImage.resolve_published")
    @patch("freshmaker.image.PyxisAPI.get_images_by_nvrs")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package_using_field_parent_brew_build(
        self, get_task_request, get_build, exists, get_images_by_nvrs, resolve_published
    ):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1",
            "target1",
            {},
        ]
        exists.return_value = True

        get_images_by_nvrs.side_effect = [self.fake_container_images_with_parent_brew_build, [], []]

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_parent_images_with_package(
            self.fake_container_images_with_parent_brew_build[0], "openssl", []
        )

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(
            set(ret[0]["content_sets"]), set(["dummy-content-set-1", "dummy-content-set-2"])
        )
        self.assertEqual(
            ret[-1]["error"],
            (
                "Couldn't find parent image some-original-nvr-7.6-252.1561619826. "
                "Pyxis data is probably incomplete"
            ),
        )

    @patch("freshmaker.image.PyxisAPI.get_images_by_nvrs")
    @patch("freshmaker.image.PyxisAPI.find_images_with_packages_from_content_set")
    @patch("freshmaker.image.PyxisAPI.find_parent_images_with_package")
    @patch("freshmaker.image.PyxisAPI._filter_out_already_fixed_published_images")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    @patch("os.path.exists")
    def test_parent_images_with_package_using_field_parent_brew_build_parent_empty(
        self,
        exists,
        koji_task_request,
        koji_get_build,
        _filter_out_already_fixed_published_images,
        find_parent_images_with_package,
        find_images_with_packages_from_content_set,
        cont_images,
    ):
        exists.return_value = True
        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        image_a = ContainerImage.create(
            {
                "brew": {"package": "image-a", "build": "image-a-v-r1"},
                "parsed_data": {"labels": [{"name": "com.redhat.hotfix", "value": "v4.6"}]},
                "parent_brew_build": "some-original-nvr-7.6-252.1561619826",
                "repository": "repo-1",
                "commit": "image-a-commit",
                "repositories": [{"repository": "foo/bar"}],
                "rpm_manifest": [{"rpms": [{"name": "dummy"}]}],
            }
        )

        find_parent_images_with_package.return_value = []
        find_images_with_packages_from_content_set.return_value = [image_a]
        cont_images.side_effect = [self.fake_container_images_with_parent_brew_build, [], []]

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_images_to_rebuild(["dummy-1-1"], ["dummy"])

        self.assertNotEqual(len(ret), 1)
        self.assertEqual(ret, [])

    @patch("freshmaker.image.PyxisAPI.get_images_by_nvrs")
    @patch("freshmaker.image.PyxisAPI.find_images_with_packages_from_content_set")
    @patch("freshmaker.image.PyxisAPI.find_parent_images_with_package")
    @patch("freshmaker.image.PyxisAPI._filter_out_already_fixed_published_images")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    @patch("os.path.exists")
    def test_dedupe_dependency_images_with_all_repositories(
        self,
        exists,
        koji_task_request,
        koji_get_build,
        _filter_out_already_fixed_published_images,
        find_parent_images_with_package,
        find_images_with_packages_from_content_set,
        get_images_by_nvrs,
    ):
        exists.return_value = True

        vulnerable_rpm_name = "oh-noes"
        vulnerable_rpm_nvr = "{}-1.0-1".format(vulnerable_rpm_name)

        ubi_image_template = {
            "brew": {"package": "ubi8-container", "build": "ubi8-container-8.1-100"},
            "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
            "parent_image_builds": {},
            "repository": "containers/ubi8",
            "commit": "2b868f757977782367bf624373a5fe3d8e6bacd6",
            "repositories": [{"repository": "ubi8"}],
            "rpm_manifest": [{"rpms": [{"name": vulnerable_rpm_name}]}],
        }
        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        directly_affected_ubi_image = ContainerImage.create(copy.deepcopy(ubi_image_template))

        dependency_ubi_image_data = copy.deepcopy(ubi_image_template)
        dependency_ubi_image_nvr = directly_affected_ubi_image.nvr + ".12345678"
        dependency_ubi_image_data["brew"]["build"] = dependency_ubi_image_nvr
        # A dependecy image is not directly published
        dependency_ubi_image_data["repositories"] = []
        dependency_ubi_image = ContainerImage.create(dependency_ubi_image_data)

        python_image = ContainerImage.create(
            {
                "brew": {"package": "python-36-container", "build": "python-36-container-1-10"},
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "parent_brew_build": directly_affected_ubi_image.nvr,
                "parent_image_builds": {},
                "repository": "containers/python-36",
                "commit": "3a740231deab2abf335d5cad9a80d466c783be7d",
                "repositories": [{"repository": "ubi8/python-36"}],
                "rpm_manifest": [{"rpms": [{"name": vulnerable_rpm_name}]}],
            }
        )

        nodejs_image = ContainerImage.create(
            {
                "brew": {
                    "package": "nodejs-12-container",
                    "build": "nodejs-12-container-1-20.45678",
                },
                "parsed_data": {"labels": [{"name": "not_com.redhat.hotfix", "value": "v4.6"}]},
                "parent_brew_build": dependency_ubi_image.nvr,
                "repository": "containers/nodejs-12",
                "commit": "97d57a9db975b58b43113e15d29e35de6c1a3f0b",
                "repositories": [{"repository": "ubi8/nodejs-12"}],
                "rpm_manifest": [{"rpms": [{"name": vulnerable_rpm_name}]}],
            }
        )

        def fake_find_parent_images_with_package(image, *args, **kwargs):
            parents = {
                directly_affected_ubi_image.nvr: directly_affected_ubi_image,
                dependency_ubi_image.nvr: dependency_ubi_image,
            }
            parent = parents.get(image.get("parent_brew_build"))
            if parent:
                return [parent]
            return []

        find_parent_images_with_package.side_effect = fake_find_parent_images_with_package

        find_images_with_packages_from_content_set.return_value = [
            directly_affected_ubi_image,
            python_image,
            nodejs_image,
        ]

        def fake_get_images_by_nvrs(nvrs, **kwargs):
            if nvrs == [dependency_ubi_image.nvr]:
                return [dependency_ubi_image]
            elif nvrs == [directly_affected_ubi_image.nvr]:
                return [directly_affected_ubi_image]
            raise ValueError("Unexpected test data, {}".format(nvrs))

        get_images_by_nvrs.side_effect = fake_get_images_by_nvrs

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        batches = pyxis.find_images_to_rebuild([vulnerable_rpm_nvr], [vulnerable_rpm_name])
        expected_batches = [
            # The dependency ubi image has a higher NVR and it should be used as
            # the parent for both images.
            {dependency_ubi_image.nvr},
            {python_image.nvr, nodejs_image.nvr},
        ]
        for batch, expected_batch_nvrs in zip(batches, expected_batches):
            batch_nvrs = set(image.nvr for image in batch)
            self.assertEqual(batch_nvrs, expected_batch_nvrs)
        self.assertEqual(len(batches), len(expected_batches))

    @patch("freshmaker.image.ContainerImage.resolve_published")
    @patch("freshmaker.image.PyxisAPI.get_images_by_nvrs")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package_using_field_parent_image_builds(
        self, get_task_request, get_build, exists, cont_images, resolve_published
    ):
        get_build.return_value = {
            "task_id": 123456,
            "extra": {
                "image": {
                    "parent_build_id": 1074147,
                    "parent_image_builds": {
                        "rh-osbs/openshift-golang-builder:1.11": {
                            "id": 969696,
                            "nvr": "openshift-golang-builder-container-v1.11.13-3.1",
                        },
                        "rh-osbs/openshift-ose-base:v4.1.34.20200131.033116": {
                            "id": 1074147,
                            "nvr": "openshift-enterprise-base-container-v4.1.34-202001310309",
                        },
                    },
                }
            },
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1",
            "target1",
            {},
        ]
        exists.return_value = True

        self.fake_container_images[0].pop("parent_brew_build")
        cont_images.side_effect = [self.fake_container_images, [], []]

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_parent_images_with_package(self.fake_container_images[0], "openssl", [])

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(
            set(ret[0]["content_sets"]), set(["dummy-content-set-1", "dummy-content-set-2"])
        )

    @patch("freshmaker.image.ContainerImage.resolve")
    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_images_with_content_set_packages_leaf_container_images(
        self, exists, gql_client, resolve
    ):
        exists.return_value = True
        gql_client.return_value.execute.side_effect = [
            self.fake_pyxis_find_repos,
            self.fake_pyxis_find_images_by_nvrs,
        ]

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        images = pyxis.find_images_with_packages_from_content_set(
            ["openssl-1.2.3-2"],
            ["foo-content-set-x86_64", "foo-content-set-ppc64le"],
            leaf_container_images=["foo-container-1-20", "bar-container-2-30"],
        )

        # Only foo-container-1-20 has the content sets enabled
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].nvr, "foo-container-1-20")

    @patch("freshmaker.pyxis_gql.Client")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_content_sets_of_multiarch_images_to_rebuild(
        self, koji_task_request, koji_get_build, gql_client
    ):

        gql_client.return_value.execute.side_effect = [
            self.fake_pyxis_find_repos,
            self.fake_pyxis_find_images_by_nvrs,
        ]
        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        pyxis = PyxisAPI(server_url=self.fake_server_url)
        ret = pyxis.find_images_with_packages_from_content_set(
            set(["openssl-1.2.3-3"]),
            [
                "foo-content-set-x86_64",
                "foo-content-set-ppc64le",
                "bar-content-set-x86_64",
                "bar-content-set-ppc64le",
            ],
            leaf_container_images=["foo-container-1-20", "bar-container-2-30"],
        )

        self.assertEqual(2, len(ret))
        foo_container = [x for x in ret if x.nvr == "foo-container-1-20"][0]
        bar_container = [x for x in ret if x.nvr == "bar-container-2-30"][0]
        self.assertEqual(
            sorted(foo_container["content_sets"]),
            ["foo-content-set-ppc64le", "foo-content-set-x86_64"],
        )
        self.assertEqual(
            sorted(bar_container["content_sets"]),
            ["bar-content-set-ppc64le", "bar-content-set-x86_64"],
        )

    @patch("freshmaker.pyxis_gql.Client")
    @patch("os.path.exists")
    def test_images_with_modular_container_image(self, exists, mocked_client):
        mocked_client.return_value.execute.return_value = {
            "find_images": {
                "data": [
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-2"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.x86_64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.x86_64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
                            }
                        ],
                    },
                    {
                        "architecture": "amd64",
                        "brew": {"build": "parent-1-3"},
                        "content_sets": ["dummy-content-set-1"],
                        "edges": {
                            "rpm_manifest": {
                                "data": {
                                    "rpms": [
                                        {
                                            "name": "openssl",
                                            "nvra": "openssl-1.2.3-2.x86_64",
                                            "srpm_name": "openssl",
                                            "srpm_nevra": "openssl-1.2.3-2.x86_64",
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
                                "repository": "product/repo1",
                                "tags": [{"name": "latest"}],
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
        exists.return_value = True
        pyxis = PyxisAPI(server_url=self.fake_server_url)
        repositories = {
            repo["repository"]: repo for repo in self.fake_repositories_with_content_sets
        }
        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-3"], repositories
        )
        self.assertEqual(sorted([image.nvr for image in ret]), ["parent-1-2", "parent-1-3"])

        ret = pyxis.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"],
            ["openssl-1.2.3-3.module+el8.2.0+12345+3d1ce0e6"],
            repositories,
        )
        self.assertEqual([image.nvr for image in ret], [])


class TestDeduplicateImagesToRebuild(helpers.FreshmakerTestCase):
    def setUp(self):
        super(TestDeduplicateImagesToRebuild, self).setUp()
        self.fake_server_url = "pyxis.localhost"
        self.pyxis = PyxisAPI(server_url=self.fake_server_url)

    def tearDown(self):
        super(TestDeduplicateImagesToRebuild, self).tearDown()

    def _create_img(self, nvr):
        return ContainerImage.create(
            {
                "brew": {"build": nvr},
                "content_sets": [],
                "content_sets_source": "distgit",
                "repositories": [{"repository": "product/repo1"}],
            }
        )

    def _create_imgs(self, nvrs):
        images = []
        for data in nvrs:
            if isinstance(data, list):
                nvr = data[0]
                image = self._create_img(nvr)
                image.update(data[1])
            else:
                image = self._create_img(data)
            if images:
                images[len(images) - 1]["parent"] = image
            images.append(image)
        return images

    def test_copy_content_sets(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                [
                    "s2i-base-1-2",
                    {
                        "content_sets": ["foo"],
                        "repositories": [{"repository": "product/repo1", "content_sets": ["foo"]}],
                    },
                ],
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    ["s2i-base-1-10", {"content_sets": ["foo"]}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    ["s2i-base-1-10", {"content_sets": ["foo"]}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_use_highest_latest_released_nvr(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        foo = self._create_imgs(
            [
                "foo-5.7-1",
                "s2i-base-1-1",
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    ["s2i-base-1-2", {"latest_released": True}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "foo-5.7-1",
                    ["s2i-base-1-2", {"latest_released": True}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        self.maxDiff = None
        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl, foo])
        self.assertEqual(ret, expected_images)

    @patch.object(freshmaker.conf, "container_released_dependencies_only", new=True)
    def test_use_highest_latest_released_nvr_include_released_only(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        foo = self._create_imgs(
            [
                "foo-5.7-1",
                "s2i-base-1-1",
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    ["s2i-base-1-2", {"latest_released": True}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    ["s2i-base-1-2", {"latest_released": True}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "foo-5.7-1",
                    ["s2i-base-1-2", {"latest_released": True}],
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        self.maxDiff = None
        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl, foo])
        self.assertEqual(ret, expected_images)

    @patch.object(freshmaker.conf, "container_released_dependencies_only", new=True)
    def test_update_parent_to_newer_version_parent(self):
        """
        When an image is replaced by a newer release, update its parent by
        the parent of newer release, even the parent has a different version.
        """
        rust_toolset = self._create_imgs(
            [
                "rust-toolset-container-1.41.1-27",
                "s2i-base-container-1-173",
                "s2i-core-container-1-147",
                "ubi8-container-8.2-299",
            ]
        )

        nodejs_10 = self._create_imgs(
            [
                "nodejs-10-container-1-66.1584015429",
                "s2i-base-container-1-142.1584015404",
                "s2i-core-container-1-119.1584015378",
                "ubi8-container-8.0-208.1584015373",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "rust-toolset-container-1.41.1-27",
                    "s2i-base-container-1-173",
                    "s2i-core-container-1-147",
                    "ubi8-container-8.2-299",
                ]
            ),
            self._create_imgs(
                [
                    "nodejs-10-container-1-66.1584015429",
                    "s2i-base-container-1-173",
                    "s2i-core-container-1-147",
                    "ubi8-container-8.2-299",
                ]
            ),
        ]

        self.maxDiff = None
        ret = self.pyxis._deduplicate_images_to_rebuild([rust_toolset, nodejs_10])
        self.assertEqual(ret, expected_images)

    def test_use_highest_nvr(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                "s2i-base-1-2",
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_keep_multiple_nvs(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                "s2i-base-2-2",
                "s2i-core-2-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    "s2i-base-2-2",
                    "s2i-core-2-2",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_same_nv_different_r_different_repos(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-2",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                [
                    "s2i-base-1-3",
                    {
                        "content_sets": ["foo"],
                        "repositories": [{"repository": "product/repo2", "content_sets": ["foo"]}],
                    },
                ],
                "s2i-core-2-12",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    "s2i-base-1-2",
                    "s2i-core-1-11",
                    "rhel-server-docker-7.4-150",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    [
                        "s2i-base-1-3",
                        {
                            "content_sets": ["foo"],
                            "repositories": [
                                {"repository": "product/repo2", "content_sets": ["foo"]}
                            ],
                        },
                    ],
                    "s2i-core-2-12",
                    "rhel-server-docker-7.4-150",
                ]
            ),
        ]

        self.maxDiff = None
        ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_batches_same_image_in_batch(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]
        )
        perl = self._create_imgs(
            [
                "perl-5.7-1",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]
        )
        to_rebuild = [httpd, perl]
        batches = self.pyxis._images_to_rebuild_to_batches(to_rebuild, set())
        batches = [sorted_by_nvr(images) for images in batches]

        # Both perl and httpd share the same parent images, so include
        # just httpd's one in expected batches - they are the same as
        # for perl one. But for the last batch, we expect both images.
        expected = [
            [httpd[3]],
            [httpd[2]],
            [httpd[1]],
            [httpd[0], perl[0]],
        ]

        self.assertEqual(batches, expected)

    def test_batches_standalone_image_in_batch(self):
        # Create to_rebuild list of following images:
        # [
        #   [httpd, s2i-base, s2i-core, rhel-server-docker],
        #   [s2i-base, s2i-core, rhel-server-docker],
        #   ...,
        #   [rhel-server-docker]
        # ]
        httpd_nvr = "httpd-2.4-12"
        deps = self._create_imgs(
            [
                httpd_nvr,
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]
        )
        to_rebuild = []
        for i in range(len(deps)):
            to_rebuild.append(deps[i:])

        batches = self.pyxis._images_to_rebuild_to_batches(to_rebuild, {httpd_nvr})
        batches = [sorted_by_nvr(images) for images in batches]

        # We expect each image to be rebuilt just once.
        expected = [[deps[3]], [deps[2]], [deps[1]], [deps[0]]]
        self.assertEqual(batches, expected)
        for batch in batches:
            for image in batch:
                if image.nvr == httpd_nvr:
                    self.assertTrue(image["directly_affected"])
                else:
                    self.assertFalse(image.get("directly_affected"))

    def test_parent_changed_in_latest_release(self):
        httpd = self._create_imgs(
            [
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "foo-7.4-125",
            ]
        )

        perl = self._create_imgs(
            [
                "perl-5.7-1",
                "s2i-base-1-2",
                "s2i-core-1-2",
                "rhel-server-docker-7.4-150",
            ]
        )

        expected_images = [
            self._create_imgs(
                [
                    "httpd-2.4-12",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "foo-7.4-125",
                ]
            ),
            self._create_imgs(
                [
                    "perl-5.7-1",
                    "s2i-base-1-10",
                    "s2i-core-1-11",
                    "foo-7.4-125",
                ]
            ),
        ]

        for val in [True, False]:
            with patch.object(freshmaker.conf, "container_released_dependencies_only", new=val):
                ret = self.pyxis._deduplicate_images_to_rebuild([httpd, perl])
                self.assertEqual(ret, expected_images)


@patch("os.path.exists", return_value=True)
@patch("freshmaker.image.PyxisAPI.get_fixed_published_image")
@patch("freshmaker.image.PyxisAPI.describe_image_group")
def test_filter_out_already_fixed_published_images(mock_dig, mock_gfpi, mock_exists):
    vulerable_bash_rpm_manifest = [
        {
            "rpms": [
                {
                    "name": "bash",
                    "nvra": "bash-4.2.46-31.el7.x86_64",
                    "srpm_name": "bash",
                    "srpm_nevra": "bash-0:4.2.46-31.el7.src",
                    "version": "4.2.46",
                }
            ]
        }
    ]
    parent_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.6-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    child_image = ContainerImage.create(
        {
            "brew": {"build": "focaccia-maker-1.0.0-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "directly_affected": True,
            "parent": parent_image,
            "parent_build_id": 1275600,
            "parent_image_builds": {
                "registry.domain.local/rhel7/rhel:latest": {
                    "id": 1275600,
                    "nvr": "rhel-server-container-7.6-1",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    fixed_parent_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "rpm_manifest": [
                {
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ]
                }
            ],
        }
    )
    second_parent_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.8-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    third_parent_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.8-2"},
            "content_sets": ["rhel-7-server-rpms"],
        }
    )
    second_child_image = ContainerImage.create(
        {
            "brew": {"build": "pizza-dough-tosser-1.0.0-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "directly_affected": True,
            "parent": second_parent_image,
            "parent_build_id": 1275601,
            "parent_image_builds": {
                "registry.domain.local/rhel7/rhel:7.8": {
                    "id": 1275601,
                    "nvr": "rhel-server-container-7.8-1",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    intermediate_image = ContainerImage.create(
        {
            "brew": {"build": "pizza-oven-2.7-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "parent_build_id": 1275600,
            "parent_image_builds": {
                "registry.domain.local/rhel7/rhel:latest": {
                    "id": 1275600,
                    "nvr": "rhel-server-container-7.6-1",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    third_child_image = ContainerImage.create(
        {
            "brew": {"build": "pineapple-topping-remover-1.0.0-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "directly_affected": True,
            "parent": second_parent_image,
            "parent_build_id": 1275801,
            "parent_image_builds": {
                "registry.domain.local/appliances/pizza-oven:2.7": {
                    "id": 1275801,
                    "nvr": "pizza-oven-2.7-1",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    fourth_child_image = ContainerImage.create(
        {
            "brew": {"build": "pizza-fries-cooker-1.0.0-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "directly_affected": True,
            "parent_build_id": 1275602,
            "parent_image_builds": {
                "registry.domain.local/rhel7/rhel:7.9": {
                    "id": 1275602,
                    "nvr": "rhel-server-container-7.9-123",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    fifth_child_image = ContainerImage.create(
        {
            "brew": {"build": "chicken-parm-you-taste-so-good-1.0.0-1"},
            "content_sets": ["rhel-7-server-rpms"],
            "directly_affected": True,
            "parent_build_id": 1275602,
            "parent_image_builds": {
                "registry.domain.local/rhel7/rhel:7.9": {
                    "id": 1275602,
                    "nvr": "rhel-server-container-7.9-123",
                }
            },
            "rpm_manifest": vulerable_bash_rpm_manifest,
        }
    )
    mock_gfpi.side_effect = [fixed_parent_image, None, fixed_parent_image]
    to_rebuild = [
        # This parent image of child image will be replaced with the published image.
        # The parent image will not be in to_rebuild after the method is executed.
        [child_image, parent_image],
        # Because get_fixed_published_image will return None on the second group,
        # this will remain the same
        [second_child_image, second_parent_image],
        # Because the intermediate image is directly affected in the third group
        # but the parent image is not and there is a published image with the
        # fix, the parent image will not be in to_rebuild after the method is
        # executed.
        [third_child_image, intermediate_image, parent_image],
        # Since there are only directly affected images, this will remain the same
        [fourth_child_image],
        # Since the third parent image in this group does not have an RPM
        # manifest, this group will remain the same
        [fifth_child_image, third_parent_image],
    ]
    directly_affected_nvrs = {
        "chicken-parm-you-taste-so-good-1.0.0-1",
        "focaccia-maker-1.0.0-1",
        "pizza-dough-tosser-1.0.0-1",
        "pizza-fries-cooker-1.0.0-1",
        "pizza-oven-2.7-1",
        "pineapple-topping-remover-1.0.0-1",
    }
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]

    pyxis = PyxisAPI("pyxis.domain.local")
    pyxis._filter_out_already_fixed_published_images(
        to_rebuild, directly_affected_nvrs, rpm_nvrs, content_sets
    )

    assert to_rebuild == [
        [child_image],
        [second_child_image, second_parent_image],
        [third_child_image, intermediate_image],
        [fourth_child_image],
        [fifth_child_image, third_parent_image],
    ]
    assert child_image["parent"] == fixed_parent_image
    assert intermediate_image["parent"] == fixed_parent_image
    assert mock_gfpi.call_count == 3
    mock_gfpi.assert_has_calls(
        (
            mock.call("rhel-server-container", "7.6", mock_dig(), set(rpm_nvrs), content_sets),
            mock.call("rhel-server-container", "7.8", mock_dig(), set(rpm_nvrs), content_sets),
            mock.call("rhel-server-container", "7.6", mock_dig(), set(rpm_nvrs), content_sets),
        )
    )


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_nvr")
@patch("freshmaker.image.ContainerImage.resolve")
def test_get_fixed_published_image(
    resolve, find_images_by_nvr, published_images, mock_exists, gql_client
):
    other_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-188"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }

    published_images.return_value = [other_rhel7_image_pyxis, latest_rhel7_image_pyxis]
    find_images_by_nvr.return_value = [latest_rhel7_image_pyxis]
    image = Mock(nvr="rhel-server-container-7.9-185")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image["brew"]["build"] == "rhel-server-container-7.9-189"

    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo2"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }

    published_images.return_value = [other_rhel7_image_pyxis, latest_rhel7_image_pyxis]
    find_images_by_nvr.return_value = [latest_rhel7_image_pyxis]

    image_2 = Mock(nvr="rhel-server-container-7.9-185")
    image_2.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group_2 = ImageGroup(image_2, Mock())
    image_2 = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group_2, rpm_nvrs, content_sets
    )

    assert image_2["brew"]["build"] == "rhel-server-container-7.9-189"


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_nvr")
def test_get_fixed_published_image_not_found(
    find_images_by_nvr, published_images, mock_exists, gql_client
):
    published_images.return_value = find_images_by_nvr.return_value = []

    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
def test_get_fixed_published_image_diff_repo(published_images, mock_exists, gql_client):
    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "other_repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    published_images.return_value = [latest_rhel7_image_pyxis]
    image = Mock(nvr="rhel-server-container-7.9-189")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
def test_get_fixed_published_image_missing_rpm(published_images, mock_exists, gql_client):
    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "foo",
                            "nvra": "foo-4.2.-34.el746.x86_64",
                            "srpm_name": "foo",
                            "srpm_nevra": "foo-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    published_images.return_value = [latest_rhel7_image_pyxis]
    image = Mock(nvr="rhel-server-container-7.9-189")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
def test_get_fixed_published_image_modularity_mismatch(published_images, mock_exists, gql_client):
    latest_rhel8_image_pyxis = {
        "brew": {"build": "rhel-server-container-8.2-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.module+el8.2.0+6123+12149598.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.module+el8.2.0+6123+12149598.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    published_images.return_value = [latest_rhel8_image_pyxis]
    image = Mock(nvr="rhel-server-container-8.2-185")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el8"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "8.2", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
def test_get_fixed_published_image_rpm_too_old(published_images, mock_exists, gql_client):
    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-33.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-33.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    published_images.return_value = [latest_rhel7_image_pyxis]
    image = Mock(nvr="rhel-server-container-7.9-185")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@pytest.mark.usefixtures("pyxis_graphql_schema")
@patch("freshmaker.pyxis_gql.Client")
@patch("os.path.exists", return_value=True)
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_name_version")
@patch("freshmaker.pyxis_gql.PyxisGQL.find_images_by_nvr")
def test_get_fixed_published_image_not_found_by_nvr(
    find_images_by_nvr, published_images, mock_exists, gql_client
):
    latest_rhel7_image_pyxis = {
        "brew": {"build": "rhel-server-container-7.9-189"},
        "content_sets": ["rhel-7-server-rpms"],
        "repositories": [{"repository": "repo"}],
        "edges": {
            "rpm_manifest": {
                "data": {
                    "image_id": "57ea8dc69c624c035f96f990",
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.el7.src",
                            "version": "4.2.46",
                        }
                    ],
                }
            }
        },
    }
    published_images.return_value = [latest_rhel7_image_pyxis]
    find_images_by_nvr.return_value = []
    image = Mock(nvr="rhel-server-container-7.9-185")
    image.get_registry_repositories.return_value = [{"repository": "repo"}]
    image_group = ImageGroup(image, Mock())
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    pyxis = PyxisAPI("pyxis.domain.local")

    image = pyxis.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None
