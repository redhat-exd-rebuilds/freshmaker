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
from freshmaker.events import (
    ErrataAdvisoryStateChangedEvent, ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.types import EventState, ArtifactType, ArtifactBuildState


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

        self.log_info("Found following Docker repositories updated by the advisory: %r",
                      repo_tags.keys())

        # Count the number of impacted builds to show them in state reason
        # when moving the Event to COMPLETE.
        num_impacted = None

        # Submit rebuild request to Bob :).
        for repo_name in repo_tags.keys():
            self.log_info("Requesting Bob rebuild of %s", repo_name)

            parent_build = self.record_build(
                db_event, repo_name, ArtifactType.IMAGE_REPOSITORY,
                state=ArtifactBuildState.DONE.value)

            bob_url = "%s/update_children/%s" % (
                conf.bob_server_url.rstrip('/'), repo_name)
            headers = {"Authorization": "Bearer %s" % conf.bob_auth_token}
            if self.dry_run:
                self.log_info("DRY RUN: Skipping request to Bob.")
                continue

            r = requests.get(bob_url, headers=headers, timeout=conf.requests_timeout)
            r.raise_for_status()
            resp = r.json()
            self.log_info("Response: %r", resp)
            if "impacted" in resp:
                if num_impacted is None:
                    num_impacted = 0
                num_impacted += len(resp["impacted"])
                for external_repo_name in resp["impacted"]:
                    self.record_build(
                        db_event, external_repo_name, ArtifactType.IMAGE_REPOSITORY,
                        state=ArtifactBuildState.DONE.value, dep_on=parent_build)

        msg = "Advisory %s: Informed Bob about update of %d image repositories." % (
            db_event.search_key, len(repo_tags))
        if num_impacted is not None:
            msg += " Bob is rebuilding %d impacted external image repositories." % (
                num_impacted)
        db_event.transition(EventState.COMPLETE, msg)
        db.session.commit()
