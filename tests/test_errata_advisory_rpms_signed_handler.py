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

import requests

from mock import patch, mock_open

import freshmaker

from freshmaker import db, log
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, Compose
from freshmaker.types import EventState
from freshmaker.errata import ErrataAdvisory
from freshmaker.config import any_
from tests import helpers


class TestErrataAdvisoryRPMsSignedHandler(helpers.ModelsTestCase):

    def setUp(self):
        super(TestErrataAdvisoryRPMsSignedHandler, self).setUp()

        # Each time when recording a build into database, freshmaker has to
        # request a pulp repo from ODCS. This is not necessary for running
        # tests.
        # There are 6 images used to run tests which will be created below, so
        # there should be 6 composes created as Pulp repos.
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.')

        # We do not want to send messages to message bus while running tests
        self.mock_messaging_publish = self.patcher.patch(
            'freshmaker.messaging.publish')

        self.mock_prepare_pulp_repo = self.patcher.patch(
            '_prepare_pulp_repo',
            side_effect=[{'id': compose_id} for compose_id in range(1, 7)])

        self.mock_find_images_to_rebuild = self.patcher.patch(
            '_find_images_to_rebuild')

        # boot.iso composes IDs should be different from pulp composes IDs as
        # when each time to request a compose from ODCS, new compose ID will
        # be returned along with new comopse.
        self.mock_request_boot_iso_compose = self.patcher.patch(
            '_request_boot_iso_compose',
            side_effect=[{'id': 100}, {'id': 101}])

        self.should_generate_yum_repourls_patcher = patch(
            'freshmaker.handlers.errata.'
            'ErrataAdvisoryRPMsSignedHandler._should_generate_yum_repourls',
            return_value=True)
        self.should_generate_yum_repourls = self.patcher.patch(
            '_should_generate_yum_repourls', return_value=True)

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
        self.mock_find_images_to_rebuild.return_value = [
            [self.image_a, self.image_b],
            [self.image_c, self.image_d, self.image_e],
            [self.image_f]
        ]

        self.rhba_event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        self.rhsa_event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))

    def tearDown(self):
        super(TestErrataAdvisoryRPMsSignedHandler, self).tearDown()
        self.patcher.unpatch_all()

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'product_short_name': 'foo'}
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_allow_build_by_product_short_name(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        self.mock_find_images_to_rebuild.return_value = [[]]
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(self.rhba_event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {
                'advisory_highest_cve_severity': ['critical', 'important']
            }
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_allow_build_by_highest_cve_severity(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        for severity in ["moderate", "critical", "important"]:
            self.rhba_event.advisory.highest_cve_severity = severity
            self.mock_find_images_to_rebuild.return_value = [[]]
            handler = ErrataAdvisoryRPMsSignedHandler()
            handler.handle(self.rhba_event)

            db_event = Event.get(db.session, message_id='123')
            self.assertEqual(db_event.state, EventState.SKIPPED.value)
            if severity == "moderate":
                self.assertTrue(db_event.state_reason.endswith(
                    "is not allowed by internal policy to trigger rebuilds."))
            else:
                self.assertEqual(
                    db_event.state_reason,
                    "No container images to rebuild for advisory 'RHBA-2017'")

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-2017'}
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_setting_fake_compose_id_dry_run_mode(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        self.mock_find_images_to_rebuild.return_value = [[]]
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(self.rhba_event)

        self.assertEqual(ErrataAdvisoryRPMsSignedHandler._FAKE_COMPOSE_ID, -1)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-2017'}
        }
    })
    def test_event_state_updated_when_no_images_to_rebuild(self):
        self.mock_find_images_to_rebuild.return_value = [[]]
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(self.rhba_event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No container images to rebuild for advisory 'RHBA-2017'")

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-2017'}
        }
    })
    def test_event_state_updated_when_all_images_failed(self):
        self.image_a['error'] = "foo"
        self.mock_find_images_to_rebuild.return_value = [
            [self.image_a]]
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(self.rhba_event)

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
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(self.rhsa_event)

        prepare_yum_repos_for_rebuilds.assert_called_once()
        start_to_build_images.assert_not_called()

        db_event = Event.get(db.session, self.rhsa_event.msg_id)
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
            'msg-id-123',
            ErrataAdvisory(123, "RHSA-2017", "SHIPPED_LIVE", [],
                           security_impact="",
                           product_short_name="product"))
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_not_called()
        get_image_builds_in_first_batch.assert_called_once_with(db.session)
        start_to_build_images.assert_called_once()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)


