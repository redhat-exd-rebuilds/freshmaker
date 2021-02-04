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
import json
import io
import http.client

from unittest import mock
from unittest.mock import call, patch, Mock

import freshmaker

from freshmaker.lightblue import ContainerImage
from freshmaker.lightblue import ContainerRepository
from freshmaker.lightblue import LightBlue
from freshmaker.lightblue import LightBlueRequestError
from freshmaker.lightblue import LightBlueSystemError
from freshmaker.utils import sorted_by_nvr
from tests.test_handler import MyHandler
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
        self.e = LightBlueRequestError(http.client.BAD_REQUEST,
                                       self.fake_error_data)

    def test_get_raw_error_json_data(self):
        self.assertEqual(self.fake_error_data, self.e.raw)

    def test_get_status_code(self):
        self.assertEqual(http.client.BAD_REQUEST, self.e.status_code)

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
        buf = io.StringIO('''
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
        self.e = LightBlueSystemError(http.client.UNAUTHORIZED,
                                      self.fake_error_data)

    def test_get_status_code(self):
        self.assertEqual(http.client.UNAUTHORIZED, self.e.status_code)

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
            http.client.BAD_REQUEST, content)
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


class TestContainerImageObject(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestContainerImageObject, self).setUp()

        self.koji_read_config_patcher = patch(
            'koji.read_config', return_value={'server': 'http://localhost/'})
        self.koji_read_config_patcher.start()

        self.patcher = helpers.Patcher(
            'freshmaker.lightblue.')

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
                        "srpm_nevra": "openssl-0:1.2.3-1.src",
                        "name": "openssl",
                        "nvra": "openssl-1.2.3-1.amd64"
                    },
                    {
                        "srpm_name": "tespackage",
                        "srpm_nevra": "testpackage-10:1.2.3-1.src",
                        "name": "tespackage",
                        "nvra": "testpackage-1.2.3-1.amd64"
                    }
                ]
            }]
        })

    def tearDown(self):
        super(TestContainerImageObject, self).tearDown()
        self.patcher.unpatch_all()
        self.koji_read_config_patcher.stop()

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

    def test_update_multi_arch(self):
        rpm_manifest_x86_64 = [{'rpms': [{'name': 'spam'}]}]
        image_x86_64 = ContainerImage.create({
            '_id': '1233829',
            'architecture': 'amd64',
            'brew': {
                'completion_date': '20151210T10:09:35.000-0500',
                'build': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6',
                'package': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker'
            },
            'rpm_manifest': rpm_manifest_x86_64,
        })

        rpm_manifest_s390x = [{'rpms': [{'name': 'maps'}]}]
        image_s390x = ContainerImage.create({
            '_id': '1233829',
            'architecture': 's390x',
            'brew': {
                'completion_date': '20151210T10:09:35.000-0500',
                'build': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker-1.1-6',
                'package': 'jboss-webserver-3-webserver30-tomcat7-openshift-docker'
            },
            'rpm_manifest': rpm_manifest_s390x,
        })

        self.assertEqual(image_x86_64['rpm_manifest'], rpm_manifest_x86_64)
        self.assertEqual(image_x86_64['multi_arch_rpm_manifest'], {'amd64': rpm_manifest_x86_64})
        self.assertEqual(image_s390x['rpm_manifest'], rpm_manifest_s390x)
        self.assertEqual(image_s390x['multi_arch_rpm_manifest'], {'s390x': rpm_manifest_s390x})

        image_x86_64.update_multi_arch(image_s390x)
        self.assertEqual(image_x86_64['rpm_manifest'], rpm_manifest_x86_64)
        self.assertEqual(image_x86_64['multi_arch_rpm_manifest'], {
            'amd64': rpm_manifest_x86_64,
            's390x': rpm_manifest_s390x
        })
        self.assertEqual(image_s390x['rpm_manifest'], rpm_manifest_s390x)
        self.assertEqual(image_s390x['multi_arch_rpm_manifest'], {'s390x': rpm_manifest_s390x})

        image_s390x.update_multi_arch(image_x86_64)
        self.assertEqual(image_x86_64['rpm_manifest'], rpm_manifest_x86_64)
        self.assertEqual(image_x86_64['multi_arch_rpm_manifest'], {
            'amd64': rpm_manifest_x86_64,
            's390x': rpm_manifest_s390x
        })
        self.assertEqual(image_s390x['rpm_manifest'], rpm_manifest_s390x)
        self.assertEqual(image_s390x['multi_arch_rpm_manifest'], {
            'amd64': rpm_manifest_x86_64,
            's390x': rpm_manifest_s390x
        })

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
        self.assertTrue(self.dummy_image["generate_pulp_repos"])

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
    @patch('freshmaker.kojiservice.KojiService.list_archives')
    def test_resolve_commit_prefer_build_source(
            self, list_archives, get_task_request, get_build):
        get_build.return_value = {
            "build_id": 67890,
            "task_id": 123456,
            "source": "git://example.com/rpms/repo-1?#commit_hash1"}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1?#origin/master", "target1", {}]
        list_archives.return_value = [
            {'btype': 'image', 'extra': {'image': {'arch': 'ppc64le'}}},
            {'btype': 'image', 'extra': {'image': {'arch': 's390x'}}}
        ]

        with patch.object(freshmaker.conf, 'supply_arch_overrides', new=True):
            self.dummy_image.resolve_commit()
        self.assertEqual(self.dummy_image["repository"], "rpms/repo-1")
        self.assertEqual(self.dummy_image["commit"], "commit_hash1")
        self.assertEqual(self.dummy_image["target"], "target1")
        self.assertEqual(self.dummy_image["arches"], 'ppc64le s390x')

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
            ["package-name-1-4-12.10"], published=True,
            include_rpm_manifest=False)

    def test_resolve_published_unpublished(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })

        lb = Mock()
        lb.get_images_by_nvrs.side_effect = [[], [{"rpm_manifest": "x"}]]
        image.resolve_published(lb)
        self.assertEqual(image["published"], False)
        lb.get_images_by_nvrs.assert_has_calls([
            call(["package-name-1-4-12.10"], published=True, include_rpm_manifest=False),
            call(["package-name-1-4-12.10"])])

        self.assertEqual(image["rpm_manifest"], "x")

    def test_resolve_published_not_image_in_lb(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })

        lb = Mock()
        lb.get_images_by_nvrs.return_value = []
        image.resolve_published(lb)


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

        self.koji_read_config_patcher = patch(
            'koji.read_config', return_value={'server': 'http://locahost/'})
        self.koji_read_config_patcher.start()

        self.patcher = helpers.Patcher(
            'freshmaker.lightblue.')

        self.fake_server_url = 'lightblue.localhost'
        self.fake_cert_file = 'path/to/cert'
        self.fake_private_key = 'path/to/private-key'
        self.fake_repositories_with_content_sets = [
            {
                "repository": "product/repo1",
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"],
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
                'parent_brew_build': 'some-original-nvr-7.6-252.1561619826',
                'repositories': [
                    {'registry': 'registry.example.com',
                     'repository': 'product1/repo1', 'published': True,
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
                            "srpm_nevra": "openssl-0:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.amd64"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src",
                            "name": "tespackage",
                            "nvra": "testpackage-1.2.3-1.amd64"
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
                    {'registry': 'registry.example.com',
                     'repository': 'product2/repo2', 'published': True,
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
                            "srpm_nevra": "openssl-1:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.amd64"
                        },
                        {
                            "srpm_name": "tespackage2",
                            "srpm_nevra": "testpackage2-10:1.2.3-1.src",
                            "name": "tespackage2",
                            "nvra": "testpackage2-1.2.3-1.amd64"
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
                    {'registry': 'registry.example.com',
                     'repository': 'product2/repo2', 'published': True,
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
                            "srpm_nevra": "openssl-0:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.amd64"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src",
                            "name": "tespackage",
                            "nvra": "testpackage-1.2.3-1.amd64"
                        }
                    ]
                }]
            },
        ]

        self.fake_images_with_modules = [
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-3-4-12.10',
                    'package': 'package-name-1'
                },
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"],
                'repositories': [
                    {'registry': 'registry.example.com',
                     'repository': 'product2/repo2', 'published': True,
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
                            "srpm_nevra": "openssl-1.2.1-2.module+el8.0.0+3248+9d514f3b.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.1-2.module+el8.0.0+3248+9d514f3b.amd64"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src",
                            "name": "tespackage",
                            "nvra": "testpackage-1.2.3-1.amd64"
                        }
                    ]
                }]
            },
        ]

        self.fake_images_with_parent_brew_build = [
            {
                'brew': {
                    'completion_date': '20170421T04:27:51.000-0400',
                    'build': 'package-name-1-4-12.10',
                    'package': 'package-name-1'
                },
                'content_sets': ['dummy-content-set-1',
                                 'dummy-content-set-2'],
                'parent_brew_build': 'some-original-nvr-7.6-252.1561619826',
                'repositories': [
                    {'registry': 'registry.example.com',
                     'repository': 'product1/repo1', 'published': True,
                     'tags': [{'name': 'latest'}]}
                ],
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1',
                            'filename': 'Dockerfile'
                        }
                    ],
                },
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-0:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.amd64"
                        },
                        {
                            "srpm_name": "tespackage",
                            "srpm_nevra": "testpackage-10:1.2.3-1.src",
                            "name": "tespackage",
                            "nvra": "testpackage-1.2.3-1.amd64"
                        }
                    ]
                }]
            }
        ]

        self.fake_container_images = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parsed_data]

        self.fake_container_images_floating_tag = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parsed_data_floating_tag]

        self.fake_images_with_modules = [
            ContainerImage.create(data)
            for data in self.fake_images_with_modules]

        self.fake_container_images_with_parent_brew_build = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parent_brew_build]

        self.fake_koji_builds = [{"task_id": 654321}, {"task_id": 123456}]
        self.fake_koji_task_requests = [
            ["git://pkgs.devel.redhat.com/rpms/repo-2#commit_hash2",
             "target2", {"git_branch": "mybranch"}],
            ["git://pkgs.devel.redhat.com/rpms/repo-1#commit_hash1",
             "target1", {"git_branch": "mybranch"}]]
        self.current_db_event_id = MyHandler.current_db_event_id

    def tearDown(self):
        super(TestQueryEntityFromLightBlue, self).tearDown()
        self.patcher.unpatch_all()
        self.koji_read_config_patcher.stop()

    @patch('os.path.exists', return_value=True)
    def test_LightBlue_returns_event(self, exists):
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key,
                       event_id=self.current_db_event_id)
        assert lb.event_id == self.current_db_event_id

    @patch('freshmaker.lightblue.requests.post')
    def test_find_container_images(self, post):
        post.return_value.status_code = http.client.OK
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
                {"field": "architecture", "include": True, "recursive": False},
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
        self.assertEqual('57ea8d289c624c035f96f4db', image['_id'])
        self.assertEqual('sadc-docker',
                         image['brew']['package'])
        image = images[1]
        self.assertEqual('57ea8d1f9c624c035f96f4b0', image['_id'])
        self.assertEqual('jboss-webserver-3-webserver30-tomcat7-openshift-docker',
                         image['brew']['package'])

    @patch('freshmaker.lightblue.ContainerImage.update_multi_arch')
    @patch('freshmaker.lightblue.requests.post')
    def test_find_container_images_with_multi_arch(self, post, update_multi_arch):
        post.return_value.status_code = http.client.OK
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
                    'architecture': 'amd64',
                    'brew': {
                        'completion_date': '20151210T10:09:35.000-0500',
                        'build': 'sadc-container-1.1-6',
                        'package': 'sadc-container',
                    },
                    'content_sets': ['dummy-content-set-1'],
                },
                {
                    '_id': '57ea8d289c624c035f96f4db',
                    'image_id': 'c1ef3345f36b901b0bddc7ab01ea3f3c83c886faa243e02553f475124eb4b46c',
                    'architecture': 's390x',
                    'brew': {
                        'completion_date': '20151203T00:35:30.000-0500',
                        'build': 'sadc-container-1.1-6',
                        'package': 'sadc-container',
                    },
                    'content_sets': ['dummy-content-set-2'],
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
                {"field": "architecture", "include": True, "recursive": False},
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
        self.assertEqual(1, len(images))
        # Verify update_multi_arch is first called with the second image,
        # then with the first image. This is to ensure all ContainerImage
        # objects for the same Brew build have the same multi arch data.
        self.assertEqual(
            ['c1ef3345f36b901b0bddc7ab01ea3f3c83c886faa243e02553f475124eb4b46c',
             'e0f97342ddf6a09972434f98837b5fd8b5bed9390f32f1d63e8a7e4893208af7'],
            [call_args[0][0]['image_id'] for call_args in update_multi_arch.call_args_list])

    @patch('freshmaker.lightblue.requests.post')
    def test_find_container_repositories(self, post):
        post.return_value.status_code = http.client.OK
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
                    },
                    'repository': 'spam',
                    'auto_rebuild_tags': ['latest'],
                },
                {
                    'creationDate': '20161020T04:52:43.365-0400',
                    'metrics': {
                        'last_update_date': '20170501T03:00:19.892-0400',
                        'pulls_in_last_30_days': 20
                    },
                    'repository': 'bacon',
                    'auto_rebuild_tags': ['latest'],
                },
                {
                    'creationDate': '20161020T04:52:43.365-0400',
                    'metrics': {
                        'last_update_date': '20170501T03:00:19.892-0400',
                        'pulls_in_last_30_days': 20
                    },
                    # This repository is ignored by Freshmaker because it does not
                    # have auto_rebuild_tags set.
                    'repository': 'ignored-due-to-missing-tags',
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

        self.assertEqual(repos[0]['repository'], 'spam')
        self.assertEqual(repos[1]['repository'], 'bacon')

    @patch('freshmaker.lightblue.requests.post')
    def test_raise_error_if_request_data_is_incorrect(self, post):
        post.return_value.status_code = http.client.BAD_REQUEST
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

    @patch.object(freshmaker.conf, 'unpublished_exceptions',
                  new=[{"repository": "some_repo", "registry": "some_registry"}])
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
                "$or": [
                    {
                        "$and": [
                            {
                                "field": "published",
                                "op": "=",
                                "rvalue": True
                            },
                            {
                                "$or": [
                                    {"field": "release_categories.*", "rvalue": "Generally Available", "op": "="},
                                    {"field": "release_categories.*", "rvalue": "Tech Preview", "op": "="},
                                    {"field": "release_categories.*", "rvalue": "Beta", "op": "="}]
                            },
                            {
                                "$or": [
                                    {"field": "vendorLabel", "rvalue": "redhat", "op": "="},
                                ]
                            },
                        ]
                    },
                    {
                        "$and": [
                            {"field": "published", "op": "=", "rvalue": False},
                            {"field": "registry", "op": "=",
                             "rvalue": "some_registry"},
                            {"field": "repository", "op": "=",
                             "rvalue": "some_repo"},
                        ]
                    }
                ]
            },
            "projection": [
                {"field": "repository", "include": True},
                {"field": "published", "include": True},
                {"field": "auto_rebuild_tags", "include": True, "recursive": True},
                {"field": "release_categories", "include": True, "recursive": True},
            ]
        }
        cont_repos.assert_called_with(expected_repo_request)

        expected_ret = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        self.assertEqual(ret, expected_ret)

    @patch.object(freshmaker.conf, 'unpublished_exceptions', new=[
        {'registry': 'unpublished_registry_1',
         'repository': 'unpublished_repo_1'},
        {'registry': 'unpublished_registry_2',
         'repository': 'unpublished_repo_2'}
    ])
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_find_images_with_included_srpm(self, exists, cont_images):
        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        # Add a duplicate simulating a multi-arch image
        self.fake_container_images.append(self.fake_container_images[1])
        cont_images.return_value = self.fake_container_images
        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2"], repositories)

        expected_image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [
                            {"field": "repositories.*.published", "op": "=",
                             "rvalue": True},
                            {
                                "$and": [
                                    {"field": "repositories.*.published",
                                     "op": "=",
                                     "rvalue": False},
                                    {"field": "repositories.*.registry",
                                     "op": "=",
                                     "rvalue": "unpublished_registry_1"},
                                    {"field": "repositories.*.repository",
                                     "op": "=",
                                     "rvalue": "unpublished_repo_1"}
                                ]
                            },
                            {
                                "$and": [
                                    {"field": "repositories.*.published",
                                     "op": "=",
                                     "rvalue": False},
                                    {"field": "repositories.*.registry",
                                     "op": "=",
                                     "rvalue": "unpublished_registry_2"},
                                    {"field": "repositories.*.repository",
                                     "op": "=",
                                     "rvalue": "unpublished_repo_2"}
                                ]
                            }
                        ]
                    },
                    {
                        "field": "repositories.*.tags.*.name", "op": "$in",
                        "values": ["latest", "tag1", "tag2"]
                    },
                    {
                        "field": "content_sets.*", "op": "$in",
                        "values": ["dummy-content-set-1", "dummy-content-set-2"]},
                    {
                        "field": "rpm_manifest.*.rpms.*.name", "op": "$in",
                        "values": ["openssl"]}
                ]
            },
            "projection": lb._get_default_projection(rpm_names=["openssl"])
        }

        # auto_rebuild_tags is a set in the source code. When generate
        # criteria for tags, the order is not guaranteed. Following lines sort
        # the tags criteria in order to assert with expected value.
        request_arg = cont_images.call_args[0][0]
        request_arg['query']['$and'][1]["values"].sort()

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
        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2"], repositories)

        self.assertEqual(
            [image.nvr for image in ret],
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
        ret = lb.find_images_with_included_rpms(
            ["content-set-1", "content-set-2"], ["openssl-1.2.3-1"], repositories)
        self.assertEqual(ret, [])

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_newer_srpm_multilpe_nvrs(
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
        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"],
            ["openssl-1.2.3-1", "openssl-1.2.3-50"], repositories)
        self.assertEqual(
            [image.nvr for image in ret],
            ['package-name-2-4-12.10', 'package-name-3-4-12.10'])

    def _filter_fnc(self, image):
        return image.nvr.startswith("filtered_")

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
                {"content_sets": ["dummy-content-set-1"],
                 "brew": {"build": "filtered_x-1-23"},
                 "repositories": [
                     {"registry": "registry.example.com",
                      "repository": "product/repo1", "published": True,
                      "tags": [{"name": "latest"}]}]})]
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
                                 "multi_arch_rpm_manifest": {},
                                 "odcs_compose_ids": None,
                                 "parent_build_id": None,
                                 "parent_image_builds": None,
                                 "published": True,
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-2-4-12.10",
                                     "package": "package-name-2"
                                 },
                                 'content_sets': ["dummy-content-set-1"],
                                 'content_sets_source': 'lightblue_container_image',
                                 'directly_affected': True,
                                 "release_categories": ["Generally Available"],
                                 'repositories': [
                                     {'registry': 'registry.example.com',
                                      'repository': 'product2/repo2', 'published': True,
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
                                             "srpm_nevra": "openssl-1:1.2.3-1.src",
                                             "name": "openssl",
                                             "nvra": "openssl-1.2.3-1.amd64"
                                         },
                                         {
                                             "srpm_name": "tespackage2",
                                             "srpm_nevra": "testpackage2-10:1.2.3-1.src",
                                             "name": "tespackage2",
                                             "nvra": "testpackage2-1.2.3-1.amd64"
                                         }
                                     ]
                                 }]
                             },
                         ])

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    @patch('os.path.exists')
    def test_images_with_content_set_packages_unpublished(
            self, exists, koji_task_request, koji_get_build, cont_images, cont_repos
    ):
        exists.return_value = True
        cont_repos.return_value = self.fake_repositories_with_content_sets

        # "filtered_x-1-23" image will be filtered by filter_fnc.
        cont_images.return_value = self.fake_container_images + [
            ContainerImage.create(
                {
                    "content_sets": ["dummy-content-set-1"],
                    "brew": {"build": "filtered_x-1-23"},
                    "repositories": [
                        {
                            "registry": "registry.example.com",
                            "repository": "product/repo1",
                            "published": True,
                            "tags": [{"name": "latest"}]
                        }
                    ]
                }
            )]
        # Include the images for second time to ensure that they will be
        # returned only once. This can happen when the image is multiarch.
        cont_images.return_value += self.fake_container_images

        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)

        ret = lb.find_images_with_packages_from_content_set(
            set(["openssl-1.2.3-3"]), ["dummy-content-set-1"],
            filter_fnc=self._filter_fnc,
            published=False
        )

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
                                 "parent_build_id": None,
                                 "parent_image_builds": None,
                                 "multi_arch_rpm_manifest": {},
                                 "published": True,
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-2-4-12.10",
                                     "package": "package-name-2"
                                 },
                                 'content_sets': ["dummy-content-set-1"],
                                 'content_sets_source': 'lightblue_container_image',
                                 'directly_affected': True,
                                 "release_categories": ["Generally Available"],
                                 'repositories': [
                                     {'registry': 'registry.example.com',
                                      'repository': 'product2/repo2', 'published': True,
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
                                             "srpm_nevra": "openssl-1:1.2.3-1.src",
                                             "name": "openssl",
                                             "nvra": "openssl-1.2.3-1.amd64"
                                         },
                                         {
                                             "srpm_name": "tespackage2",
                                             "srpm_nevra": "testpackage2-10:1.2.3-1.src",
                                             "name": "tespackage2",
                                             "nvra": "testpackage2-1.2.3-1.amd64"
                                         }
                                     ]
                                 }]
                             },
                         ])

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    @patch('os.path.exists')
    def test_images_with_content_set_packages_beta(
            self, exists, koji_task_request, koji_get_build, cont_images, cont_repos):
        exists.return_value = True
        cont_repos.return_value = self.fake_repositories_with_content_sets
        cont_repos.return_value[1]["release_categories"] = ["Beta"]
        cont_images.return_value = self.fake_container_images
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
        self.assertTrue("latest_released" not in ret[0])
        self.assertEqual(ret[0]["release_categories"], ["Beta"])

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
            self.fake_container_images[0], "openssl")

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(set(ret[0]["content_sets"]),
                         set(["dummy-content-set-1", "dummy-content-set-2"]))

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
            self.fake_container_images[0], "openssl", [])

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
    @patch('freshmaker.lightblue.LightBlue._filter_out_already_fixed_published_images')
    @patch('os.path.exists')
    def test_images_to_rebuild(self,
                               exists,
                               _filter_out_already_fixed_published_images,
                               find_parent_images_with_package,
                               find_images_with_packages_from_content_set):
        exists.return_value = True

        image_a = ContainerImage.create({
            'brew': {'package': 'image-a', 'build': 'image-a-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-a-commit'
        })
        image_b = ContainerImage.create({
            'brew': {'package': 'image-b', 'build': 'image-b-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-b-commit',
            'parent': image_a,
        })
        image_c = ContainerImage.create({
            'brew': {'package': 'image-c', 'build': 'image-c-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-c-commit',
            'parent': image_b,
        })
        image_e = ContainerImage.create({
            'brew': {'package': 'image-e', 'build': 'image-e-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-e-commit',
            'parent': image_a,
        })
        image_d = ContainerImage.create({
            'brew': {'package': 'image-d', 'build': 'image-d-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-d-commit',
            'parent': image_e,
        })
        image_j = ContainerImage.create({
            'brew': {'package': 'image-j', 'build': 'image-j-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-j-commit',
            'parent': image_e,
        })
        image_k = ContainerImage.create({
            'brew': {'package': 'image-k', 'build': 'image-k-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-k-commit',
            'parent': image_j,
        })
        image_g = ContainerImage.create({
            'brew': {'package': 'image-g', 'build': 'image-g-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-g-commit',
            'parent': None,
        })
        image_f = ContainerImage.create({
            'brew': {'package': 'image-f', 'build': 'image-f-v-r1'},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'image-f-commit',
            'parent': image_g,
        })

        leaf_image1 = ContainerImage.create({
            'brew': {'build': 'leaf-image-1-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image1-commit',
        })
        leaf_image2 = ContainerImage.create({
            'brew': {'build': 'leaf-image-2-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image2-commit',
        })
        leaf_image3 = ContainerImage.create({
            'brew': {'build': 'leaf-image-3-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image3-commit',
        })
        leaf_image4 = ContainerImage.create({
            'brew': {'build': 'leaf-image-4-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image4-commit',
        })
        leaf_image5 = ContainerImage.create({
            'brew': {'build': 'leaf-image-5-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image5-commit',
        })
        leaf_image6 = ContainerImage.create({
            'brew': {'build': 'leaf-image-6-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{"repository": "foo/bar"}],
            'repository': 'repo-1',
            'commit': 'leaf-image6-commit',
        })
        leaf_image7 = ContainerImage.create({
            'brew': {'build': 'leaf-image-7-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repositories': [{'repository': 'foo/bar'}],
            'repository': 'repo-1',
            'commit': 'leaf-image7-commit',
        })
        images = [
            leaf_image1, leaf_image2, leaf_image3, leaf_image4, leaf_image5, leaf_image6,
            leaf_image7,
        ]

        for image in images:
            image["rpm_manifest"] = [{
                "rpms": [
                    {"name": "dummy"}
                ]
            }]
            image["directly_affected"] = True

        find_images_with_packages_from_content_set.return_value = images

        leaf_image6_as_parent = copy.deepcopy(leaf_image6)
        leaf_image6_as_parent['parent'] = image_f
        # When the image is a parent, directly_affected is not set
        del leaf_image6_as_parent["directly_affected"]
        find_parent_images_with_package.side_effect = [
            [image_b, image_a],                        # parents of leaf_image1
            [image_c, image_b, image_a],               # parents of leaf_image2
            [image_k, image_j, image_e, image_a],      # parents of leaf_image3
            [image_d, image_e, image_a],               # parents of leaf_image4
            [image_a],                                 # parents of leaf_image5
            [image_f, image_g],                        # parents of leaf_image6
            [leaf_image6_as_parent, image_f, image_g]  # parents of leaf_image7
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
            [image_k, leaf_image2, leaf_image4, leaf_image7],
            [leaf_image3]
        ]
        expected_batches_nvrs = [
            {image.nvr for image in batch}
            for batch in expected_batches
        ]

        returned_batches_nvrs = [
            {image.nvr for image in batch}
            for batch in batches
        ]

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
            "leaf-image-5-1", "leaf-image-1-1", "leaf-image-3-1", "leaf-image-6-1",
            "leaf-image-7-1", "leaf-image-4-1", "leaf-image-2-1",
        }

        _filter_out_already_fixed_published_images.assert_called_once_with(
            mock.ANY, expected_directly_affected_nvrs, ["dummy-1-1"], ["dummy"]
        )

    @patch("freshmaker.lightblue.ContainerImage.resolve_published")
    @patch("freshmaker.lightblue.LightBlue.get_images_by_nvrs")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package_using_field_parent_brew_build(
            self, get_task_request, get_build, exists, cont_images,
            resolve_published):
        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]
        exists.return_value = True

        cont_images.side_effect = [self.fake_container_images_with_parent_brew_build, [], []]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images_with_parent_brew_build[0], "openssl", [])

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(set(ret[0]["content_sets"]),
                         set(["dummy-content-set-1", "dummy-content-set-2"]))
        self.assertEqual(ret[-1]['error'], (
            "Couldn't find parent image some-original-nvr-7.6-252.1561619826. "
            "Lightblue data is probably incomplete"))

    @patch("freshmaker.lightblue.LightBlue.get_images_by_nvrs")
    @patch('freshmaker.lightblue.LightBlue.find_images_with_packages_from_content_set')
    @patch('freshmaker.lightblue.LightBlue.find_parent_images_with_package')
    @patch('freshmaker.lightblue.LightBlue._filter_out_already_fixed_published_images')
    @patch('os.path.exists')
    def test_parent_images_with_package_using_field_parent_brew_build_parent_empty(
            self, exists, _filter_out_already_fixed_published_images,
            find_parent_images_with_package, find_images_with_packages_from_content_set,
            cont_images):
        exists.return_value = True

        image_a = ContainerImage.create({
            "brew": {"package": "image-a", "build": "image-a-v-r1"},
            "parent_brew_build": "some-original-nvr-7.6-252.1561619826",
            "repository": "repo-1",
            "commit": "image-a-commit",
            "repositories": [{"repository": "foo/bar"}],
            "rpm_manifest": [{
                "rpms": [
                    {"name": "dummy"}
                ]
            }]
        })

        find_parent_images_with_package.return_value = []
        find_images_with_packages_from_content_set.return_value = [image_a]
        cont_images.side_effect = [self.fake_container_images_with_parent_brew_build, [], []]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_images_to_rebuild(["dummy-1-1"], ["dummy"])

        self.assertEqual(len(ret), 1)
        self.assertIsNotNone(ret[0][0].get("parent"))

    @patch("freshmaker.lightblue.LightBlue.get_images_by_nvrs")
    @patch('freshmaker.lightblue.LightBlue.find_images_with_packages_from_content_set')
    @patch('freshmaker.lightblue.LightBlue.find_parent_images_with_package')
    @patch('freshmaker.lightblue.LightBlue._filter_out_already_fixed_published_images')
    @patch('os.path.exists')
    def test_dedupe_dependency_images_with_all_repositories(
            self, exists, _filter_out_already_fixed_published_images,
            find_parent_images_with_package, find_images_with_packages_from_content_set,
            get_images_by_nvrs):
        exists.return_value = True

        vulnerable_rpm_name = 'oh-noes'
        vulnerable_rpm_nvr = '{}-1.0-1'.format(vulnerable_rpm_name)

        ubi_image_template = {
            "brew": {"package": "ubi8-container", "build": "ubi8-container-8.1-100"},
            "parent_image_builds": {},
            "repository": "containers/ubi8",
            "commit": "2b868f757977782367bf624373a5fe3d8e6bacd6",
            "repositories": [{"repository": "ubi8"}],
            "rpm_manifest": [{
                "rpms": [
                    {"name": vulnerable_rpm_name}
                ]
            }]
        }

        directly_affected_ubi_image = ContainerImage.create(copy.deepcopy(ubi_image_template))

        dependency_ubi_image_data = copy.deepcopy(ubi_image_template)
        dependency_ubi_image_nvr = directly_affected_ubi_image.nvr + ".12345678"
        dependency_ubi_image_data["brew"]["build"] = dependency_ubi_image_nvr
        # A dependecy image is not directly published
        dependency_ubi_image_data["repositories"] = []
        dependency_ubi_image = ContainerImage.create(dependency_ubi_image_data)

        python_image = ContainerImage.create({
            "brew": {"package": "python-36-container", "build": "python-36-container-1-10"},
            "parent_brew_build": directly_affected_ubi_image.nvr,
            "parent_image_builds": {},
            "repository": "containers/python-36",
            "commit": "3a740231deab2abf335d5cad9a80d466c783be7d",
            "repositories": [{"repository": "ubi8/python-36"}],
            "rpm_manifest": [{
                "rpms": [
                    {"name": vulnerable_rpm_name}
                ]
            }]
        })

        nodejs_image = ContainerImage.create({
            "brew": {"package": "nodejs-12-container", "build": "nodejs-12-container-1-20.45678"},
            "parent_brew_build": dependency_ubi_image.nvr,
            "repository": "containers/nodejs-12",
            "commit": "97d57a9db975b58b43113e15d29e35de6c1a3f0b",
            "repositories": [{"repository": "ubi8/nodejs-12"}],
            "rpm_manifest": [{
                "rpms": [
                    {"name": vulnerable_rpm_name}
                ]
            }]
        })

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
            directly_affected_ubi_image, python_image, nodejs_image,
        ]

        def fake_get_images_by_nvrs(nvrs, **kwargs):
            if nvrs == [dependency_ubi_image.nvr]:
                return [dependency_ubi_image]
            elif nvrs == [directly_affected_ubi_image.nvr]:
                return [directly_affected_ubi_image]
            raise ValueError("Unexpected test data, {}".format(nvrs))

        get_images_by_nvrs.side_effect = fake_get_images_by_nvrs

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        batches = lb.find_images_to_rebuild([vulnerable_rpm_nvr], [vulnerable_rpm_name])
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

    @patch("freshmaker.lightblue.ContainerImage.resolve_published")
    @patch("freshmaker.lightblue.LightBlue.get_images_by_nvrs")
    @patch("os.path.exists")
    @patch("freshmaker.kojiservice.KojiService.get_build")
    @patch("freshmaker.kojiservice.KojiService.get_task_request")
    def test_parent_images_with_package_using_field_parent_image_builds(
            self, get_task_request, get_build, exists, cont_images,
            resolve_published):
        get_build.return_value = {
            "task_id": 123456,
            "extra": {
                "image": {
                    "parent_build_id": 1074147,
                    "parent_image_builds": {
                        "rh-osbs/openshift-golang-builder:1.11": {
                            "id": 969696,
                            "nvr": "openshift-golang-builder-container-v1.11.13-3.1"
                        },
                        "rh-osbs/openshift-ose-base:v4.1.34.20200131.033116": {
                            "id": 1074147,
                            "nvr": "openshift-enterprise-base-container-v4.1.34-202001310309"
                        },
                    }
                }
            }
        }
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]
        exists.return_value = True

        self.fake_container_images[0].pop('parent_brew_build')
        cont_images.side_effect = [self.fake_container_images, [], []]

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            self.fake_container_images[0], "openssl", [])

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")
        self.assertEqual(set(ret[0]["content_sets"]),
                         set(["dummy-content-set-1", "dummy-content-set-2"]))

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_content_set_packages_exception(self, exists,
                                                        cont_images,
                                                        cont_repos):

        exists.return_value = True
        cont_repos.side_effect = LightBlueRequestError(
            {"errors": [{"msg": "dummy error"}]}, http.client.REQUEST_TIMEOUT)
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
            {"errors": [{"msg": "dummy error"}]}, http.client.REQUEST_TIMEOUT)

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
                    {'$or': [{'field': 'content_sets.*', 'rvalue': 'dummy-content-set', 'op': '='}]},
                    {'$or': [{'field': 'rpm_manifest.*.rpms.*.name', 'rvalue': 'openssl', 'op': '='}]}]},
             'projection': [{'field': 'brew', 'include': True, 'recursive': True},
                            {'field': 'parsed_data.files', 'include': True, 'recursive': True},
                            {'field': 'parsed_data.layers.*', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.published', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.registry', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.repository', 'include': True, 'recursive': True},
                            {'field': 'repositories.*.tags.*.name', 'include': True, 'recursive': True},
                            {'field': 'content_sets', 'include': True, 'recursive': True},
                            {'field': 'parent_brew_build', 'include': True, 'recursive': False},
                            {'field': 'architecture', 'include': True, 'recursive': False},
                            {'field': 'rpm_manifest.*.rpms.*.srpm_nevra', 'include': True, 'recursive': True},
                            {'field': 'rpm_manifest.*.rpms.*.nvra', 'include': True, 'recursive': True},
                            {'field': 'rpm_manifest.*.rpms.*.name', 'include': True, 'recursive': True},
                            {'field': 'rpm_manifest.*.rpms.*.srpm_name', 'include': True, 'recursive': True}],
             'objectType': 'containerImage'})

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    def test_content_sets_of_multiarch_images_to_rebuild(
            self, find_images, find_repos):
        new_images = [
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'build1-name-1.1',
                    'package': 'package-name-3'
                },
                "content_sets": ["content-set-1",
                                 "content-set-2"],
                'parent_brew_build': 'some-original-nvr-7.6-252.1561619826',
                'repositories': [
                    {'repository': 'product1/repo1', 'published': True,
                     'tags': [{"name": "latest"}]}
                ],
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-0:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.amd64"
                        }
                    ]
                }],
                'architecture': 'amd64'
            },
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'build1-name-1.1',
                    'package': 'package-name-4'
                },
                "content_sets": ["content-set-2",
                                 "content-set-3"],
                'parent_brew_build': 'some-original-nvr-7.6-252.1561619826',
                'repositories': [
                    {'repository': 'product1/repo1', 'published': True,
                     'tags': [{"name": "latest"}]}
                ],
                'rpm_manifest': [{
                    'rpms': [
                        {
                            "srpm_name": "openssl",
                            "srpm_nevra": "openssl-0:1.2.3-1.src",
                            "name": "openssl",
                            "nvra": "openssl-1.2.3-1.s390x"
                        }
                    ]
                }],
                'architecture': 's390x'
            }
        ]
        new_images = [ContainerImage.create(i) for i in new_images]
        find_repos.return_value = self.fake_repositories_with_content_sets
        find_images.return_value = self.fake_container_images + new_images
        right_content_sets = [["dummy-content-set-1", "dummy-content-set-2"],
                              ["dummy-content-set-1"],
                              ["content-set-1", "content-set-2"],
                              ["content-set-2", "content-set-3"]]
        with patch('os.path.exists'):
            lb = LightBlue(server_url=self.fake_server_url,
                           cert=self.fake_cert_file,
                           private_key=self.fake_private_key)
            ret = lb.find_images_with_packages_from_content_set(
                set(["openssl-1.2.3-3"]),
                ["content-set-1", "content-set-2", "content-set-3"],
                leaf_container_images=['placeholder'])

        self.assertEqual(4, len(ret))
        images_content_sets = [sorted(i.get('content_sets', ['!'])) for i in ret]
        self.assertEqual(images_content_sets, right_content_sets)

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_modular_container_image(
            self, exists, cont_images):

        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        cont_images.return_value = (
            self.fake_images_with_modules)
        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2.module+el8.0.0+3248+9d514f3b.src"], repositories)
        self.assertEqual(
            [image.nvr for image in ret],
            ["package-name-3-4-12.10"])
        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2.el8.0.0+3248+9d514f3b.src"], repositories)
        self.assertEqual(
            [image.nvr for image in ret],
            [])

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_filter_out_by_content_sets(
            self, exists, cont_images):

        repos = [{
            "registry": "registry.example.com",
            "repository": "product/repo1", "published": True,
            'tags': [{"name": "latest"}]}]
        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        parent = ContainerImage.create({
            "brew": {"build": "parent-1-2"}, "repositories": repos,
            "content_sets": ["dummy-content-set-1"]})
        latest_parent = ContainerImage.create({
            "brew": {"build": "parent-1-3"}, "repositories": repos,
            "content_sets": ["dummy-content-set-1"]})
        older_parent = ContainerImage.create({
            "brew": {"build": "parent-1-1"}, "repositories": repos,
            "content_sets": ["dummy-content-set-2"]})
        cont_images.return_value = [parent, latest_parent, older_parent]

        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1"], ["openssl-1.2.3-2.module+el8.0.0+3248+9d514f3b"], repositories)
        self.assertEqual(
            [image.nvr for image in ret],
            ["parent-1-2", "parent-1-3"])

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_srpm_but_exclude_build_repo_images(self, exists, find_images):
        """Test images from build repositories will be excluded."""
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = {
            repo["repository"]: repo for repo in
            self.fake_repositories_with_content_sets}
        build_repo_image = {
            'brew': {
                'completion_date': u'20170421T04:27:51.000-0400',
                'build': 'package-name-3.1-238',
                'package': 'package-name-3'
            },
            "content_sets": ["dummy-content-set-1",
                             "dummy-content-set-2"],
            'parent_brew_build': 'some-base-container-202-30',
            'repositories': [
                {'registry': 'registry.internel-build.example.com',
                 'repository': 'product2/repo2', 'published': False,
                 'tags': [{"name": "latest"}]}
            ],
            'rpm_manifest': [{
                'rpms': [
                    {
                        "srpm_name": "openssl",
                        "srpm_nevra": "openssl-0:1.2.3-1.src",
                        "name": "openssl",
                        "nvra": "openssl-1.2.3-1.amd64"
                    }
                ]
            }],
            'architecture': 'amd64'
        }
        build_repo_image = ContainerImage.create(build_repo_image)
        self.fake_container_images.append(build_repo_image)
        find_images.return_value = self.fake_container_images

        ret = lb.find_images_with_included_rpms(
            ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2"], repositories)

        self.assertEqual(ret, [find_images.return_value[1], find_images.return_value[-1]])

        # again, but this time we have build registries set
        build_registries = ["registry.internel-build.example.com"]
        with patch.object(
            freshmaker.conf, "image_build_repository_registries", new=build_registries
        ):
            ret = lb.find_images_with_included_rpms(
                ["dummy-content-set-1", "dummy-content-set-2"], ["openssl-1.2.3-2"], repositories)

        self.assertEqual(ret, [find_images.return_value[1]])


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
            'repositories': [{"repository": "product/repo1"}],
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

    @patch.object(freshmaker.conf, 'lightblue_released_dependencies_only',
                  new=True)
    def test_update_parent_to_newer_version_parent(self):
        """
        When an image is replaced by a newer release, update its parent by
        the parent of newer release, even the parent has a different version.
        """
        rust_toolset = self._create_imgs([
            "rust-toolset-container-1.41.1-27",
            "s2i-base-container-1-173",
            "s2i-core-container-1-147",
            "ubi8-container-8.2-299",
        ])

        nodejs_10 = self._create_imgs([
            "nodejs-10-container-1-66.1584015429",
            "s2i-base-container-1-142.1584015404",
            "s2i-core-container-1-119.1584015378",
            "ubi8-container-8.0-208.1584015373",
        ])

        expected_images = [
            self._create_imgs([
                "rust-toolset-container-1.41.1-27",
                "s2i-base-container-1-173",
                "s2i-core-container-1-147",
                "ubi8-container-8.2-299",
            ]),
            self._create_imgs([
                "nodejs-10-container-1-66.1584015429",
                "s2i-base-container-1-173",
                "s2i-core-container-1-147",
                "ubi8-container-8.2-299",
            ]),
        ]

        self.maxDiff = None
        ret = self.lb._deduplicate_images_to_rebuild([rust_toolset, nodejs_10])
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

    def test_same_nv_different_r_different_repos(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-2",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-125",
        ])

        perl = self._create_imgs([
            "perl-5.7-1",
            ["s2i-base-1-3", {
                "content_sets": ["foo"],
                "repositories": [{
                    "repository": "product/repo2",
                    "content_sets": ["foo"]
                }]}],
            "s2i-core-2-12",
            "rhel-server-docker-7.4-150",
        ])

        expected_images = [
            self._create_imgs([
                "httpd-2.4-12",
                "s2i-base-1-2",
                "s2i-core-1-11",
                "rhel-server-docker-7.4-150",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                ["s2i-base-1-3", {
                    "content_sets": ["foo"],
                    "repositories": [{
                        "repository": "product/repo2",
                        "content_sets": ["foo"]
                    }]}],
                "s2i-core-2-12",
                "rhel-server-docker-7.4-150",
            ])
        ]

        self.maxDiff = None
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
        batches = self.lb._images_to_rebuild_to_batches(to_rebuild, set())
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
        deps = self._create_imgs([
            httpd_nvr,
            "s2i-base-1-10",
            "s2i-core-1-11",
            "rhel-server-docker-7.4-150",
        ])
        to_rebuild = []
        for i in range(len(deps)):
            to_rebuild.append(deps[i:])

        batches = self.lb._images_to_rebuild_to_batches(to_rebuild, {httpd_nvr})
        batches = [sorted_by_nvr(images) for images in batches]

        # We expect each image to be rebuilt just once.
        expected = [[deps[3]], [deps[2]], [deps[1]], [deps[0]]]
        self.assertEqual(batches, expected)
        for batch in batches:
            for image in batch:
                if image.nvr == httpd_nvr:
                    self.assertTrue(image['directly_affected'])
                else:
                    self.assertFalse(image.get('directly_affected'))

    def test_parent_changed_in_latest_release(self):
        httpd = self._create_imgs([
            "httpd-2.4-12",
            "s2i-base-1-10",
            "s2i-core-1-11",
            "foo-7.4-125",
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
                "foo-7.4-125",
            ]),
            self._create_imgs([
                "perl-5.7-1",
                "s2i-base-1-10",
                "s2i-core-1-11",
                "foo-7.4-125",
            ])
        ]

        for val in [True, False]:
            with patch.object(freshmaker.conf, 'lightblue_released_dependencies_only', new=val):
                ret = self.lb._deduplicate_images_to_rebuild([httpd, perl])
                self.assertEqual(ret, expected_images)


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.get_fixed_published_image')
@patch('freshmaker.lightblue.LightBlue.describe_image_group')
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
        "pineapple-topping-remover-1.0.0-1"
    }
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]

    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")
    lb._filter_out_already_fixed_published_images(
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
            mock.call('rhel-server-container', '7.6', mock_dig(), set(rpm_nvrs), content_sets),
            mock.call('rhel-server-container', '7.8', mock_dig(), set(rpm_nvrs), content_sets),
            mock.call('rhel-server-container', '7.6', mock_dig(), set(rpm_nvrs), content_sets),
        )
    )


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image(mock_fci, mock_exists):
    other_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-188"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
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
    latest_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
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
    # Don't have `resolve` reach out over the network
    other_rhel7_image.resolve = Mock()
    latest_rhel7_image.resolve = Mock()
    mock_fci.side_effect = [[other_rhel7_image, latest_rhel7_image], [latest_rhel7_image]]
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image == latest_rhel7_image


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_not_found(mock_fci, mock_exists):
    mock_fci.return_value = []
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_diff_repo(mock_fci, mock_exists):
    latest_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "other_repo"}],
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
    mock_fci.return_value = [latest_rhel7_image]
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_missing_rpm(mock_fci, mock_exists):
    latest_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
        }
    )
    mock_fci.return_value = [latest_rhel7_image]
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_modularity_mismatch(mock_fci, mock_exists):
    latest_rhel8_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-8.2-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
            "rpm_manifest": [
                {
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-34.module+el8.2.0+6123+12149598.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-34.module+el8.2.0+6123+12149598.src",
                            "version": "4.2.46",
                        }
                    ]
                }
            ],
        }
    )
    mock_fci.return_value = [latest_rhel8_image]
    image_group = "rhel-server-container-8.2-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el8"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "8.2", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_rpm_too_old(mock_fci, mock_exists):
    latest_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
            "rpm_manifest": [
                {
                    "rpms": [
                        {
                            "name": "bash",
                            "nvra": "bash-4.2.46-33.el7.x86_64",
                            "srpm_name": "bash",
                            "srpm_nevra": "bash-0:4.2.46-33.el7.src",
                            "version": "4.2.46",
                        }
                    ]
                }
            ],
        }
    )
    mock_fci.return_value = [latest_rhel7_image]
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None


@patch('os.path.exists', return_value=True)
@patch('freshmaker.lightblue.LightBlue.find_container_images')
def test_get_fixed_published_image_not_found_by_nvr(mock_fci, mock_exists):
    latest_rhel7_image = ContainerImage.create(
        {
            "brew": {"build": "rhel-server-container-7.9-189"},
            "content_sets": ["rhel-7-server-rpms"],
            "repositories": [{"repository": "repo"}],
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
    # Don't have `resolve` reach out over the network
    latest_rhel7_image.resolve = Mock()
    mock_fci.side_effect = [[latest_rhel7_image], []]
    image_group = "rhel-server-container-7.9-['repo']"
    rpm_nvrs = ["bash-4.2.46-34.el7"]
    content_sets = ["rhel-7-server-rpms"]
    lb = LightBlue("lb.domain.local", "/path/to/cert", "/path/to/key")

    image = lb.get_fixed_published_image(
        "rhel-server-container", "7.9", image_group, rpm_nvrs, content_sets
    )

    assert image is None
