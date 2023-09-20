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
# Written by Filip Valder <fvalder@redhat.com>

from freshmaker import conf, log, db
from freshmaker.models import ArtifactBuild
from freshmaker.handlers import BaseHandler
from freshmaker.events import FreshmakerManageEvent
from freshmaker.kojiservice import koji_service


class CancelEventOnFreshmakerManageRequest(BaseHandler):
    name = "CancelEventOnFreshmakerManageRequest"
    order = 0

    def can_handle(self, event):
        if isinstance(event, FreshmakerManageEvent) and event.action == "eventcancel":
            return True

        return False

    def handle(self, event):
        """
        Handle Freshmaker manage request to cancel actions triggered by
        event, given by event_id in the event.body. This especially
        means to cancel running Koji builds. If some of the builds
        couldn't be canceled for some reason, there's ongoing event
        containing only those builds (by DB id).
        """

        failed_to_cancel_builds_id = []
        log_fail = log.error if event.last_try else log.warning
        with koji_service(conf.koji_profile, log, dry_run=event.dry_run) as session:
            builds = (
                db.session.query(ArtifactBuild)
                .filter(ArtifactBuild.id.in_(event.body["builds_id"]))
                .all()
            )
            for build in builds:
                if session.cancel_build(build.build_id):
                    build.state_reason = "Build canceled in external build system."
                    continue
                if event.last_try:
                    build.state_reason = (
                        "Build was NOT canceled in external build system."
                        " Max number of tries reached!"
                    )
                failed_to_cancel_builds_id.append(build.id)
            db.session.commit()

        if failed_to_cancel_builds_id:
            log_fail(
                "Builds which failed to cancel in external build system," " by DB id: %s; try #%s",
                failed_to_cancel_builds_id,
                event.try_count,
            )
        if event.last_try or not failed_to_cancel_builds_id:
            return []

        event.body["builds_id"] = failed_to_cancel_builds_id
        return [event]
