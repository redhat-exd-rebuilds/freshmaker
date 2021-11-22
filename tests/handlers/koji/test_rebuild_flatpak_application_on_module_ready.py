# SPDX-License-Identifier: MIT

from unittest.mock import patch

from freshmaker import db
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.handlers.koji import RebuildFlatpakApplicationOnModuleReady
from freshmaker.models import Event
from freshmaker.types import EventState
from tests import helpers


@patch("freshmaker.events.conf.parsers",
       [
           "freshmaker.parsers.errata:ErrataAdvisorySigningChangedParser",
           "freshmaker.parsers.errata:ErrataAdvisoryStateChangedParser",
       ])
class TestFlatpakModuleAdvisoryReadyEvent(helpers.ModelsTestCase):

    def _patch(self, to_patch):
        patcher = patch(to_patch, autospec=True)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def setUp(self):
        super().setUp()

        self.consumer = self.create_consumer()

        self.get_pulp_repository_ids = self._patch("freshmaker.errata.Errata.get_pulp_repository_ids")
        self.get_pulp_repository_ids.return_value = ["rhel-8-for-x86_64-hidden-rpms"]

        self.builds_signed = self._patch("freshmaker.errata.Errata.builds_signed")
        self.builds_signed.return_value = True

        self.from_advisory_id = self._patch("freshmaker.errata.ErrataAdvisory.from_advisory_id")
        self.advisory = ErrataAdvisory(123, "RHSA-123", "QE", ["module"], "Critical")
        self.from_advisory_id.return_value = self.advisory
        self.handler = RebuildFlatpakApplicationOnModuleReady()
        self.mock_get_auto_rebuild_image_list = self._patch('freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._get_auto_rebuild_image_list')
        self.mock_filter_images_with_higher_rpm_nvr = self._patch('freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._filter_images_with_higher_rpm_nvr')
        self.event = FlatpakModuleAdvisoryReadyEvent("123", self.advisory)

    def tearDown(self):
        self.consumer = self.create_consumer()

    def test_event_from_signing_message(self):
        self.assertEqual(self.advisory.is_flatpak_module_advisory_ready(), True)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.signing",
            "msg": {
                "content_types": ["module"],
                "errata_status": "QE",
                "errata_id": 123,
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertIsInstance(event, FlatpakModuleAdvisoryReadyEvent)
        self.assertEqual("fake-msg-id", event.msg_id)
        self.assertEqual(self.handler.can_handle(event), True)

    def test_no_event_from_signing_message_in_new_files(self):
        advisory = ErrataAdvisory(123, "RHSA-123", "NEW_FILES", ["module"], "Critical")
        self.from_advisory_id.return_value = advisory
        self.assertEqual(advisory.is_flatpak_module_advisory_ready(), False)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.signing",
            "msg": {
                "content_types": ["module"],
                "errata_status": "NEW_FILES",
                "errata_id": 123,
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertEqual(event, None)
        self.assertEqual(self.handler.can_handle(event), False)

    def test_no_event_from_signing_message_for_rpm(self):
        advisory = ErrataAdvisory(123, "RHSA-123", "NEW_FILES", ["rpm"], "Critical")
        self.from_advisory_id.return_value = advisory
        self.assertEqual(advisory.is_flatpak_module_advisory_ready(), False)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.signing",
            "msg": {
                "content_types": ["rpm"],
                "errata_status": "QE",
                "errata_id": 123,
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertEqual(event, None)

    def test_no_event_from_signing_message_for_nonhidden_repo(self):
        self.get_pulp_repository_ids.return_value = ["rhel-8-for-x86_64-rpms"]
        self.assertEqual(self.advisory.is_flatpak_module_advisory_ready(), False)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.signing",
            "msg": {
                "content_types": ["module"],
                "errata_status": "QE",
                "errata_id": 123,
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertEqual(event, None)

    def test_no_event_from_signing_message_for_unsigned(self):
        self.builds_signed.return_value = False
        self.assertEqual(self.advisory.is_flatpak_module_advisory_ready(), False)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.signing",
            "msg": {
                "content_types": ["module"],
                "errata_status": "QE",
                "errata_id": 123,
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertEqual(event, None)

    def test_event_from_state_change_message(self):
        advisory = ErrataAdvisory(123, "RHSA-123", "QE", ["module"], "Critical")
        self.from_advisory_id.return_value = advisory
        self.assertEqual(advisory.is_flatpak_module_advisory_ready(), True)

        msg = {
            "msg_id": "fake-msg-id",
            "topic": "/topic/VirtualTopic.eng.errata.activity.status",
            "msg": {
                "errata_id": 123,
                "to": "QE",
            }
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertIsInstance(event, FlatpakModuleAdvisoryReadyEvent)
        self.assertEqual("fake-msg-id", event.msg_id)
        self.assertEqual(self.handler.can_handle(event), True)

    def test_event_state_updated_when_no_auto_rebuild_images(self):
        self.mock_get_auto_rebuild_image_list.return_value = []
        handler = RebuildFlatpakApplicationOnModuleReady()
        handler.handle(self.event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "There is no auto rebuild image can be rebuilt. message_id: 123")

    def test_event_state_updated_when_no_images_with_higher_rpm_nvr(self):
        self.mock_get_auto_rebuild_image_list.return_value = ["image-foo-bar"]
        self.mock_filter_images_with_higher_rpm_nvr.return_value = []
        handler = RebuildFlatpakApplicationOnModuleReady()
        handler.handle(self.event)

        db_event = Event.get(db.session, message_id='123')
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "There is no image with higher rpm nvr can be rebuilt. message_id: 123")
