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
import json
from datetime import datetime
from unittest.mock import patch, call, MagicMock

import pytest
import freezegun

from freshmaker import db, conf
from freshmaker.events import (
    BotasErrataShippedEvent,
    ManualRebuildWithAdvisoryEvent,
    TestingEvent)
from freshmaker.handlers.botas import HandleBotasAdvisory
from freshmaker.errata import ErrataAdvisory
from freshmaker.models import Event, ArtifactBuild, ArtifactBuildState
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
        self.get_blocking_advisories = \
            self.patcher.patch("freshmaker.errata.Errata.get_blocking_advisories_builds",
                               return_value=set())

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

    def test_handle(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.handler.allow_build = MagicMock(return_value=True)
        self.handler._create_original_to_rebuilt_nvrs_map = \
            MagicMock(return_value={"original_1": "some_name-1-12345",
                                    "original_2": "some_name_2-2-2"})
        nvr_to_digest = {
            "original_1": "original_1_digest",
            "some_name-1-12345": "some_name-1-12345_digest",
            "original_2": "original_2_digest",
            "some_name_2-2-2": "some_name_2-2-2_digest",
        }
        bundles = [{"bundle_path_digest": "original_1_digest"},
                   {"bundle_path_digest": "some_name-1-12345_digest"},
                   {"bundle_path_digest": "original_2_digest"},
                   {"bundle_path_digest": "some_name_2-2-2_digest"}]
        bundles_with_related_images = {
            "original_1_digest": [
                {
                    "bundle_path_digest": "bundle_with_related_images_1_digest",
                    "csv_name": "image.1.2.3",
                    "version": "1.2.3",
                },
            ],
            "original_2_digest": [
                {
                    "bundle_path_digest": "bundle_with_related_images_2_digest",
                    "csv_name": "image.1.2.4",
                    "version": "1.2.4",
                },
            ]
        }

        image_by_digest = {
            "bundle_with_related_images_1_digest": {"brew": {"build": "bundle1_nvr-1-1"}},
            "bundle_with_related_images_2_digest": {"brew": {"build": "bundle2_nvr-1-1"}},
        }
        self.pyxis().get_manifest_list_digest_by_nvr.side_effect = lambda x: nvr_to_digest[x]
        self.pyxis().get_operator_indices.return_value = []
        self.pyxis().get_latest_bundles.return_value = bundles
        # return bundles for original images
        self.pyxis().get_bundles_by_related_image_digest.side_effect = lambda x, y: bundles_with_related_images[x]
        self.pyxis().get_images_by_digest.side_effect = lambda x: [image_by_digest[x]]
        self.handler.image_has_auto_rebuild_tag = MagicMock(return_value=True)
        get_build = self.patcher.patch("freshmaker.kojiservice.KojiService.get_build")
        builds = {
            "bundle1_nvr-1-1": {
                "task_id": 1,
                "extra": {
                    "image": {
                        "operator_manifests": {
                            "related_images": {
                                "created_by_osbs": True,
                                "pullspecs": [{
                                    "new": "registry/repo/operator1@original_1_digest",
                                    "original": "registry/repo/operator1:v2.2.0",
                                    "pinned": True,
                                }]
                            },
                        }
                    }
                }
            },
            "bundle2_nvr-1-1": {
                "task_id": 2,
                "extra": {
                    "image": {
                        "operator_manifests": {
                            "related_images": {
                                "created_by_osbs": True,
                                "pullspecs": [{
                                    "new": "registry/repo/operator2@original_2_digest",
                                    "original": "registry/repo/operator2:v2.2.0",
                                    "pinned": True,
                                }]
                            },
                        }
                    }
                }
            }
        }
        get_build.side_effect = lambda x: builds[x]
        db_event = Event.get_or_create_from_event(db.session, event)
        self.handler._prepare_builds = MagicMock(return_value=[
            ArtifactBuild.create(db.session, db_event, "ed0", "image", 1234,
                                 original_nvr="some_name-2-12345", rebuilt_nvr="some_name-2-12346"),
            ArtifactBuild.create(db.session, db_event, "ed0", "image", 12345,
                                 original_nvr="some_name_2-2-2", rebuilt_nvr="some_name_2-2-210")
        ])
        self.handler.start_to_build_images = MagicMock()
        db.session.commit()

        now = datetime(year=2020, month=12, day=25, hour=0, minute=0, second=0)
        with freezegun.freeze_time(now):
            self.handler.handle(event)

        self.assertEqual(db_event.state, EventState.BUILDING.value)
        get_build.assert_has_calls([call("bundle1_nvr-1-1"), call("bundle2_nvr-1-1")], any_order=True)
        bundles_by_digest = {
            "bundle_with_related_images_1_digest": {
                "auto_rebuild": True,
                "images": [{"brew": {"build": "bundle1_nvr-1-1"}}],
                "nvr": "bundle1_nvr-1-1",
                "osbs_pinning": True,
                "pullspecs": [
                    {
                        "new": "registry/repo/operator1@some_name-1-12345_digest",
                        "original": "registry/repo/operator1:v2.2.0",
                        "pinned": True,
                    }
                ],
                "update": {
                    "metadata": {
                        "name": "image.1.2.3+0.1608854400.patched",
                        "annotations": {"olm.substitutesFor": "1.2.3"},
                    },
                    "spec": {"version": "1.2.3+0.1608854400.patched"},
                },
            },
            "bundle_with_related_images_2_digest": {
                "auto_rebuild": True,
                "images": [{"brew": {"build": "bundle2_nvr-1-1"}}],
                "nvr": "bundle2_nvr-1-1",
                "osbs_pinning": True,
                "pullspecs": [
                    {
                        "new": "registry/repo/operator2@some_name_2-2-2_digest",
                        "original": "registry/repo/operator2:v2.2.0",
                        "pinned": True,
                    }
                ],
                "update": {
                    "metadata": {
                        "name": "image.1.2.4+0.1608854400.patched",
                        "annotations": {"olm.substitutesFor": "1.2.4"},
                    },
                    "spec": {"version": "1.2.4+0.1608854400.patched"},
                },
            },
        }
        self.handler._prepare_builds.assert_called_with(
            db_event, bundles_by_digest, {'bundle_with_related_images_1_digest', 'bundle_with_related_images_2_digest'})

    @patch.object(conf, "dry_run", new=True)
    @patch.object(conf, "handler_build_allowlist", new={
        "HandleBotasAdvisory": {
            "image": {
                "advisory_name": "RHBA-2020"
            }
        }})
    @patch("freshmaker.handlers.botas.botas_shipped_advisory.HandleBotasAdvisory.get_published_original_nvr")
    def test_get_original_nvrs(self, get_build):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.botas_advisory._builds = {
            "product_name": {
                "builds": [{"nvr": "some_name-2-2"},
                           {"nvr": "some_name_two-2-2"}]
            }
        }
        get_build.return_value = "some_name-1-0"

        self.handler.handle(event)
        self.pyxis().get_manifest_list_digest_by_nvr.assert_has_calls([
            call("some_name-1-0"),
            call("some_name_two-2-2"),
        ], any_order=True)

    @patch.object(conf, 'dry_run', new=True)
    @patch.object(conf, 'handler_build_allowlist', new={
        'HandleBotasAdvisory': {
            'image': {
                'advisory_name': 'RHBA-2020'
            }
        }})
    def test_handle_no_digests_error(self):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.pyxis().get_manifest_list_digest_by_nvr.return_value = None
        self.botas_advisory._builds = {}

        self.handler.handle(event)
        db_event = Event.get(db.session, message_id='test_msg_id')

        self.assertEqual(db_event.state, EventState.SKIPPED.value)
        self.assertTrue(
            db_event.state_reason.startswith("None of the original images have digest"))

    @patch.object(conf, 'dry_run', new=True)
    @patch.object(conf, 'handler_build_allowlist', new={
        'HandleBotasAdvisory': {
            'image': {
                'advisory_name': 'RHBA-2020'
            }
        }})
    @patch("freshmaker.handlers.botas.botas_shipped_advisory.HandleBotasAdvisory.get_published_original_nvr")
    @patch("freshmaker.handlers.botas.botas_shipped_advisory.KojiService")
    def test_multiple_bundles_to_single_related_image(self, mock_koji,
                                                      get_published):
        event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.botas_advisory._builds = {
            "product_name": {
                "builds": [{"nvr": "foo-1-2.123"},
                           {"nvr": "bar-2-2.134"}]
            }
        }

        published_nvrs = {
            "foo-1-2.123": "foo-1-2",
            "bar-2-2.134": "bar-2-2"
        }
        get_published.side_effect = lambda x: published_nvrs[x]

        digests_by_nvrs = {
            "foo-1-2": "sha256:111",
            "bar-2-2": "sha256:222",
            "foo-1-2.123": "sha256:333",
            "bar-2-2.134": "sha256:444",
        }
        self.pyxis().get_manifest_list_digest_by_nvr.side_effect = lambda x: digests_by_nvrs[x]

        bundles_by_related_digest = {
            "sha256:111": [
                {
                    "bundle_path": "bundle-a/path",
                    "bundle_path_digest": "sha256:123123",
                    "channel_name": "streams-1.5.x",
                    "csv_name": "amq-streams.1.5.3",
                    "related_images": [
                        {
                            "image": "foo@sha256:111",
                            "name": "foo",
                            "digest": "sha256:111"
                        },
                    ],
                    "version": "1.5.3"
                },
                {
                    "bundle_path": "bundle-b/path",
                    "bundle_path_digest": "sha256:023023",
                    "channel_name": "4.5",
                    "csv_name": "amq-streams.2.4.2",
                    "related_images": [
                        {
                            "image": "foo@sha256:111",
                            "name": "foo",
                            "digest": "sha256:111"
                        },
                    ],
                    "version": "2.4.2"
                },
            ],
            "sha256:222": []
        }
        self.pyxis().get_bundles_by_related_image_digest.side_effect = \
            lambda x, _: bundles_by_related_digest[x]

        bundle_images = {
            "sha256:123123": [{
                "brew": {
                    "build": "foo-a-bundle-2.1-2",
                    "nvra": "foo-a-bundle-2.1-2.amd64",
                    "package": "foo-a-bundle",
                },
                "repositories": [
                    {
                        "content_advisory_ids": [],
                        "manifest_list_digest": "sha256:12322",
                        "manifest_schema2_digest": "sha256:123123",
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foo/foo-a-operator-bundle",
                        "tags": [{"name": "2"}, {"name": "2.1"}],
                    }
                ],
            }],
            "sha256:023023": [{
                "brew": {
                    "build": "foo-b-bundle-3.1-2",
                    "nvra": "foo-b-bundle-3.1-2.amd64",
                    "package": "foo-b-bundle",
                },
                "repositories": [
                    {
                        "content_advisory_ids": [],
                        "manifest_list_digest": "sha256:12345",
                        "manifest_schema2_digest": "sha256:023023",
                        "published": True,
                        "registry": "registry.example.com",
                        "repository": "foo/foo-b-operator-bundle",
                        "tags": [{"name": "3"}, {"name": "3.1"}],
                    }
                ],
            }]
        }
        self.pyxis().get_images_by_digest.side_effect = lambda x: bundle_images[x]

        def _fake_get_auto_rebuild_tags(registry, repository):
            if repository == "foo/foo-a-operator-bundle":
                return ["2", "latest"]
            if repository == "foo/foo-b-operator-bundle":
                return ["3", "latest"]

        self.pyxis().get_auto_rebuild_tags.side_effect = _fake_get_auto_rebuild_tags

        koji_builds = {
            "foo-a-bundle-2.1-2": {
                "build_id": 123,
                "extra": {
                    "image": {
                        "operator_manifests": {
                            "related_images": {
                                "created_by_osbs": True,
                                "pullspecs": [
                                    {
                                        "new": "registry.example.com/foo/foo-container@sha256:111",
                                        "original": "registry.exampl.com/foo/foo-container:0.1",
                                        "pinned": True,
                                    }
                                ],
                            }
                        },
                    }
                },
                "name": "foo-a-bundle",
                "nvr": "foo-a-bundle-2.1-2",

            },
            "foo-b-bundle-3.1-2": {
                "build_id": 234,
                "extra": {
                    "image": {
                        "operator_manifests": {
                            "related_images": {
                                "created_by_osbs": True,
                                "pullspecs": [
                                    {
                                        "new": "registry.example.com/foo/foo-container@sha256:111",
                                        "original": "registry.exampl.com/foo/foo-container:0.1",
                                        "pinned": True,
                                    }
                                ],
                            }
                        },
                    }
                },
                "name": "foo-b-bundle",
                "nvr": "foo-b-bundle-3.1-2",

            }
        }
        mock_koji.return_value.get_build.side_effect = lambda x: koji_builds[x]
        self.handler._prepare_builds = MagicMock()
        self.handler.start_to_build_images = MagicMock()

        self.handler.handle(event)
        db_event = Event.get(db.session, message_id='test_msg_id')

        self.pyxis().get_images_by_digest.assert_has_calls([
            call("sha256:123123"),
            call("sha256:023023")
        ], any_order=True)
        self.assertEqual(db_event.state, EventState.BUILDING.value)

    def test_can_handle_manual_rebuild_with_advisory(self):
        event = ManualRebuildWithAdvisoryEvent("123", self.botas_advisory, [])
        self.assertFalse(self.handler.can_handle(event))

    def test_get_published_original_nvr_single_event(self):
        event1 = Event.create(db.session, "id1", "RHSA-1", TestingEvent)
        ArtifactBuild.create(db.session, event1, "ed0", "image", 1234,
                             original_nvr="nvr1-0-1",
                             rebuilt_nvr="nvr1-0-2")
        db.session.commit()
        self.pyxis()._pagination.return_value = [
            {"repositories": [{"published": True}]}
        ]

        ret_nvr = self.handler.get_published_original_nvr("nvr1-0-2")
        self.assertEqual(ret_nvr, "nvr1-0-1")

    def test_get_published_original_nvr(self):
        event1 = Event.create(db.session, "id1", "RHSA-1", TestingEvent)
        ArtifactBuild.create(db.session, event1, "ed0", "image", 1234,
                             original_nvr="nvr1", rebuilt_nvr="nvr1-001")

        event2 = Event.create(db.session, "id2", "RHSA-1",
                              ManualRebuildWithAdvisoryEvent)
        ArtifactBuild.create(db.session, event2, "ed1", "image", 12345,
                             original_nvr="nvr1-001", rebuilt_nvr="nvr1-002")

        event3 = Event.create(db.session, "id3", "RHSA-1",
                              ManualRebuildWithAdvisoryEvent)
        ArtifactBuild.create(db.session, event3, "ed2", "image", 123456,
                             original_nvr="nvr1-002", rebuilt_nvr="nvr1-003")
        db.session.commit()
        self.pyxis()._pagination.side_effect = [
            [{"repositories": [{"published": False}]}],
            [{"repositories": [{"published": True}]}]
        ]

        ret_nvr = self.handler.get_published_original_nvr("nvr1-003")
        self.assertEqual(ret_nvr, "nvr1-001")

    def test_no_original_build_by_nvr(self):
        self.pyxis()._pagination.return_value = [
            {"repositories": [{"published": True}]}
        ]
        self.assertIsNone(self.handler.get_published_original_nvr("nvr2"))

    def test_image_has_auto_rebuild_tag(self):
        bundle_image = {
            "brew": {
                "build": "foo-operator-2.1-2",
                "nvra": "foo-operator-2.1-2.amd64",
                "package": "foo",
            },
            "repositories": [
                {
                    "content_advisory_ids": [],
                    "manifest_list_digest": "sha256:12345",
                    "manifest_schema2_digest": "sha256:23456",
                    "published": True,
                    "registry": "registry.example.com",
                    "repository": "foo/foo-operator-bundle",
                    "tags": [{"name": "2"}, {"name": "2.1"}],
                }
            ],
        }

        self.pyxis().get_auto_rebuild_tags.return_value = ["2", "latest"]

        has_auto_rebuild_tag = self.handler.image_has_auto_rebuild_tag(bundle_image)
        self.assertTrue(has_auto_rebuild_tag)

    @patch("freshmaker.handlers.botas.botas_shipped_advisory.HandleBotasAdvisory.get_published_original_nvr")
    def test_create_original_to_rebuilt_nvrs_map(self, get_original_build):
        get_original_build.side_effect = ["original_1", "original_2"]
        self.handler.event = BotasErrataShippedEvent("test_msg_id", self.botas_advisory)
        self.botas_advisory._builds = {
            "product_name": {
                "builds": [{"nvr": "some_name-2-12345"},
                           {"nvr": "some_name_two-2-2"}]
            }
        }
        self.get_blocking_advisories.return_value = {"some_name-1-1",
                                                     "some_name-2-1"}
        expected_map = {"original_1": "some_name-2-12345",
                        "original_2": "some_name_two-2-2",
                        "some_name-2-1": "some_name-2-12345"}

        mapping = self.handler._create_original_to_rebuilt_nvrs_map()

        self.assertEqual(get_original_build.call_count, 2)
        self.assertEqual(mapping, expected_map)

    @patch("freshmaker.lightblue.ContainerImage.get_additional_data_from_koji")
    def test_prepare_builds(self, get_koji_data):
        get_koji_data.return_value = {
            "repository": "repo",
            "commit": "commit_1",
            "target": "target_1",
            "git_branch": "git_branch_1",
            "arches": ["arch_1", "arch_1"]
        }
        pullspec_override_url = "https://localhost/api/2/pullspec_overrides/"
        db_event = Event.create(db.session, "id1", "RHSA-1", TestingEvent)
        db.session.commit()

        bundle_data = {
            "digest": {
                "images": ["image1", "image2"],
                "nvr": "nvr-1-1",
                "auto_rebuild": True,
                "osbs_pinning": True,
                "pullspecs": [{
                    'new': 'registry/repo/operator@sha256:123',
                    'original': 'registry/repo/operator:v2.2.0',
                    'pinned': True,
                }],
                "update": {
                    "metadata": {
                        'name': "amq-streams.2.2.0+0.1608854400.patched",
                        "annotations": {"olm.substitutesFor": "2.2.0"},
                    },
                    'spec': {
                        'version': "2.2.0+0.1608854400.patched",
                    }
                },
            }
        }

        ret_builds = self.handler._prepare_builds(db_event, bundle_data, ["digest"])

        builds = ArtifactBuild.query.all()
        self.assertEqual(builds, ret_builds)
        submitted_build = builds[0]
        expected_csv_modifications = {
            "pullspecs": [
                {
                    "new": "registry/repo/operator@sha256:123",
                    "original": "registry/repo/operator:v2.2.0",
                    "pinned": True,
                }
            ],
            "update": {
                "metadata": {
                    "name": "amq-streams.2.2.0+0.1608854400.patched",
                    "annotations": {"olm.substitutesFor": "2.2.0"},
                },
                "spec": {
                    "version": "2.2.0+0.1608854400.patched",
                }
            },
        }
        self.assertEqual(submitted_build.bundle_pullspec_overrides, expected_csv_modifications)
        self.assertEqual(submitted_build.state, ArtifactBuildState.PLANNED.value)
        self.assertEqual(json.loads(submitted_build.build_args)["operator_csv_modifications_url"],
                         pullspec_override_url + str(submitted_build.id))


@pytest.mark.parametrize(
    "version, expected",
    (
        ("1.2.3", ("1.2.3+0.1608854400.patched", "0.1608854400.patched")),
        ("1.2.3+beta3", ("1.2.3+beta3.0.1608854400.patched", "0.1608854400.patched")),
        (
            "1.2.3+beta3.0.1608853000.patched",
            ("1.2.3+beta3.0.1608854400.patched", "0.1608854400.patched"),
        ),
    )
)
def test_get_rebuild_bundle_version(version, expected):
    now = datetime(year=2020, month=12, day=25, hour=0, minute=0, second=0)
    with freezegun.freeze_time(now):
        assert HandleBotasAdvisory._get_rebuild_bundle_version(version) == expected


def test_get_csv_name():
    version = "1.2.3"
    rebuild_version = "1.2.3+0.1608854400.patched"
    fm_suffix = "0.1608854400.patched"
    rv = HandleBotasAdvisory._get_csv_name("amq-streams.1.2.3", version, rebuild_version, fm_suffix)
    assert rv == "amq-streams.1.2.3+0.1608854400.patched"

    # If the version is not present in the CSV name (it's supposed to be), then Freshmaker
    # will just append the suffix to make it unique
    rv = HandleBotasAdvisory._get_csv_name("amq-streams.123", version, rebuild_version, fm_suffix)
    assert rv == "amq-streams.123.0.1608854400.patched"


@patch("freshmaker.handlers.botas.botas_shipped_advisory.HandleBotasAdvisory._get_csv_name")
@patch("freshmaker.handlers.botas.botas_shipped_advisory.HandleBotasAdvisory._get_rebuild_bundle_version")
def test_get_csv_updates(mock_grbv, mock_gcn):
    mock_grbv.return_value = ("1.2.3+0.1608854400.patched", "0.1608854400.patched")
    mock_gcn.return_value = "amq-streams.1.2.3+0.1608854400.patched"
    rv = HandleBotasAdvisory._get_csv_updates("amq-streams.1.2.3", "1.2.3")
    assert rv == {
        "update": {
            "metadata": {
                'name': "amq-streams.1.2.3+0.1608854400.patched",
                "annotations": {"olm.substitutesFor": "1.2.3"}
            },
            'spec': {
                'version': "1.2.3+0.1608854400.patched",
            }
        }
    }
