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
import unittest

from mock import call, patch, Mock
from six.moves import http_client

from freshmaker.lightblue import ContainerImage
from freshmaker.lightblue import ContainerRepository
from freshmaker.lightblue import LightBlue
from freshmaker.lightblue import LightBlueRequestError
from freshmaker.lightblue import LightBlueSystemError


class TestLightBlueRequestError(unittest.TestCase):
    """Test case for exception LightBlueRequestError"""

    def setUp(self):
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


class TestLightBlueSystemError(unittest.TestCase):
    """Test LightBlueSystemError"""

    def setUp(self):
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

    def test__str__(self):
        self.assertEqual(
            'JBWEB000065: HTTP Status 401 - JBWEB000009: No client certificate'
            ' chain in this request',
            str(self.e))

    def test__repr__(self):
        self.assertEqual('<{} [{}]>'.format(self.e.__class__.__name__,
                                            self.e.status_code),
                         repr(self.e))


class TestContainerImageObject(unittest.TestCase):

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

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_koji_fallback(self, get_task_request, get_build):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'completion_date': u'20170421T04:27:51.000-0400',
                'build': 'package-name-1-4-12.10',
                'package': 'package-name-1'
            },
            'rpm_manifest': {
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
            }
        })

        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]

        image.resolve_commit("openssl")
        self.assertEqual(image["repository"], "rpms/repo-1")
        self.assertEqual(image["commit"], "commit_hash1")
        self.assertEqual(image["target"], "target1")
        self.assertEqual(image["srpm_nevra"], "openssl-0:1.2.3-1.src")

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_no_koji_build(self, get_task_request, get_build):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'completion_date': u'20170421T04:27:51.000-0400',
                'build': 'package-name-1-4-12.10',
                'package': 'package-name-1'
            },
            'rpm_manifest': {
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
            }
        })

        get_build.return_value = {}

        image.resolve_commit("openssl")
        self.assertEqual(image["repository"], None)
        self.assertEqual(image["commit"], None)
        self.assertEqual(image["target"], None)
        self.assertEqual(image["srpm_nevra"], "openssl-0:1.2.3-1.src")
        self.assertTrue(image["error"].find(
            "Cannot find Koji build with nvr package-name-1-4-12.10 in "
            "Koji.") != -1)

    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_resolve_commit_no_task_id(self, get_task_request, get_build):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'completion_date': u'20170421T04:27:51.000-0400',
                'build': 'package-name-1-4-12.10',
                'package': 'package-name-1'
            },
            'rpm_manifest': {
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
            }
        })

        get_build.return_value = {"task_id": None}

        image.resolve_commit("openssl")
        self.assertEqual(image["repository"], None)
        self.assertEqual(image["commit"], None)
        self.assertEqual(image["target"], None)
        self.assertEqual(image["srpm_nevra"], "openssl-0:1.2.3-1.src")
        self.assertTrue(image["error"].find(
            "Cannot find task_id or container_koji_task_id in the Koji build "
            "{'task_id': None}") != -1)

    def test_resolve_content_sets_no_repositories(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
        })
        self.assertTrue("content_sets" not in image)

        lb = Mock()
        image.resolve_content_sets(lb)
        self.assertEqual(image["content_sets"], [])

    def test_resolve_content_sets_empty_repositories(self):
        image = ContainerImage.create({
            '_id': '1233829',
            'brew': {
                'build': 'package-name-1-4-12.10',
            },
            'repositories': []
        })
        self.assertTrue("content_sets" not in image)

        lb = Mock()
        image.resolve_content_sets(lb)
        self.assertEqual(image["content_sets"], [])


class TestContainerRepository(unittest.TestCase):

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


