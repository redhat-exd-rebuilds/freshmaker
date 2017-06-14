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

from mock import call, patch
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
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/rpms/repo-1/plain/Dockerfile?id=commit_hash1',
                            'filename': u'Dockerfile'
                        }
                    ],
                    'rpm_manifest': [
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
                'parsed_data': {
                    'files': [
                        {
                            'key': 'buildfile',
                            'content_url': 'http://git.repo.com/cgit/ns/repo-2/plain/Dockerfile?id=commit_hash2',
                            'filename': 'Dockerfile'
                        },
                        {
                            'key': 'bogusfile',
                            'content_url': 'bogus_test_url',
                            'filename': 'bogus.file'
                        }
                    ],
                    'rpm_manifest': [
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
                        "field": "parsed_data.rpm_manifest.*.srpm_name",
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
            "projection": [
                {"field": "brew", "include": True, "recursive": True},
                {"field": "parsed_data.files", "include": True, "recursive": True},
                {"field": "parsed_data.rpm_manifest.*.srpm_nevra", "include": True, "recursive": True},
                {"field": "parsed_data.rpm_manifest.*.srpm_name", "include": True, "recursive": True}
            ]
        }
        cont_images.assert_called_with(expected_image_request)
        self.assertEqual(ret, cont_images.return_value)

    @patch('freshmaker.lightblue.LightBlue.find_container_repositories')
    @patch('freshmaker.lightblue.LightBlue.find_container_images')
    @patch('os.path.exists')
    def test_images_with_content_set_packages(self, exists,
                                              cont_images,
                                              cont_repos):

        exists.return_value = True
        cont_repos.return_value = self.fake_repositories_with_content_sets
        cont_images.return_value = self.fake_images_with_parsed_data

        lb = LightBlue(server_url=self.fake_server_url,
                       cert=self.fake_cert_file,
                       private_key=self.fake_private_key)
        ret = lb.find_images_with_package_from_content_set("openssl",
                                                           ["dummy-content-set-1"])

        self.assertEqual(2, len(ret))
        self.assertEqual(ret,
                         [
                             {
                                 "repository": "rpms/repo-1",
                                 "commit": "commit_hash1",
                                 "srpm_nevra": "openssl-0:1.2.3-1.src",
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-1-4-12.10",
                                     "package": "package-name-1"
                                 }
                             },
                             {
                                 "repository": "ns/repo-2",
                                 "commit": "commit_hash2",
                                 "srpm_nevra": "openssl-1:1.2.3-1.src",
                                 "brew": {
                                     "completion_date": u"20170421T04:27:51.000-0400",
                                     "build": "package-name-2-4-12.10",
                                     "package": "package-name-2"
                                 }
                             }
                         ])

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
