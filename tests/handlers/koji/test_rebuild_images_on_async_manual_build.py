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

from unittest.mock import MagicMock

from freshmaker import db
from freshmaker.handlers.koji import RebuildImagesOnAsyncManualBuild
from freshmaker.events import FreshmakerAsyncManualBuildEvent
from freshmaker.types import EventState
from freshmaker.models import Event
from freshmaker.image import ContainerImage
from tests import helpers


class TestRebuildImagesOnAsyncManualBuild(helpers.ModelsTestCase):
    def setUp(self):
        super(TestRebuildImagesOnAsyncManualBuild, self).setUp()

        self.patcher = helpers.Patcher("freshmaker.handlers.koji.RebuildImagesOnAsyncManualBuild.")
        # We do not want to send messages to message bus while running tests
        self.mock_messaging_publish = self.patcher.patch("freshmaker.messaging.publish")

        # Mocking koji
        self.mock_get_build = self.patcher.patch(
            "freshmaker.kojiservice.KojiService.get_build",
            return_value={"build_id": 123456, "extra": {"container_koji_task_id": 21938204}},
        )
        self.mock_get_task_request = self.patcher.patch(
            "freshmaker.kojiservice.KojiService.get_task_request",
            return_value=[
                "git://example.com/rpms/repo-1#commit_hash1",
                "test-target",
                {
                    "compose_ids": None,
                    "git_branch": "test_branch",
                    "scratch": False,
                    "signing_intent": None,
                    "yum_repourls": [("fake-url.repo")],
                },
            ],
        )

        self.mock_allow_build = self.patcher.patch("allow_build", return_value=True)

        # Mocking Lightblue
        self.mock_find_images_to_rebuild = self.patcher.patch("_find_images_to_rebuild")
        self.mock_pyxis = self.patcher.patch("init_pyxis_api_instance")

        self.mock_start_to_build_images = self.patcher.patch("start_to_build_images")
        self.mock_get_image_builds_in_first_batch = self.patcher.patch(
            "freshmaker.models.Event.get_image_builds_in_first_batch"
        )

        # Structure of the images used for testing:
        #       image_0
        #         +
        #         |
        #         +
        #      image_a
        #         +
        #         |
        #    +----+----+
        #    |         |
        #    +         +
        # image_b    image_d
        #              +
        #              |
        #              +
        #            image_e

        # image_c and image_f are unrelated.

        # image_0 is a base image, with no parent
        self.image_0 = ContainerImage(
            {
                "repository": "repo_1",
                "commit": "1234567",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_0_content_set_1", "image_0_content_set_2"],
                "arches": "x86_64",
                "brew": {
                    "build": "image-container-1.0-2",
                    "package": "image-container",
                },
                "parent": None,
                "parsed_data": {
                    "layers": [
                        "sha512:7890",
                        "sha512:5678",
                    ]
                },
                "published": False,
            }
        )

        self.image_a = ContainerImage(
            {
                "repository": "repo_1",
                "commit": "1234567",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_a_content_set_1", "image_a_content_set_2"],
                "arches": "x86_64",
                "brew": {
                    "build": "image-a-container-1.0-2",
                    "package": "image-a-container",
                },
                "parent": self.image_0,
                "parsed_data": {
                    "layers": [
                        "sha512:7890",
                        "sha512:5678",
                    ]
                },
                "published": False,
            }
        )

        # image_b is a child image of image_a
        self.image_b = ContainerImage(
            {
                "repository": "repo_2",
                "commit": "5678901",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_b_content_set_1", "image_b_content_set_2"],
                "arches": "x86_64",
                "brew": {"build": "image-b-container-2.14-1", "package": "image-b-container"},
                "parent": self.image_a,
                "parsed_data": {
                    "layers": [
                        "sha512:f109",
                        "sha512:7890",
                        "sha512:5678",
                    ]
                },
                "published": False,
            }
        )

        # image_c is an image unrelated to image_a and image_b
        # it also has no parent image.
        # image_c has the same name of image_a, that's why it has this name
        self.image_c = ContainerImage(
            {
                "repository": "repo_1",
                "commit": "1234569",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_a_content_set_1", "image_a_content_set_2"],
                "arches": "x86_64",
                "brew": {
                    "build": "image-a-container-1.0-3",
                    "package": "image-a-container",
                },
                "parent": None,
                "parsed_data": {
                    "layers": [
                        "sha512:7890",
                        "sha512:5678",
                    ]
                },
                "published": False,
            }
        )

        # image_d is a child image of image_a, same as image_b
        # so image_d and image_b are unrelated, since they are sibilings
        self.image_d = ContainerImage(
            {
                "repository": "repo_2",
                "commit": "5678906",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_d_content_set_1", "image_d_content_set_2"],
                "arches": "x86_64",
                "brew": {"build": "image-d-container-3.3-1", "package": "image-d-container"},
                "parent": self.image_a,
                "parsed_data": {
                    "layers": [
                        "sha512:f109",
                    ]
                },
                "published": False,
            }
        )

        # image_e is a child image of image_d
        self.image_e = ContainerImage(
            {
                "repository": "repo_2",
                "commit": "5678906",
                "target": "container-candidate",
                "git_branch": "test_branch",
                "content_sets": ["image_e_content_set_1", "image_e_content_set_2"],
                "arches": "x86_64",
                "brew": {"build": "image-e-container-3.3-1", "package": "image-e-container"},
                "parent": self.image_d,
                "parsed_data": {
                    "layers": [
                        "sha512:f109",
                    ]
                },
                "published": False,
            }
        )

        self.image_f = ContainerImage(
            {
                "architecture": "arm64",
                "brew": {
                    "build": "s2i-core-container-1-147",
                    "completion_date": "20200603T12:00:24.000-0400",
                    "nvra": "s2i-core-container-1-147.arm64",
                    "package": "s2i-core-container",
                },
                "content_sets": [
                    "rhel-8-for-x86_64-appstream-rpms",
                    "rhel-8-for-aarch64-baseos-rpms",
                    "rhel-8-for-x86_64-baseos-rpms",
                    "rhel-8-for-s390x-baseos-rpms",
                    "rhel-8-for-aarch64-appstream-rpms",
                    "rhel-8-for-ppc64le-appstream-rpms",
                    "rhel-8-for-ppc64le-baseos-rpms",
                    "rhel-8-for-s390x-appstream-rpms",
                ],
                "multi_arch_rpm_manifest": {},
                "parent_brew_build": "ubi8-container-8.2-299",
                "parsed_data": {},
                "repositories": [
                    {
                        "published": True,
                        "repository": "rhel8/s2i-core",
                        "tags": [{"name": "1-147"}],
                    },
                    {"published": True, "repository": "ubi8/s2i-core", "tags": [{"name": "1-147"}]},
                ],
            }
        )

    def test_can_handle_event(self):
        event = FreshmakerAsyncManualBuildEvent("msg-id-01", "repo-branch", ["image1", "image2"])
        handler = RebuildImagesOnAsyncManualBuild()
        self.assertTrue(handler.can_handle(event))

    def test_building_single_image(self):
        """
        This tests the successful build of a single image
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_a]
        self.mock_find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild", return_value=[[self.image_a]]
        )
        event = FreshmakerAsyncManualBuildEvent("msg-id-123", "test_branch", ["image-a-container"])
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 1)
        self.mock_start_to_build_images.assert_called_once()

    def test_building_related_images_correct_order(self):
        """
        This tests the successful build of 2 related images in the correct order.
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_a, self.image_b]
        self.mock_find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild", return_value=[[self.image_a, self.image_b]]
        )
        self.mock_generate_batches = self.patcher.patch(
            "generate_batches", return_value=[[self.image_a], [self.image_b]]
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123", "test_branch", ["image-b-container", "image-a-container"]
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 2)
        self.mock_start_to_build_images.assert_called_once()

    def test_failed_to_build_images_never_built_before(self):
        """
        This test checks that trying to build an image that was never built before (for that
        branch) will make the build fail.
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_a]
        self.mock_find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild", return_value=[[self.image_a]]
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123", "another-branch", ["image-a-container"]
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)
        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.FAILED.value, db_event.state)

    def test_multiple_nvrs_for_the_same_name(self):
        """
        This test checks that when for one name more nvrs are returned by Pyxis, Freshmaker
        will pick the one with higher nvr.
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_a, self.image_c]
        self.mock_find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild", return_value=[[self.image_c]]
        )
        event = FreshmakerAsyncManualBuildEvent("msg-id-123", "test_branch", ["image-a-container"])
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.mock_start_to_build_images.assert_called_once()
        self.assertEqual(len(db_event.builds.all()), 1)
        self.assertEqual(db_event.builds.one().original_nvr, "image-a-container-1.0-3")

    def test_building_sibilings(self):
        """
        This test checks that when the users requests to rebuild 2 images that are sibilings
        (or other unrelated images) Freshmaker will rebuild them separately, without the need
        of rebuilding the parent.
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_b, self.image_d]
        self.find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild",
            return_value=[
                [self.image_b, self.image_a, self.image_0],
                [self.image_d, self.image_a, self.image_0],
            ],
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123", "test_branch", ["image-b-container", "image-d-container"]
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 2)
        self.mock_start_to_build_images.assert_called_once()

    def test_building_images_with_disconnected_tree(self):
        self.mock_find_images_to_rebuild.return_value = [self.image_b, self.image_d, self.image_e]
        self.find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild",
            return_value=[
                [self.image_b, self.image_a, self.image_0],
                [self.image_d, self.image_a, self.image_0],
                [self.image_e, self.image_d, self.image_a, self.image_0],
            ],
        )
        self.mock_generate_batches = self.patcher.patch(
            "generate_batches", return_value=[[self.image_b, self.image_d], [self.image_e]]
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123",
            "test_branch",
            ["image-b-container", "image-d-container", "image-e-container"],
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 3)
        self.mock_start_to_build_images.assert_called_once()

    def test_intermediate_images_are_build(self):
        self.mock_find_images_to_rebuild.return_value = [self.image_b, self.image_d, self.image_0]
        self.find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild",
            return_value=[
                [self.image_0],
                [self.image_b, self.image_a, self.image_0],
                [self.image_d, self.image_a, self.image_0],
            ],
        )
        self.mock_generate_batches = self.patcher.patch(
            "generate_batches",
            return_value=[[self.image_0], [self.image_a], [self.image_b, self.image_d]],
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123",
            "test_branch",
            ["image-container", "image-b-container", "image-d-container"],
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 4)
        self.mock_start_to_build_images.assert_called_once()

    def test_related_images_are_built(self):
        self.mock_find_images_to_rebuild.return_value = [self.image_b, self.image_d, self.image_a]
        self.find_images_trees_to_rebuild = self.patcher.patch(
            "find_images_trees_to_rebuild",
            return_value=[
                [self.image_a, self.image_0],
                [self.image_b, self.image_a, self.image_0],
                [self.image_d, self.image_a, self.image_0],
            ],
        )
        self.mock_generate_batches = self.patcher.patch(
            "generate_batches", return_value=[[self.image_a], [self.image_b, self.image_d]]
        )
        event = FreshmakerAsyncManualBuildEvent(
            "msg-id-123",
            "test_branch",
            ["image-a-container", "image-b-container", "image-d-container"],
        )
        handler = RebuildImagesOnAsyncManualBuild()
        handler.handle(event)

        db_event = Event.get(db.session, "msg-id-123")
        self.assertEqual(EventState.BUILDING.value, db_event.state)
        self.mock_get_image_builds_in_first_batch.assert_called_once_with(db.session)
        self.assertEqual(len(db_event.builds.all()), 3)
        self.mock_start_to_build_images.assert_called_once()

    def test_parent_if_image_without_parent(self):
        """
        This tests if we get parent as brew build of single image to rebuild
        when image doesn't have "parent" key
        """
        self.mock_find_images_to_rebuild.return_value = [self.image_f]
        event = FreshmakerAsyncManualBuildEvent("msg-id-123", "test_branch", ["image-a-container"])
        find_parent_mock = MagicMock()
        find_parent_mock.find_parent_brew_build_nvr_from_child.return_value = (
            "ubi8-container-8.2-299"
        )
        self.mock_pyxis.return_value = find_parent_mock
        RebuildImagesOnAsyncManualBuild().handle(event)

        db_event = Event.get(db.session, "msg-id-123")

        # Check if build in DB corresponds to parent of the image
        build = db_event.builds.first().json()
        self.assertEqual(build["build_args"].get("original_parent", 0), "ubi8-container-8.2-299")
        # check if we are calling Lightblue to get proper parent of image
        find_parent_mock.find_parent_brew_build_nvr_from_child.assert_called_once_with(self.image_f)

    def test_parent_if_image_with_parent(self):
        """
        This tests if we get parent of single image to rebuild, when image
        has "parent" key as None OR as some image
        """
        for index, image in enumerate([self.image_0, self.image_a], 1):
            self.mock_find_images_to_rebuild.return_value = [image]
            event_id = f"msg-id-{index}"
            event = FreshmakerAsyncManualBuildEvent(event_id, "test_branch", ["image-a-container"])
            RebuildImagesOnAsyncManualBuild().handle(event)

            db_event = Event.get(db.session, event_id)

            if image["parent"] is not None:
                original_parent = image["parent"]["brew"]["build"]
            else:
                original_parent = None

            # Check if build in DB corresponds to parent of the image
            build = db_event.builds.first().json()
            self.assertEqual(build["build_args"].get("original_parent", 0), original_parent)
