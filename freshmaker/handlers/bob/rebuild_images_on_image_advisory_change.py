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
# Written by Jan Kaluza <jkaluza@redhat.com>

import requests

from freshmaker import conf, db
from freshmaker.models import Event
from freshmaker.errata import Errata
from freshmaker.pulp import Pulp
from freshmaker.events import (ErrataAdvisoryStateChangedEvent,
                               ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.types import EventState


class RebuildImagesOnImageAdvisoryChange(ContainerBuildHandler):
    name = 'RebuildImagesOnImageAdvisoryChange'

    def can_handle(self, event):
        if (not isinstance(event, ErrataAdvisoryStateChangedEvent) and
                not isinstance(event, ManualRebuildWithAdvisoryEvent)):
            return False

        if 'docker' not in event.advisory.content_types:
            self.log_info('Skip non-Docker advisory %s.', event.advisory.errata_id)
            return False

        return True

    @fail_event_on_handler_exception
    def handle(self, event):
        if event.dry_run:
            self.force_dry_run()

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        # Check if we are allowed to build this advisory.
        if not event.is_allowed(self):
            msg = ("Errata advisory {0} is not allowed by internal policy "
                   "to trigger Bob rebuilds.".format(event.advisory.errata_id))
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        self.rebuild_images_depending_on_advisory(
            db_event, event.advisory.errata_id)

    def rebuild_images_depending_on_advisory(self, db_event, errata_id):
        """
        Submits requests to Bob to rebuild the images depending on the
        images updated in the advisory with ID `errata_id`.
        """
        # Get the list of CDN repository names for each build in the advisory
        # as well as the name of tags used for the images.
        errata = Errata()
        repo_tags = errata.get_docker_repo_tags(errata_id)
        if not repo_tags:
            msg = "No CDN repo found for advisory %r" % errata_id
            self.log_info(msg)
            db_event.transition(EventState.FAILED, msg)
            db.session.commit()
            return

        # Use the Pulp to get the Docker repository name from the CDN repository
        # name and store it into `docker_repos` dict.
        pulp = Pulp(conf.pulp_docker_server_url, conf.pulp_docker_username,
                    conf.pulp_docker_password)
        # {docker_repository_name: [list, of, docker, tags], ...}
        docker_repos = {}
        for per_build_repo_tags in repo_tags.values():
            for cdn_repo, docker_repo_tags in per_build_repo_tags.items():
                docker_repo = pulp.get_docker_repository_name(cdn_repo)
                if not docker_repo:
                    self.log_error("No Docker repo found for CDN repo %r", cdn_repo)
                    continue
                docker_repos[docker_repo] = docker_repo_tags

        self.log_info("Found following Docker repositories updated by the advisory: %r",
                      docker_repos.keys())

        # Submit rebuild request to Bob :).
        for repo_name in docker_repos.keys():
            self.log_info("Requesting Bob rebuild of %s", repo_name)
            bob_url = "%s/update_children/%s" % (
                conf.bob_server_url.rstrip('/'), repo_name)
            headers = {"Authorization": "Bearer %s" % conf.bob_auth_token}
            if self.dry_run:
                self.log_info("DRY RUN: Skipping request to Bob.")
                continue

            r = requests.get(bob_url, headers=headers)
            r.raise_for_status()
            # TODO: Once the Bob API is clear here, we can handle the response,
            # but for now just log it. This should also be changed to log_debug
            # once we are in production, but for now log_info makes debugging
            # this new code easier.
            self.log_info("Response: %r", r.json())

        db_event.transition(EventState.COMPLETE)
        db.session.commit()
