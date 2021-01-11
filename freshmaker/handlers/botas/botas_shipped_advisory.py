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

from freshmaker import db, conf, log
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import BotasErrataShippedEvent
from freshmaker.models import ArtifactBuild, ArtifactType, Event
from freshmaker.types import EventState
from freshmaker.pyxis import Pyxis
from freshmaker.kojiservice import KojiService


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
                raise ValueError("'pyxis_server_url' parameter should be set")
            self._pyxis = Pyxis(conf.pyxis_server_url)

    def can_handle(self, event):
        if (isinstance(event, BotasErrataShippedEvent) and
                'docker' in event.advisory.content_types):
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

        # Get builds NVRs from the advisory attached to the message/event and
        # then get original NVR for every build

        # Mapping of original build nvrs to rebuilt nvrs in advisory
        nvrs_mapping = {}
        for product_info in event.advisory.builds.values():
            for build in product_info['builds']:
                # Search for the first build that triggered the chain of rebuilds
                # for every shipped NVR to get original NVR from it
                original_nvr = self.get_published_original_nvr(build['nvr'])
                if original_nvr is None:
                    continue
                nvrs_mapping[original_nvr] = build['nvr']

        original_nvrs = nvrs_mapping.keys()
        self.log_info(
            "Orignial nvrs of build in the advisory #{0} are: {1}".format(
                event.advisory.errata_id, " ".join(original_nvrs)))

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
            digest = self._pyxis.get_manifest_list_digest_by_nvr(nvr)
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

        # A set of unique bundle digests
        bundle_digests = set()

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
                bundle_digests.add(bundle_digest)
                bundle_digests_by_related_nvr.setdefault(image_nvr, []).append(bundle_digest)

        if not bundle_digests_by_related_nvr:
            msg = "None of the original images have related bundles, skip."
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            return []

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
            'pullspecs': [],
        }

        # Get images for each bundle digest, a bundle digest can have multiple images
        # with different arches.
        for digest in bundle_digests:
            bundles = self._pyxis.get_images_by_digest(digest)
            # If no bundle image found, just skip this bundle digest
            if not bundles:
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
                buildinfo.get("extra", {})
                .get("image", {})
                .get("operator_manifests", {})
                .get("related_images", {})
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
                continue

            for pullspec in bundle_data['pullspecs']:
                # A pullspec item example:
                # {
                #   'new': 'registry.exampe.io/repo/example-operator@sha256:<sha256-value>'
                #   'original': 'registry.example.io/repo/example-operator:v2.2.0',
                #   'pinned': True
                # }

                # If related image is not pinned by OSBS, skip
                if not pullspec.get('pinned', False):
                    continue

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

                # Replace the old digest with new digest
                pullspec_elems[1] = new_digest
                new_pullspec = '@'.join(pullspec_elems)
                pullspec['new'] = new_pullspec

                # Once a pullspec in this bundle has been overrided, add this bundle
                # to rebuild list
                to_rebuild_digests.add(digest)

        # Skip that event because we can't proceed with processing it.
        # TODO
        # Now when we have bundle images' nvrs we can procceed with rebuilding it
        msg = f"Skipping the rebuild of {len(to_rebuild_digests)} bundle images " \
              "due to being blocked on further implementation for now."
        db_event.transition(EventState.SKIPPED, msg)
        return []

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
        return False
