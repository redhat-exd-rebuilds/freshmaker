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

import json
import six

from mock import call, patch, Mock
from six.moves import http_client

import freshmaker

from freshmaker.lightblue import ContainerImage
from freshmaker.lightblue import ContainerRepository
from freshmaker.lightblue import KojiLookupError
from freshmaker.lightblue import LightBlue
from freshmaker.lightblue import LightBlueRequestError
from freshmaker.lightblue import LightBlueSystemError
from freshmaker.utils import sorted_by_nvr
from freshmaker import log
from tests import helpers


class TestLightBlueRequestError(helpers.FreshmakerTestCase):
    """Test case for exception LightBlueRequestError"""

    def setUp(self):
        super(TestLightBlueRequestError, self).setUp()
        self.fake_error_data = {
            'entity': 'containerImage',
            'entityVersion': '0.0.11',
            'errors': [
                {
                    'context': 'rest/FindCommand/containerImage/find(containerImage:0.0.11)/'
                               'containerImage/parsed_data/rpm_manifes',
                    'errorCode': 'metadata:InvalidFieldReference',
                    'msg': 'rpm_manifes in parsed_data.rpm_manifes.*.nvra',
                    'objectType': 'error'
                }
            ],
            'hostname': 'lightbluecrud1.dev2.a1.vary.redhat.com',
            'matchCount': 0,
            'modifiedCount': 0,
            'status': 'ERROR'
        }
        self.e = LightBlueRequestError(http_client.BAD_REQUEST,
                                       self.fake_error_data)

    def test_get_raw_error_json_data(self):
        self.assertEqual(self.fake_error_data, self.e.raw)

    def test_get_status_code(self):
        self.assertEqual(http_client.BAD_REQUEST, self.e.status_code)

    def test_get_inner_errors(self):
        self.assertEqual(self.fake_error_data['errors'], self.e.raw['errors'])

    def test_errors_listed_in_str(self):
        expected_s = '\n'.join(('    {}'.format(err['msg'])
                                for err in self.fake_error_data['errors']))
        self.assertIn(expected_s, str(self.e))


class TestLightBlueSystemError(helpers.FreshmakerTestCase):
    """Test LightBlueSystemError"""

    def setUp(self):
        super(TestLightBlueSystemError, self).setUp()
        buf = six.StringIO('''
<html><head><title>JBWEB000065: HTTP Status 401 - JBWEB000009: No client
certificate chain in this request</title><style><!--H1 {font-family:Tahoma,
Arial,sans-serif;color:white;background-color:#525D76;font-size:22px;} H2
{font-family:Tahoma,Arial,sans-serif;color:white;background-color:#525D76;
font-size:16px;} H3 {font-family:Tahoma,Arial,sans-serif;color:white;
background-color:#525D76;font-size:14px;} BODY {font-family:Tahoma,Arial,
sans-serif;color:black;background-color:white;} B {font-family:Tahoma,Arial,
sans-serif;color:white;background-color:#525D76;} P {font-family:Tahoma,Arial,
sans-serif;background:white;color:black;font-size:12px;}A {color : black;}
A.name {color : black;}HR {color : #525D76;}--></style> </head><body><h1>
JBWEB000065: HTTP Status 401 - JBWEB000009: No client certificate chain in
this request</h1><HR size="1" noshade="noshade"><p><b>JBWEB000309: type</b>
JBWEB000067: Status report</p><p><b>JBWEB000068: message</b> <u>JBWEB000009:
No client certificate chain in this request</u></p><p><b>JBWEB000069:
description</b> <u>JBWEB000121: This request requires HTTP authentication.</u>
</p><HR size="1" noshade="noshade"></body></html>
''')
        self.fake_error_data = ' '.join((line.strip() for line in buf))
        self.e = LightBlueSystemError(http_client.UNAUTHORIZED,
                                      self.fake_error_data)

    def test_get_status_code(self):
        self.assertEqual(http_client.UNAUTHORIZED, self.e.status_code)

    def test_raw(self):
        self.assertEqual(self.fake_error_data, self.e.raw)

    def test_str_from_json(self):
        content = (
            '{"status":"ERROR","modifiedCount":0,"matchCount":0,'
            '"hostname":"periwinklec9.web.prod.int.phx2.redhat.com",'
            '"errors":[{"objectType":"error","context":"rest/FindCommand/'
            'containerImage/find(containerImage:null)/containerImage/'
            'includes_multiple_content_streams","errorCode":"'
            'metadata:InvalidFieldReference","msg":'
            '"includes_multiple_content_streams in '
            'includes_multiple_content_streams"}]}')
        e = LightBlueSystemError(
            http_client.BAD_REQUEST, content)
        self.assertEqual(
            'metadata:InvalidFieldReference: includes_multiple_content_streams'
            ' in includes_multiple_content_streams\n', str(e))

    def test__str__(self):
        self.assertEqual(
            'JBWEB000065: HTTP Status 401 - JBWEB000009: No client certificate'
            ' chain in this request',
            str(self.e))

    def test__repr__(self):
        self.assertEqual('<{} [{}]>'.format(self.e.__class__.__name__,
                                            self.e.status_code),
                         repr(self.e))


