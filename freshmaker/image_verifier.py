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

from freshmaker import conf
from freshmaker.lightblue import LightBlue


class ImageVerifier(object):

    def __init__(self, lb=None):
        """
        Creates new ImageVerifier.

        :param LightBlue lb: Lightblue instance to use to verify images.
            When None, new default Lightblue class is created.
        """
        self.lb = lb if lb else LightBlue(
            server_url=conf.lightblue_server_url,
            cert=conf.lightblue_certificate,
            private_key=conf.lightblue_private_key)

    def _verify_repository_data(self, repo):
        """
        Verifies the Lightblue ContainerRepository data.
        Raises ValueError in case of error.
        """
        if "Generally Available" not in repo["release_categories"]:
            raise ValueError(
                "Only repositories with \"Generally Available\" release_categories can be "
                "rebuilt, but found %r." % repo["release_categories"])

        if not repo["published"]:
            raise ValueError(
                "Only published repositories can be rebuilt, but this repository is not "
                "published.")

        if "auto_rebuild_tags" in repo and repo["auto_rebuild_tags"] == []:
            raise ValueError(
                "The \"auto_rebuild_tags\" in COMET is set to an empty list, this means "
                "rebuilds of images in this repository are disabled.")

    def _verify_image_data(self, image):
        """
        Verifies the Lightblue ContainerImage data.
        Raises ValueError in case of error.
        """
        if not image["content_sets"]:
            raise ValueError(
                "Found image \"%s\" in this repository, but it cannot be rebuilt, because "
                "the \"content_sets\" are not set for this image." % image["brew"]["build"])

    def _get_repository_from_name(self, repo_name):
        """
        Returns the ContainerRepository object based on the Repository name.
        """
        query = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "field": "repository",
                        "op": "=",
                        "rvalue": repo_name
                    },

                ]
            },
            "projection": [
                {"field": "*", "include": True, "recursive": True}
            ]
        }

        repos = self.lb.find_container_repositories(query)
        if not repos:
            raise ValueError("Cannot get repository %s from Lightblue." % repo_name)
        if len(repos) != 1:
            raise ValueError("Multiple records found in Lightblue for repository %s." % repo_name)

        return repos[0]

    def _get_repository_from_image(self, nvr):
        """
        Returns the ContainerRepository object based on the image NVR.
        """
        query = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "field": "images.*.brew.build",
                        "op": "=",
                        "rvalue": nvr
                    },

                ]
            },
            "projection": [
                {"field": "*", "include": True, "recursive": True}
            ]
        }

        repos = self.lb.find_container_repositories(query)
        if not repos:
            raise ValueError("Cannot get repository for image %s from Lightblue." % nvr)
        if len(repos) != 1:
            raise ValueError(
                "Image %s found in multiple repositories in Lightblue." % nvr)

        return repos[0]

    def verify_image(self, image_nvr):
        """
        Verifies the image defined by `image_nvr`.
        Raises ValueError in case of error.

        :param str image_nvr: NVR of image to verify.
        :rtype: dict
        :return: Dict with image NVR as key and list of content_sets as values.
        """
        repo = self._get_repository_from_image(image_nvr)
        self._verify_repository_data(repo)

        images = self.lb.get_images_by_nvrs([image_nvr], include_rpms=False)
        if not images:
            raise ValueError(
                "No published images tagged by %r found in repository" % (
                    repo["auto_rebuild_tags"]))

        image = images[0]
        self._verify_image_data(image)

        return {
            image["brew"]["build"]: image["content_sets"]
        }

    def verify_repository(self, repo_name):
        """
        Verifies the images in repository defined by `repo_name`.
        Raises ValueError in case of error.

        :param str repo_name: Name of repository to verify.
        :rtype: dict
        :return: Dict with image NVR as key and list of content_sets as values.
        """
        repo = self._get_repository_from_name(repo_name)
        self._verify_repository_data(repo)

        rebuildable_images = {}
        images = self.lb.find_images_with_included_srpms(
            [], [], {repo["repository"]: repo}, include_rpms=False)
        for image in images:
            nvr = image["brew"]["build"]
            self._verify_image_data(image)
            rebuildable_images[nvr] = image["content_sets"]

        if not rebuildable_images:
            raise ValueError(
                "No published images tagged by %r found in repository" % (
                    repo["auto_rebuild_tags"]))

        return rebuildable_images
