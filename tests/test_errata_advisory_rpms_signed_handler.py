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

from mock import patch

import freshmaker

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.models import Event
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

        # Fake images found to rebuild has these relationships
        #
        # Batch 1  |         Batch 2            |          Batch 3
        # image_a  | image_c (child of image_a) | image_f (child of image_e)
        # image_b  | image_d (child of image_a) |
        #          | image_e (child of image_b) |
        #
        self.image_a = {
            'repository': 'repo_1',
            'commit': '1234567',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_a_content_set_1', 'image_a_content_set_2'],
            'brew': {
                'build': 'image-a-1.0-2',
            },
            'parent': None,
        }
        self.image_b = {
            'repository': 'repo_2',
            'commit': '23e9f22',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_b_content_set_1', 'image_b_content_set_2'],
            'brew': {
                'build': 'image-b-1.0-1'
            },
            'parent': None,
        }
        self.image_c = {
            'repository': 'repo_2',
            'commit': '2345678',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_c_content_set_1', 'image_d_content_set_2'],
            'brew': {
                'build': 'image-c-0.2-9',
            },
            'parent': self.image_a,
        }
        self.image_d = {
            'repository': 'repo_2',
            'commit': '5678901',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_d_content_set_1', 'image_d_content_set_2'],
            'brew': {
                'build': 'image-d-2.14-1',
            },
            'parent': self.image_a,
        }
        self.image_e = {
            'repository': 'repo_2',
            'commit': '7890123',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_e_content_set_1', 'image_e_content_set_2'],
            'brew': {
                'build': 'image-e-1.0-1',
            },
            'parent': self.image_b,
        }
        self.image_f = {
            'repository': 'repo_2',
            'commit': '3829384',
            'target': 'docker-container-candidate',
            'git_branch': 'rhel-7.4',
            'content_sets': ['image_f_content_set_1', 'image_f_content_set_2'],
            'brew': {
                'build': 'image-f-0.2-1',
            },
            'parent': self.image_b,
        }
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

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'allow_build', return_value=True)
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_build_first_batch')
    def test_rebuild_if_errata_state_is_prior_to_SHIPPED_LIVE(
            self, build_first_batch, prepare_yum_repos_for_rebuilds,
            allow_build):
        event = ErrataAdvisoryRPMsSignedEvent(
            'msg-id-123', 'RHSA-2017', 123, '', 'REL_PREP')
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_called_once()
        build_first_batch.assert_not_called()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)

    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           'allow_build', return_value=True)
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_prepare_yum_repos_for_rebuilds')
    @patch('freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.'
           '_build_first_batch')
    def test_rebuild_if_errata_state_is_SHIPPED_LIVE(
            self, build_first_batch, prepare_yum_repos_for_rebuilds,
            allow_build):
        event = ErrataAdvisoryRPMsSignedEvent(
            'msg-id-123', 'RHSA-2017', 123, '', 'SHIPPED_LIVE')
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        prepare_yum_repos_for_rebuilds.assert_not_called()
        build_first_batch.assert_called_once()

        db_event = Event.get(db.session, event.msg_id)
        self.assertEqual(EventState.BUILDING.value, db_event.state)