class TestGetAdditionalDataFromDistGit(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestGetAdditionalDataFromDistGit, self).setUp()

        self.patcher = helpers.Patcher(
            "freshmaker.lightblue.")
        self.get_distgit_files = self.patcher.patch("get_distgit_files")
        self.get_distgit_files.return_value = {
            "content_sets.yml": None,
            "container.yaml": None,
        }

    def tearDown(self):
        super(TestGetAdditionalDataFromDistGit, self).tearDown()
        self.patcher.unpatch_all()

    def test_generate(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": "compose:\n  pulp_repos: True",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], False)

        self.get_distgit_files.assert_called_once_with(
            'rpms', 'foo-docker', "commit",
            ["content_sets.yml", "container.yaml"], logger=log, ssh=False)

    def test_generate_os_error(self):
        self.get_distgit_files.side_effect = OSError(
            "Got an error (128) from git: fatal: reference is not a tree: "
            "4d42e2009cec70d871c65de821396cd750d523f1")

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], False)

        self.assertEqual(
            image["error"],
            "Error while fetching dist-git repo files: Got an error (128) from git: "
            "fatal: reference is not a tree: 4d42e2009cec70d871c65de821396cd750d523f1")

        self.get_distgit_files.assert_called_once_with(
            'rpms', 'foo-docker', 'commit',
            ["content_sets.yml", "container.yaml"], logger=log, ssh=False)

    def test_generate_no_namespace(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": "compose:\n  pulp_repos: True",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], False)

        self.get_distgit_files.assert_called_once_with(
            'rpms', 'foo-docker', "commit",
            ["content_sets.yml", "container.yaml"], logger=log, ssh=False)

    def test_generate_no_pulp_repos(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": "compose:\n  pulp_repos_x: True",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)

    def test_generate_pulp_repos_false(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": "compose:\n  pulp_repos: False",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)

    def test_generate_no_content_sets_yml(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": None,
            "container.yaml": "compose:\n  pulp_repos: False",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)

    def test_generate_no_container_yaml(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": None,
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)

    def test_generate_content_sets_yml_empty(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "",
            "container.yaml": "compose:\n  pulp_repos: False",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)

    def test_generate_container_yaml_empty(self):
        self.get_distgit_files.return_value = {
            "content_sets.yml": "x86_64:\n  - content_set",
            "container.yaml": "",
        }

        image = ContainerImage.create({"brew": {"build": "nvr"}})
        ret = image._get_additional_data_from_distgit(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret["generate_pulp_repos"], True)


class TestContainerImageObject(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestContainerImageObject, self).setUp()

        self.patcher = helpers.Patcher(
            'freshmaker.lightblue.')
        self.get_distgit_files = self.patcher.patch("get_distgit_files")
        self.get_distgit_files.return_value = {
            "content_sets.yml": None,
            "container.yaml": None,
        }

        self.dummy_image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'completion_date': u'20170421T04:27:51.000-0400',
                'build': 'package-name-1-4-12.10',
                'package': 'package-name-1'
            },
            'rpm_manifest': [{
                'rpms': [
                    {
                        "srpm_name": "openssl",
                        "srpm_nevra": "openssl-0:1.2.3-1.src"
                    },
                    {
                        "srpm_name": "tespackage",
                        "srpm_nevra": "testpackage-10:1.2.3-1.src"
                    }
                ]
            }]
        })

    def tearDown(self):
        super(TestContainerImageObject, self).tearDown()
        self.patcher.unpatch_all()

    def test_create(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'completion_date': '20151210T10:09:35.000-0500',
                'build': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6',
                'package': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker'
            }
        })

        self.assertEqual('1233829', image['_id'])
        self.assertEqual('20151210T10:09:35.000-0500', image['brew']['completion_date'])

    def test_log_error(self):
        image = ContainerImage.create({
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })

        image.log_error("foo")
        self.assertEqual(image['error'], "foo")

        image.log_error("bar")
        self.assertEqual(image['error'], "foo; bar")

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_odcs_compose_ids(
            self, get_task_request, get_build):
        get_build.return_value = {
            "task_id": 123456,
            'extra': {
                'image': {
                    'odcs': {
                        'compose_ids': [7300, 7301],
                        'signing_intent': 'release',
                        'signing_intent_overridden': False
                    }
                }
            }
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#commit_hash1", "target1", {}]

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")
        self.assertEqual(self.dummy_image["odcs_compose_ids"], [7300, 7301])

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_koji_fallback(self, get_task_request, get_build):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#commit_hash1", "target1", {}]

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")
        self.assertEqual(self.dummy_image["odcs_compose_ids"], None)

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_no_koji_build(self, get_task_request, get_build):
        get_build.return_value = {}

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], None)
        self.assertEqual(self.dummy_image["commit"], None)
        self.assertEqual(self.dummy_image["target"], None)
        self.assertTrue(self.dummy_image["error"].find(
            "Cannot find Koji build with nvr package-name-1-4-12.10 in "
            "Koji.") != -1)

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_no_task_id(self, get_task_request, get_build):
        get_build.return_value = {"task_id": None}

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], None)
        self.assertEqual(self.dummy_image["commit"], None)
        self.assertEqual(self.dummy_image["target"], None)
        self.assertTrue(self.dummy_image["error"].find(
            "Cannot find task_id or container_koji_task_id in the Koji build "
            "{'task_id': None}") != -1)

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_prefer_build_source(
            self, get_task_request, get_build):
        get_build.return_value = {
            "task_id": 123456,
            "source": "git://example.com/rpms/repo-1?#commit_hash1"}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master", "target1", {}]

        self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_invalid_hash(self, get_task_request, get_build):
        get_build.return_value = {
            "task_id": 123456,
            "source": "git://example.com/rpms/repo-1"}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master", "target1", {}]

        self.dummy_image.resolve_commit()
        self.assertTrue(self.dummy_image["error"].find(
            "Cannot find valid source of Koji build") != -1)

    @patch('freshmaker.lightblue.ContainerImage.resolve_commit')
    def test_resolve_commit_exception(self, resolve_commit):
        resolve_commit.side_effect = ValueError("Expected exception.")
        self.dummy_image.resolve(None)
        self.assertEqual(
            self.dummy_image["error"],
            "Cannot resolve the container image: Expected exception.")

    def test_resolve_content_sets_already_included_in_lb_response(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
            'repository': 'foo',
            'git_branch': 'branch',
            'commit': 'commithash',
            'content_sets': ['dummy-contentset'],
        })

        lb = Mock()
        image.resolve_content_sets(lb)
        self.assertEqual(image["content_sets"], ['dummy-contentset'])
        self.assertEqual(image["content_sets_source"],
                         "lightblue_container_image")

    def test_resolve_content_sets_no_repositories(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
            'repository': 'foo',
            'git_branch': 'branch',
            'commit': 'commithash',
        })
        self.assertTrue("content_sets" not in image)

        lb = Mock()
        image.resolve_content_sets(lb)
        self.assertEqual(image["content_sets"], [])

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_content_sets_no_repositories_children_set(
            self, get_task_request, get_build):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
            'repository': 'foo',
            'git_branch': 'branch',
            'commit': 'commithash',
        })
        self.assertTrue("content_sets" not in image)

        child1 = ContainerImage.create({
            '_id': '1233828',
            'brew': {
                'build': 'child1-name-1-4-12.10',
            },
        })

        child2 = ContainerImage.create({
            '_id': '1233828',
            'brew': {
                'build': 'child2-name-1-4-12.10',
            },
            'content_sets': ["foo", "bar"],
        })

        lb = Mock()
        image.resolve_content_sets(lb, children=[child1, child2])
        self.assertEqual(image["content_sets"], ["foo", "bar"])

    def test_resolve_content_sets_empty_repositories(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
            'repositories': [],
            'repository': 'foo',
            'git_branch': 'branch',
            'commit': 'commithash',
        })
        self.assertTrue("content_sets" not in image)

        lb = Mock()
        image.resolve_content_sets(lb)
        self.assertEqual(image["content_sets"], [])

    def test_resolve_published(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })

        lb = Mock()
        lb.get_images_by_nvrs.return_value = [image]
        image.resolve_published(lb)
        self.assertEqual(image["published"], True)
        lb.get_images_by_nvrs.assert_called_once_with(
            ["package-name-1-4-12.10"], published=True)

    def test_resolve_published_unpublished(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })

        lb = Mock()
        lb.get_images_by_nvrs.return_value = []
        image.resolve_published(lb)
        self.assertEqual(image["published"], False)


