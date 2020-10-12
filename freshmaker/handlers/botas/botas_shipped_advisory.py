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

from freshmaker import db
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import BotasErrataShippedEvent
from freshmaker.models import Event
from freshmaker.types import EventState


class HandleBotasAdvisory(ContainerBuildHandler):
    """
    Handles event that was created by transition of an advisory filed by
    BOTAS to SHIPPED_LIVE state
    """
    name = "HandleBotasAdvisory"

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
            db.session.commit()
            self.log_info(msg)
            return []

        # Get original nvrs of all builds in the advisory
        original_nvrs = [build.original_nvr for build in db_event.builds]
        self.log_info(
            "Orignial nvrs of build in the advisory #{0} are: {1}".format(
                db_event.search_key, " ".join(original_nvrs)))

        msg = "Skipping due to being blocked on further implementation for now."

        # Skip that event because we can't proceed with processing it.
        # TODO
        # Next step would be queries Pyxis and getting the digests of these nvrs
        db_event.transition(EventState.SKIPPED, msg)
        db.session.commit()
        return []
