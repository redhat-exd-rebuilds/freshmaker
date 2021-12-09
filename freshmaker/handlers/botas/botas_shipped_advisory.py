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
import copy
import json
from datetime import datetime
import re

import koji
from kobo.rpmlib import parse_nvr
import semver

from freshmaker import db, conf, log
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import BotasErrataShippedEvent, ManualBundleRebuildEvent
from freshmaker.lightblue import ContainerImage
from freshmaker.models import ArtifactBuild, ArtifactType, Event
from freshmaker.types import EventState, ArtifactBuildState, RebuildReason
from freshmaker.pyxis import Pyxis
from freshmaker.kojiservice import KojiService
from freshmaker.errata import Errata


class HandleBotasAdvisory(ContainerBuildHandler):
    """
    Handles event that was created by transition of an advisory filed by
    BOTAS to SHIPPED_LIVE state
    """

    name = "HandleBotasAdvisory"

    def __init__(self, pyxis=None):
        super().__init__()
        if pyxis:
            self._pyxis = pyxis
        else:
            if not conf.pyxis_server_url:
                raise ValueError("'PYXIS_SERVER_URL' parameter should be set")
            self._pyxis = Pyxis(conf.pyxis_server_url)

        if not conf.freshmaker_root_url or "://" not in conf.freshmaker_root_url:
            raise ValueError("'FRESHMAKER_ROOT_URL' parameter should be set to a valid URL")
        # Currently processed event
        self.event = None

    def can_handle(self, event):
        if isinstance(event, BotasErrataShippedEvent) and "docker" in event.advisory.content_types:
            return True
        # This handler can handle manual bundle rebuilds too
        if isinstance(event, ManualBundleRebuildEvent):
            return True

        return False

    def handle(self, event):
        if event.dry_run:
            self.force_dry_run()
        self.event = event

        self.db_event = Event.get_or_create_from_event(db.session, event)

        self.set_context(self.db_event)

        # Check if event is allowed by internal policies
        if not self.event.is_allowed(self):
            msg = f"This event is not allowed by internal policy. message_id: {event.msg_id}"
            log.info(msg)
            self.db_event.transition(EventState.SKIPPED, msg)
            return []

        bundles_to_rebuild, reason = self._get_bundles_to_rebuild()
        if not bundles_to_rebuild:
            msg = reason or f"No bundles to rebuild for advisory {self.event.advisory.errata_id}"
            log.info(msg)
            self.db_event.transition(EventState.SKIPPED, msg)
            return []

        builds = self._prepare_builds(bundles_to_rebuild)

        # Reset context to db_event.
        self.set_context(self.db_event)

        self.start_to_build_images(builds)
        if all([b.state == ArtifactBuildState.FAILED.value for b in builds]):
            self.db_event.transition(EventState.FAILED, "All bundle rebuilds failed")
        else:
            msg = (
                f"Advisory {self.db_event.search_key}: Rebuilding "
                f"{len(self.db_event.builds.all())} bundle images."
            )
            self.db_event.transition(EventState.BUILDING, msg)

        return []

    def _get_bundles_to_rebuild(self):
        """ Get the impacted bundle to rebuild

        :return: a tuple of bundles and reason
        :rtype: tuple ([dict], str)
        """
        # This returns a tuple of two elements, the first one is a list of bundles,
        # each bundle is a dict with keys of bundle NVR, pullspec_replacements and
        # CSV update data. The second one is a reason string, which will be set
        # when no bundle is found for rebuild.
        #
        # Example bundle dict:
        #   {
        #       "nvr": "foobar-bundle-1-123",
        #       "pullspec_replacements": [
        #           {
        #               "new": "registry/repo/foobar@sha256:value",
        #               "original": "registry/repo/foobar:v2.2.0",
        #               "pinned": True,
        #           }
        #       ],
        #       "update": {
        #           "metadata": {
        #               "name": "foobar.1-123.1608854400.p",
        #               "annotations": {"olm.substitutesFor": "foobar-1.2.3"},
        #           },
        #           "spec": {"version": "1.2.3+0.1608854400.p"},
        #       }
        #   }

        # Mapping of original operator/operand build NVRs to rebuilt NVRs in advisory
        log.debug("Getting NVR mapping of original images to rebuilt images")
        nvrs_mapping = self._create_original_to_rebuilt_nvrs_map()

        original_nvrs = nvrs_mapping.keys()
        if not original_nvrs:
            return None, "Can't find any published original builds for images in advisory."

        log.info(
            "Orignial NVRs of build in advisory %s are: %s",
            self.event.advisory.errata_id,
            " ".join(original_nvrs),
        )

        # Get image manifest_list_digest for all original images, manifest_list_digest is used
        # in pullspecs in bundle's related images
        original_digests_by_nvr = {}
        original_nvrs_by_digest = {}
        for nvr in original_nvrs:
            log.debug("Getting manifest_list_digest of image: %s", nvr)
            digest = self._pyxis.get_manifest_list_digest_by_nvr(nvr)
            if digest:
                original_digests_by_nvr[nvr] = digest
                original_nvrs_by_digest[digest] = nvr
            else:
                log.warning(
                    f"Image manifest_list_digest not found for original image {nvr} in Pyxis, "
                    "skip this image"
                )

        if not original_digests_by_nvr:
            return (
                None,
                f"None of the original images have digests in Pyxis: {','.join(original_nvrs)}",
            )

        # Get image manifest_list_digest for all rebuilt images, manifest_list_digest is used
        # in pullspecs of bundle's related images
        rebuilt_digests_by_nvr = {}
        rebuilt_nvrs = nvrs_mapping.values()
        for nvr in rebuilt_nvrs:
            # Don't require that the manifest list digest be published in this case because
            # there's a delay from after an advisory is shipped and when the published repositories
            # entry is populated
            log.debug("Getting manifest_list_digest of image: %s", nvr)
            digest = self._pyxis.get_manifest_list_digest_by_nvr(nvr, must_be_published=False)
            if digest:
                rebuilt_digests_by_nvr[nvr] = digest
            else:
                log.warning(
                    f"Image manifest_list_digest not found for rebuilt image {nvr} in Pyxis, "
                    "skip this image"
                )

        if not rebuilt_digests_by_nvr:
            return [], f"None of the rebuilt images have digests in Pyxis: {','.join(rebuilt_nvrs)}"

        bundle_nvrs = []
        check_auto_rebuild_tags = True
        if hasattr(self.event, "container_images") and self.event.container_images:
            # For bundles specified explicitly in manual request, consider them as
            # impacted at this moment, will check related images later to determine
            # whether they're impacted by the advisory
            # These specified container images can be unpublished, so don't check
            # the auto rebuild tags
            check_auto_rebuild_tags = False
            for bundle_nvr in self.event.container_images:
                if not self._pyxis.is_bundle(bundle_nvr):
                    log.error("Image %s is not an operator bundle, skip it.", bundle_nvr)
                    continue
                bundle_nvrs.append(bundle_nvr)
        else:
            # Get impacted bundles from Pyxis, they include the digests of original
            # images in related images
            bundle_nvrs = self._get_impacted_bundles(original_digests_by_nvr.values())

        if not bundle_nvrs:
            return None, f"No bundle image is impacted by {self.event.advisory.errata_id}, skip."

        for bundle_nvr in bundle_nvrs[:]:
            # Filter out builds from dependent event that were rebuilt successfully before
            done_build = self.db_event.get_artifact_build_from_event_dependencies(bundle_nvr)
            if done_build:
                log.debug(
                    "Ignoring bundle %s, because it was already rebuilt in dependent events",
                    bundle_nvr,
                )
                bundle_nvrs.remove(bundle_nvr)

        if not bundle_nvrs:
            return None, "All bundles have been rebuilt successfully by dependent events, skip."

        # Unauthenticated koji session to fetch build info of bundles
        koji_api = KojiService(conf.koji_profile)

        bundles_by_nvr = {}
        for bundle_nvr in bundle_nvrs:
            images = self._pyxis.get_images_by_nvr(bundle_nvr)
            if not images:
                log.warning("Image %s is not found in Pyxis, ignore it.", bundle_nvr)
                continue

            if check_auto_rebuild_tags and not self.image_has_auto_rebuild_tag(images[0]):
                log.warning("Image %s is not tagged with auto-rebuild tags", bundle_nvr)
                continue

            related_images = koji_api.get_bundle_related_images(bundle_nvr)
            if not related_images.get("created_by_osbs", False):
                log.warning("Image %s is not using OSBS pinning, skip it.")
                continue

            pullspecs = related_images.get("pullspecs", [])
            if not pullspecs:
                log.warning("Image %s doesn't have pullspecs data in brew, skip it")
                continue

            pullspec_replacements = copy.deepcopy(pullspecs)
            pullspec_updated = False
            for pullspec in pullspec_replacements:
                # A pullspec path is in format of "registry/repository@digest"
                pullspec_elems = pullspec.get("new").split("@")
                old_digest = pullspec_elems[1]
                if old_digest not in original_nvrs_by_digest:
                    # This related image is not one of the original images
                    continue

                old_nvr = original_nvrs_by_digest[old_digest]
                new_nvr = nvrs_mapping[old_nvr]
                new_digest = rebuilt_digests_by_nvr[new_nvr]

                old_pullspec = pullspec.get("new")

                # Replace the old digest with new digest
                pullspec_elems[1] = new_digest
                new_pullspec = "@".join(pullspec_elems)
                pullspec["new"] = new_pullspec
                # Always set pinned to True when it was replaced by Freshmaker
                # since it indicates that the pullspec was modified from the
                # original pullspec
                pullspec["pinned"] = True

                log.info(
                    "Bundle %s: changing pullspec %r to %r", bundle_nvr, old_pullspec, new_pullspec
                )
                pullspec_updated = True

            if pullspec_updated:
                bundles_by_nvr[bundle_nvr] = {"pullspec_replacements": pullspec_replacements}

        if not bundles_by_nvr:
            return None, f"No bundle image is impacted by {self.event.advisory.errata_id}, skip."

        # Add olm.substitutesFor annotation by default, unless it's disabled in manual
        # request metadata.
        olm_substitutes = self.db_event.requester_metadata_json.get("olm_substitutes", True)
        bundles_to_rebuild = []
        for bundle_nvr, bundle_data in bundles_by_nvr.items():
            bundle_data["nvr"] = bundle_nvr
            csv_name, version = self._get_bundle_csv_name_and_version(bundle_nvr)
            if not (csv_name and version):
                log.error("CSV data is missing for bundle %s, skip it.", bundle_nvr)
                continue
            bundle_data.update(
                self._get_csv_updates(csv_name, version, olm_substitutes=olm_substitutes)
            )
            bundles_to_rebuild.append(bundle_data)
        if not bundles_to_rebuild:
            return (
                None,
                f"CSV data is not available for impacted bundles: {','.join(bundles_by_nvr.keys())}, skip.",
            )

        return bundles_to_rebuild, None

    def _get_impacted_bundles(self, related_digests):
        """
        Get impacted bundles which include the related digests (in related_images)

        :param list related_digests: list of digests
        :param list bundle_nvrs: list of bundle NVRs
        :return: list of impacted bundle NVRs
        :rtype: list
        """
        impacted_bundles = set()
        index_paths = self._pyxis.get_index_paths()
        for digest in related_digests:
            log.debug("Finding bundles by related image digest: %s", digest)
            bundles = self._pyxis.get_bundles_by_related_image_digest(digest, index_paths)
            if not bundles:
                log.info("No latest bundle found with the related digest: %s", digest)
                continue
            for bundle in bundles:
                bundle_images = self._pyxis.get_images_by_digest(bundle["bundle_path_digest"])
                if not bundle_images:
                    log.error(
                        "Image not found with bundle path digest: %s, ignore it.",
                        bundle["bundle_path_digest"],
                    )
                bundle_nvr = bundle_images[0]["brew"]["build"]
                log.debug("Found impacted bundle: %s", bundle_nvr)
                impacted_bundles.add(bundle_nvr)

        return list(impacted_bundles)

    def _get_bundle_csv_name_and_version(self, bundle_nvr):
        """
        Get bundle image's CSV name and version

        :param str bundle_nvr: NVR of bundle image
        :return: a tuple of bundle image's CSV name and version
        :rtype: tuple
        """
        csv_name = version = None
        bundles = self._pyxis.get_bundles_by_nvr(bundle_nvr)
        if bundles:
            csv_name = bundles[0]["csv_name"]
            version = bundles[0]["version_original"]
        else:
            # Bundle data not in Pyxis, probably this is an unreleased bundle,
            # try to get the data from brew
            log.debug(
                "Can't find bundle data of %s in Pyxis, trying to find that in brew.", bundle_nvr
            )
            koji_api = KojiService(conf.koji_profile)
            csv_data = koji_api.get_bundle_csv(bundle_nvr)
            # this should not happen
            if not csv_data:
                log.error("Bundle data of %s is not available in brew.", bundle_nvr)
            else:
                csv_name = csv_data["metadata"]["name"]
                version = csv_data["spec"]["version"]
        return (csv_name, version)

    @classmethod
    def _get_csv_updates(cls, csv_name, version, olm_substitutes=True):
        """
        Determine the CSV updates required for the bundle image.

        :param str csv_name: the name field in the bundle's ClusterServiceVersion file
        :param str version: the version of the bundle image being rebuilt
        :param bool olm_substitutes: add `olm.substitutesFor` annotation if True
        :return: a dictionary of the CSV updates needed
        :rtype: dict
        """
        csv_modifications = {}
        new_version, fm_suffix = cls._get_rebuild_bundle_version(version)
        new_csv_name = cls._get_csv_name(csv_name, version, new_version, fm_suffix)
        csv_modifications["update"] = {
            "metadata": {
                # Update the name of the CSV to something uniquely identify the rebuild
                "name": new_csv_name,
            },
            "spec": {
                # Update the version of the rebuild to be unique and a newer version than the
                # the version of the bundle being rebuilt
                "version": new_version,
            },
        }
        if olm_substitutes:
            # Declare that this rebuild is a substitute of the bundle being rebuilt
            csv_modifications["update"]["metadata"]["annotations"] = {
                "olm.substitutesFor": csv_name
            }

        return csv_modifications

    @classmethod
    def _get_rebuild_bundle_version(cls, version):
        """
        Get a bundle version for the Freshmaker rebuild of the bundle image.

        Examples:
            1.2.3 => 1.2.3+0.$timestamp.p (no build ID and not a rebuild)
            1.2.3+48273 => 1.2.3+48273.0.$timestamp.p (build ID and not a rebuild)
            1.2.3+48273.0.1616457250.p => 1.2.3+48273.0.$timestamp.p (build ID and a rebuild)

        :param str version: the version of the bundle image being rebuilt
        :return: a tuple of the bundle version of the Freshmaker rebuild of the bundle image and
            the suffix that was added by Freshmaker
        :rtype: tuple(str, str)
        """
        parsed_version = semver.VersionInfo.parse(version)
        # Strip off the microseconds of the timestamp
        timestamp = int(datetime.utcnow().timestamp())
        new_fm_suffix = f"0.{timestamp}.p"
        if parsed_version.build:
            # Check if the bundle was a Freshmaker rebuild. Include .patched
            # for backwards compatibility with the old suffix.
            fm_suffix_search = re.search(
                r"(?P<fm_suffix>0\.\d+\.(?:p|patched))$", parsed_version.build
            )
            if fm_suffix_search:
                fm_suffix = fm_suffix_search.groupdict()["fm_suffix"]
                # Get the build without the Freshmaker suffix. This may include a build ID
                # from the original build before Freshmaker rebuilt it or be empty.
                build_wo_fm_suffix = parsed_version.build[: -len(fm_suffix)]
                new_build = f"{build_wo_fm_suffix}{new_fm_suffix}"
            else:
                # This was not previously rebuilt by Freshmaker so just append the suffix
                # to the existing build ID with '.' separating it.
                new_build = f"{parsed_version.build}.{new_fm_suffix}"
        else:
            # If there is existing build ID, then make the Freshmaker suffix the build ID
            new_build = new_fm_suffix

        # Don't use the replace method in order to support semver 2.8.1
        new_version_dict = parsed_version._asdict()
        new_version_dict["build"] = new_build
        new_version = str(semver.VersionInfo(**new_version_dict))

        return new_version, new_fm_suffix

    @staticmethod
    def _get_csv_name(csv_name, version, rebuild_version, fm_suffix):
        """
        Get a bundle CSV name for the Freshmaker rebuild of the bundle image.

        :param str csv_name: the name of the ClusterServiceVersion (CSV) file of the bundle image
        :param str version: the version of the bundle image being rebuilt
        :param str rebuild_version: the new version being assigned by Freshmaker for the rebuild
        :param str fm_suffix: the portion of rebuild_version that was generated by Freshmaker
        :return: the bundle ClusterServiceVersion (CSV) name of the Freshmaker rebuild of the bundle
            image
        :rtype: str
        """
        # The CSV name must be in the format of a valid DNS name, which means the + from the
        # build ID must be replaced. In the event this was a previous Freshmaker rebuild, version
        # may have a build ID that would be the DNS safe version in the CSV name.
        dns_safe_version = version.replace("+", "-")
        if dns_safe_version in csv_name:
            dns_safe_rebuild_version = rebuild_version.replace("+", "-")
            return csv_name.replace(dns_safe_version, dns_safe_rebuild_version)
        else:
            return f"{csv_name}.{fm_suffix}"

    def get_published_original_nvr(self, rebuilt_nvr):
        """
        Search for an original build, that has been built and published to a
            repository, and get original_nvr from it

        :param str rebuilt_nvr: rebuilt NVR to look build by
        :rtype: str or None
        :return: original NVR from the first published FM build for given NVR
        """
        original_nvr = None
        # artifact build should be only one in database, or raise an error
        artifact_build = (
            db.session.query(ArtifactBuild)
            .filter(
                ArtifactBuild.rebuilt_nvr == rebuilt_nvr,
                ArtifactBuild.type == ArtifactType.IMAGE.value,
            )
            .one_or_none()
        )
        # recursively search for original artifact build
        if artifact_build is not None:
            original_nvr = artifact_build.original_nvr

            # check if image is published
            request_params = {"include": "data.repositories", "page_size": 1}
            images = self._pyxis._pagination(f"images/nvr/{original_nvr}", request_params)
            if not images:
                return None
            # stop recursion if the image is published in some repo
            if any(repo["published"] for repo in images[0].get("repositories")):
                return original_nvr

            next_nvr = self.get_published_original_nvr(original_nvr)
            if next_nvr is not None:
                original_nvr = next_nvr

        return original_nvr

    def image_has_auto_rebuild_tag(self, image):
        """Check if image has a tag enabled for auto rebuild.

        :param dict image: Dict representation of an image entity in Pyxis.
        :rtype: bool
        :return: True if image has a tag enabled for auto rebuild in repository, otherwise False.
        """
        for repo in image["repositories"]:
            # Skip unpublished repository
            if not repo["published"]:
                continue

            auto_rebuild_tags = self._pyxis.get_auto_rebuild_tags(
                repo["registry"], repo["repository"]
            )
            tags = [t["name"] for t in repo.get("tags", [])]
            if set(auto_rebuild_tags) & set(tags):
                return True

        # It'd be more efficient to do this check first, but the exceptions are edge cases
        # (e.g. testing) and it's best to not use it unless absolutely necessary
        nvr = image["brew"]["build"]
        parsed_nvr = parse_nvr(nvr)
        nv = f'{parsed_nvr["name"]}-{parsed_nvr["version"]}'
        if nv in conf.bundle_autorebuild_tag_exceptions:
            self.log_info(
                "The bundle %r has an exception for being tagged with an auto-rebuild tag", nvr
            )
            return True

        return False

    def _create_original_to_rebuilt_nvrs_map(self):
        """
        Creates mapping of original operator build NVRs to rebuilt NVRs in advisory.
        Including NVRs of the builds from the blocking advisories

        :rtype: dict
        :return: map of the original NVRs as keys and rebuilt NVRs as values
        """
        nvrs_mapping = {}

        # Get builds from all blocking advisories
        blocking_advisories_builds = Errata().get_blocking_advisories_builds(
            self.event.advisory.errata_id
        )
        # Get builds NVRs from the advisory attached to the message/event and
        # then get original NVR for every build
        for product_info in self.event.advisory.builds.values():
            for build in product_info["builds"]:
                # Each build is a one key/value pair, and key is the build NVR
                build_nvr = next(iter(build))

                log.debug("Getting published original image of %s", build_nvr)
                # Search for the first build that triggered the chain of rebuilds
                # for every shipped NVR to get original NVR from it
                original_nvr = self.get_published_original_nvr(build_nvr)
                if original_nvr is None:
                    continue
                nvrs_mapping[original_nvr] = build_nvr
                parsed_build_nvr = parse_nvr(build_nvr)

                # Check builds from blocking advisories and add to the mapping
                # all of them, that have overlapping package names
                for block_build in blocking_advisories_builds:
                    block_build_nvr = parse_nvr(block_build)
                    if (
                        block_build_nvr["name"] == parsed_build_nvr["name"]
                        and block_build_nvr["version"] == parsed_build_nvr["version"]  # noqa: W503
                    ):
                        nvrs_mapping[block_build] = build_nvr
        return nvrs_mapping

    def _prepare_builds(self, to_rebuild_bundles):
        """
        Prepare models.ArtifactBuild instance for every bundle that will be
        rebuilt

        :param list to_rebuild_bundles: bundles to rebuild
        :return: builds that already in database and ready to be submitted to brew
        :rtype: list
        """
        builds = []
        csv_mod_url = conf.freshmaker_root_url + "/api/2/pullspec_overrides/{}"
        for bundle in to_rebuild_bundles:
            # Reset context to db_event for each iteration before
            # the ArtifactBuild is created.
            self.set_context(self.db_event)

            rebuild_reason = RebuildReason.DIRECTLY_AFFECTED.value
            bundle_name = koji.parse_NVR(bundle["nvr"])["name"]

            build = self.record_build(
                self.db_event,
                bundle_name,
                ArtifactType.IMAGE,
                state=ArtifactBuildState.PLANNED.value,
                original_nvr=bundle["nvr"],
                rebuild_reason=rebuild_reason,
            )

            # Set context to particular build so logging shows this build
            # in case of error.
            self.set_context(build)

            build.transition(ArtifactBuildState.PLANNED.value, "")

            additional_data = ContainerImage.get_additional_data_from_koji(bundle["nvr"])
            build.build_args = json.dumps(
                {
                    "repository": additional_data["repository"],
                    "commit": additional_data["commit"],
                    "target": additional_data["target"],
                    "branch": additional_data["git_branch"],
                    "arches": additional_data["arches"],
                    # The build system always enforces that bundle images build from
                    # "scratch", so there is no parent image. See:
                    # https://osbs.readthedocs.io/en/latest/users.html?#operator-manifest-bundle-builds
                    "original_parent": None,
                    "operator_csv_modifications_url": csv_mod_url.format(build.id),
                }
            )
            build.bundle_pullspec_overrides = {
                "pullspec_replacements": bundle["pullspec_replacements"],
                "update": bundle["update"],
            }

            db.session.commit()
            builds.append(build)
        return builds