class TestGetBaseImageBuildTarget(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_base_image_build_target"""

    def setUp(self):
        super(TestGetBaseImageBuildTarget, self).setUp()

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


class TestGetBaseImageBuildTag(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_base_image_build_tag"""

    def setUp(self):
        super(TestGetBaseImageBuildTag, self).setUp()

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

    @helpers.mock_koji
    def test_get_build_tag_name(self, mocked_koji):
        result = self.handler._get_base_image_build_tag(
            'guest-rhel-7.4-docker')
        self.assertEqual('guest-rhel-7.4-docker-build', result)

    @helpers.mock_koji
    def test_no_target_is_returned(self, mocked_koji):
        result = self.handler._get_base_image_build_tag(
            'guest-rhel-7.4-docker-unknown')
        self.assertIsNone(result)


class TestRequestBootISOCompose(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._request_boot_iso_compose"""

    def setUp(self):
        super(TestRequestBootISOCompose, self).setUp()

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

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'create_odcs_client')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_target')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_get_base_image_build_tag')
    def test_get_boot_iso_compose(
            self, get_base_image_build_tag, get_base_image_build_target,
            create_odcs_client):
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


class TestFindImagesToRebuild(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestFindImagesToRebuild, self).setUp()

        self.patcher = helpers.Patcher(
            "freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.")

        self.find_build_srpm_name = self.patcher.patch(
            '_find_build_srpm_name', return_value="httpd")

        self.get_content_set_by_repo_ids = self.patcher.patch(
            'freshmaker.pulp.Pulp.get_content_set_by_repo_ids',
            return_value=["content-set-1"])

        self.get_pulp_repository_ids = self.patcher.patch(
            'freshmaker.errata.Errata.get_pulp_repository_ids',
            return_value=["pulp_repo_x86_64"])

        self.get_builds = self.patcher.patch(
            'freshmaker.errata.Errata.get_builds',
            return_value=["httpd-2.4-11.el7"])

        self.find_images_to_rebuild = self.patcher.patch(
            'freshmaker.lightblue.LightBlue.find_images_to_rebuild',
            return_value=[[]])

        self.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        self.handler = ErrataAdvisoryRPMsSignedHandler()
        self.handler.event = self.event

    def tearDown(self):
        super(TestFindImagesToRebuild, self).tearDown()
        self.patcher.unpatch_all()

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_unset(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_category='Generally Available')

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_multiple_srpms(self, exists):
        self.get_builds.return_value = ["httpd-2.4-11.el7", "httpd-2.2-11.el6"]
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_category='Generally Available')

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': any_({'advisory_name': 'RHBA-*', 'published': True,
                           'advisory_product_short_name': 'foo'},
                          {'advisory_name': 'RHBA-*', 'published': False,
                           'advisory_product_short_name': 'product'})
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_false(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=None, release_category=None)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryRPMsSignedHandler': {
            'image': {'advisory_name': 'RHBA-*',
                      'published': True}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_true(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_category='Generally Available')


class TestShouldGenerateYumRepourls(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestShouldGenerateYumRepourls, self).setUp()

        self.patcher = helpers.Patcher(
            "freshmaker.handlers.errata.errata_advisory_rpms_signed.")
        self.clone_distgit_repo = self.patcher.patch("clone_distgit_repo")
        self.path_exists = self.patcher.patch("os.path.exists")
        self.patched_open = self.patcher.patch("open", create=True)

        self.handler = ErrataAdvisoryRPMsSignedHandler()

    def tearDown(self):
        super(TestShouldGenerateYumRepourls, self).tearDown()
        self.patcher.unpatch_all()

    def test_generate(self):
        self.path_exists.return_value = True
        self.patched_open.return_value = mock_open(
            read_data="compose:\n  pulp_repos: True").return_value

        ret = self.handler._should_generate_yum_repourls(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret, False)

        self.clone_distgit_repo.assert_called_once_with(
            'rpms', 'foo-docker',
            helpers.AnyStringWith('freshmaker-rpms-foo-docker'),
            commit='commit', logger=log, ssh=False)

    def test_generate_no_namespace(self):
        self.path_exists.return_value = True
        self.patched_open.return_value = mock_open(
            read_data="compose:\n  pulp_repos: True").return_value

        ret = self.handler._should_generate_yum_repourls(
            "foo-docker", "branch", "commit")
        self.assertEqual(ret, False)

        self.clone_distgit_repo.assert_called_once_with(
            'rpms', 'foo-docker',
            helpers.AnyStringWith('freshmaker-rpms-foo-docker'),
            commit='commit', logger=log, ssh=False)

    def test_generate_no_pulp_repos(self):
        self.path_exists.return_value = True
        self.patched_open.return_value = mock_open(
            read_data="compose:\n  pulp_repos_x: True").return_value

        ret = self.handler._should_generate_yum_repourls(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret, True)

    def test_generate_pulp_repos_false(self):
        self.path_exists.return_value = True
        self.patched_open.return_value = mock_open(
            read_data="compose:\n  pulp_repos: False").return_value

        ret = self.handler._should_generate_yum_repourls(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret, True)

    def test_generate_no_content_sets_yml(self):
        def mocked_path_exists(path):
            return not path.endswith("content_sets.yml")
        self.path_exists.side_effect = mocked_path_exists

        ret = self.handler._should_generate_yum_repourls(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret, True)

    def test_generate_no_container_yaml(self):
        def mocked_path_exists(path):
            return not path.endswith("container.yaml")
        self.path_exists.side_effect = mocked_path_exists

        ret = self.handler._should_generate_yum_repourls(
            "rpms/foo-docker", "branch", "commit")
        self.assertEqual(ret, True)
