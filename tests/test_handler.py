# -*- coding: utf-8 -*-
#
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Chenxiong Qi <cqi@redhat.com>

import json

from unittest.mock import patch
from requests.exceptions import HTTPError

import freshmaker

from freshmaker import db
from freshmaker.events import ErrataRPMAdvisoryShippedEvent, BotasErrataShippedEvent
from freshmaker.handlers import ContainerBuildHandler, ODCSComposeNotReady
from freshmaker.models import (
    ArtifactBuild,
    ArtifactBuildState,
    ArtifactBuildCompose,
    Compose,
    Event,
    EVENT_TYPES,
)
from freshmaker.errors import UnprocessableEntity, ProgrammingError
from freshmaker.types import ArtifactType, EventState
from freshmaker.config import any_, all_
from freshmaker.odcsclient import COMPOSE_STATES
from tests import helpers


class MyHandler(ContainerBuildHandler):
    """Handler for running tests to test things defined in parents"""

    name = "MyHandler"

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestContext(helpers.ModelsTestCase):
    """Test setting context of handler"""

    def test_context_event(self):
        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataRPMAdvisoryShippedEvent
        )
        db.session.commit()
        handler = MyHandler()
        handler.set_context(db_event)

        self.assertEqual(handler.current_db_event_id, db_event.id)
        self.assertEqual(handler.current_db_artifact_build_id, None)

    def test_context_artifact_build(self):
        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataRPMAdvisoryShippedEvent
        )
        build = ArtifactBuild.create(db.session, db_event, "parent1-1-4", "image")
        db.session.commit()
        handler = MyHandler()
        handler.set_context(build)

        self.assertEqual(handler.current_db_event_id, db_event.id)
        self.assertEqual(handler.current_db_artifact_build_id, build.id)

    def test_context_unknown(self):
        handler = MyHandler()
        self.assertRaises(ProgrammingError, handler.set_context, "something")


class TestDryRun(helpers.FreshmakerTestCase):
    def test_force_dry_run(self):
        handler = MyHandler()
        self.assertFalse(handler.dry_run)

        handler.force_dry_run()
        self.assertTrue(handler.dry_run)


