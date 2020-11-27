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

import json
from unittest.mock import patch, PropertyMock, Mock, call

import freshmaker

from freshmaker.config import all_
from freshmaker import db, events
from freshmaker.events import (
    ErrataAdvisoryRPMsSignedEvent,
    ManualRebuildWithAdvisoryEvent,
    BaseEvent)
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, Compose, ArtifactBuild, EVENT_TYPES
from freshmaker.types import (
    ArtifactBuildState, ArtifactType, EventState, RebuildReason)
from freshmaker.errata import ErrataAdvisory
from freshmaker.config import any_
from freshmaker import conf
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
        for content_type in [["rpm"], ["module"]]:
            event = ManualRebuildWithAdvisoryEvent(
                "123",
                ErrataAdvisory(123, "RHBA-2017", "REL_PREP", content_type,
                               security_impact="",
                               product_short_name="product"),
                ["foo-container", "bar-container"])
            handler = RebuildImagesOnRPMAdvisoryChange()
            ret = handler.can_handle(event)
            self.assertTrue(ret)

    def test_cannot_handle_manual_rebuild_for_non_rpm_and_module(self):
        for content_type in [["non-rpm"], []]:
            event = ManualRebuildWithAdvisoryEvent(
                "123",
                ErrataAdvisory(123, "RHBA-2017", "REL_PREP", content_type,
                               security_impact="",
                               product_short_name="product"),
                ["foo-container", "bar-container"])
            handler = RebuildImagesOnRPMAdvisoryChange()
            ret = handler.can_handle(event)
            self.assertFalse(ret)

    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_requester_on_manual_rebuild(self):
        event = ManualRebuildWithAdvisoryEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", ["rpm"],
                           security_impact="",
                           product_short_name="product"),
            ["foo-container", "bar-container"],
            requester="requester1")
        handler = RebuildImagesOnRPMAdvisoryChange()
        ret = handler.can_handle(event)
        self.assertTrue(ret)
        handler.handle(event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.requester, 'requester1')

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {
                'advisory_security_impact': ['critical', 'important']
            }
        }
    })
    @patch.object(freshmaker.conf, 'dry_run', new=True)
    def test_allow_build_by_security_impact(self):
        compose_4 = Compose(odcs_compose_id=4)
        db.session.add(compose_4)
        db.session.commit()

        for severity in ["moderate", "critical", "important"]:
            self.rhba_event.advisory.security_impact = severity
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

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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

        self.get_affected_srpm_nvrs = self.patcher.patch(
            'freshmaker.errata.Errata.get_cve_affected_rpm_nvrs',
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

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_published_unset(self, exists):
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            ['httpd-2.4-11.el7'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=conf.lightblue_release_categories,
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch('os.path.exists', return_value=True)
    def test_multiple_srpms(self, exists):
        self.get_affected_srpm_nvrs.return_value = ["httpd-2.4-11.el7", "httpd-2.2-11.el6"]
        for x in self.handler._find_images_to_rebuild(123456):
            pass

        self.find_images_to_rebuild.assert_called_once_with(
            ['httpd-2.4-11.el7', 'httpd-2.2-11.el6'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=conf.lightblue_release_categories,
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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
            ['httpd-2.4-11.el7'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=None, release_categories=None,
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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
            ['httpd-2.4-11.el7'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=conf.lightblue_release_categories,
            leaf_container_images=None)

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
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
            ['httpd-2.4-11.el7'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=conf.lightblue_release_categories,
            leaf_container_images=["foo", "bar"])

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
        'RebuildImagesOnRPMAdvisoryChange': {
            'image': {'advisory_name': 'RHBA-*'}
        }
    })
    @patch("freshmaker.errata.ErrataAdvisory.affected_rpm_nvrs",
           new_callable=PropertyMock,
           return_value=["nodejs-10.19.0-1.module+el8.1.0+5726+6ed65f8c.x86_64"])
    @patch('os.path.exists', return_value=True)
    def test_affected_packages_with_modules(self, exists, affected_rpm_nvrs):
        self.handler._find_images_to_rebuild(123456)

        self.find_images_to_rebuild.assert_called_once_with(
            ['nodejs-10.19.0-1.module+el8.1.0+5726+6ed65f8c.x86_64'], ['content-set-1'],
            filter_fnc=self.handler._filter_out_not_allowed_builds,
            published=True, release_categories=conf.lightblue_release_categories,
            leaf_container_images=None)


class TestAllowBuild(helpers.ModelsTestCase):
    """Test RebuildImagesOnRPMAdvisoryChange.allow_build"""

    @patch("freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange."
           "_find_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_allowlist",
           new_callable=PropertyMock, return_value={
               "RebuildImagesOnRPMAdvisoryChange": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_false(self, handler_build_allowlist, record_images):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(event)

        record_images.assert_not_called()

    @patch("freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange."
           "_find_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_allowlist",
           new_callable=PropertyMock, return_value={
               "RebuildImagesOnRPMAdvisoryChange": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_true(self, handler_build_allowlist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(event)

        record_images.assert_called_once()
        self.assertEqual(handler.current_db_event_id, 1)

    @patch("freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange."
           "_find_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_allowlist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ],
                    "image_name": "foo",
                }
            }
        })
    def test_allow_security_impact_important_true(
            self, handler_build_allowlist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="Important",
                           product_short_name="product"))
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(event)

        record_images.assert_called_once()

    @patch("freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange."
           "_find_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_allowlist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }
            }
        })
    def test_allow_security_impact_important_false(
            self, handler_build_allowlist, record_images):
        """
        Tests that allow_build dost filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.handle(event)

        record_images.assert_not_called()

    @patch(
        "freshmaker.config.Config.handler_build_allowlist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": {
                    "image_name": ["foo", "bar"]
                }
            }
        })
    def test_filter_out_not_allowed_builds(
            self, handler_build_allowlist):
        """
        Tests that allow_build does filter images based on image_name.
        """

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = ContainerImage({"brew": {"build": "foo-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "foo2-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "bar-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "unknown-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)

    @patch(
        "freshmaker.config.Config.handler_build_allowlist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": {
                    "image_name": ["foo", "bar"],
                    "advisory_name": "RHSA-.*",
                }
            }
        })
    def test_filter_out_image_name_and_advisory_name(
            self, handler_build_allowlist):
        """
        Tests that allow_build does filter images based on image_name.
        """

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = ContainerImage({"brew": {"build": "foo-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "unknown-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)

    @patch(
        "freshmaker.config.Config.handler_build_allowlist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": {
                    "image_name": ["foo", "bar"]
                }
            }
        })
    @patch(
        "freshmaker.config.Config.handler_build_blocklist",
        new_callable=PropertyMock,
        return_value={
            "RebuildImagesOnRPMAdvisoryChange": {
                "image": all_(
                    {
                        "image_name": "foo",
                        "image_version": "7.3",
                    }
                )
            }
        })
    def test_filter_out_not_allowed_builds_image_version(
            self, handler_build_blocklist, handler_build_allowlist):
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = ContainerImage({"brew": {"build": "foo-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "foo-1-7.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = ContainerImage({"brew": {"build": "foo-7.3-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)

        image = ContainerImage({"brew": {"build": "unknown-1-2.3"}})
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)


class TestBatches(helpers.ModelsTestCase):
    """Test handling of batches"""

    def setUp(self):
        super(TestBatches, self).setUp()
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.')

    def tearDown(self):
        super(TestBatches, self).tearDown()
        self.patcher.unpatch_all()

    def _mock_build(
            self, build, parent=None, error=None, **kwargs):
        if parent:
            parent = ContainerImage({"brew": {"build": parent + "-1-1.25"}})
        d = {
            'brew': {'build': build + "-1-1.25"},
            'repository': build + '_repo',
            'parsed_data': {
                'layers': [
                    'sha512:1234',
                    'sha512:4567',
                    'sha512:7890',
                ],
            },
            'commit': build + '_123',
            'parent': parent,
            "target": "t1",
            'git_branch': 'mybranch',
            "error": error,
            "content_sets": ["first-content-set"],
            "generate_pulp_repos": True,
            "arches": "x86_64",
            "odcs_compose_ids": [10, 11],
            "published": False,
        }
        d.update(kwargs)
        return ContainerImage(d)

    @patch('freshmaker.odcsclient.create_odcs_client')
    def test_batches_records(self, create_odcs_client):
        """
        Tests that batches are properly recorded in DB.
        """
        odcs = create_odcs_client.return_value
        # There are 8 mock builds below and each of them requires one pulp
        # compose.
        composes = [{
            'id': compose_id,
            'result_repofile': 'http://localhost/{}.repo'.format(compose_id),
            'state_name': 'done'
        } for compose_id in range(1, 9)]
        odcs.new_compose.side_effect = composes
        odcs.get_compose.side_effect = composes

        # Creates following tree:
        # shared_parent
        #   |- child1_parent3
        #     |- child1_parent2
        #       |- child1_parent1
        #         |- child1
        #   |- child2_parent2
        #     |- child2_parent1
        #       |- child2
        batches = [[self._mock_build("shared_parent")],
                   [self._mock_build("child1_parent3", "shared_parent"),
                    self._mock_build("child2_parent2", "shared_parent")],
                   [self._mock_build("child1_parent2", "child1_parent3"),
                    self._mock_build("child2_parent1", "child2_parent2")],
                   [self._mock_build("child1_parent1", "child1_parent2", error="Fail"),
                    self._mock_build("child2", "child2_parent1", directly_affected=True)],
                   [self._mock_build("child1", "child1_parent1", directly_affected=True)]]

        # Flat list of images from batches with brew build id as a key.
        images = {}
        for batch in batches:
            for image in batch:
                images[image.nvr] = image

        # Record the batches.
        event = events.BrewSignRPMEvent("123", "openssl-1.1.0-1")
        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, event)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            # child1_parent1 and child1 are in FAILED states, because LB failed
            # to resolve child1_parent1 and therefore also child1 cannot be
            # build.
            if build.name in ["child1_parent1", "child1"]:
                self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            else:
                self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)
            self.assertEqual(build.type, ArtifactType.IMAGE.value)

            image = images[build.original_nvr]
            if image['parent']:
                self.assertEqual(build.dep_on.original_nvr, image['parent']['brew']['build'])
            else:
                self.assertEqual(build.dep_on, None)

            if build.name in ["child1", "child2"]:
                self.assertEqual(build.rebuild_reason, RebuildReason.DIRECTLY_AFFECTED.value)
            else:
                self.assertEqual(build.rebuild_reason, RebuildReason.DEPENDENCY.value)

            args = json.loads(build.build_args)
            self.assertEqual(args["repository"], build.name + "_repo")
            self.assertEqual(args["commit"], build.name + "_123")
            self.assertEqual(args["original_parent"],
                             build.dep_on.original_nvr if build.dep_on else None)
            self.assertEqual(args["renewed_odcs_compose_ids"],
                             [10, 11])


class TestCheckImagesToRebuild(helpers.ModelsTestCase):
    """Test handling of batches"""

    def setUp(self):
        super(TestCheckImagesToRebuild, self).setUp()

        build_args = json.dumps({
            "original_parent": "nvr",
            "repository": "repo",
            "target": "target",
            "commit": "hash",
            "branch": "mybranch",
            "yum_repourl": "http://localhost/composes/latest-odcs-3-1/compose/"
                           "Temporary/odcs-3.repo",
            "odcs_pulp_compose_id": 15,
        })

        self.ev = Event.create(db.session, 'msg-id', '123',
                               EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        self.b1 = ArtifactBuild.create(
            db.session, self.ev, "parent", "image",
            state=ArtifactBuildState.PLANNED,
            original_nvr="parent-1-25")
        self.b1.build_args = build_args
        self.b2 = ArtifactBuild.create(
            db.session, self.ev, "child", "image",
            state=ArtifactBuildState.PLANNED,
            dep_on=self.b1,
            original_nvr="child-1-25")
        self.b2.build_args = build_args
        db.session.commit()

    def test_check_images_to_rebuild(self):
        builds = {
            "parent-1-25": self.b1,
            "child-1-25": self.b2
        }

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)

    def test_check_images_to_rebuild_missing_dep(self):
        # Do not include child nvr here to test that _check_images_to_rebuild
        # sets the state of event to failed.
        builds = {
            "parent-1-25": self.b1
        }

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)

    def test_check_images_to_rebuild_extra_build(self):
        builds = {
            "parent-1-25": self.b1,
            "child-1-25": self.b2,
            "something-1-25": self.b1,
        }

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)


class TestRecordBatchesImages(helpers.ModelsTestCase):
    """Test RebuildImagesOnRPMAdvisoryChange._record_batches"""

    def setUp(self):
        super(TestRecordBatchesImages, self).setUp()

        self.mock_event = Mock(spec=BaseEvent, msg_id='msg-id', search_key=12345,
                               manual=False, dry_run=False)

        self.patcher = helpers.Patcher(
            'freshmaker.handlers.koji.RebuildImagesOnRPMAdvisoryChange.')

        self.mock_prepare_pulp_repo = self.patcher.patch(
            'freshmaker.odcsclient.FreshmakerODCSClient.prepare_pulp_repo',
            side_effect=[{'id': 1}, {'id': 2}])

        self.patcher.patch_dict(
            'freshmaker.models.EVENT_TYPES', {self.mock_event.__class__: 0})

    def tearDown(self):
        super(TestRecordBatchesImages, self).tearDown()
        self.patcher.unpatch_all()

    def test_record_batches(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:2345af2e293',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertNotEqual(None, parent_image)
        self.assertEqual(ArtifactBuildState.PLANNED.value, parent_image.state)

        # Check child image
        child_image = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertNotEqual(None, child_image)
        self.assertEqual(parent_image, child_image.dep_on)
        self.assertEqual(ArtifactBuildState.PLANNED.value, child_image.state)

    def test_record_batches_should_not_generate_pulp_repos(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": False,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": True,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertNotEqual(None, parent_image)
        self.assertEqual(ArtifactBuildState.PLANNED.value, parent_image.state)
        self.mock_prepare_pulp_repo.assert_not_called()

    def test_record_batches_generate_pulp_repos_when_image_unpublished(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": False,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertNotEqual(None, parent_image)
        self.assertEqual(ArtifactBuildState.PLANNED.value, parent_image.state)
        self.mock_prepare_pulp_repo.assert_called()

    def test_pulp_compose_generated_just_once(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "arches": "x86_64",
                "generate_pulp_repos": True,
                "odcs_compose_ids": None,
                "published": False,
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:2345af2e293',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "arches": "x86_64",
                "generate_pulp_repos": True,
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        parent_build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertEqual(1, len(parent_build.composes))
        compose_ids = sorted([rel.compose.odcs_compose_id
                              for rel in parent_build.composes])
        self.assertEqual([1], compose_ids)

        child_build = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertEqual(1, len(child_build.composes))

        self.mock_prepare_pulp_repo.assert_has_calls([
            call(parent_build, ["content-set-1"])
        ])

    def test_no_parent(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occurs while getting this image.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()

        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_failed_state_if_image_has_error(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occurs while getting this image.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()

        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_state_failed_if_depended_image_is_failed(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:378a8ef2730',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured too.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

        build = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_base_image_failed_if_fail_to_request_boot_iso_compose(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })],
        ]

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, self.mock_event)

        build = db.session.query(ArtifactBuild).filter_by(
            original_nvr='rhel-server-docker-7.3-82').first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

        # Pulp repo should not be prepared for FAILED build.
        self.mock_prepare_pulp_repo.assert_not_called()

    def test_parent_image_already_built(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:2345af2e293',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        et_event = ErrataAdvisoryRPMsSignedEvent(
            "msg-id-2",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))
        event0 = Event.create(db.session, 'msg-id-1', '1230',
                              EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        event1 = Event.create(db.session, 'msg-id-2', '1231',
                              EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        ArtifactBuild.create(
            db.session, event0, "parent", "image",
            state=ArtifactBuildState.DONE,
            original_nvr="rhel-server-docker-7.3-82", rebuilt_nvr="some-test-nvr")
        db.session.commit()
        event1.add_event_dependency(db.session, event0)
        db.session.commit()

        handler = RebuildImagesOnRPMAdvisoryChange()
        handler._record_batches(batches, et_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).all()
        self.assertEqual(len(parent_image), 1)
        self.assertEqual(ArtifactBuildState.DONE.value, parent_image[0].state)

        # Check child image
        child_image = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertNotEqual(None, child_image)
        self.assertEqual(child_image.dep_on, None)
