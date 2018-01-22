# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import unittest
import requests

from mock import patch

import freshmaker

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, Compose
from freshmaker.types import EventState


class TestErrataAdvisoryRPMsSignedHandler(unittest.TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        # We do not want to send messages to message bus while running tests
        self.messaging_publish_patcher = patch('freshmaker.messaging.publish')
        self.mock_messaging_publish = self.messaging_publish_patcher.start()

        # Each time when recording a build into database, freshmaker has to
        # request a pulp repo from ODCS. This is not necessary for running
        # tests.
        # There are 6 images used to run tests which will be created below, so
        # there should be 6 composes created as Pulp repos.
        self.prepare_pulp_repo_patcher = patch(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
            '_prepare_pulp_repo',
            side_effect=[{'id': compose_id} for compose_id in range(1, 7)])
        self.mock_prepare_pulp_repo = self.prepare_pulp_repo_patcher.start()

        self.find_images_patcher = patch(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
            '_find_images_to_rebuild')
        self.mock_find_images_to_rebuild = self.find_images_patcher.start()

        # boot.iso composes IDs should be different from pulp composes IDs as
        # when each time to request a compose from ODCS, new compose ID will
        # be returned along with new comopse.
        self.request_boot_iso_compose_patcher = patch(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
            '_request_boot_iso_compose',
            side_effect=[{'id': 100}, {'id': 101}])
        self.mock_request_boot_iso_compose = \
            self.request_boot_iso_compose_patcher.start()

        # Fake images found to rebuild has these relationships
        #
        # Batch 1  |         Batch 2            |          Batch 3
        # image_a  | image_c (child of image_a) | image_f (child of image_e)
        # image_b  | image_d (child of image_a) |
        #          | image_e (child of image_b) |
        #
        self.image_a = ContainerImage({
            'repository': 'repo_1',
            'commit': '1234567',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_a_content_set_1', 'image_a_content_set_2'],
            'brew': {
                'build': 'image-a-1.0-2',
            },
            'parent': None,
            'parsed_data': {
                'layers': [
                    'sha512:7890',
                    'sha512:5678',
                ]
            },
        })
        self.image_b = ContainerImage({
            'repository': 'repo_2',
            'commit': '23e9f22',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_b_content_set_1', 'image_b_content_set_2'],
            'brew': {
                'build': 'image-b-1.0-1'
            },
            'parent': None,
            'parsed_data': {
                'layers': [
                    'sha512:1234',
                    'sha512:4567',
                ]
            },
        })
        self.image_c = ContainerImage({
            'repository': 'repo_2',
            'commit': '2345678',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_c_content_set_1', 'image_d_content_set_2'],
            'brew': {
                'build': 'image-c-0.2-9',
            },
            'parent': self.image_a,
            'parsed_data': {
                'layers': [
                    'sha512:4ef3',
                    'sha512:7890',
                    'sha512:5678',
                ]
            },
        })
        self.image_d = ContainerImage({
            'repository': 'repo_2',
            'commit': '5678901',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_d_content_set_1', 'image_d_content_set_2'],
            'brew': {
                'build': 'image-d-2.14-1',
            },
            'parent': self.image_a,
            'parsed_data': {
                'layers': [
                    'sha512:f109',
                    'sha512:7890',
                    'sha512:5678',
                ]
            },
        })
        self.image_e = ContainerImage({
            'repository': 'repo_2',
            'commit': '7890123',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_e_content_set_1', 'image_e_content_set_2'],
            'brew': {
                'build': 'image-e-1.0-1',
            },
            'parent': self.image_b,
            'parsed_data': {
                'layers': [
                    'sha512:5aae',
                    'sha512:1234',
                    'sha512:4567',
                ]
            },
        })
        self.image_f = ContainerImage({
            'repository': 'repo_2',
            'commit': '3829384',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_f_content_set_1', 'image_f_content_set_2'],
            'brew': {
                'build': 'image-f-0.2-1',
            },
            'parent': self.image_b,
            'parsed_data': {
                'layers': [
                    'sha512:8b9e',
                    'sha512:1234',
                    'sha512:4567',
                ]
            },
        })
        # For simplicify, mocking _find_images_to_rebuild to just return one
        # batch, which contains images found for rebuild from parent to
        # childrens.
        self.mock_find_images_to_rebuild.return_value = iter([
            [
                [self.image_a, self.image_b],
                [self.image_c, self.image_d, self.image_e],
                [self.image_f]
            ]
        ])

    def tearDown(self):
        self.request_boot_iso_compose_patcher.stop()
        self.find_images_patcher.stop()
        self.prepare_pulp_repo_patcher.stop()
        self.messaging_publish_patcher.stop()

        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': [{'advisory_name': 'RHBA-2017'}]
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_setting_fake_compose_id_dry_run_mode(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        self.mock_find_images_to_rebuild.return_value = iter([[[]]])
        event = ErrataAdvisoryRPMsSignedEvent(
            "123", "RHBA-2017", 123, "", "REL_PREP")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        self.assertEqual(ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID, 5)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': [{'advisory_name': 'RHBA-2017'}]
        }
    })
    def test_event_state_updated_when_no_images_to_rebuild(self):
        self.mock_find_images_to_rebuild.return_value = iter([[[]]])
        event = ErrataAdvisoryRPMsSignedEvent(
            "123", "RHBA-2017", 123, "", "REL_PREP")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No container images to rebuild for advisory 'RHBA-2017'")

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': [{'advisory_name': 'RHBA-2017'}]
        }
    })
    def test_event_state_updated_when_all_images_failed(self):
        self.image_a['error'] = "foo"
        self.mock_find_images_to_rebuild.return_value = iter([
            [
                [self.image_a]
            ]
        ])
        event = ErrataAdvisoryRPMsSignedEvent(
            "123", "RHBA-2017", 123, "", "REL_PREP")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.COMPLETE.value)
        self.assertEqual(
            db_event.state_reason,
            "No container images to rebuild, all are in failed state.")

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'allow_build', return_value=True)
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'start_to_build_images')
    def test_rebuild_if_errata_state_is_prior_to_SHIPPED_LIVE(
            self, start_to_build_images, prepare_yum_repos_for_rebuilds,
            allow_build):
        event = ErrataAdvisoryRPMsSignedEvent(
            'msg-id-123', 'RHSA-2017', 123, '', 'REL_PREP')
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_called_once()
        start_to_build_images.assert_not_called()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'allow_build', return_value=True)
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'start_to_build_images')
    @patch('freshmaker.models.Event.get_image_builds_in_first_batch')
    def test_rebuild_if_errata_state_is_SHIPPED_LIVE(
            self, get_image_builds_in_first_batch, start_to_build_images,
            prepare_yum_repos_for_rebuilds, allow_build):
        event = ErrataAdvisoryRPMsSignedEvent(
            'msg-id-123', 'RHSA-2017', 123, '', 'SHIPPED_LIVE')
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_not_called()
        get_image_builds_in_first_batch.assert_called_once_with(db.session)
        start_to_build_images.assert_called_once()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)


