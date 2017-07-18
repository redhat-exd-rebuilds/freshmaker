# -*- coding: utf-8 -*-
# Copyright (c) 2016  Red Hat, Inc.
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
#
# Written by Chenxiong Qi <cqi@redhat.com>

from itertools import chain

from freshmaker import conf
from freshmaker import log
from freshmaker.events import BrewSignRPMEvent
from freshmaker.handlers import BaseHandler
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType


class BrewSignRPMHanlder(BaseHandler):
    """Rebuild docker images when a RPM is signed in Brew"""

    name = 'BrewSignRPMHandler'

    def can_handle(self, event):
        return isinstance(event, BrewSignRPMEvent)

    def handle(self, event):
        """Rebuild docker images which contains this signed RPM

        Before rebuilding docker images, freshmaker has to find which docker
        images includes the signed RPM. As of writing this feature, this
        information is stored in LightBlue, and need to use content_sets to
        find out those images.

        There are several external services taking part in the process of
        rebuilding docker images.

        * Errata Tool: get which advisories contains the signed RPM, and Pulp
          repositories the signed RPM will end up eventually when shipped.
        * Pulp: query content set with repositories got from Errata Tool.
        * LightBlue: this is where to query docker images that contains RPMs
          from those content sets.
        """

        images = self._find_images_to_rebuild(event)

        if not images:
            log.info('Not find docker images to rebuild.')
            return []

        log.info('Found docker images to rebuild: %s', images)

        # TODO: build yum repo to contain that signed RPM and start to rebuild

        return []

    def _find_images_to_rebuild(self, event):
        # When get a signed RPM, first step is to find out advisories
        # containing that RPM and has to ensure all builds are signed.
        errata = Errata(conf.errata_tool_server_url)
        advisories = errata.advisories_from_event(event)

        # Filter out advisories which are not allow by configuration
        advisories = [advisory for advisory in advisories
                      if self.allow_build(ArtifactType.IMAGE,
                                          advisory_name=advisory.name)]
        if not advisories:
            log.info("No advisories found suitable for rebuilding Docker "
                     "images")
            return []

        if not all((errata.builds_signed(advisory.errata_id)
                    for advisory in advisories)):
            log.info('Not all builds in %s are signed. Do not rebuild any '
                     'docker image until signed.', advisories)
            return []

        # Use the advisories to find out Pulp repository IDs from Errata Tool
        # and furthermore get content_sets from Pulp where signed RPM will end
        # up eventually when advisories are shipped.
        pulp_repo_ids = list(set(chain(
            *[errata.get_pulp_repository_ids(advisory.errata_id)
              for advisory in advisories]
        )))

        pulp = Pulp(server_url=conf.pulp_server_url,
                    username=conf.pulp_username,
                    password=conf.pulp_password)
        content_sets = pulp.get_content_set_by_repo_ids(pulp_repo_ids)

        log.info('RPM will end up within content sets %s', content_sets)

        # Query images from LightBlue by signed RPM's srpm name and found
        # content sets
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key)

        srpm_name = self._find_build_srpm_name(event.nvr)
        return lb.find_images_with_package_from_content_set(srpm_name,
                                                            content_sets)

    def _find_build_srpm_name(self, build_nvr):
        """Find srpm name from a build"""
        with koji_service(conf.koji_profile, log) as session:
            rpm_infos = session.get_build_rpms(build_nvr, arches='src')
            if not rpm_infos:
                raise ValueError(
                    'Build {} does not have a SRPM, although this should not '
                    'happen in practice.'.format(build_nvr))
            return rpm_infos[0]['name']