class TestGetRepoURLs(helpers.ModelsTestCase):
    def setUp(self):
        super(TestGetRepoURLs, self).setUp()

        self.compose_1 = Compose(odcs_compose_id=5)
        self.compose_2 = Compose(odcs_compose_id=6)
        self.compose_3 = Compose(odcs_compose_id=7)
        self.compose_4 = Compose(odcs_compose_id=8)
        db.session.add(self.compose_1)
        db.session.add(self.compose_2)
        db.session.add(self.compose_3)
        db.session.add(self.compose_4)

        self.event = Event.create(
            db.session,
            "msg-1",
            "search-key-1",
            EVENT_TYPES[ErrataRPMAdvisoryShippedEvent],
            state=EventState.BUILDING,
            released=False,
        )

        build_args = {}
        build_args["repository"] = "repo"
        build_args["commit"] = "hash"
        build_args["original_parent"] = None
        build_args["target"] = "target"
        build_args["branch"] = "branch"
        build_args["arches"] = "x86_64"
        build_args["renewed_odcs_compose_ids"] = None

        self.build_1 = ArtifactBuild.create(
            db.session,
            self.event,
            "build-1",
            ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED,
            original_nvr="foo-1-2",
        )
        self.build_1.build_args = json.dumps(build_args)

        self.build_2 = ArtifactBuild.create(
            db.session,
            self.event,
            "build-2",
            ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED,
            original_nvr="foo-2-2",
        )
        self.build_2.build_args = json.dumps(build_args)

        db.session.commit()

        rels = (
            (self.build_1.id, self.compose_1.id),
            (self.build_1.id, self.compose_2.id),
            (self.build_1.id, self.compose_3.id),
            (self.build_1.id, self.compose_4.id),
        )

        for build_id, compose_id in rels:
            db.session.add(ArtifactBuildCompose(build_id=build_id, compose_id=compose_id))

        db.session.commit()

        def mocked_odcs_get_compose(compose_id):
            return {
                "id": compose_id,
                "result_repofile": "http://localhost/%d.repo" % compose_id,
                "state": COMPOSE_STATES["done"],
            }

        self.patch_odcs_get_compose = patch(
            "freshmaker.handlers.ContainerBuildHandler.odcs_get_compose",
            side_effect=mocked_odcs_get_compose,
        )
        self.odcs_get_compose = self.patch_odcs_get_compose.start()

    def tearDown(self):
        super(TestGetRepoURLs, self).tearDown()
        self.patch_odcs_get_compose.stop()

    def test_get_repo_urls_no_composes(self):
        handler = MyHandler()
        repos = handler.get_repo_urls(self.build_2)
        self.assertEqual(repos, [])

    def test_get_repo_urls_only_odcs_composes(self):
        handler = MyHandler()
        repos = handler.get_repo_urls(self.build_1)
        self.assertEqual(repos, [])

    @patch.object(
        freshmaker.conf, "image_extra_repo", new={"build-3": "http://localhost/test.repo"}
    )
    def test_get_repo_urls_extra_image_repo(self):
        build_3 = ArtifactBuild.create(
            db.session,
            self.event,
            "build-3",
            ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED,
            original_nvr="build-3-1",
        )

        handler = MyHandler()
        repos = handler.get_repo_urls(build_3)
        self.assertEqual(repos, ["http://localhost/test.repo"])

    @patch("time.time")
    @patch("freshmaker.handlers.ContainerBuildHandler.build_container")
    def test_build_image_artifact_build_only_odcs_composes(self, build_container, time):
        time.return_value = 1234567.1234
        handler = MyHandler()
        handler.build_image_artifact_build(self.build_1)
        build_container.assert_called_once_with(
            "git://pkgs.devel.redhat.com/repo#hash",
            "branch",
            "target",
            arch_override="x86_64",
            compose_ids=[5, 6, 7, 8],
            flatpak=False,
            isolated=True,
            koji_parent_build=None,
            release="2.1234567",
            repo_urls=None,
            operator_csv_modifications_url=None,
        )

    @patch("time.time")
    @patch("freshmaker.handlers.ContainerBuildHandler.build_container")
    def test_build_image_artifact_build_renewed_odcs_composes(self, build_container, time):
        time.return_value = 1234567.1234
        build_args = json.loads(self.build_1.build_args)
        build_args["renewed_odcs_compose_ids"] = [7300, 7301]
        self.build_1.build_args = json.dumps(build_args)
        db.session.commit()

        handler = MyHandler()
        handler.build_image_artifact_build(self.build_1)
        build_container.assert_called_once_with(
            "git://pkgs.devel.redhat.com/repo#hash",
            "branch",
            "target",
            arch_override="x86_64",
            compose_ids=[5, 6, 7, 8, 7300, 7301],
            flatpak=False,
            isolated=True,
            koji_parent_build=None,
            release="2.1234567",
            repo_urls=None,
            operator_csv_modifications_url=None,
        )

    @patch("time.time")
    @patch("freshmaker.handlers.ContainerBuildHandler.build_container")
    def test_build_image_artifact_build_repo_urls(self, build_container, time):
        time.return_value = 1234567.1234
        handler = MyHandler()
        handler.build_image_artifact_build(self.build_1, ["http://localhost/x.repo"])

        repo_urls = ["http://localhost/x.repo"]
        build_container.assert_called_once_with(
            "git://pkgs.devel.redhat.com/repo#hash",
            "branch",
            "target",
            arch_override="x86_64",
            compose_ids=[5, 6, 7, 8],
            flatpak=False,
            isolated=True,
            koji_parent_build=None,
            release="2.1234567",
            repo_urls=repo_urls,
            operator_csv_modifications_url=None,
        )

    @patch("time.time")
    @patch("freshmaker.kojiservice.KojiService.session")
    @patch.object(freshmaker.conf, "koji_container_scratch_build", new=False)
    def test_build_image_artifact_build_flatpak(self, koji_session, time):
        time.return_value = 1234567.1234
        handler = MyHandler()
        flatpak_build = ArtifactBuild.create(
            db.session,
            self.event,
            "flatpak-build-1",
            ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED,
            original_nvr="foo-1-2",
        )
        build_args = json.loads(self.build_1.build_args)
        build_args.update(
            {
                "flatpak": True,
                "renewed_odcs_compose_ids": [7300],
            }
        )
        flatpak_build.build_args = json.dumps(build_args)
        db.session.add(
            ArtifactBuildCompose(build_id=flatpak_build.id, compose_id=self.compose_1.id)
        )

        handler.build_image_artifact_build(flatpak_build)
        koji_session.buildContainer.assert_called_once_with(
            "git://pkgs.devel.redhat.com/repo#hash",
            "target",
            {
                "scratch": False,
                "git_branch": "branch",
                "compose_ids": [5, 7300],
                "flatpak": True,
                "isolated": True,
                "arch_override": "x86_64",
                "release": "2.1234567",
            },
        )

    @patch("freshmaker.handlers.ContainerBuildHandler.build_container")
    def test_build_image_artifact_build_repo_urls_compose_not_ready(self, build_container):
        def mocked_odcs_get_compose(compose_id):
            return {
                "id": compose_id,
                "result_repofile": "http://localhost/%d.repo" % compose_id,
                "state": COMPOSE_STATES["generating"],
            }

        self.odcs_get_compose.side_effect = mocked_odcs_get_compose

        with self.assertRaises(ODCSComposeNotReady):
            handler = MyHandler()
            handler.build_image_artifact_build(self.build_1, ["http://localhost/x.repo"])

        self.assertEqual(self.build_1.state, ArtifactBuildState.PLANNED.value)