class TestQueryEntityFromLightBlue(unittest.TestCase):

    def setUp(self):
        # Clear the ContainerImage Koji cache.
        ContainerImage.KOJI_BUILDS_CACHE = {}

        self.fake_server_url = 'lightblue.localhost'
        self.fake_cert_file = 'path/to/cert'
        self.fake_private_key = 'path/to/private-key'
        self.fake_repositories_with_content_sets = [
            {
                "repository": "product/repo1",
                "content_sets": ["dummy-content-set-1",
                                 "dummy-content-set-2"]
            },
            {
                "repository": "product2/repo2",
                "content_sets": ["dummy-content-set-1"]
            }
        ]

        self.fake_images_with_parsed_data = [
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-1-4-12.10',
                    'package': 'package-name-1'
                },
                'repositories': [
                    {'repository': 'product1/repo1', 'published': True}
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
                'rpm_manifest': {
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
                }
            },
            {
                'brew': {
                    'completion_date': u'20170421T04:27:51.000-0400',
                    'build': 'package-name-2-4-12.10',
                    'package': 'package-name-2'
                },
                'repositories': [
                    {'repository': 'product2/repo2', 'published': True}
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
                'rpm_manifest': {
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
                }
            },
        ]

        self.fake_container_images = [
            ContainerImage.create(data)
            for data in self.fake_images_with_parsed_data]

        self.fake_koji_builds = [{"task_id": 123456}, {"task_id": 654321}]
        self.fake_koji_task_requests = [
            ["git://pkgs.devel.redhat.com/rpms/repo-1#commit_hash1",
             "target1", {"git_branch": "mybranch"}],
            ["git://pkgs.devel.redhat.com/rpms/repo-2#commit_hash2",
             "target2", {"git_branch": "mybranch"}]]

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
    def test_find_repositories_with_content_sets(self, exists,
                                                 cont_repos):
        exists.return_value = True
        queried_content_set = "rhel-7-server-rpms"
        cont_repos.return_value = self.fake_repositories_with_content_sets
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_repositories_with_content_sets([queried_content_set])
        expected_repo_request = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "$or": [
                            {
                                "field": "content_sets.*",
                                "op": "=",
                                "rvalue": queried_content_set
                            }
                        ],
                    },
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
                {"field": "content_sets", "include": True, "recursive": True}

            ]
        }
        cont_repos.assert_called_with(expected_repo_request)
        self.assertEqual(ret, cont_repos.return_value)

    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_included_srpm(self, exists,
                                       cont_images):

        exists.return_value = True
        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        repositories = self.fake_repositories_with_content_sets
        cont_images.return_value = self.fake_images_with_parsed_data
        ret = lb.find_images_with_included_srpm(repositories,
                                                "openssl")

        expected_image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [
                            {
                                "field": "repositories.*.repository",
                                "op": "=",
                                "rvalue": "product/repo1"
                            },
                            {
                                "field": "repositories.*.repository",
                                "op": "=",
                                "rvalue": "product2/repo2"
                            },
                        ],
                    },
                    {
                        "field": "repositories.*.published",
                        "op": "=",
                        "rvalue": True
                    },
                    {
                        "field": "repositories.*.tags.*.name",
                        "op": "=",
                        "rvalue": "latest"
                    },
                    {
                        "field": "rpm_manifest.*.rpms.*.srpm_name",
                        "op": "=",
                        "rvalue": "openssl"
                    },
                    {
                        "field": "parsed_data.files.*.key",
                        "op": "=",
                        "rvalue": "buildfile"
                    }
                ]
            },
            "projection": lb._get_default_projection()
        }
        cont_images.assert_called_with(expected_image_request)
        self.assertEqual(ret, cont_images.return_value)

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
            ContainerImage.create({"brew": {"build": "filtered_x-1-23"}})]
        koji_task_request.side_effect = self.fake_koji_task_requests
        koji_get_build.side_effect = self.fake_koji_builds

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_images_with_package_from_content_set(
            "openssl", ["dummy-content-set-1"], filter_fnc=self._filter_fnc)

        self.assertEqual(2, len(ret))
        self.assertEqual(ret,
                         [
                             {
                                 "repository": "rpms/repo-1",
                                 "commit": "commit_hash1",
                                 "srpm_nevra": "openssl-0:1.2.3-1.src",
                                 "target": "target1",
                                 "git_branch": "mybranch",
                                 "error": None,
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-1-4-12.10",
                                     "package": "package-name-1"
                                 },
                                 'repositories': [{'repository': 'product1/repo1', 'published': True}],
                                 'content_sets': ['dummy-content-set-1', 'dummy-content-set-2'],
                                 'parsed_data': {
                                     'files': [
                                         {
                                             'key': 'buildfile',
                                             'content_url': 'http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1',
                                             'filename': u'Dockerfile'
                                         }
                                     ]
                                 },
                                 'rpm_manifest': {
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
                                 }
                             },
                             {
                                 "repository": "rpms/repo-2",
                                 "commit": "commit_hash2",
                                 "srpm_nevra": "openssl-1:1.2.3-1.src",
                                 "target": "target2",
                                 "git_branch": "mybranch",
                                 "error": None,
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-2-4-12.10",
                                     "package": "package-name-2"
                                 },
                                 'content_sets': ['dummy-content-set-1', 'dummy-content-set-2'],
                                 'repositories': [{'repository': 'product2/repo2', 'published': True}],
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
                                 'rpm_manifest': {
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
                                 }
                             }
                         ])

    @patch('freshmaker.lightblue.LightBlue.find_content_sets_for_repository')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    @patch('freshmaker.kojiservice.KojiService.get_build')
    @patch('freshmaker.kojiservice.KojiService.get_task_request')
    def test_parent_images_with_package(self, get_task_request, get_build,
                                        exists, cont_images, cont_sets):

        get_build.return_value = {"task_id": 123456}
        get_task_request.return_value = [
            "git://example.com/rpms/repo-1#commit_hash1", "target1", {}]
        exists.return_value = True
        cont_images.side_effect = [self.fake_container_images, [],
                                   self.fake_container_images]
        cont_sets.return_value = set(["content-set"])

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_parent_images_with_package(
            "openssl", ["layer0", "layer1", "layer2", "layer3"])

        self.assertEqual(1, len(ret))
        self.assertEqual(ret[0]["brew"]["package"], "package-name-1")

    @patch('freshmaker.lightblue.LightBlue.find_images_with_package_from_content_set')
    @patch('freshmaker.lightblue.LightBlue.find_parent_images_with_package')
    @patch('freshmaker.lightblue.LightBlue.find_unpublished_image_for_build')
    @patch('os.path.exists')
    def test_images_to_rebuild(self,
                               exists,
                               find_unpublished_image_for_build,
                               find_parent_images_with_package,
                               find_images_with_package_from_content_set):
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
            'brew': {'build': 'leaf-image-1'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image1-commit',
        })
        leaf_image2 = ContainerImage.create({
            'brew': {'build': 'leaf-image-2'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image2-commit',
        })
        leaf_image3 = ContainerImage.create({
            'brew': {'build': 'leaf-image-3'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image3-commit',
        })
        leaf_image4 = ContainerImage.create({
            'brew': {'build': 'leaf-image-4'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image4-commit',
        })
        leaf_image5 = ContainerImage.create({
            'brew': {'build': 'leaf-image-5'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image5-commit',
        })
        leaf_image6 = ContainerImage.create({
            'brew': {'build': 'leaf-image-6'},
            'parsed_data': {'layers': ['fake layer']},
            'repository': 'repo-1',
            'commit': 'leaf-image6-commit',
        })
        images = [
            leaf_image1, leaf_image2, leaf_image3,
            leaf_image4, leaf_image5, leaf_image6
        ]
        find_unpublished_image_for_build.side_effect = images
        find_images_with_package_from_content_set.return_value = images

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
        batches = lb.find_images_to_rebuild("dummy", "dummy")

        # Each of batch is sorted for assertion easily
        expected_batches = [
            [image_a, image_g],
            [image_b, image_e, image_f, leaf_image5],
            [image_c, image_d, image_j, leaf_image1, leaf_image6],
            [image_k, leaf_image2, leaf_image4],
            [leaf_image3]
        ]

        self.assertEqual(
            expected_batches,
            [sorted(images, key=lambda image: image['brew']['build'])
             for images in batches])

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
            lb.find_images_with_package_from_content_set(
                "openssl",
                ["dummy-content-set-1"])

        cont_repos.return_value = self.fake_repositories_with_content_sets
        cont_images.side_effect = LightBlueRequestError(
            {"errors": [{"msg": "dummy error"}]}, http_client.REQUEST_TIMEOUT)

        with self.assertRaises(LightBlueRequestError):
            lb.find_images_with_package_from_content_set(
                "openssl",
                ["dummy-content-set-1"])


class TestEntityVersion(unittest.TestCase):
    """Test case for ensuring correct entity version in request"""

    def setUp(self):
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
