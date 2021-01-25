# -*- coding: utf-8 -*-
# Copyright (c) 2021  Red Hat, Inc.
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

import re

from freshmaker import conf
from freshmaker.events import ManualRebuildWithAdvisoryEvent
from freshmaker.lightblue import LightBlue
from freshmaker.errata import Errata
from .rebuild_images_on_rpm_advisory_change import RebuildImagesOnRPMAdvisoryChange


class RebuildEUSBaseImages(RebuildImagesOnRPMAdvisoryChange):
    """
    Rebuilds Extended Life Support base images
    """

    name = 'RebuildEUSBaseImages'

    def can_handle(self, event):
        if not super().can_handle(event):
            return False

        # If 'content_sets' of the event doesn't exist yet, create and fill it
        if self.event.content_sets is None:
            errata = Errata()
            self._set_event_content_sets(errata, int(event.search_key))

        # Check if any of the content sets is EUS content set
        return any(re.match(r'.+-eus-rpms', c) for c in self.event.content_sets)

    def _find_images_to_rebuild(self, errata_id):
        """
        Finds docker rebuild images from each build added to specific Errata
        advisory.

        But only EUS base images that DON'T have children should be rebuilt.
        So other batches including EUS images with children will be handled by
        other handler and hence should be filtered out here.

        :param int errata_id: Errata ID.
        """
        errata = Errata()
        errata_id = int(errata_id)

        self._set_event_content_sets(errata)

        self.log_info('RPMs from advisory ends up in following content sets: '
                      '%s', self.event.content_sets)

        # Query images from LightBlue by signed RPM's srpm name and found
        # content sets
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key,
                       event_id=self.current_db_event_id)

        # Limit the Lightblue query to particular leaf images if set in Event.
        leaf_container_images = None
        if isinstance(self.event, ManualRebuildWithAdvisoryEvent):
            leaf_container_images = self.event.container_images

        # Get binary rpm nvrs which are affected by the CVEs in this advisory
        affected_nvrs = self.event.advisory.affected_rpm_nvrs

        # If there is no CVE affected binary rpms, this can be non-RHSA advisory,
        # just rebuild images that have the builds in this advisory installed
        if not affected_nvrs:
            affected_nvrs = errata.get_binary_rpm_nvrs(errata_id)

        self.log_info(
            "Going to find all the container images to rebuild as "
            "result of %r update.", affected_nvrs)
        batches = lb.find_images_to_rebuild(
            affected_nvrs, self.event.content_sets,
            filter_fnc=self._filter_out_not_allowed_builds,
            published=False, release_categories=None,
            leaf_container_images=leaf_container_images)

        # Only EUS base images without children should be rebuilt
        single_eus_images = []
        for batch in batches:
            if len(batch) == 1:
                single_eus_images.append(batch)
        return single_eus_images
