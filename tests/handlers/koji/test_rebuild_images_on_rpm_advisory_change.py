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

from mock import patch

import freshmaker

from freshmaker import db
from freshmaker.events import (
    ErrataAdvisoryRPMsSignedEvent,
    ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, Compose
from freshmaker.types import EventState
from freshmaker.errata import ErrataAdvisory
from freshmaker.config import any_
from tests import helpers


class TestRebuildImagesOnRPMAdvisoryChange(helpers.ModelsTestCase):

    def setUp(self):
        super(TestRebuildImagesOnRPMAdvisoryChange, self).setUp()

        # Each time when recording a build into database, freshmaker has to
        # request a pulp repo from ODCS. This is not necessary for running
        # tests.
        # There are 6 images used to run tests which will be created below, so
        # there should be 6 composes created as Pulp repos.
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.')

        # We do not want to send messages to message bus while running tests
        self.mock_messaging_publish = self.patcher.patch(
            'freshmaker.messaging.publish')

        self.mock_prepare_pulp_repo = self.patcher.patch(
            'freshmaker.odcsclient.FreshmakerODCSClient.prepare_pulp_repo',
            side_effect=[{'id': compose_id} for compose_id in range(1, 7)])

        self.mock_find_images_to_rebuild = self.patcher.patch(
            '_find_images_to_rebuild')

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
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
        })
        self.image_b = ContainerImage({
            'repository': 'repo_2',
            'commit': '23e9f22',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_b_content_set_1', 'image_b_content_set_2'],
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
        })
        self.image_c = ContainerImage({
            'repository': 'repo_2',
            'commit': '2345678',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_c_content_set_1', 'image_d_content_set_2'],
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
        })
        self.image_d = ContainerImage({
            'repository': 'repo_2',
            'commit': '5678901',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_d_content_set_1', 'image_d_content_set_2'],
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
        })
        self.image_e = ContainerImage({
            'repository': 'repo_2',
            'commit': '7890123',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_e_content_set_1', 'image_e_content_set_2'],
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
        })
        self.image_f = ContainerImage({
            'repository': 'repo_2',
            'commit': '3829384',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_f_content_set_1', 'image_f_content_set_2'],
            "arches": "x86_64",
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
            "generate_pulp_repos": True,
            "odcs_compose_ids": None,
            "published": False,
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
        super(TestRebuildImagesOnRPMAdvisoryChange, self).tearDown()
        self.patcher.unpatch_all()

    def test_can_handle_manual_rebuild_with_advisory_event(self):
        event = ManualRebuildWithAdvisoryEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", ["rpm"],
                           security_impact="",
                           product_short_name="product"),
            ["foo-container", "bar-container"])
        handler = RebuildImagesOnRPMAdvisoryChange()
        ret = handler.can_handle(event)
        self.assertTrue(ret)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'product_short_name': 'foo'}
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_allow_build_by_product_short_name(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        self.mock_find_images_to_rebuild.return_value = [[]]
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(self.rhba_event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
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
            handler = RebuildImagesOnRPMAdvisoryChange()
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
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {
                'advisory_has_hightouch_bug': True,
            }
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_allow_build_has_hightouch_bug(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        for has_hightouch_bug in [False, True]:
            self.rhba_event.advisory.has_hightouch_bug = has_hightouch_bug
            self.mock_find_images_to_rebuild.return_value = [[]]
            handler = RebuildImagesOnRPMAdvisoryChange()
            handler.handle(self.rhba_event)

            db_event = Event.get(db.session, message_id='123')
            self.assertEqual(db_event.state, EventState.SKIPPED.value)
            if not has_hightouch_bug:
                self.assertTrue(db_event.state_reason.endswith(
                    "is not allowed by internal policy to trigger rebuilds."))
            else:
                self.assertEqual(
                    db_event.state_reason,
                    "No container images to rebuild for advisory 'RHBA-2017'")

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-2017'}
        }
    })
    def test_event_state_updated_when_no_images_to_rebuild(self):
        self.mock_find_images_to_rebuild.return_value = [[]]
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(self.rhba_event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No container images to rebuild for advisory 'RHBA-2017'")

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-2017'}
        }
    })
    def test_event_state_updated_when_all_images_failed(self):
        self.image_a['error'] = "foo"
        self.mock_find_images_to_rebuild.return_value = [
            [self.image_a]]
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(self.rhba_event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.COMPLETE.value)
        self.assertEqual(
            db_event.state_reason,
            "No container images to rebuild, all are in failed state.")

    @patch('freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.'
           'allow_build', return_value=True)
    @patch('freshmaker.odcsclient.FreshmakerODCSClient.prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.'
           'start_to_build_images')
    def test_rebuild_if_errata_state_is_prior_to_SHIPPED_LIVE(
            self, start_to_build_images, prepare_yum_repos_for_rebuilds,
            allow_build):
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(self.rhsa_event)

        prepare_yum_repos_for_rebuilds.assert_called_once()
        start_to_build_images.assert_called_once()

        db_event = Event.get(db.session, self.rhsa_event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)

    @patch('freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.'
           'allow_build', return_value=True)
    @patch('freshmaker.odcsclient.FreshmakerODCSClient.prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.'
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
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_not_called()
        get_image_builds_in_first_batch.assert_called_once_with(db.session)
        start_to_build_images.assert_called_once()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)


class TestFindImagesToRebuild(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestFindImagesToRebuild, self).setUp()

        self.patcher = helpers.Patcher(
            "freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.")

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
        self.manual_event = ManualRebuildWithAdvisoryEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"),
            ["foo", "bar"])
        self.handler = RebuildImagesOnRPMAdvisoryChange()
        self.handler.event = self.event

    def tearDown(self):
        super(TestFindImagesToRebuild, self).tearDown()
        self.patcher.unpatch_all()

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_unset(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd-2.4-11.el7']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=('Generally Available', 'Tech Preview', 'Beta'),
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_multiple_srpms(self, exists):
        self.get_builds.return_value = ["httpd-2.4-11.el7", "httpd-2.2-11.el6"]
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd-2.4-11.el7', 'httpd-2.2-11.el6']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=('Generally Available', 'Tech Preview', 'Beta'),
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
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
            set(['httpd-2.4-11.el7']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=None, release_categories=None,
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*',
                      'published': True}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_true(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd-2.4-11.el7']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=('Generally Available', 'Tech Preview', 'Beta'),
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*',
                      'published': True}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_manual_event_leaf_container_images(self, exists):
        self.handler.event = self.manual_event
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            set(['httpd-2.4-11.el7']), ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=('Generally Available', 'Tech Preview', 'Beta'),
            leaf_container_images=["foo", "bar"])