class TestGetBaseImageBuildTarget(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_base_image_build_target"""

    def setUp(self):
        self.image = ContainerImage({
            'repository': 'repo_1',
            'commit': '1234567',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_a_content_set_1', 'image_a_content_set_2'],
            'brew': {
                'build': 'image-a-1.0-2',
            },
            'parent': None,
            'parsed_data': {
                'layers': [
                    'sha512:7890',
                    'sha512:5678',
                ],
                'files': [
                    {
                        'filename': 'Dockerfile',
                        'content_url': 'http://pkgs.localhost/cgit/rpms/'
                                       'image-a/plain/Dockerfile?id=fa521323',
                        'key': 'buildfile'
                    }
                ]
            },
        })
        self.handler = ErrataAdvisoryRPMsSignedHandler()

    @patch('requests.get')
    def test_get_target_from_image_build_conf(self, get):
        get.return_value.content = '''\
[image-build]
name = image-a
arches = x86_64
format = docker
disk_size = 10
ksurl = git://git.localhost/spin-kickstarts.git?rhel7#HEAD
kickstart = rhel-7.4-server-docker.ks
version = 7.4
target = guest-rhel-7.4-docker
distro = RHEL-7.4
ksversion = RHEL7'''

        result = self.handler._get_base_image_build_target(self.image)
        self.assertEqual('guest-rhel-7.4-docker', result)

    @patch('requests.get')
    def test_image_build_conf_is_unavailable_in_distgit(self, get):
        get.return_value.raise_for_status.side_effect = \
            requests.exceptions.HTTPError('error')

        result = self.handler._get_base_image_build_target(self.image)
        self.assertIsNone(result)

    @patch('requests.get')
    def test_image_build_conf_is_empty(self, get):
        get.return_value.content = ''

        result = self.handler._get_base_image_build_target(self.image)
        self.assertIsNone(result)

    @patch('requests.get')
    def test_image_build_conf_is_not_INI(self, get):
        get.return_value.content = 'abc'

        result = self.handler._get_base_image_build_target(self.image)
        self.assertIsNone(result)


class TestGetBaseImageBuildTag(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_base_image_build_tag"""

    def setUp(self):
        self.image = ContainerImage({
            'repository': 'repo_1',
            'commit': '1234567',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_a_content_set_1', 'image_a_content_set_2'],
            'brew': {
                'build': 'image-a-1.0-2',
            },
            'parent': None,
            'parsed_data': {
                'layers': [
                    'sha512:7890',
                    'sha512:5678',
                ],
                'files': [
                    {
                        'filename': 'Dockerfile',
                        'content_url': 'http://pkgs.localhost/cgit/rpms/'
                                       'image-a/plain/Dockerfile?id=fa521323',
                        'key': 'buildfile'
                    }
                ]
            },
        })
        self.handler = ErrataAdvisoryRPMsSignedHandler()

    @patch('freshmaker.kojiservice.KojiService')
    def test_get_build_tag_name(self, KojiService):
        koji_service = KojiService.return_value
        koji_service.get_build_target.return_value = {
            'build_tag': 10052,
            'build_tag_name': 'guest-rhel-7.4-docker-build',
            'dest_tag': 10051,
            'dest_tag_name': 'guest-rhel-7.4-candidate',
            'id': 3205,
            'name': 'guest-rhel-7.4-docker'
        }

        result = self.handler._get_base_image_build_tag(
            'guest-rhel-7.4-docker')
        self.assertEqual('guest-rhel-7.4-docker-build', result)

    @patch('freshmaker.kojiservice.KojiService')
    def test_no_target_is_returned(self, KojiService):
        koji_service = KojiService.return_value
        koji_service.get_build_target.return_value = None

        result = self.handler._get_base_image_build_tag(
            'guest-rhel-7.4-docker')
        self.assertIsNone(result)


class TestRequestBootISOCompose(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._request_boot_iso_compose"""

    def setUp(self):
        self.image = ContainerImage({
            'repository': 'repo_1',
            'commit': '1234567',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_a_content_set_1', 'image_a_content_set_2'],
            'brew': {
                'build': 'image-a-1.0-2',
            },
            'parent': None,
            'parsed_data': {
                'layers': [
                    'sha512:7890',
                    'sha512:5678',
                ],
                'files': [
                    {
                        'filename': 'Dockerfile',
                        'content_url': 'http://pkgs.localhost/cgit/rpms/'
                                       'image-a/plain/Dockerfile?id=fa521323',
                        'key': 'buildfile'
                    }
                ]
            },
        })
        self.handler = ErrataAdvisoryRPMsSignedHandler()

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.krb_context')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'create_odcs_client')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_target')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_tag')
    def test_get_boot_iso_compose(
            self, get_base_image_build_tag, get_base_image_build_target,
            create_odcs_client, krb_context):
        odcs = create_odcs_client.return_value
        odcs.new_compose.return_value = {'id': 1}

        get_base_image_build_target.return_value = 'build-target'
        get_base_image_build_tag.return_value = 'build-tag'

        result = self.handler._request_boot_iso_compose(self.image)

        self.assertEqual(odcs.new_compose.return_value, result)
        odcs.new_compose.assert_called_once_with(
            'build-tag', 'tag', results=['boot.iso'])

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_target')
    def test_cannot_get_image_build_target(self, get_base_image_build_target):
        get_base_image_build_target.return_value = None

        result = self.handler._request_boot_iso_compose(self.image)
        self.assertIsNone(result)

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_target')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_tag')
    def test_cannot_get_build_tag_from_target(
            self, get_base_image_build_tag, get_base_image_build_target):
        get_base_image_build_target.return_value = 'build-target'
        get_base_image_build_tag.return_value = None

        result = self.handler._request_boot_iso_compose(self.image)
        self.assertIsNone(result)
