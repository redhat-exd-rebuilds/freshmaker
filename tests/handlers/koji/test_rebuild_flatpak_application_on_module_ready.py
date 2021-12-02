# SPDX-License-Identifier: MIT

import json
from unittest.mock import patch

from freshmaker import db
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.handlers.koji import RebuildFlatpakApplicationOnModuleReady
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event
from freshmaker.types import EventState
from tests import helpers


@patch(
    "freshmaker.events.conf.parsers",
    [
        "freshmaker.parsers.errata:ErrataAdvisorySigningChangedParser",
        "freshmaker.parsers.errata:ErrataAdvisoryStateChangedParser",
    ],
)
class TestFlatpakModuleAdvisoryReadyEvent(helpers.ModelsTestCase):
    def _patch(self, to_patch):
        patcher = patch(to_patch, autospec=True)
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
        self.mock_get_auto_rebuild_image_mapping = self._patch(
            "freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._get_auto_rebuild_image_mapping"
        )
        self.mock_filter_images_with_higher_rpm_nvr = self._patch(
            "freshmaker.handlers.koji.RebuildFlatpakApplicationOnModuleReady._filter_images_with_higher_rpm_nvr"
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
        get_cve_affected_build_nvrs = self._patch(
            "freshmaker.errata.Errata.get_cve_affected_build_nvrs"
        )
        get_cve_affected_build_nvrs.return_value = []
        self.mock_get_auto_rebuild_image_mapping.return_value = {}
        handler = RebuildFlatpakApplicationOnModuleReady()
        handler.handle(self.event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "Images are not enabled for auto rebuild.  message_id: 123",
        )

    def test_event_state_updated_when_no_images_with_higher_rpm_nvr(self):
        get_cve_affected_build_nvrs = self._patch(
            "freshmaker.errata.Errata.get_cve_affected_build_nvrs"
        )
        get_cve_affected_build_nvrs.return_value = []
        self.mock_get_auto_rebuild_image_mapping.return_value = {
            "module-foo-bar": "image-foo-bar"
        }
        self.mock_filter_images_with_higher_rpm_nvr.return_value = []
        handler = RebuildFlatpakApplicationOnModuleReady()
        handler.handle(self.event)

        db_event = Event.get(db.session, message_id="123")
        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertEqual(
            db_event.state_reason,
            "No images are impacted by the advisory.  message_id: 123",
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
        outdated_composes = self.handler._outdated_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        missing_composes = self.handler._missing_composes(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(outdated_composes, {"985716"})
        self.assertEqual(missing_composes, set())

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
        outdated_composes = self.handler._outdated_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        missing_composes = self.handler._missing_composes(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(outdated_composes, {"985716"})
        self.assertEqual(missing_composes, {"name:stream:version"})

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
        outdated_composes = self.handler._outdated_composes(
            original_odcs_compose_ids, module_name_stream_set
        )
        missing_composes = self.handler._missing_composes(
            original_odcs_compose_ids,
            module_name_stream_set,
            module_name_stream_version_set,
        )
        self.assertEqual(outdated_composes, set())
        self.assertEqual(
            missing_composes,
            {"name:stream:9823933", "nodejs:14:8040020211213111158"},
        )

    def _mock_image(self, build):
        d = {
            "brew": {"build": build + "-1-1.25"},
            "repository": build + "_repo",
            "commit": build + "_123",
            "target": "t1",
            "git_branch": "mybranch",
            "arches": "x86_64",
            "original_odcs_compose_ids": [10, 11],
            "directly_affected": True,
        }
        return ContainerImage(d)

    @patch("freshmaker.odcsclient.create_odcs_client")
    def test_record_builds(self, create_odcs_client):
        """
        Tests that builds are properly recorded in DB.
        """
        resolve_commit = self._patch(
            "freshmaker.lightblue.ContainerImage.resolve_commit"
        )
        resolve_commit.return_value = None
        resolve_original_odcs_compose_ids = self._patch(
            "freshmaker.lightblue.ContainerImage.resolve_original_odcs_compose_ids"
        )
        resolve_original_odcs_compose_ids.return_value = None

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

        get_cve_affected_build_nvrs = self._patch(
            "freshmaker.errata.Errata.get_cve_affected_build_nvrs"
        )
        get_cve_affected_build_nvrs.return_value = []

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

        self.mock_get_auto_rebuild_image_mapping.return_value = {
            "build%s-1-1.25" % build_id: [] for build_id in range(1, 3)
        }
        self.mock_filter_images_with_higher_rpm_nvr.return_value = [
            self._mock_image("build%s" % build_id) for build_id in range(1, 3)
        ]
        handler = RebuildFlatpakApplicationOnModuleReady()
        handler.handle(self.event)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            args = json.loads(build.build_args)
            self.assertEqual(args["repository"], build.name + "_repo")
            self.assertEqual(args["commit"], build.name + "_123")
            self.assertEqual(args["renewed_odcs_compose_ids"], [10, 11])
