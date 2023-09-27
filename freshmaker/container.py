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
import re

from typing import Any, Optional, Union

from freshmaker import conf, log
from freshmaker.kojiservice import KojiService, KojiLookupError
from freshmaker.odcsclient import create_odcs_client
from freshmaker.pyxis_gql import PyxisGQL


class ExtraRepoNotConfiguredError(ValueError):
    """Extra repo required but missing in config"""

    pass


class Container:
    def __new__(cls, *args, **kwargs):
        raise TypeError(
            f"Instances of {cls.__name__} should not be created using __init__. "
            f"Use {cls.__name__}.create_from_images instead."
        )

    def __init__(self, nvr: str):
        # Avoid direct instantiation with `Container(nvr)`, use create_from_images method instead
        self.nvr = nvr
        self.package = None

        self.parent_brew_build: Optional[str] = None
        self.published: Optional[bool] = None

        # Per-arch data
        self.content_sets_by_arch: dict[str, list[str]] = {}
        self.rpms_by_arch: dict[str, list[dict]] = {}

        self.parsed_data: Optional[dict[str, Any]] = None
        self.repositories: Optional[list[dict[str, Any]]] = None

        # Store build related metadata from Brew
        self.build_metadata: Optional[dict[str, Any]] = None

        # Store ODCS composes
        self.compose_sources: Optional[list[str]] = None

    @classmethod
    def create_from_images(cls, images: list[dict[str, Any]]):
        """Create an instance with the provided list of images"""
        nvrs = {x["brew"]["build"] for x in images}
        if len(nvrs) > 1:
            raise RuntimeError(
                "Images associated with a container should share the same build NVR. "
                f"The following NVRs are found: {', '.join(nvrs)}."
            )

        nvr = nvrs.pop()
        container = super().__new__(cls)
        container.__init__(nvr)  # type: ignore

        # Get the following data from the first image, they're same for all arches
        container.package = images[0]["brew"]["package"]
        container.parent_brew_build = images[0]["parent_brew_build"]
        container.repositories = images[0]["repositories"]

        # The `parsed_data` can contain arch-specific data, but what we'll consume later is
        # not arch-specific
        container.parsed_data = images[0]["parsed_data"]

        container.published = any(
            any(repo["published"] for repo in img["repositories"]) for img in images
        )

        # Store per-arch data for content_sets and rpms
        for image in images:
            arch = image["architecture"]
            container.content_sets_by_arch[arch] = image["content_sets"]

            rpms = image.get("edges", {}).get("rpm_manifest", {}).get("data", {}).get("rpms", None)
            if isinstance(rpms, list):
                container.rpms_by_arch[arch] = rpms

        return container

    @property
    def arches(self) -> list[str]:
        """All supported architectures"""
        return list(self.content_sets_by_arch.keys())

    @property
    def rpms(self) -> list[dict]:
        """RPMs for all architectures"""
        if not self.rpms_by_arch:
            return []

        all_rpms = [rpm for rpms in self.rpms_by_arch.values() for rpm in rpms]
        unique_rpms = {tuple(dct.items()) for dct in all_rpms}
        return [dict(rpm) for rpm in unique_rpms]

    def has_older_rpms(self, rpm_nvrs: list[str]) -> bool:
        """Check if container has any installed rpms is older than the provided NVRs

        :param str rpm_nvrs: List of rpm NVRs
        :return: True if container has older rpms installed than provided NVRs, otherwise False
        :rtype: bool
        """
        if not self.rpms:
            return False

        parsed_nvrs = [kobo.rpmlib.parse_nvr(nvr) for nvr in rpm_nvrs]

        for installed_rpm in self.rpms:
            parsed_installed_nvr = kobo.rpmlib.parse_nvra(installed_rpm["nvra"])

            for parsed_nvr in parsed_nvrs:
                if parsed_installed_nvr["name"] != parsed_nvr["name"]:
                    continue
                # If any installed rpm has lower NVR, return True
                if kobo.rpmlib.compare_nvr(parsed_installed_nvr, parsed_nvr) < 0:
                    return True
        return False

    def resolve_build_metadata(self, koji_session: KojiService) -> None:
        """
        Populates build metadata by querying Koji

        :param KojiService koji_session: koji session to connect
        """
        # This has been populated, skip.
        if getattr(self, "build_metadata", None) is not None:
            return

        self.build_metadata = {}

        build = koji_session.get_build(self.nvr)
        if not build:
            raise KojiLookupError(f"Cannot find koji build with NVR {self.nvr}")

        if "task_id" not in build or not build["task_id"]:
            task_id = build.get("extra", {}).get("container_koji_task_id", None)
            if task_id:
                build["task_id"] = task_id
            else:
                raise KojiLookupError(f"Cannot find build task id in koji build {build}")

        fs_koji_task_id = build.get("extra", {}).get("filesystem_koji_task_id")
        if fs_koji_task_id:
            self.build_metadata["filesystem_koji_task_id"] = fs_koji_task_id

        extra_image = build.get("extra", {}).get("image", {})
        # Get the list of ODCS composes used to build the image.
        if extra_image.get("odcs", {}).get("compose_ids"):
            self.build_metadata["odcs_compose_ids"] = extra_image["odcs"]["compose_ids"]

        self.build_metadata["parent_build_id"] = extra_image.get("parent_build_id")
        self.build_metadata["parent_image_builds"] = extra_image.get("parent_image_builds")

        flatpak = extra_image.get("flatpak", False)
        if flatpak:
            self.build_metadata["flatpak"] = flatpak

        brew_task = koji_session.get_task_request(build["task_id"])
        source = brew_task[0]
        self.build_metadata["target"] = brew_task[1]
        extra_data = brew_task[2]
        if "git_branch" in extra_data:
            self.build_metadata["git_branch"] = extra_data["git_branch"]
        else:
            self.build_metadata["git_branch"] = "unknown"

        # Some builds do not have "source" attribute filled in, so try
        # both build["source"] and task_request[0] sources.
        sources = [source]
        if "source" in build:
            sources.insert(0, build["source"])
        for src in sources:
            m = re.match(r".*/(?P<namespace>.*)/(?P<container>.*)#(?P<commit>.*)", src)
            if m:
                namespace = m.group("namespace")
                # For some Koji tasks, the container part ends with "?" in
                # source URL. This is just because some custom scripts for
                # submitting those builds include this character in source URL
                # to mark the query part of URL. We need to handle that by
                # stripping that character.
                container_name = m.group("container").rstrip("?")
                self.build_metadata["repository"] = namespace + "/" + container_name

                # There might be tasks which have branch name in
                # "origin/branch_name" format, so detect it set commit
                # hash only if this is not true.
                if "/" not in m.group("commit"):
                    self.build_metadata["commit"] = m.group("commit")
                    break

        if not self.build_metadata["commit"]:
            raise KojiLookupError("Cannot find valid source of Koji build %r" % build)

        if not conf.supply_arch_overrides:
            self.build_metadata["arches"] = None
        else:
            self.build_metadata["arches"] = koji_session.get_build_arches(build["build_id"])

    def resolve_compose_sources(self):
        """Get source values of ODCS composes used in image build task"""
        # This has been populated, skip.
        if getattr(self, "compose_sources", None) is not None:
            return

        self.compose_sources = []
        odcs_client = create_odcs_client()
        compose_ids = self.build_metadata.get("odcs_compose_ids")
        if not compose_ids:
            return

        compose_sources = set()
        for compose_id in compose_ids:
            # Get odcs compose source value from odcs server
            compose = odcs_client.get_compose(compose_id)
            source = compose.get("source", "")
            if source:
                compose_sources.update(source.split())

        self.compose_sources = list(compose_sources)
        log.info("Container %s uses following compose sources: %r", self.nvr, self.compose_sources)

    def resolve(self, pyxis_instance: PyxisGQL, koji_session: KojiService) -> None:
        """
        Resolves the container - populates additional metadata by
        querying Pyxis and Koji

        :param PyxisGQL pyxis_instance: Pyxis instance to connect
        :param KojiService koji_session: Koji session to connect
        """
        self.resolve_build_metadata(koji_session)
        self.resolve_compose_sources()

    def resolve_content_sets(
        self, pyxis_instance: PyxisGQL, koji_session: KojiService, children=None
    ):
        """Resolve each child in children if content_sets_by_arch is not set"""
        if self.content_sets_by_arch:
            log.info(
                "Container image %s uses following content sets: %r",
                self.nvr,
                self.content_sets_by_arch,
            )
            return
        if not children:
            return

        for child in children:
            if not child.content_sets_by_arch:
                child.resolve(pyxis_instance, koji_session)
            if not child.content_sets_by_arch:
                continue

            log.info(
                "Container image %s does not have 'content-sets' set "
                "in Pyxis. Using child image %s content_sets: %r",
                self.nvr,
                child.nvr,
                child.content_sets_by_arch,
            )
            self.content_sets_by_arch = child.content_sets_by_arch
            return

        log.warning(
            "Container image %s does not have 'content_sets' set in Pyxis as well "
            "as its children, this is suspicious.",
            self.nvr,
        )


class ContainerAPI:
    def __init__(self, pyxis_graphql_url: str, cert: Union[str, tuple[str, str]]):
        self.pyxis = PyxisGQL(url=pyxis_graphql_url, cert=cert)

    def find_auto_rebuild_containers_with_older_rpms(
        self,
        rpm_nvrs: list[str],
        content_sets: list[str],
        published: bool = True,
        release_categories: Optional[list[str]] = None,
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

        images_by_nvr: dict[str, list[dict[str, Any]]] = {}
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
            # Create Container instance with the images data
            container = Container.create_from_images(images)
            containers.append(container)

        # Filter out images which don't have older rpms installed
        containers = list(filter(lambda x: x.has_older_rpms(rpm_nvrs), containers))
        return containers