class TestAllowBuildBasedOnAllowlist(helpers.FreshmakerTestCase):
    """Test BaseHandler.allow_build"""

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "global": {
                "image": any_(
                    {
                        "advisory_state": "ON_QA",
                        "advisory_name": "RHBA-.*",
                    }
                )
            },
        },
    )
    def test_allowlist_not_overwritten(self):
        """
        Test that "global" config section is not overwritten by handler-specific
        section after calling the handler.allow_build().
        """
        handler = MyHandler()
        handler.name = "foo"
        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_state="SHIPPED_LIVE")
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf, "handler_build_allowlist", new={"MyHandler": {"image": {"name": "test"}}}
    )
    def test_allow_build_in_allowlist(self):
        """Test if artifact is in the handlers allowlist"""
        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(
            ArtifactType.IMAGE, name=container["name"], branch=container["branch"]
        )
        assert allow

    @patch.object(
        freshmaker.conf, "handler_build_allowlist", new={"MyHandler": {"image": {"name": "test1"}}}
    )
    def test_allow_build_not_in_allowlist(self):
        """Test if artifact is not in the handlers allowlist"""
        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(
            ArtifactType.IMAGE, name=container["name"], branch=container["branch"]
        )
        assert not allow

    @patch.object(
        freshmaker.conf, "handler_build_allowlist", new={"MyHandler": {"image": {"name": "te(st"}}}
    )
    def test_allow_build_regex_exception(self):
        """If there is a regex error, method will raise UnprocessableEntity error"""

        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        with self.assertRaises(UnprocessableEntity):
            handler.allow_build(
                ArtifactType.IMAGE, name=container["name"], branch=container["branch"]
            )

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={"MyHandler": {"image": {"advisory_state": ["REL_PREP", "SHIPPED_LIVE"]}}},
    )
    def test_rule_not_defined(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_state="SHIPPED_LIVE")
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_state="SHIPPED_LIVE", published=True
        )
        self.assertTrue(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "MyHandler": {
                "image": {"advisory_state": ["REL_PREP", "SHIPPED_LIVE"], "published": False}
            }
        },
    )
    def test_boolean_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_state="SHIPPED_LIVE", published=True
        )
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={"MyHandler": {"image": {"advisory_state": ["REL_PREP", "SHIPPED_LIVE"]}}},
    )
    def test_not_allow_if_none_passed_rule_is_configured(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, state="SHIPPED_LIVE")
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, "handler_build_allowlist", new={})
    def test_not_allow_if_allowlist_is_not_configured(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, state="SHIPPED_LIVE")
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={"MyHandler": {"image": {"advisory_state": ["REL_PREP", "SHIPPED_LIVE"]}}},
    )
    def test_define_rule_values_as_list(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_state="SHIPPED_LIVE")
        self.assertTrue(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={"MyHandler": {"image": {"advisory_name": r"RHSA-\d+:\d+"}}},
    )
    def test_define_rule_value_as_single_regex_string(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_name="RHSA-2017:31861")
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_name="RHBA-2017:31861")
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "MyHandler": {"image": {"advisory_name": r"RHSA-\d+:\d+", "advisory_state": "REL_PREP"}}
        },
    )
    def test_AND_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name="RHSA-2017:1000", advisory_state="REL_PREP"
        )
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name="RHSA-2017:1000", advisory_state="SHIPPED_LIVE"
        )
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "MyHandler": {
                "image": any_(
                    {"advisory_name": r"RHSA-\d+:\d+"},
                    {"advisory_state": "REL_PREP"},
                )
            }
        },
    )
    def test_OR_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name="RHSA-2017:1000", advisory_state="SHIPPED_LIVE"
        )
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name="RHSA-2017", advisory_state="REL_PREP"
        )
        self.assertTrue(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "MyHandler": {
                "image": all_(
                    {"advisory_name": r"RHSA-\d+:\d+"},
                    any_({"has_hightouch_bugs": True}, {"severity": ["critical", "important"]}),
                )
            }
        },
    )
    def test_OR_between_subrules(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE,
            advisory_name="RHSA-2017:1000",
            has_hightouch_bugs=True,
            severity="low",
        )
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE,
            advisory_name="RHSA-2017:1000",
            has_hightouch_bugs=False,
            severity="critical",
        )
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE,
            advisory_name="RHSA-2017:1000",
            has_hightouch_bugs=False,
            severity="low",
        )
        self.assertFalse(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE,
            advisory_name="RHBA-2017:1000",
            has_hightouch_bugs=False,
            severity="critical",
        )
        self.assertFalse(allowed)

    @patch.object(
        freshmaker.conf,
        "handler_build_allowlist",
        new={
            "MyHandler": {
                "image": {"advisory_name": r"RHSA-\d+:\d+"},
            }
        },
    )
    @patch.object(
        freshmaker.conf,
        "handler_build_blocklist",
        new={
            "MyHandler": {
                "image": {"advisory_name": r"RHSA-2016:\d+"},
            }
        },
    )
    def test_blocklist(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_name="RHSA-2017:1000")
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE, advisory_name="RHSA-2016:1000")
        self.assertFalse(allowed)


