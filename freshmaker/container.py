# -*- coding: utf-8 -*-
# Copyright (c) 2022  Red Hat, Inc.
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

import kobo.rpmlib

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Union, Tuple

from freshmaker import conf
from freshmaker.pyxis_gql import PyxisGQL


@dataclass
class Container:
    # Image NVR
    nvr: str

    parsed_data: dict = field(repr=False, default_factory=dict)
    repositories: List[Dict[str, Any]] = field(repr=False, default_factory=list)
    parent_brew_build: Optional[str] = field(repr=False, default=None)

    # Content sets by architechure
    content_sets_by_arch: Dict[str, List[str]] = field(repr=False, default_factory=dict)
    # Installed rpms without architechure info
    rpms: Optional[List[Dict[str, Any]]] = field(repr=False, default=None)

    @classmethod
    def load(cls, data: Dict[str, Any]):
        """Load container data from given image data"""
        container = cls(data["brew"]["build"])

        exclude_fields = ["nvr", "content_sets_by_arch", "rpms"]
        defined_fields = set(f.name for f in fields(cls) if f.name not in exclude_fields)

        container.content_sets_by_arch[data["architecture"]] = data["content_sets"]
        rpms = data.get("edges", {}).get("rpm_manifest", {}).get("data", {}).get("rpms", None)
        if isinstance(rpms, list):
            container.rpms = []
            # We don't care about rpm architecture, just keep NVR
            for rpm in rpms:
                parsed_nvra = kobo.rpmlib.parse_nvra(rpm["nvra"])
                nvr = "-".join(
                    [parsed_nvra["name"], parsed_nvra["version"], parsed_nvra["release"]]
                )
                parsed_nvra = kobo.rpmlib.parse_nvra(rpm["srpm_nevra"])
                srpm_nvr = "-".join(
                    [parsed_nvra["name"], parsed_nvra["version"], parsed_nvra["release"]]
                )
                container.rpms.append(
                    {
                        "name": rpm["name"],
                        "nvr": nvr,
                        "srpm_name": rpm["srpm_name"],
                        "srpm_nvr": srpm_nvr,
                    }
                )

        for name, value in data.items():
            if name not in defined_fields:
                # Silently ignore unknown fields
                continue
            setattr(container, name, value)
        return container

    @property
    def arches(self) -> list[str]:
        """All supported architectures"""
        return list(self.content_sets_by_arch.keys())

    def add_arch(self, data: Dict[str, Any]) -> None:
        """Update container data to add arch specific data for other arches.

        :param dict data: data for an arch specific image
        """
        if data["architecture"] not in self.arches:
            self.content_sets_by_arch[data["architecture"]] = data["content_sets"]

    def as_dict(self) -> Dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def has_older_rpms(self, rpm_nvrs: List[str]) -> bool:
        """Check if container has any installed rpms is older than the provided NVRs

        :param str rpm_nvrs: List of rpm NVRs
        :return: True if container has older rpms installed than provided NVRs, otherwise False
        :rtype: bool
        """
        if self.rpms is None:
            return False

        for rpm in self.rpms:
            installed_nvr = kobo.rpmlib.parse_nvr(rpm["nvr"])
            if any(
                kobo.rpmlib.compare_nvr(installed_nvr, kobo.rpmlib.parse_nvr(nvr)) < 0
                for nvr in rpm_nvrs
            ):
                return True
        return False


class ContainerAPI:
    def __init__(self, pyxis_graphql_url: str, pyxis_cert: Union[str, Tuple[str]]):
        self.pyxis = PyxisGQL(url=pyxis_graphql_url, cert=pyxis_cert)

    def find_auto_rebuild_containers_with_older_rpms(
        self,
        rpm_nvrs: List[str],
        content_sets: List[str],
        published: bool = True,
        release_categories: Optional[List[str]] = None,
    ):
        """Find images which have older NVRs of the provided rpms installed

        :param list rpm_nvrs: List of rpm NVRs
        :param list content_sets: List of content sets enabled in image
        :param bool published: Published attribution of container
        :param list release_categories: List of image release categories
        """
        repositories = self.pyxis.find_repositories(
            published=True, release_categories=release_categories
        )

        # Exclude repositories which don't have any auto-rebuild tag
        repositories = [r for r in repositories if r["auto_rebuild_tags"]]

        # Find out images that have the related rpms installed and tagged with any of
        # the auto-rebuild tags, we can't get images only tagged with the corresponding
        # auto-rebuilds tags in each repository from Pyxis server, we will need to check
        # that from client side later.
        rpm_names = list({kobo.rpmlib.parse_nvr(rpm_nvr)["name"] for rpm_nvr in rpm_nvrs})

        auto_rebuild_tags = set()
        for repo in repositories:
            auto_rebuild_tags |= set(repo["auto_rebuild_tags"])

        repos_by_path = {r["repository"]: r for r in repositories}
        images = self.pyxis.find_images_by_installed_rpms(
            rpm_names,
            content_sets=content_sets,
            repositories=list(repos_by_path.keys()),
            published=published,
            tags=list(auto_rebuild_tags),
        )

        images_by_nvr: Dict[str, List[Dict[str, Any]]] = {}
        # Filter images to keep images which are only tagged with the auto-rebuild tags
        # in its repository
        for image in images:
            image_nvr = image["brew"]["build"]
            if image_nvr in images_by_nvr:
                # Just add this image if it has been in the result with other arches
                images_by_nvr[image_nvr].append(image)
                continue

            for repository in image["repositories"]:
                repo_path = repository["repository"]

                if repo_path not in repos_by_path:
                    continue

                # Skip internal build repositories
                if repository["registry"] in conf.image_build_repository_registries:
                    continue

                image_tags = set(tag["name"] for tag in repository["tags"])
                rebuild_tags = set(repos_by_path[repo_path]["auto_rebuild_tags"])

                # Skip if image is not tagged with any auto-rebuild tags in this repo
                if not image_tags & rebuild_tags:
                    continue

                images_by_nvr.setdefault(image_nvr, []).append(image)
                # No necessary to check other repositories if this image is tagged with
                # auto-rebuild tags in one of its repositories
                break

        containers = []
        for nvr, images in images_by_nvr.items():
            # Create a ContainerImage instance with the first architecture image data
            image = Container.load(images[0])
            # Update the instance to add data for other arches
            for img in images[1:]:
                image.add_arch(img)

            containers.append(image)

        # Filter out images which don't have older rpms installed
        containers = list(filter(lambda x: x.has_older_rpms(rpm_nvrs), containers))
        return containers