class TestContainerRepository(helpers.FreshmakerTestCase):

    def test_create(self):
        image = ContainerRepository.create({
            'creationDate': '20160927T11:14:56.420-0400',
            'metrics': {
                'pulls_in_last_30_days': 0,
                'last_update_date': '20170223T08:28:40.913-0500'
            }
        })

        self.assertEqual('20160927T11:14:56.420-0400', image['creationDate'])
        self.assertEqual(0, image['metrics']['pulls_in_last_30_days'])
        self.assertEqual('20170223T08:28:40.913-0500', image['metrics']['last_update_date'])


class TestQueryEntityFromLightBlue(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestQueryEntityFromLightBlue, self).setUp()
        # Clear the ContainerImage Koji cache.
        ContainerImage.KOJI_BUILDS_CACHE = {}

        self.patcher = helpers.Patcher(
            'freshmaker.lightblue.')
        self.get_distgit_files = self.patcher.patch("get_distgit_files")
        self.get_distgit_files.return_value = {
            "content_sets.yml": None,
            "container.yaml": None,
        }

        self.fake_server_url = 'lightblue.localhost'
        self.fake_cert_file = 'path/to/cert'
        self.fake_private_key = 'path/to/private-key'
        self.fake_repositories_with_content_sets = [
            {
                "repository": "product/repo1",
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"],
                "auto_rebuild_tags": ["latest", "tag1"],
            },
            {
                "repository": "product2/repo2",
                "content_sets": ["dummy-content-set-1"],
                "auto_rebuild_tags": ["latest", "tag2"],
            }
        ]

        self.fake_images_with_parsed_data = [
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-1-4-12.10',
                    'package': 'package-name-1'
                },
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"],
                'repositories': [
                    {'repository': 'product1/repo1', 'published': True,
                     'tags': [{"name": "latest"}]}
                ],
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1',
                            'filename': u'Dockerfile'
                        }
                    ],
                },
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-0:1.2.3-1.src"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src"
                        }
                    ]
                }]
            },
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-2-4-12.10',
                    'package': 'package-name-2'
                },
                "content_sets": ["dummy-content-set-1"],
                'repositories': [
                    {'repository': 'product2/repo2', 'published': True,
                     'tags': [{"name": "latest"}]}
                ],
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/rpms/repo-2/plain/Dockerfile?id=commit_hash2',
                            'filename': 'Dockerfile'
                        },
                        {
                            'key': 'bogusfile',
                            'content_url': 'bogus_test_url',
                            'filename': 'bogus.file'
                        }
                    ],
                },
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-1:1.2.3-1.src"
                        },
                        {
                            "srpm_name": "tespackage2",
                            "srpm_nevra": "testpackage2-10:1.2.3-1.src"
                        }
                    ]
                }]
            },
        ]

        self.fake_images_with_parsed_data_floating_tag = [
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-3-4-12.10',
                    'package': 'package-name-1'
                },
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"],
                'repositories': [
                    {'repository': 'product2/repo2', 'published': True,
                     'tags': [{"name": "tag2"}]}
                ],
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1',
                            'filename': u'Dockerfile'
                        }
                    ],
                },
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-0:1.2.3-1.src"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src"
                        }
                    ]
                }]
            },
        ]

        self.fake_container_images = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parsed_data]

        self.fake_container_images_floating_tag = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parsed_data_floating_tag]

        self.fake_koji_builds = [{"task_id": 654321}, {"task_id": 123456}]
        self.fake_koji_task_requests = [
            ["git://pkgs.devel.redhat.com/rpms/repo-2#commit_hash2",
             "target2", {"git_branch": "mybranch"}],
            ["git://pkgs.devel.redhat.com/rpms/repo-1#commit_hash1",
             "target1", {"git_branch": "mybranch"}]]

    def tearDown(self):
        super(TestQueryEntityFromLightBlue, self).tearDown()
        self.patcher.unpatch_all()

    @patch('freshmaker.lightblue.requests.post')
    def test_find_container_images(self, post):
        post.return_value.status_code = http_client.OK
        post.return_value.json.return_value = {
            'modifiedCount': 0,
            'resultMetadata': [],
            'entityVersion': '0.0.12',
            'hostname': self.fake_server_url,
            'matchCount': 2,
            'processed': [
                {
                    '_id': '57ea8d1f9c624c035f96f4b0',
                    'image_id': 'e0f97342ddf6a09972434f98837b5fd8b5bed9390f32f1d63e8a7e4893208af7',
                    'brew': {
                        'completion_date': '20151210T10:09:35.000-0500',
                        'build': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6',
                        'package': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker'
                    },
                },
                {
                    '_id': '57ea8d289c624c035f96f4db',
                    'image_id': 'c1ef3345f36b901b0bddc7ab01ea3f3c83c886faa243e02553f475124eb4b46c',
                    'brew': {
                        'package': 'sadc-docker',
                        'completion_date': '20151203T00:35:30.000-0500',
                        'build': 'sadc-docker-7.2-7'
                    },
                }
            ],
            'status': 'COMPLETE',
            'entity': 'containerImage'
        }

        fake_request = {
            "objectType": "containerImage",
            "projection": [
                {"field": "_id", "include": True},
                {"field": "image_id", "include": True},
                {"field": "brew", "include": True, "recursive": True},
            ],
        }

        with patch('os.path.exists'):
            lb = LightBlue(server_url=self.fake_server_url,
                           cert=self.fake_cert_file,
                           private_key=self.fake_private_key)
            images = lb.find_container_images(request=fake_request)

        post.assert_called_once_with(
            '{}/{}/'.format(lb.api_root, 'find/containerImage'),
            data=json.dumps(fake_request),
            verify=lb.verify_ssl,
            cert=(self.fake_cert_file, self.fake_private_key),
            headers={'Content-Type': 'application/json'}
        )
        self.assertEqual(2, len(images))

        image = images[0]
        self.assertEqual('57ea8d1f9c624c035f96f4b0', image['_id'])
        self.assertEqual('jboss-webserver-3-webserver30-tomcat7-openshift-docker',
                         image['brew']['package'])

    @patch('freshmaker.lightblue.requests.post')
    def test_find_container_repositories(self, post):
        post.return_value.status_code = http_client.OK
        post.return_value.json.return_value = {
            'entity': 'containerRepository',
            'status': 'COMPLETE',
            'modifiedCount': 0,
            'matchCount': 2,
            'processed': [
                {
                    'creationDate': '20160927T11:14:56.420-0400',
                    'metrics': {
                        'pulls_in_last_30_days': 0,
                        'last_update_date': '20170223T08:28:40.913-0500'
                    }
                },
                {
                    'creationDate': '20161020T04:52:43.365-0400',
                    'metrics': {
                        'last_update_date': '20170501T03:00:19.892-0400',
                        'pulls_in_last_30_days': 20
                    }
                }
            ],
            'entityVersion': '0.0.11',
            'hostname': self.fake_server_url,
            'resultMetadata': []
        }

        fake_request = {
            "objectType": "containerRepository",
            "projection": [
                {"field": "creationDate", "include": True},
                {"field": "metrics", "include": True, "recursive": True}
            ],
        }

        with patch('os.path.exists'):
            lb = LightBlue(server_url=self.fake_server_url,
                           cert=self.fake_cert_file,
                           private_key=self.fake_private_key)
            repos = lb.find_container_repositories(request=fake_request)

        post.assert_called_once_with(
            '{}/{}/'.format(lb.api_root, 'find/containerRepository'),
            data=json.dumps(fake_request),
            verify=lb.verify_ssl,
            cert=(self.fake_cert_file, self.fake_private_key),
            headers={'Content-Type': 'application/json'}
        )

        self.assertEqual(2, len(repos))

        repo = repos[0]
        self.assertEqual('20160927T11:14:56.420-0400', repo['creationDate'])
        self.assertEqual(0, repo['metrics']['pulls_in_last_30_days'])
        self.assertEqual('20170223T08:28:40.913-0500', repo['metrics']['last_update_date'])
        self.assertEqual(["latest"], repo["auto_rebuild_tags"])

    @patch('freshmaker.lightblue.requests.post')
    def test_raise_error_if_request_data_is_incorrect(self, post):
        post.return_value.status_code = http_client.BAD_REQUEST
        post.return_value.json.return_value = {
            'entity': 'containerImage',
            'entityVersion': '0.0.11',
            'errors': [
                {
                    'context': 'rest/FindCommand/containerImage/find(containerImage:0.0.11)/'
                               'containerImage/parsed_data/rpm_manifes',
                    'errorCode': 'metadata:InvalidFieldReference',
                    'msg': 'rpm_manifes in parsed_data.rpm_manifes.*.nvra',
                    'objectType': 'error'
                }
            ],
            'hostname': 'lightbluecrud1.dev2.a1.vary.redhat.com',
            'matchCount': 0,
            'modifiedCount': 0,
            'status': 'ERROR'
        }

        fake_request = {
            "objectType": "containerRepository",
            "projection": [
                {"fiel": "creationDate", "include": True},
            ],
        }

        with patch('os.path.exists'):
            lb = LightBlue(server_url=self.fake_server_url,
                           cert=self.fake_cert_file,
                           private_key=self.fake_private_key)
            self.assertRaises(LightBlueRequestError,
                              lb._make_request, 'find/containerRepository/', fake_request)

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('os.path.exists')
    def test_find_all_container_repositories(self, exists, cont_repos):
        exists.return_value = True
        cont_repos.return_value = self.fake_repositories_with_content_sets
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_all_container_repositories()
        expected_repo_request = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "field": "published",
                        "op": "=",
                        "rvalue": True
                    },
                    {
                        "field": "deprecated",
                        "op": "=",
                        "rvalue": False
                    },
                    {
                        "field": "release_categories.*",
                        "op": "=",
                        "rvalue": "Generally Available"
                    }
                ]
            },
            "projection": [
                {"field": "repository", "include": True},
                {"field": "auto_rebuild_tags", "include": True, "recursive": True},
            ]
        }
        cont_repos.assert_called_with(expected_repo_request)

        expected_ret = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        self.assertEqual(ret, expected_ret)

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_srpm(self, exists,
                                       cont_images):

        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        cont_images.return_value = self.fake_images_with_parsed_data
        ret = lb.find_images_with_included_srpms(
            ["content-set-1", "content-set-2"], ["openssl-1.2.3-2"], repositories)

        expected_image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [
                            {
                                "field": "content_sets.*",
                                "op": "=",
                                "rvalue": "content-set-1"
                            },
                            {
                                "field": "content_sets.*",
                                "op": "=",
                                "rvalue": "content-set-2"
                            },
                        ],
                    },
                    {
                        "$or": [
                            {
                                "field": "repositories.*.tags.*.name",
                                "op": "=",
                                "rvalue": "latest"
                            },
                            {
                                "field": "repositories.*.tags.*.name",
                                "op": "=",
                                "rvalue": "tag1"
                            },
                            {
                                "field": "repositories.*.tags.*.name",
                                "op": "=",
                                "rvalue": "tag2"
                            },
                        ],
                    },
                    {
                        "$or": [
                            {
                                "field": "rpm_manifest.*.rpms.*.srpm_name",
                                "op": "=",
                                "rvalue": "openssl"
                            },
                        ],
                    },
                    {
                        "field": "parsed_data.files.*.key",
                        "op": "=",
                        "rvalue": "buildfile"
                    },
                    {
                        "field": "repositories.*.published",
                        "op": "=",
                        "rvalue": True
                    },
                ]
            },
            "projection": lb._get_default_projection(srpm_names=["openssl"])
        }

        # auto_rebuild_tags is a set in the source code. When generate
        # criteria for tags, the order is not guaranteed. Following lines sort
        # the tags criteria in order to assert with expected value.
        args, _ = cont_images.call_args
        request_arg = args[0]
        tags_criteira = request_arg['query']['$and'][1]['$or']
        request_arg['query']['$and'][1]['$or'] = sorted(
            tags_criteira, key=lambda item: item['rvalue'])

        self.assertEqual(expected_image_request, request_arg)

        # Only the second image should be returned, because the first one
        # is in repository "product1/repo1", but we have asked for images
        # in repository "product/repo1".
        self.assertEqual(ret, [cont_images.return_value[1]])

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_srpm_floating_tag(
            self, exists, cont_images):

        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        cont_images.return_value = (
            self.fake_container_images +
            self.fake_container_images_floating_tag)
        ret = lb.find_images_with_included_srpms(
            ["content-set-1", "content-set-2"], ["openssl-1.2.3-2"], repositories)

        self.assertEqual(
            [image["brew"]["build"] for image in ret],
            ['package-name-2-4-12.10', 'package-name-3-4-12.10'])

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_newer_srpm(
            self, exists, cont_images):

        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        cont_images.return_value = (
            self.fake_container_images +
            self.fake_container_images_floating_tag)
        ret = lb.find_images_with_included_srpms(
            ["content-set-1", "content-set-2"], ["openssl-1.2.3-1"], repositories)
        self.assertEqual(ret, [])

    def _filter_fnc(self, image):
        return image["brew"]["build"].startswith("filtered_")

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    @patch('os.path.exists')
    def test_images_with_content_set_packages(self, exists, koji_task_request,
                                              koji_get_build, cont_images,
                                              cont_repos):

        exists.return_value = True
        cont_repos.return_value = self.fake_repositories_with_content_sets
        # "filtered_x-1-23" image will be filtered by filter_fnc.
        cont_images.return_value = self.fake_container_images + [
            ContainerImage.create(
                {"brew": {"build": "filtered_x-1-23"},
                 'repositories': [
                     {'repository': 'product/repo1', 'published': True,
                      'tags': [{"name": "latest"}]}]})]
        # Include the images for second time to ensure that they will be
        # returned only once. This can happen when the image is multiarch.
        cont_images.return_value += self.fake_container_images
        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_images_with_packages_from_content_set(
            set(["openssl-1.2.3-3"]), ["dummy-content-set-1"], filter_fnc=self._filter_fnc)

        # Only the first image should be returned, because the first one
        # is in repository "product1/repo1", but we have asked for images
        # in repository "product/repo1".
        self.assertEqual(1, len(ret))
        self.assertEqual(ret,
                         [
                             {
                                 "latest_released": True,
                                 "generate_pulp_repos": True,
                                 "repository": "rpms/repo-2",
                                 "commit": "commit_hash2",
                                 "target": "target2",
                                 "git_branch": "mybranch",
                                 "error": None,
                                 "arches": None,
                                 "odcs_compose_ids": None,
                                 "published": True,
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-2-4-12.10",
                                     "package": "package-name-2"
                                 },
                                 'content_sets': ["dummy-content-set-1"],
                                 'content_sets_source': 'lightblue_container_image',
                                 'repositories': [
                                     {'repository': 'product2/repo2', 'published': True,
                                      'tags': [{"name": "latest"}]}
                                 ],
                                 'parsed_data': {
                                     'files': [
                                         {
                                             'key': 'buildfile',
                                             'content_url': 'http://git.repo.com/cgit/rpms/repo-2/plain/Dockerfile?id=commit_hash2',
                                             'filename': 'Dockerfile'
                                         },
                                         {
                                             'key': 'bogusfile',
                                             'content_url': 'bogus_test_url',
                                             'filename': 'bogus.file'
                                         }
                                     ]
                                 },
                                 'rpm_manifest': [{
                                     'rpms': [
                                         {
                                             "srpm_name": "openssl",
                                             "srpm_nevra": "openssl-1:1.2.3-1.src"
                                         },
                                         {
                                             "srpm_name": "tespackage2",
                                             "srpm_nevra": "testpackage2-10:1.2.3-1.src"
                                         }
                                     ]
                                 }]
                             },
                         ])

    @patch('freshmaker.lightblue.ContainerImage.resolve_published')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_parent_images_with_package(
            self, get_task_request, get_build, exists, cont_images,
            resolve_published):

        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]
        exists.return_value = True

        # Test that even when the parent image does not have the repositories
        # set, it will take the content_sets from the child image.
        images_without_repositories = []
        for data in self.fake_images_with_parsed_data:
            img = ContainerImage.create(data)
            del img["repositories"]
            images_without_repositories.append(img)

        cont_images.side_effect = [images_without_repositories, [],
                                   images_without_repositories]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images[0], "openssl",
            ["layer0", "layer1", "layer2", "layer3"])

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(set(ret[0]["content_sets"]),
                         set(["dummy-content-set-1", "dummy-content-set-2"]))

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_parent_images_no_rpm_manifest(self, exists, cont_images):
        exists.return_value = True
        images_without_rpm_manifest = []
        for data in self.fake_images_with_parsed_data:
            img = ContainerImage.create(data)
            del img["rpm_manifest"]
            images_without_rpm_manifest.append(img)

        cont_images.side_effect = [images_without_rpm_manifest, [],
                                   images_without_rpm_manifest]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images[0], "openssl",
            ["layer0", "layer1", "layer2", "layer3"])

        self.assertEqual(0, len(ret))

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_parent_images_empty_rpm_manifest(self, exists, cont_images):
        exists.return_value = True
        images_without_rpm_manifest = []
        for data in self.fake_images_with_parsed_data:
            img = ContainerImage.create(data)
            img["rpm_manifest"] = []
            images_without_rpm_manifest.append(img)

        cont_images.side_effect = [images_without_rpm_manifest, [],
                                   images_without_rpm_manifest]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images[0], "openssl",
            ["layer0", "layer1", "layer2", "layer3"])

        self.assertEqual(0, len(ret))

    @patch('freshmaker.lightblue.ContainerImage.resolve_published')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_parent_images_with_package_last_parent_content_sets(
            self, get_task_request, get_build, exists, cont_images,
            resolve_published):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]
        exists.return_value = True

        # Test that even when the parent image does not have the repositories
        # set, it will take the content_sets from the child image.
        images_without_repositories = []
        for data in self.fake_images_with_parsed_data:
            img = ContainerImage.create(data)
            del img["repositories"]
            images_without_repositories.append(img)

        cont_images.side_effect = [self.fake_container_images,
                                   images_without_repositories,
                                   images_without_repositories, [],
                                   images_without_repositories]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images[0], "openssl",
            ["layer0", "layer1", "layer2", "layer3", "layer4"])

        self.assertEqual(3, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(set(ret[0]["content_sets"]),
                         set(['dummy-content-set-1', 'dummy-content-set-2']))
        self.assertEqual(set(ret[1]["content_sets"]),
                         set(['dummy-content-set-1', 'dummy-content-set-2']))
        self.assertEqual(set(ret[2]["content_sets"]),
                         set(['dummy-content-set-1', 'dummy-content-set-2']))

    @patch('freshmaker.lightblue.LightBlue.find_images_with_packages_from_content_set')
    @patch('freshmaker.lightblue.LightBlue.find_parent_images_with_package')
    @patch('freshmaker.lightblue.LightBlue.find_unpublished_image_for_build')
    @patch('os.path.exists')
    def test_images_to_rebuild(self,
                               exists,
                               find_unpublished_image_for_build,
                               find_parent_images_with_package,
                               find_images_with_packages_from_content_set):
        exists.return_value = True

        image_a = ContainerImage.create({
            'brew': {'package': 'image-a', 'build': 'image-a-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-a-commit'
        })
        image_b = ContainerImage.create({
            'brew': {'package': 'image-b', 'build': 'image-b-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-b-commit',
            'parent': image_a,
        })
        image_c = ContainerImage.create({
            'brew': {'package': 'image-c', 'build': 'image-c-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-c-commit',
            'parent': image_b,
        })
        image_e = ContainerImage.create({
            'brew': {'package': 'image-e', 'build': 'image-e-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-e-commit',
            'parent': image_a,
        })
        image_d = ContainerImage.create({
            'brew': {'package': 'image-d', 'build': 'image-d-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-d-commit',
            'parent': image_e,
        })
        image_j = ContainerImage.create({
            'brew': {'package': 'image-j', 'build': 'image-j-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-j-commit',
            'parent': image_e,
        })
        image_k = ContainerImage.create({
            'brew': {'package': 'image-k', 'build': 'image-k-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-k-commit',
            'parent': image_j,
        })
        image_g = ContainerImage.create({
            'brew': {'package': 'image-g', 'build': 'image-g-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-g-commit',
            'parent': None,
        })
        image_f = ContainerImage.create({
            'brew': {'package': 'image-f', 'build': 'image-f-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-f-commit',
            'parent': image_g,
        })

        leaf_image1 = ContainerImage.create({
            'brew': {'build': 'leaf-image-1-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image1-commit',
        })
        leaf_image2 = ContainerImage.create({
            'brew': {'build': 'leaf-image-2-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image2-commit',
        })
        leaf_image3 = ContainerImage.create({
            'brew': {'build': 'leaf-image-3-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image3-commit',
        })
        leaf_image4 = ContainerImage.create({
            'brew': {'build': 'leaf-image-4-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image4-commit',
        })
        leaf_image5 = ContainerImage.create({
            'brew': {'build': 'leaf-image-5-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image5-commit',
        })
        leaf_image6 = ContainerImage.create({
            'brew': {'build': 'leaf-image-6-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image6-commit',
        })
        images = [
            leaf_image1, leaf_image2, leaf_image3,
            leaf_image4, leaf_image5, leaf_image6
        ]

        for image in images:
            image["rpm_manifest"] = [{
                "rpms": [
                    {"srpm_name": "dummy"}
                ]
            }]

        find_unpublished_image_for_build.side_effect = images
        find_images_with_packages_from_content_set.return_value = images

        find_parent_images_with_package.side_effect = [
            [image_b, image_a],                    # parents of leaf_image1
            [image_c, image_b, image_a],           # parents of leaf_image2
            [image_k, image_j, image_e, image_a],  # parents of leaf_image3
            [image_d, image_e, image_a],           # parents of leaf_image4
            [image_a],                             # parents of leaf_image5
            [image_f, image_g]                     # parents of leaf_image6
        ]
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        batches = lb.find_images_to_rebuild(["dummy-1-1"], ["dummy"])

        # Each of batch is sorted for assertion easily
        expected_batches = [
            [image_a, image_g],
            [image_b, image_e, image_f, leaf_image5],
            [image_c, image_d, image_j, leaf_image1, leaf_image6],
            [image_k, leaf_image2, leaf_image4],
            [leaf_image3]
        ]

        returned_batches = [sorted(imgs, key=lambda image: image['brew']['build'])
                            for imgs in batches]
        self.assertEqual(expected_batches, returned_batches)

    @patch('freshmaker.lightblue.LightBlue.find_images_with_packages_from_content_set')
    @patch('freshmaker.lightblue.LightBlue.find_unpublished_image_for_build')
    @patch('os.path.exists')
    def test_images_to_rebuild_cannot_find_unpublished(
            self, exists, find_unpublished_image_for_build,
            find_images_with_packages_from_content_set):
        exists.return_value = True

        image_a = ContainerImage.create({
            'brew': {'package': 'image-a', 'build': 'image-a-v-r1'},
            'repository': 'repo-1',
            'commit': 'image-a-commit',
            'rpm_manifest': [{
                "rpms": [
                    {"srpm_name": "dummy"}
                ]
            }]
        })

        find_unpublished_image_for_build.return_value = None
        find_images_with_packages_from_content_set.return_value = [image_a]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        batches = lb.find_images_to_rebuild(["dummy-1-1"], ["dummy"])

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)
        self.assertEqual(
            list(batches[0])[0]["error"],
            "Cannot find unpublished version of image, "
            "Lightblue data is probably incomplete")

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_content_set_packages_exception(self, exists,
                                                        cont_images,
                                                        cont_repos):

        exists.return_value = True
        cont_repos.side_effect = LightBlueRequestError(
            {"errors": [{"msg": "dummy error"}]}, http_client.REQUEST_TIMEOUT)
        cont_images.return_value = self.fake_images_with_parsed_data

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        with self.assertRaises(LightBlueRequestError):
            lb.find_images_with_packages_from_content_set(
                "openssl",
                ["dummy-content-set-1"])

        cont_repos.return_value = self.fake_repositories_with_content_sets
        cont_images.side_effect = LightBlueRequestError(
            {"errors": [{"msg": "dummy error"}]}, http_client.REQUEST_TIMEOUT)

        with self.assertRaises(LightBlueRequestError):
            lb.find_images_with_packages_from_content_set(
                "openssl",
                ["dummy-content-set-1"])

    @patch('freshmaker.lightblue.ContainerImage.resolve')
    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_content_set_packages_leaf_container_images(
            self, exists, cont_images, cont_repos, resolve):

        exists.return_value = True
        cont_images.return_value = self.fake_container_images
        cont_repos.return_value = self.fake_repositories_with_content_sets

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        lb.find_images_with_packages_from_content_set(
            ["openssl-1.2.3-2"], ["dummy-content-set"],
            leaf_container_images=["foo", "bar"])
        cont_images.assert_called_once_with(
            {'query': {
                '$and': [
                    {'$or': [
                        {'field': 'brew.build', 'rvalue': 'foo', 'op': '='},
                        {'field': 'brew.build', 'rvalue': 'bar', 'op': '='}]},
                    {'field': 'parsed_data.files.*.key', 'rvalue': 'buildfile', 'op': '='},
                    {'$or': [{'field': 'content_sets.*', 'rvalue': 'dummy-content-set', 'op': '='}]},
                    {'$or': [{'field': 'rpm_manifest.*.rpms.*.srpm_name', 'rvalue': 'openssl', 'op': '='}]}]},
             'projection': [{'field': 'brew', 'include': True, 'recursive': True},
                            {'field': 'parsed_data.files', 'include': True, 'recursive': True},
                            {'field': 'parsed_data.layers.*', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.published', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.repository', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.tags.*.name', 'include': True, 'recursive': True},
                            {'field': 'content_sets', 'include': True, 'recursive': True},
                            {'field': 'rpm_manifest.*.rpms', 'include': True, 'recursive': True},
                            {'field': 'rpm_manifest.*.rpms.*.srpm_name', 'include': True, 'recursive': True}],
             'objectType': 'containerImage'})


class TestEntityVersion(helpers.FreshmakerTestCase):
    """Test case for ensuring correct entity version in request"""

    def setUp(self):
        super(TestEntityVersion, self).setUp()
        self.fake_server_url = 'lightblue.localhost'
        self.fake_cert_file = 'path/to/cert'
        self.fake_private_key = 'path/to/private-key'
        self.fake_entity_versions = {
            'containerImage': '0.0.11',
            'containerRepository': '0.0.12',
        }

    @patch('freshmaker.lightblue.LightBlue._make_request')
    @patch('os.path.exists', return_value=True)
    def test_use_specified_container_image_version(self, exists, _make_request):
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key,
                       entity_versions=self.fake_entity_versions)
        lb.find_container_images({})

        _make_request.assert_called_once_with('find/containerImage/0.0.11', {})

    @patch('freshmaker.lightblue.LightBlue._make_request')
    @patch('os.path.exists', return_value=True)
    def test_use_specified_container_repository_version(self, exists, _make_request):
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key,
                       entity_versions=self.fake_entity_versions)
        lb.find_container_repositories({})

        _make_request.assert_called_once_with('find/containerRepository/0.0.12', {})

    @patch('freshmaker.lightblue.LightBlue._make_request')
    @patch('os.path.exists', return_value=True)
    def test_use_default_entity_version(self, exists, _make_request):
        _make_request.return_value = {
            # Omit other attributes that are not useful for this test
            'processed': []
        }

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        lb.find_container_repositories({})
        lb.find_container_images({})

        _make_request.assert_has_calls([
            call('find/containerRepository/', {}),
            call('find/containerImage/', {}),
        ])


class TestDeduplicateImagesToRebuild(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestDeduplicateImagesToRebuild, self).setUp()
        self.fake_server_url = 'lightblue.localhost'
        self.fake_cert_file = 'path/to/cert'
        self.fake_private_key = 'path/to/private-key'

        self.os_path_exists_patcher = patch("os.path.exists")
        self.os_path_exists_patcher.start()

        self.lb = LightBlue(server_url=self.fake_server_url,
                            cert=self.fake_cert_file,
                            private_key=self.fake_private_key)

    def tearDown(self):
        super(TestDeduplicateImagesToRebuild, self).tearDown()
        self.os_path_exists_patcher.stop()

    def _create_img(self, nvr):
        return ContainerImage.create({
            'brew': {'build': nvr},
            'content_sets': [],
            'content_sets_source': 'distgit',
        })

    def _create_imgs(self, nvrs):
        images = []
        for data in nvrs:
            if type(data) == list:
                nvr = data[0]
                image = self._create_img(nvr)
                image.update(data[1])
            else:
                image = self._create_img(data)
            if images:
                images[len(images) - 1]['parent'] = image
            images.append(image)
        return images

    def test_copy_content_sets(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            ["s2i-base-1-2", {
                "content_sets": ["foo"],
                "repositories": [{
                    "repository": "product/repo1",
                    "content_sets": ["foo"]
                }]}],
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                ["s2i-base-1-10", {"content_sets": ["foo"]}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                ["s2i-base-1-10", {"content_sets": ["foo"]}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ])
        ]

        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_use_highest_latest_released_nvr(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            ["s2i-base-1-2", {"latest_released": True}],
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        foo = self._create_imgs([
            "foo-5.7-1",
            "s2i-base-1-1",
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "foo-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ])
        ]

        self.maxDiff = None
        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl, foo])
        self.assertEqual(ret, expected_images)

    @patch.object(freshmaker.conf, 'lightblue_released_dependencies_only',
                  new=True)
    def test_use_highest_latest_released_nvr_include_released_only(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            ["s2i-base-1-2", {"latest_released": True}],
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        foo = self._create_imgs([
            "foo-5.7-1",
            "s2i-base-1-1",
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "foo-5.7-1",
                ["s2i-base-1-2", {"latest_released": True}],
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ])
        ]

        self.maxDiff = None
        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl, foo])
        self.assertEqual(ret, expected_images)

    def test_use_highest_nvr(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            "s2i-base-1-2",
            "s2i-core-1-2",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ])
        ]

        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_keep_multiple_nvs(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            "s2i-base-2-2",
            "s2i-core-2-2",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                "s2i-base-2-2",
                "s2i-core-2-2",
                "rhel-server-docker-7.4-150",
            ])
        ]

        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)

    def test_batches_same_image_in_batch(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-150",
        ])
        perl = self._create_imgs([
            "perl-5.7-1",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-150",
        ])
        to_rebuild = [httpd, perl]
        batches = self.lb._images_to_rebuild_to_batches(to_rebuild)
        batches = [
            sorted_by_nvr(images, get_nvr=lambda image: image['brew']['build'])
            for images in batches]

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
        deps = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-150",
        ])
        to_rebuild = []
        for i in range(len(deps)):
            to_rebuild.append(deps[i:])

        batches = self.lb._images_to_rebuild_to_batches(to_rebuild)
        batches = [
            sorted_by_nvr(images, get_nvr=lambda image: image['brew']['build'])
            for images in batches]

        # We expect each image to be rebuilt just once.
        expected = [[deps[3]], [deps[2]], [deps[1]], [deps[0]]]
        self.assertEqual(batches, expected)

    def test_replace_docker_with_container(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            "s2i-base-1-2",
            "s2i-core-1-2",
            "rhel-server-container-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-container-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "rhel-server-container-7.4-150",
            ])
        ]

        self.maxDiff = None
        ret = self.lb._deduplicate_images_to_rebuild([httpd, perl])
        self.assertEqual(ret, expected_images)


class TestArchitecturesFromRegistry(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestArchitecturesFromRegistry, self).setUp()
        self.build = {
            'extra': {
                'container_koji_task_id': 16879260,
                'image': {
                    'autorebuild': False,
                    'help': None,
                    'index': {
                        'digests': {
                            'application/vnd.docker.distribution.manifest.list.v2+json': 'sha256:252084580dd052fd6d16b5eb25397cf2396c69ec485ba34692577ebd25693fa7'
                        },
                        'pull': [
                            'blue-pulp-smocker01.sledmat.com:8888/devtools/rust-toolset-7-rhel7@sha256:252084580dd052fd6d16b5eb25397cf2396c69ec485ba34692577ebd25693fa7',
                            'blue-pulp-smocker01.sledmat.com:8888/devtools/rust-toolset-7-rhel7:1.26.2-4',
                        ],
                        'tags': ['latest', '1.26.2', '1.26.2-4']
                    },
                    'isolated': False,
                    'media_types': [
                        'application/json',
                        'application/vnd.docker.distribution.manifest.list.v2+json',
                        'application/vnd.docker.distribution.manifest.v1+json',
                        'application/vnd.docker.distribution.manifest.v2+json'],
                    'parent_build_id': 714853,
                },
                'submitter': 'osbs'
            },
        }

    def test_feature_flag(self):
        """ Unless configured, the method should always return None. """
        image = ContainerImage.create({"brew": {"build": "nvr"}})
        result = image._get_architectures_from_registry('foo', 'whatever')
        self.assertEqual(result, None)

    @patch.object(freshmaker.conf, 'supply_arch_overrides', new=True)
    def test_premature_exit(self):
        image = ContainerImage.create({"brew": {"build": "nvr"}})
        result = image._get_architectures_from_registry('foo', 'whatever')
        self.assertEqual(result, 'x86_64')

    @patch.object(freshmaker.conf, 'supply_arch_overrides', new=True)
    @patch('freshmaker.lightblue.requests')
    def test_happy_path(self, requests):
        image = ContainerImage.create({"brew": {"build": "nvr"}})
        requests.get.return_value.json.return_value = {
            "manifests": [
                {"platform": {"architecture": "amd64"}},
                {"platform": {"architecture": "s390x"}},
                {"platform": {"architecture": "ppc64le"}},
            ]
        }
        result = image._get_architectures_from_registry("foo", self.build)
        self.assertEqual(result, 'x86_64 s390x ppc64le')
        requests.get.assert_called_once_with(
            'http://blue-pulp-smocker01.sledmat.com:8888/v2/devtools/'
            'rust-toolset-7-rhel7/manifests/'
            'sha256:252084580dd052fd6d16b5eb25397cf2396c69ec485ba34692577ebd25693fa7',
            headers={'Accept': 'application/vnd.docker.distribution.manifest.list.v2+json'},
        )

    @patch.object(freshmaker.conf, 'supply_arch_overrides', new=True)
    @patch('freshmaker.lightblue.requests')
    def test_invalid_json(self, requests):
        image = ContainerImage.create({"brew": {"build": "nvr"}})
        requests.get.return_value.json.side_effect = ValueError
        self.assertRaises(KojiLookupError, image._get_architectures_from_registry, "foo", self.build)

    @patch.object(freshmaker.conf, 'supply_arch_overrides', new=True)
    @patch('freshmaker.lightblue.requests')
    def test_bad_status(self, requests):
        image = ContainerImage.create({"brew": {"build": "nvr"}})
        requests.get.return_value.ok = False
        self.assertRaises(KojiLookupError, image._get_architectures_from_registry, "foo", self.build)
