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

from freshmaker import db, conf, log
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import BotasErrataShippedEvent
from freshmaker.models import Event
from freshmaker.types import EventState
from freshmaker.pyxis import Pyxis
from freshmaker.kojiservice import koji_service


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

        # Get event from database or create new one.
        # Then we can get original NVRs from it.
        db_event = Event.get_or_create_from_event(db.session, event)

        self.set_context(db_event)

        # Check if event is allowed by internal policies
        if not self.event.is_allowed(self):
            msg = ("This image rebuild is not allowed by internal policy. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            self.log_info(msg)
            return []

        # Get original nvrs of all builds in the advisory
        original_nvrs = [build.original_nvr for build in db_event.builds]
        self.log_info(
            "Orignial nvrs of build in the advisory #{0} are: {1}".format(
                db_event.search_key, " ".join(original_nvrs)))
        # Get images by nvrs and then get their digests
        original_images_digests = set(self._pyxis.get_digests_by_nvrs(original_nvrs))
        if not original_images_digests:
            msg = f"The are no digests for NVRs: {','.join(original_nvrs)}"
            log.warning(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

        index_images = self._pyxis.get_operator_indices()
        # get latest bundle images per channel per index image filtered
        # by the highest semantic version
        all_bundles = self._pyxis.get_latest_bundles(index_images)

        bundles = self._pyxis.filter_bundles_by_related_image_digests(
            original_images_digests, all_bundles)
        bundle_digests = set()
        for bundle in bundles:
            if not bundle.get('bundle_path_digest'):
                log.warning("Bundle %s doesn't have 'bundle_path_digests' set",
                            bundle['bundle_path'])
                continue
            bundle_digests.add(bundle['bundle_path_digest'])
        bundle_images = self._pyxis.get_images_by_digests(bundle_digests)

        # get NVRs only of those bundles, which have OSBS pinning
        bundles_nvrs = self._filter_bundles_by_pinned_related_images(
            bundle_images)

        # Skip that event because we can't proceed with processing it.
        # TODO
        # Now when we have bundle images' nvrs we can procceed with rebuilding it
        msg = f"Skipping the rebuild of {len(bundles_nvrs)} bundle images " \
              "due to being blocked on further implementation for now."
        db_event.transition(EventState.SKIPPED, msg)
        return []

    def _filter_bundles_by_pinned_related_images(self, bundle_images):
        """
        If the digests were not pinned by OSBS, the bundle image
        will be filtered out.

        There is no need in checking pinning for every of related images,
        because we already know that digest points to the manifest list,
        because of previous filtering.

        :param list bundle_images: ContainerImages of operator bundles
        :return: list of NVRs of bundle images that have at least one
            original related image that was rebuilt
        """
        ret_bundle_images_nvrs = set()
        with koji_service(conf.koji_profile, log, dry_run=self.dry_run,
                          login=False) as session:
            for bundle in bundle_images:
                nvr = bundle['brew']['build']
                build = session.get_build(nvr)
                if not build:
                    log.error("Could not find the build %s in Koji", nvr)
                    continue
                related_images = (
                    build.get("build", {})
                         .get("extra", {})
                         .get("image", {})
                         .get("operator_manifests", {})
                         .get("related_images", {})
                )

                # Skip the bundle if the related images section was not populated by OSBS
                if related_images.get("created_by_osbs") is not True:
                    continue
                ret_bundle_images_nvrs.add(nvr)
        return ret_bundle_images_nvrs
