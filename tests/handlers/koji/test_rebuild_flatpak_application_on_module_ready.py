# SPDX-License-Identifier: MIT

import json
from unittest.mock import patch

from freshmaker import db
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import (
    FlatpakApplicationManualBuildEvent,
    FlatpakModuleAdvisoryReadyEvent,
)
from freshmaker.handlers.koji import RebuildFlatpakApplicationOnModuleReady
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event
from freshmaker.types import EventState
from tests import helpers


def _mock_image(image_nvr):
    image_name = image_nvr.rsplit("-", 2)[0]
    d = {
        "brew": {"build": image_nvr},
        "repository": image_name + "_repo",
        "commit": image_name + "_123",
        "target": "t1",
        "git_branch": "mybranch",
        "arches": "x86_64",
        "odcs_compose_ids": [10, 11],
        "directly_affected": True,
    }
    return ContainerImage(d)


@patch(
    "freshmaker.events.conf.parsers",
    [
        "freshmaker.parsers.errata:ErrataAdvisorySigningChangedParser",
        "freshmaker.parsers.errata:ErrataAdvisoryStateChangedParser",
    ],
)
class TestFlatpakModuleAdvisoryReadyEvent(helpers.ModelsTestCase):
    def _patch(self, to_patch, **kwargs):
        patcher = patch(to_patch, autospec=True, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def setUp(self):
        super().setUp()

        self.consumer = self.create_consumer()

        self.get_pulp_repository_ids = self._patch(
            "freshmaker.errata.Errata.get_pulp_repository_ids"
        )
        self.get_pulp_repository_ids.return_value = ["rhel-8-for-x86_64-hidden-rpms"]

        self.builds_signed = self._patch("freshmaker.errata.Errata.builds_signed")
        self.builds_signed.return_value = True

        self.from_advisory_id = self._patch(
            "freshmaker.errata.ErrataAdvisory.from_advisory_id"
        )
        self.advisory = ErrataAdvisory(123, "RHSA-123", "QE", ["module"], "Critical")
        self.from_advisory_id.return_value = self.advisory
        self.handler = RebuildFlatpakApplicationOnModuleReady()

        self.mock_image_modules_mapping = self._patch(
            "freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._image_modules_mapping",
            return_value={"image-foo-bar": {"module-foo-bar"}}
        )

        self.mock_lb = self._patch(
            "freshmaker.handlers.koji.rebuild_flatpak_application_on_module_ready.LightBlue"
        )
        self.mock_lb.return_value.get_images_by_nvrs.side_effect = lambda images, rpm_nvrs: [
            _mock_image(image) for image in images
        ]

        self.mock_pyxis = self._patch(
            "freshmaker.handlers.koji.rebuild_flatpak_application_on_module_ready.Pyxis"
        )
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = True

        self.mock_errata = self._patch(
            "freshmaker.handlers.koji.rebuild_flatpak_application_on_module_ready.Errata"
        )

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
            },
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
            },
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
            },
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
            },
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
            },
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
            },
        }
        event = self.consumer.get_abstracted_msg(msg)
        self.assertIsInstance(event, FlatpakModuleAdvisoryReadyEvent)
        self.assertEqual("fake-msg-id", event.msg_id)
        self.assertEqual(self.handler.can_handle(event), True)

    def test_event_state_updated_when_no_auto_rebuild_images(self):
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = False
        self.handler.handle(self.event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No images impacted by the advisory are enabled for auto rebuild. message_id: 123",
        )

    def test_event_state_updated_when_no_images_with_higher_rpm_nvr(self):
        self.mock_lb.return_value.get_images_by_nvrs.side_effect = lambda images, rpm_nvrs: []
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = True
        self.handler.handle(self.event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "Images are no longer impacted by the advisory. message_id: 123",
        )

    @patch("freshmaker.odcsclient.create_odcs_client")
    def test_prepare_data_for_compose_not_module_type(self, create_odcs_client):
        odcs = create_odcs_client.return_value
        # Test for compose source_type not module type
        odcs.get_compose.return_value = {
            "arches": "x86_64",
            "id": 985716,
            "owner": "auto/example.com",
            "result_repo": "http://example.com/composes/odcs-985590/compose/Temporary",
            "result_repofile": "http://example.com/composes/odcs-985590/compose/Temporary/odcs-985590.repo",
            "results": ["repository"],
            "source": "nodejs:14:8040020211213111158:522a0ee4",
            "source_type": 4,
            "state": 2,
            "state_name": "done",
            "state_reason": "Compose is generated successfully",
            "target_dir": "default",
        }
        original_odcs_compose_ids = ["985716"]
        module_name_stream_set = set(["nodejs:14"])
        module_name_stream_version_set = set(["nodejs:14:8040020211213111158"])
        reused_composes = self.handler._reused_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        updated_compose_source = self.handler._updated_compose_source(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(reused_composes, {"985716"})
        self.assertEqual(updated_compose_source, "")

    @patch("freshmaker.odcsclient.create_odcs_client")
    def test_prepare_data_for_compose_all_sources_not_in_adv(self, create_odcs_client):
        odcs = create_odcs_client.return_value
        # All original compose sources not in advisory(compose source_type module type)
        odcs.get_compose.return_value = {
            "arches": "x86_64",
            "id": 985716,
            "owner": "auto/example.com",
            "result_repo": "http://example.com/composes/odcs-985590/compose/Temporary",
            "result_repofile": "http://example.com/composes/odcs-985590/compose/Temporary/odcs-985590.repo",
            "results": ["repository"],
            "source": "nodejs:14:8040020211213111158:522a0ee4",
            "source_type": 2,
            "state": 2,
            "state_name": "done",
            "state_reason": "Compose is generated successfully",
            "target_dir": "default",
        }
        original_odcs_compose_ids = ["985716"]
        module_name_stream_set = set(["name:stream"])
        module_name_stream_version_set = set(["name:stream:version"])
        reused_composes = self.handler._reused_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        updated_compose_source = self.handler._updated_compose_source(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(reused_composes, {"985716"})
        self.assertEqual(updated_compose_source, "name:stream:version")

    @patch("freshmaker.odcsclient.create_odcs_client")
    def test_prepare_data_for_compose_some_sources_in_adv(self, create_odcs_client):
        odcs = create_odcs_client.return_value
        # Some original compose sources in advisory(compose source_type module type)
        odcs.get_compose.return_value = {
            "arches": "x86_64",
            "id": 985716,
            "owner": "auto/example.com",
            "result_repo": "http://example.com/composes/odcs-985590/compose/Temporary",
            "result_repofile": "http://example.com/composes/odcs-985590/compose/Temporary/odcs-985590.repo",
            "results": ["repository"],
            "source": "nodejs:14:8040020211213111158:522a0ee4 name:stream:9823933:8233ee4",
            "source_type": 2,
            "state": 2,
            "state_name": "done",
            "state_reason": "Compose is generated successfully",
            "target_dir": "default",
        }
        original_odcs_compose_ids = ["985716"]
        module_name_stream_set = set(["name:stream"])
        module_name_stream_version_set = set(["name:stream:9823933"])
        reused_composes = self.handler._reused_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        updated_compose_source = self.handler._updated_compose_source(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(reused_composes, set())
        self.assertEqual(
            updated_compose_source,
            "name:stream:9823933 nodejs:14:8040020211213111158",
        )

    @patch("freshmaker.odcsclient.create_odcs_client")
    def test_record_builds(self, create_odcs_client):
        """
        Tests that builds are properly recorded in DB.
        """
        resolve_commit = self._patch(
            "freshmaker.lightblue.ContainerImage.resolve_commit"
        )
        resolve_commit.return_value = None

        odcs = create_odcs_client.return_value
        composes = [
            {
                "id": compose_id,
                "result_repofile": "http://localhost/{}.repo".format(compose_id),
                "state_name": "done",
            }
            for compose_id in range(1, 3)
        ]
        odcs.new_compose.side_effect = composes
        odcs.get_compose.return_value = {}

        get_build = self._patch("freshmaker.kojiservice.KojiService.get_build")
        get_build.return_value = {
            "extra": {
                "typeinfo": {
                    "module": {
                        "modulemd_str": '---\ndocument: modulemd\nversion: 2\ndata:\n  name: ghc\n  stream: "9.2"\n  version: 3620211101111632\n  context: d099bf28\n  summary: Haskell GHC 9.2\n  description: >-\n    This module provides the Glasgow Haskell Compiler version 9.2.1\n',
                    }
                }
            },
        }

        self.mock_image_modules_mapping.return_value = {
            "build%s-1-1.25" % build_id: [] for build_id in range(1, 3)
        }
        self.handler.handle(self.event)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            args = json.loads(build.build_args)
            self.assertEqual(args["repository"], build.name + "_repo")
            self.assertEqual(args["commit"], build.name + "_123")
            self.assertEqual(args["renewed_odcs_compose_ids"], [10, 11])

    def test_manual_event_can_handle(self):
        event = FlatpakApplicationManualBuildEvent(
            "123", self.advisory, container_images=[])
        self.assertEqual(event.manual, True)
        self.assertEqual(self.handler.can_handle(event), True)

    @patch("freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._record_builds")
    def test_manual_event_initialized(self, mock_record_builds):
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = True
        event = FlatpakApplicationManualBuildEvent(
            "123", self.advisory, container_images=[])
        self.handler.handle(event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.BUILDING.value)
        mock_record_builds.assert_called()

    @patch("freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._record_builds")
    def test_manual_event_initialized_when_matching_images(self, mock_record_builds):
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = True
        event = FlatpakApplicationManualBuildEvent(
            "123", self.advisory, container_images=["image-foo-bar"])
        self.handler.handle(event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.BUILDING.value)
        mock_record_builds.assert_called()

    def test_manual_event_skipped_when_no_matching_images(self):
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = False
        event = FlatpakApplicationManualBuildEvent(
            "123", self.advisory, container_images=["image-foo-bar2"])
        self.handler.handle(event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "None of the specified images are listed in flatpak index"
            " service as latest published images impacted by"
            " the advisory: image-foo-bar2. message_id: 123",
        )

    def test_manual_event_skipped_when_no_auto_rebuild_images(self):
        self.mock_pyxis.return_value.image_is_tagged_auto_rebuild.return_value = False
        event = FlatpakApplicationManualBuildEvent(
            "123", self.advisory, container_images=[])
        self.handler.handle(event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No images impacted by the advisory are enabled for auto rebuild. message_id: 123",
        )
