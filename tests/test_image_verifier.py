# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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
#
# Written by Jan Kaluza <jkaluza@redhat.com>

from unittest.mock import MagicMock

from freshmaker.image_verifier import ImageVerifier
from freshmaker.lightblue import ContainerRepository, ContainerImage
from tests import helpers


class TestImageVerifier(helpers.FreshmakerTestCase):

    def setUp(self):
        super(TestImageVerifier, self).setUp()
        self.lb = MagicMock()
        self.verifier = ImageVerifier(self.lb)

    def test_verify_repository_no_repo(self):
        self.lb.find_container_repositories.return_value = None
        self.assertRaisesRegex(
            ValueError, r'Cannot get repository.*',
            self.verifier.verify_repository, "foo/bar")

    def test_get_verify_repository_multiple_repos(self):
        self.lb.find_container_repositories.return_value = ["foo", "bar"]
        self.assertRaisesRegex(
            ValueError, r'Multiple records found.*',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository_deprecated(self):
        self.lb.find_container_repositories.return_value = [{
            "release_categories": ["Deprecated"],
            "published": True,
            "auto_rebuild_tags": "latest"}]
        self.assertRaisesRegex(
            ValueError, r'.*but found \[\'Deprecated\'\].',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository_not_published(self):
        self.lb.find_container_repositories.return_value = [{
            "release_categories": ["Generally Available"],
            "published": False,
            "auto_rebuild_tags": "latest"}]
        self.assertRaisesRegex(
            ValueError, r'.*is not published.',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository_no_auto_rebuild_tags(self):
        self.lb.find_container_repositories.return_value = [{
            "release_categories": ["Generally Available"],
            "published": True,
            "auto_rebuild_tags": []}]
        self.assertRaisesRegex(
            ValueError, r'.*this repository are disabled.',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository_no_images(self):
        self.lb.find_container_repositories.return_value = [{
            "repository": "foo/bar",
            "release_categories": ["Generally Available"],
            "published": True,
            "auto_rebuild_tags": ["latest"]}]
        self.lb.get_images_by_nvrs.return_value = []
        self.assertRaisesRegex(
            ValueError, r'No published images tagged by.*',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository_no_content_sets(self):
        self.lb.find_container_repositories.return_value = [
            ContainerRepository({
                "repository": "foo/bar",
                "release_categories": ["Generally Available"],
                "published": True,
                "auto_rebuild_tags": ["latest"]
            })
        ]
        self.lb.find_images_with_included_rpms.return_value = [
            ContainerImage({
                "brew": {"build": "foo-1-1"},
                "content_sets": []
            })
        ]
        self.assertRaisesRegex(
            ValueError, r'.*are not set for this image.',
            self.verifier.verify_repository, "foo/bar")

    def test_verify_repository(self):
        self.lb.find_container_repositories.return_value = [
            ContainerRepository({
                "repository": "foo/bar",
                "release_categories": ["Generally Available"],
                "published": True,
                "auto_rebuild_tags": ["latest"]
            })
        ]
        self.lb.find_images_with_included_rpms.return_value = [
            ContainerImage({
                "brew": {"build": "foo-1-1"},
                "content_sets": ["content-set"],
                "repositories": [
                    {
                        "registry": "registry.example.com",
                        "published": True,
                        "repository": "foo/bar",
                        "tags": [{"name": "1"}, {"name": "latest"}, {"name": "1-1"}],
                    },
                    {
                        "registry": "registry.build.example.com",
                        "published": False,
                        "repository": "buildsys/foobar",
                        "tags": [{"name": "1-1"}, {"name": "1.old"}],
                    },
                ]
            })
        ]
        ret = self.verifier.verify_repository("foo/bar")
        expected = {
            "repository": {"auto_rebuild_tags": ["latest"]},
            "images": {
                "foo-1-1": {"content_sets": ["content-set"], "tags": ["1", "latest", "1-1"]}
            },
        }
        self.assertEqual(ret, expected)

    def test_get_verify_image(self):
        self.lb.find_container_repositories.return_value = [
            ContainerRepository({
                "repository": "foo/bar",
                "release_categories": ["Generally Available"],
                "published": True,
                "auto_rebuild_tags": ["latest"]
            })
        ]
        self.lb.get_images_by_nvrs.return_value = [
            ContainerImage({
                "brew": {"build": "foo-1-1"},
                "content_sets": ["content-set"]
            })
        ]
        ret = self.verifier.verify_image("foo-1-1")
        self.assertEqual(ret, {"foo-1-1": ["content-set"]})

    def test_get_verify_image_no_repo(self):
        self.lb.find_container_repositories.return_value = []
        self.assertRaisesRegex(
            ValueError, r'Cannot get repository.*',
            self.verifier.verify_image, "foo/bar")

    def test_get_verify_image_multiple_repos(self):
        self.lb.find_container_repositories.return_value = ["foo", "bar"]
        self.assertRaisesRegex(
            ValueError, r'.*found in multiple repositories in Lightblue.',
            self.verifier.verify_image, "foo/bar")

    def test_verify_image_no_images(self):
        self.lb.find_container_repositories.return_value = [{
            "repository": "foo/bar",
            "release_categories": ["Generally Available"],
            "published": True,
            "auto_rebuild_tags": ["latest"]}]
        self.lb.get_images_by_nvrs.return_value = []
        self.assertRaisesRegex(
            ValueError, r'No published images tagged by.*',
            self.verifier.verify_image, "foo/bar")
