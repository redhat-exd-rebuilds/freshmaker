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

from mypy_extensions import TypedDict
from typing import Optional

from freshmaker import conf
from freshmaker.pyxis_gql import PyxisGQL


class DataElements(TypedDict):
    repository: dict[str, list[str]]
    images: dict[str, dict[str, list[str]]]


class ImageVerifier(object):
    def __init__(self, pyxis: Optional[PyxisGQL] = None):
        """
        Creates new ImageVerifier. When None, new default PyxisGQL class is created.

        :param PyxisGQL pyxis: PyxisGQL instance to use to verify images.
        """
        self.pyxis = (
            pyxis
            if pyxis
            else PyxisGQL(
                url=conf.pyxis_server_url, cert=(conf.pyxis_certificate, conf.pyxis_private_key)
            )
        )

    def _verify_repository_data(self, repo):
        """
        Verifies the PyxisGQL ContainerRepository data.
        Raises ValueError in case of error.
        """
        categories = set(conf.container_release_categories)
        repo_categories = repo.get("release_categories", [])

        if not set(repo_categories).intersection(categories):
            raise ValueError(
                "Only repositories with one of %r release_categories can be "
                "rebuilt, but found %r." % (categories, repo_categories)
            )

        if not repo["published"]:
            for exc in conf.unpublished_exceptions:
                if repo["repository"] == exc["repository"]:
                    break
            else:
                raise ValueError(
                    "Only published repositories or unpublished exceptions can be rebuilt, but "
                    "this repository is not published.")

        if "auto_rebuild_tags" not in repo or repo["auto_rebuild_tags"] is None:
            raise ValueError('The "auto_rebuild_tags" in COMET is not set.')

        if "auto_rebuild_tags" in repo and repo["auto_rebuild_tags"] == []:
            raise ValueError(
                'The "auto_rebuild_tags" in COMET is set to an empty list, this means '
                "rebuilds of images in this repository are disabled."
            )

    def _verify_image_data(self, image):
        """
        Verifies the PyxisGQL ContainerImage data.
        Raises ValueError in case of error.
        """
        if not image["content_sets"]:
            raise ValueError(
                'Found image "%s" in this repository, but it cannot be rebuilt, because '
                'the "content_sets" are not set for this image.'
                % image["brew"]["build"]
            )

    def _get_repository_from_name(self, repo_name: str):
        """
        Returns the ContainerRepository object based on the Repository name.
        """
        repos = self.pyxis.find_repositories_by_repository_name(repo_name)

        if not repos:
            raise ValueError("Cannot get repository %s from Pyxis." % repo_name)

        if len(repos) != 1:
            raise ValueError(
                "Multiple records found in Pyxis for image repository %s." % repo_name
            )

        return repos[0]

    def _get_repository_from_image(self, image):
        """
        Returns the ContainerRepository object based on the image defined by the image NVR.
        """
        if "repositories" not in image or not image["repositories"]:
            raise ValueError("Cannot get repository for image %s from Pyxis." % image["brew"]["build"])

        repos = [repo for repo in image["repositories"] if repo["registry"] != "conf.image_build_repository_registries"]
        image_repo = repos[0]

        # returns a single repository
        return self.pyxis.get_repository_by_registry_path(image_repo["registry"], image_repo["repository"])

    def verify_image(self, image_nvr: str) -> dict[str, list[str]]:
        """
        Verifies the image defined by `image_nvr`.
        Raises ValueError in case of error.

        :param str image_nvr: NVR of image to verify.
        :rtype: dict
        :return: Dict with image NVR as key and list of content_sets as values.
        """
        images = self.pyxis.find_images_by_nvr(image_nvr)

        if not images:
            raise ValueError("No images found for the specified NVR")

        content_sets = set()
        for image in images:
            self._verify_image_data(image)
            content_sets.update(image["content_sets"])

        repo = self._get_repository_from_image(images[0])
        self._verify_repository_data(repo)

        return {images[0]["brew"]["build"]: sorted(content_sets)}

    def verify_repository(self, repo_name: str) -> DataElements:
        """
        Verifies the images in repository defined by `repo_name`.
        Raises ValueError in case of error.

        :param str repo_name: Name of repository to verify.
        :rtype: dict
        :return: A dict with "repository" and "images" as keys. "repository" is
        a dict with "auto_rebuild_tags" as key and list of auto rebuild tags as
        values. "images" is a dict with image NVR as key, value is a dict with
        tags and content_sets info.
        """
        repo = self._get_repository_from_name(repo_name)
        self._verify_repository_data(repo)

        data: DataElements = {
            "repository": {"auto_rebuild_tags": repo["auto_rebuild_tags"]},
            "images": {}
        }

        images = self.pyxis.find_images_by_repository(repo["repository"], repo["auto_rebuild_tags"])

        images_by_nvr: dict[str, dict[str, list[str]]] = {}
        for image in images:
            self._verify_image_data(image)
            nvr = image["brew"]["build"]
            images_by_nvr.setdefault(nvr, {"content_sets": [], "tags": []})
            # Image tags should be same for all architectures, just set it once
            if not images_by_nvr[nvr]["tags"]:
                for repodata in image["repositories"]:
                    if repodata["repository"] == repo_name:
                        images_by_nvr[nvr]["tags"] = [t["name"] for t in repodata["tags"]]
                        break
            for cs in image["content_sets"]:
                if cs not in images_by_nvr[nvr]["content_sets"]:
                    images_by_nvr[nvr]["content_sets"].append(cs)
            data["images"] = images_by_nvr

        if not data["images"]:
            raise ValueError(
                "No published images tagged by %r found in repository" % (repo["auto_rebuild_tags"])
            )

        return data
