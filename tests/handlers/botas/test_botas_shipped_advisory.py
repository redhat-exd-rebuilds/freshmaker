# -*- coding: utf-8 -*-
# Copyright (c) 2020  Red Hat, Inc.
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

from unittest.mock import patch, call, MagicMock

from freshmaker import db, conf
from freshmaker.events import (
    BotasErrataShippedEvent,
    ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers.botas import HandleBotasAdvisory
from freshmaker.errata import ErrataAdvisory
from freshmaker.models import Event
from freshmaker.types import EventState
from tests import helpers


class TestBotasShippedAdvisory(helpers.ModelsTestCase):

    def setUp(self):
        super(TestBotasShippedAdvisory, self).setUp()

        # Each time when recording a build into database, freshmaker has to
        # request a pulp repo from ODCS. This is not necessary for running
        # tests.
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.botas.botas_shipped_advisory.')
        self.pyxis = self.patcher.patch("Pyxis")

        # We do not want to send messages to message bus while running tests
        self.mock_messaging_publish = self.patcher.patch(
            'freshmaker.messaging.publish')

        self.handler = HandleBotasAdvisory()

        self.botas_advisory = ErrataAdvisory(
            123, "RHBA-2020", "SHIPPED_LIVE", ['docker'])
        self.botas_advisory._reporter = "botas/pnt-devops-jenkins@REDHAT.COM"

    def tearDown(self):
        super(TestBotasShippedAdvisory, self).tearDown()
        self.patcher.unpatch_all()

    @patch.object(conf, 'pyxis_server_url', new='test_url')
    def test_init(self):
        handler1 = HandleBotasAdvisory(self.pyxis)
        self.assertEqual(handler1._pyxis, self.pyxis)

        HandleBotasAdvisory()
        self.pyxis.assert_called_with('test_url')

    @patch.object(conf, 'pyxis_server_url', new='')
    def test_init_no_pyxis_server(self):
        with self.assertRaises(ValueError, msg="'pyxis_server_url' parameter should be set"):
            HandleBotasAdvisory()

    def test_can_handle_botas_adisory(self):
        handler = HandleBotasAdvisory()
        event = BotasErrataShippedEvent("123", self.botas_advisory)
        self.assertTrue(handler.can_handle(event))

    def test_handle_set_dry_run(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory,
                                        dry_run=True)
        self.handler.handle(event)

        self.assertTrue(self.handler._force_dry_run)
        self.assertTrue(self.handler.dry_run)

    def test_handle_isnt_allowed_by_internal_policy(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)

        self.handler.handle(event)
        db_event = Event.get(db.session, message_id='test_msg_id')

        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertTrue(db_event.state_reason.startswith(
            "This image rebuild is not allowed by internal policy."))

    @patch.object(conf, 'dry_run', new=True)
    @patch.object(conf, 'handler_build_allowlist', new={
        'HandleBotasAdvisory': {
            'image': {
                'advisory_name': 'RHBA-2020'
            }
        }})
    def test_handle_no_digests_error(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.pyxis().get_digests_by_nvrs.return_value = set()

        self.handler.handle(event)
        db_event = Event.get(db.session, message_id='test_msg_id')

        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertTrue(
            db_event.state_reason.startswith("The are no digests for NVRs:"))

    @patch.object(conf, 'dry_run', new=True)
    @patch.object(conf, 'handler_build_allowlist', new={
        'HandleBotasAdvisory': {
            'image': {
                'advisory_name': 'RHBA-2020'
            }
        }})
    def test_handle_get_bundle_paths(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.pyxis().get_digests_by_nvrs.return_value = {'nvr1'}
        bundles = [
            {
                "bundle_path": "some_path",
                "bundle_path_digest": "sha256:123123",
                "channel_name": "streams-1.5.x",
                "related_images": [
                    {
                        "image": "registry/amq7/amq-streams-r-operator@sha256:111",
                        "name": "strimzi-cluster-operator",
                        "digest": "sha256:111"
                    },
                ],
                "version": "1.5.3"
            },
            {
                "bundle_path": "some_path_2",
                "channel_name": "streams-1.5.x",
                "related_images": [
                    {
                        "image": "registry/amq7/amq-streams-r-operator@sha256:555",
                        "name": "strimzi-cluster-operator",
                        "digest": "sha256:555"
                    },
                ],
                "version": "1.5.4"
            },
        ]
        self.pyxis().filter_bundles_by_related_image_digests.return_value = bundles

        self.handler.handle(event)
        db_event = Event.get(db.session, message_id='test_msg_id')

        # should be called only with the first digest, because second one
        # doesn't have 'bundle_path_digest'
        self.pyxis().get_images_by_digests.assert_called_once_with({"sha256:123123"})
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertTrue(
            db_event.state_reason.startswith("Skipping the rebuild of"))

    def test_can_handle_manual_rebuild_with_advisory(self):
        event = ManualRebuildWithAdvisoryEvent("123", self.botas_advisory, [])
        self.assertFalse(self.handler.can_handle(event))

    @patch('freshmaker.handlers.botas.botas_shipped_advisory.koji_service')
    def test_filter_bundles_by_pinned_related_images(self, service):
        bundle_images_nvrs = {"some_nvr_1", "some_nvr_2"}
        temp_mock = MagicMock()
        service.return_value.__enter__.return_value = temp_mock
        temp_mock.get_build.side_effect = [
            {
                "build": {
                    "extra": {
                        "image": {
                            "operator_manifests": {
                                "related_images": {
                                    "created_by_osbs": True
                                }
                            }
                        }
                    }
                }
            },
            {
                "build": {
                    "extra": {
                        "image": {
                            "operator_manifests": {
                                "related_images": {
                                    "created_by_osbs": False
                                }
                            }
                        }
                    }
                }
            },
            # To check that we will ignore invalid/not found build
            None
        ]

        nvrs = self.handler._filter_bundles_by_pinned_related_images(bundle_images_nvrs)
        bundle_list = list(bundle_images_nvrs)

        temp_mock.get_build.assert_has_calls([call(bundle_list[0]),
                                             call(bundle_list[1])])
        self.assertEqual(nvrs, {bundle_list[0]})