class TestStartToBuildImages(helpers.ModelsTestCase):
    @patch("freshmaker.handlers.ContainerBuildHandler.build_image_artifact_build")
    def test_start_to_build_images(self, build_artifact):
        build_artifact.side_effect = [HTTPError("500 Server Error"), 1]
        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataRPMAdvisoryShippedEvent
        )
        build = ArtifactBuild.create(db.session, db_event, "parent1-1-4", "image")
        build2 = ArtifactBuild.create(db.session, db_event, "parent1-1-5", "image")
        db.session.commit()
        handler = MyHandler()

        with self.assertLogs("freshmaker", "ERROR"):
            handler.start_to_build_images([build, build2])

        self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
        self.assertEqual(build2.state, ArtifactBuildState.BUILD.value)
        self.assertEqual(len(db.session.query(ArtifactBuild).all()), 2)

    @patch("freshmaker.kojiservice.KojiService.get_ocp_versions_range")
    def test_start_to_build_invalid_bundle_image(self, mock_get_ocp):
        mock_get_ocp.return_value = "v4.7,v4.8"

        db_event = Event.get_or_create(db.session, "msg1", "current_event", BotasErrataShippedEvent)
        build = ArtifactBuild.create(
            db.session, db_event, "foobar-2-123", "image", state=ArtifactBuildState.PLANNED.value
        )
        build.build_args = json.dumps({"repo": "foobar"})
        build.original_nvr = "foobar-2-123"
        db.session.commit()
        handler = MyHandler()
        handler.build_image_artifact_build(build)

        self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
        self.assertTrue("invalid openshift versions range" in build.state_reason)
