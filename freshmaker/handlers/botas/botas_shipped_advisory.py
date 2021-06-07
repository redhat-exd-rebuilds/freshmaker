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
from freshmaker.events import BotasErrataShippedEvent, ManualBundleRebuild
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
    # This prefix should be added to event reason, when skipping the event.
    # Because Release Driver checks event's reason for certain prefixes,
    # to determine if there is an error in bundles processing.
    _no_bundle_prefix = "No bundles to rebuild: "

    def __init__(self, pyxis=None):
        super().__init__()
        if pyxis:
            self._pyxis = pyxis
        else:
            if not conf.pyxis_server_url:
                raise ValueError("'PYXIS_SERVER_URL' parameter should be set")
            self._pyxis = Pyxis(conf.pyxis_server_url)

        if not conf.freshmaker_root_url or "://" not in conf.freshmaker_root_url:
            raise ValueError("'FRESHMAKER_ROOT_URL' parameter should be set to "
                             "a valid URL")
        # Currently processed event
        self.event = None

    def can_handle(self, event):
        if (isinstance(event, BotasErrataShippedEvent) and
                'docker' in event.advisory.content_types):
            return True
        # This handler can handle manual bundle rebuilds too
        if isinstance(event, ManualBundleRebuild):
            return True

        return False

    def handle(self, event):
        if event.dry_run:
            self.force_dry_run()
        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)

        self.set_context(db_event)

        # Check if event is allowed by internal policies
        if not self.event.is_allowed(self):
            msg = ("This image rebuild is not allowed by internal policy. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            self.log_info(msg)
            return []

        if isinstance(event, ManualBundleRebuild):
            bundles_to_rebuild = self._handle_manual_rebuild(db_event)
        else:
            bundles_to_rebuild = self._handle_auto_rebuild(db_event)

        if not bundles_to_rebuild:
            return []

        builds = self._prepare_builds(db_event, bundles_to_rebuild)

        # Reset context to db_event.
        self.set_context(db_event)

        self.start_to_build_images(builds)
        msg = f"Advisory {db_event.search_key}: Rebuilding " \
              f"{len(db_event.builds.all())} bundle images."
        db_event.transition(EventState.BUILDING, msg)

        return []

    def _handle_auto_rebuild(self, db_event):
        """
        Handle auto rebuild for an advisory created by Botas

        :param db_event: database event that represent rebuild event
        :rtype: list
        :return: list of advisories that should be rebuilt
        """
        # Mapping of original build nvrs to rebuilt nvrs in advisory
        nvrs_mapping = self._create_original_to_rebuilt_nvrs_map()

        original_nvrs = nvrs_mapping.keys()
        self.log_info(
            "Orignial nvrs of build in the advisory #{0} are: {1}".format(
                self.event.advisory.errata_id, " ".join(original_nvrs)))

        # Get image manifest_list_digest for all original images, manifest_list_digest is used
        # in pullspecs in bundle's related images
        original_digests_by_nvr = {}
        original_nvrs_by_digest = {}
        for nvr in original_nvrs:
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
            msg = f"None of the original images have digests in Pyxis: {','.join(original_nvrs)}"
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []

        # Get image manifest_list_digest for all rebuilt images, manifest_list_digest is used
        # in pullspecs of bundle's related images
        rebuilt_digests_by_nvr = {}
        rebuilt_nvrs = nvrs_mapping.values()
        for nvr in rebuilt_nvrs:
            # Don't require that the manifest list digest be published in this case because
            # there's a delay from after an advisory is shipped and when the published repositories
            # entry is populated
            digest = self._pyxis.get_manifest_list_digest_by_nvr(nvr, must_be_published=False)
            if digest:
                rebuilt_digests_by_nvr[nvr] = digest
            else:
                log.warning(
                    f"Image manifest_list_digest not found for rebuilt image {nvr} in Pyxis, "
                    "skip this image"
                )

        if not rebuilt_digests_by_nvr:
            msg = f"None of the rebuilt images have digests in Pyxis: {','.join(rebuilt_nvrs)}"
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []

        index_images = self._pyxis.get_operator_indices()
        # get latest bundle images per channel per index image filtered
        # by the highest semantic version
        all_bundles = self._pyxis.get_latest_bundles(index_images)
        self.log_debug(
            "There are %d bundles that are latest in a channel in the found index images",
            len(all_bundles),
        )

        # A mapping of digests to bundle metadata. This metadata is used to
        # for the CSV metadata updates.
        bundle_mds_by_digest = {}

        # get bundle digests for original images
        bundle_digests_by_related_nvr = {}
        for image_nvr, image_digest in original_digests_by_nvr.items():
            bundles = self._pyxis.get_bundles_by_related_image_digest(
                image_digest, all_bundles
            )
            if not bundles:
                log.info(f"No latest bundle image with the related image of {image_nvr}")
                continue

            for bundle in bundles:
                bundle_digest = bundle['bundle_path_digest']
                bundle_mds_by_digest[bundle_digest] = bundle
                bundle_digests_by_related_nvr.setdefault(image_nvr, []).append(bundle_digest)

        if not bundle_digests_by_related_nvr:
            msg = "None of the original images have related bundles, skip."
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []
        self.log_info(
            "Found %d bundles with relevant related images", len(bundle_digests_by_related_nvr)
        )

        # Mapping of bundle digest to bundle data
        # {
        #     digest: {
        #         "images": [image_amd64, image_aarch64],
        #         "nvr": NVR,
        #         "auto_rebuild": True/False,
        #         "osbs_pinning": True/False,
        #         "pullspecs": [...],
        #     }
        # }
        bundles_by_digest = {}
        default_bundle_data = {
            'images': [],
            'nvr': None,
            'auto_rebuild': False,
            'osbs_pinning': False,
            # CSV modifications for the rebuilt bundle image
            'pullspecs': [],
            'update': {},
        }

        # Get images for each bundle digest, a bundle digest can have multiple images
        # with different arches.
        for digest in bundle_mds_by_digest:
            bundles = self._pyxis.get_images_by_digest(digest)
            # If no bundle image found, just skip this bundle digest
            if not bundles:
                self.log_warn('The bundle digest %r was not found in Pyxis. Skipping.', digest)
                continue

            bundles_by_digest.setdefault(digest, copy.deepcopy(default_bundle_data))
            bundles_by_digest[digest]['nvr'] = bundles[0]['brew']['build']
            bundles_by_digest[digest]['images'] = bundles

        # Unauthenticated koji session to fetch build info of bundles
        koji_api = KojiService(conf.koji_profile)

        # For each bundle, check whether it should be rebuilt by comparing the
        # auto_rebuild_tags of repository and bundle's tags
        for digest, bundle_data in bundles_by_digest.items():
            bundle_nvr = bundle_data['nvr']

            # Images are for different arches, just check against the first image
            image = bundle_data['images'][0]
            if self.image_has_auto_rebuild_tag(image):
                bundle_data['auto_rebuild'] = True

            # Fetch buildinfo
            buildinfo = koji_api.get_build(bundle_nvr)
            related_images = (
                buildinfo.get('extra', {})
                .get('image', {})
                .get('operator_manifests', {})
                .get('related_images', {})
            )
            bundle_data['osbs_pinning'] = related_images.get('created_by_osbs', False)
            # Save the original pullspecs
            bundle_data['pullspecs'] = related_images.get('pullspecs', [])

        # Digests of bundles to be rebuilt
        to_rebuild_digests = set()

        # Now for each bundle, replace the original digest with rebuilt
        # digest (override pullspecs)
        for digest, bundle_data in bundles_by_digest.items():
            # Override pullspecs only when auto_rebuild is enabled and OSBS-pinning
            # mechanism is used.
            if not (bundle_data['auto_rebuild'] and bundle_data['osbs_pinning']):
                self.log_info(
                    'The bundle %r does not have auto-rebuild tags (%r) and/or OSBS pinning (%r)',
                    bundle_data['nvr'],
                    bundle_data['auto_rebuild'],
                    bundle_data['osbs_pinning'],
                )
                continue

            csv_name = bundle_mds_by_digest[digest]['csv_name']
            version = bundle_mds_by_digest[digest]['version']
            bundle_data.update(self._get_csv_updates(csv_name, version))

            for pullspec in bundle_data['pullspecs']:
                # A pullspec item example:
                # {
                #   'new': 'registry.exampe.io/repo/example-operator@sha256:<sha256-value>',
                #   'original': 'registry.example.io/repo/example-operator:v2.2.0',
                #   'pinned': True,
                #   # value used for internal purpose during manual rebuilds, it's an old pullspec that was replaced
                #   '_old': 'registry.exampe.io/repo/example-operator@sha256:<previous-sha256-value>,
                # }

                # A pullspec path is in format of "registry/repository@digest"
                pullspec_elems = pullspec.get('new').split('@')
                old_digest = pullspec_elems[1]

                if old_digest not in original_nvrs_by_digest:
                    # This related image is not one of the original images
                    continue

                # This related image is one of our original images
                old_nvr = original_nvrs_by_digest[old_digest]
                new_nvr = nvrs_mapping[old_nvr]
                new_digest = rebuilt_digests_by_nvr[new_nvr]

                # save pullspec that image had before rebuild
                pullspec['_old'] = pullspec.get('new')

                # Replace the old digest with new digest
                pullspec_elems[1] = new_digest
                new_pullspec = '@'.join(pullspec_elems)
                pullspec['new'] = new_pullspec
                # Always set pinned to True when it was replaced by Freshmaker
                # since it indicates that the pullspec was modified from the
                # original pullspec
                pullspec['pinned'] = True

                # Once a pullspec in this bundle has been overrided, add this bundle
                # to rebuild list
                self.log_info(
                    'Changing pullspec %r to %r in the bundle %r',
                    pullspec['_old'],
                    pullspec['new'],
                    bundle_data['nvr'],
                )
                to_rebuild_digests.add(digest)

        if not to_rebuild_digests:
            msg = self._no_bundle_prefix + "No bundle images to rebuild for " \
                                           f"advisory {self.event.advisory.name}"
            self.log_info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

        bundles_to_rebuild = list(map(lambda x: bundles_by_digest[x],
                                      to_rebuild_digests))
        return bundles_to_rebuild

    def _handle_manual_rebuild(self, db_event):
        """
        Handle manual rebuild submitted by Release Driver for an advisory created by Botas

        :param db_event: database event that represents a rebuild event
        :rtype: list
        :return: list of advisories that should be rebuilt
        """
        old_to_new_pullspec_map = self._get_pullspecs_mapping()

        if not old_to_new_pullspec_map:
            msg = self._no_bundle_prefix + 'None of the bundle images have ' \
                                           'applicable pullspecs to replace'
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []

        # Unauthenticated koji session to fetch build info of bundles
        koji_api = KojiService(conf.koji_profile)
        rebuild_nvr_to_pullspecs_map = dict()
        # compare replaced pullspecs with pullspecs in 'container_images' and
        # create map for bundles that should be rebuilt with their nvrs
        for container_image_nvr in self.event.container_images:
            artifact_build = db.session.query(ArtifactBuild).filter(
                ArtifactBuild.rebuilt_nvr == container_image_nvr,
                ArtifactBuild.type == ArtifactType.IMAGE.value,
            ).one_or_none()
            pullspecs = []
            # Try to find build in FM database, if it's not there check in Brew
            if artifact_build:
                pullspecs = artifact_build.bundle_pullspec_overrides["pullspecs"]
            else:
                # Fetch buildinfo from Koji
                buildinfo = koji_api.get_build(container_image_nvr)
                # Get the original pullspecs
                pullspecs = (
                    buildinfo.get('extra', {})
                             .get('image', {})
                             .get('operator_manifests', {})
                             .get('related_images', {})
                             .get('pullspecs', [])
                )

            for pullspec in pullspecs:
                if pullspec.get('new') not in old_to_new_pullspec_map:
                    continue
                # use newer pullspecs in the image
                pullspec['new'] = old_to_new_pullspec_map[pullspec['new']]
                rebuild_nvr_to_pullspecs_map[container_image_nvr] = pullspecs

        if not rebuild_nvr_to_pullspecs_map:
            msg = self._no_bundle_prefix + 'None of the container images have ' \
                                           'applicable pullspecs from the input bundle images'
            log.info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []

        # list with metadata about every bundle to do rebuild
        to_rebuild_bundles = []
        # fill 'append' and 'update' fields for bundles to rebuild
        for nvr, pullspecs in rebuild_nvr_to_pullspecs_map.items():
            bundle_digest = self._pyxis.get_manifest_list_digest_by_nvr(nvr)
            if bundle_digest is not None:
                bundles = self._pyxis.get_bundles_by_digest(bundle_digest)
                temp_bundle = bundles[0]
                csv_updates = (self._get_csv_updates(temp_bundle['csv_name'],
                                                     temp_bundle['version']))
                to_rebuild_bundles.append({
                    'nvr': nvr,
                    'update': csv_updates['update'],
                    'pullspecs': pullspecs,
                })
            else:
                log.warning('Can\'t find manifest_list_digest for bundle '
                            f'"{nvr}" in Pyxis')

        if not to_rebuild_bundles:
            msg = 'Can\'t find digests for any of the bundles to rebuild'
            log.warning(msg)
            db_event.transition(EventState.FAILED, msg)
            return []

        return to_rebuild_bundles

    def _get_pullspecs_mapping(self):
        """
        Get map of all replaced pullspecs from 'bundle_images' provided in an event.

        :rtype: dict
        :return: map of all '_old' pullspecs that was replaced by 'new'
            pullspecs in previous Freshmaker rebuilds
        """
        old_to_new_pullspec_map = dict()
        for bundle_nvr in self.event.bundle_images:
            artifact_build = db.session.query(ArtifactBuild).filter(
                ArtifactBuild.rebuilt_nvr == bundle_nvr,
                ArtifactBuild.type == ArtifactType.IMAGE.value,
            ).one_or_none()
            if artifact_build is None:
                log.warning(
                    f'Can\'t find build for a bundle image "{bundle_nvr}"')
                continue
            pullspec_overrides = artifact_build.bundle_pullspec_overrides
            for pullspec in pullspec_overrides['pullspecs']:
                old_pullspec = pullspec.get('_old', None)
                if old_pullspec is None:
                    continue
                old_to_new_pullspec_map[old_pullspec] = pullspec['new']

        return old_to_new_pullspec_map

    @classmethod
    def _get_csv_updates(cls, csv_name, version):
        """
        Determine the CSV updates required for the bundle image.

        :param str csv_name: the name field in the bundle's ClusterServiceVersion file
        :param str version: the version of the bundle image being rebuilt
        :return: a dictionary of the CSV updates needed
        :rtype: dict
        """
        csv_modifications = {}
        new_version, fm_suffix = cls._get_rebuild_bundle_version(version)
        new_csv_name = cls._get_csv_name(csv_name, version, new_version, fm_suffix)
        csv_modifications['update'] = {
            'metadata': {
                # Update the name of the CSV to something uniquely identify the rebuild
                'name': new_csv_name,
                # Declare that this rebuild is a substitute of the bundle being rebuilt
                'annotations': {'olm.substitutesFor': version}
            },
            'spec': {
                # Update the version of the rebuild to be unique and a newer version than the
                # the version of the bundle being rebuilt
                'version': new_version,
            }
        }

        return csv_modifications

    @classmethod
    def _get_rebuild_bundle_version(cls, version):
        """
        Get a bundle version for the Freshmaker rebuild of the bundle image.

        Examples:
            1.2.3 => 1.2.3+0.$timestamp.patched (no build ID and not a rebuild)
            1.2.3+48273 => 1.2.3+48273.0.$timestamp.patched (build ID and not a rebuild)
            1.2.3+48273.0.1616457250.patched => 1.2.3+48273.0.$timestamp.patched (build ID and a rebuild)

        :param str version: the version of the bundle image being rebuilt
        :return: a tuple of the bundle version of the Freshmaker rebuild of the bundle image and
            the suffix that was added by Freshmaker
        :rtype: tuple(str, str)
        """
        parsed_version = semver.VersionInfo.parse(version)
        # Strip off the microseconds of the timestamp
        timestamp = int(datetime.utcnow().timestamp())
        new_fm_suffix = f'0.{timestamp}.patched'
        if parsed_version.build:
            # Check if the bundle was a Freshmaker rebuild
            fm_suffix_search = re.search(
                r'(?P<fm_suffix>0\.\d+\.patched)$', parsed_version.build
            )
            if fm_suffix_search:
                fm_suffix = fm_suffix_search.groupdict()['fm_suffix']
                # Get the build without the Freshmaker suffix. This may include a build ID
                # from the original build before Freshmaker rebuilt it or be empty.
                build_wo_fm_suffix = parsed_version.build[:- len(fm_suffix)]
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
        if version in csv_name:
            return csv_name.replace(version, rebuild_version)
        else:
            return f'{csv_name}.{fm_suffix}'

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
        artifact_build = db.session.query(ArtifactBuild).filter(
            ArtifactBuild.rebuilt_nvr == rebuilt_nvr,
            ArtifactBuild.type == ArtifactType.IMAGE.value,
        ).one_or_none()
        # recursively search for original artifact build
        if artifact_build is not None:
            original_nvr = artifact_build.original_nvr

            # check if image is published
            request_params = {'include': 'data.repositories',
                              'page_size': 1}
            images = self._pyxis._pagination(f'images/nvr/{original_nvr}',
                                             request_params)
            if not images:
                return None
            # stop recursion if the image is published in some repo
            if any(repo['published'] for repo in images[0].get('repositories')):
                return original_nvr

            next_nvr = self.get_published_original_nvr(original_nvr)
            if next_nvr is not None:
                original_nvr = next_nvr

        return original_nvr

    def image_has_auto_rebuild_tag(self, image):
        """ Check if image has a tag enabled for auto rebuild.

        :param dict image: Dict representation of an image entity in Pyxis.
        :rtype: bool
        :return: True if image has a tag enabled for auto rebuild in repository, otherwise False.
        """
        for repo in image['repositories']:
            # Skip unpublished repository
            if not repo['published']:
                continue

            auto_rebuild_tags = self._pyxis.get_auto_rebuild_tags(
                repo['registry'], repo['repository']
            )
            tags = [t['name'] for t in repo.get('tags', [])]
            if set(auto_rebuild_tags) & set(tags):
                return True

        # It'd be more efficient to do this check first, but the exceptions are edge cases
        # (e.g. testing) and it's best to not use it unless absolutely necessary
        nvr = image['brew']['build']
        parsed_nvr = parse_nvr(nvr)
        nv = f'{parsed_nvr["name"]}-{parsed_nvr["version"]}'
        if nv in conf.bundle_autorebuild_tag_exceptions:
            self.log_info(
                'The bundle %r has an exception for being tagged with an auto-rebuild tag', nvr
            )
            return True

        return False

    def _create_original_to_rebuilt_nvrs_map(self):
        """
        Creates mapping of original build NVRs to rebuilt NVRs in advisory.
        Including NVRs of the builds from the blocking advisories

        :rtype: dict
        :return: map of the original NVRs as keys and rebuilt NVRs as values
        """
        nvrs_mapping = {}

        # Get builds from all blocking advisories
        blocking_advisories_builds = \
            Errata().get_blocking_advisories_builds(self.event.advisory.errata_id)
        # Get builds NVRs from the advisory attached to the message/event and
        # then get original NVR for every build
        for product_info in self.event.advisory.builds.values():
            for build in product_info['builds']:
                # Each build is a one key/value pair, and key is the build NVR
                build_nvr = next(iter(build))

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
                    if block_build_nvr['name'] == parsed_build_nvr['name'] and \
                            block_build_nvr['version'] == parsed_build_nvr['version']:
                        nvrs_mapping[block_build] = build_nvr
        return nvrs_mapping

    def _prepare_builds(self, db_event, to_rebuild_bundles):
        """
        Prepare models.ArtifactBuild instance for every bundle that will be
        rebuilt

        :param models.Event db_event: database event that will contain builds
        :param list to_rebuild_bundles: bundles to rebuild
        :return: builds that already in database and ready to be submitted to brew
        :rtype: list
        """
        builds = []
        csv_mod_url = conf.freshmaker_root_url + "/api/2/pullspec_overrides/{}"
        for bundle in to_rebuild_bundles:
            # Reset context to db_event for each iteration before
            # the ArtifactBuild is created.
            self.set_context(db_event)

            rebuild_reason = RebuildReason.DIRECTLY_AFFECTED.value
            bundle_name = koji.parse_NVR(bundle["nvr"])["name"]

            build = self.record_build(
                db_event, bundle_name, ArtifactType.IMAGE,
                state=ArtifactBuildState.PLANNED.value,
                original_nvr=bundle["nvr"],
                rebuild_reason=rebuild_reason)

            # Set context to particular build so logging shows this build
            # in case of error.
            self.set_context(build)

            build.transition(ArtifactBuildState.PLANNED.value, "")

            additional_data = ContainerImage.get_additional_data_from_koji(bundle["nvr"])
            build.build_args = json.dumps({
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
            })
            build.bundle_pullspec_overrides = {
                "pullspecs": bundle["pullspecs"],
                "update": bundle["update"],
            }

            db.session.commit()
            builds.append(build)
        return builds
