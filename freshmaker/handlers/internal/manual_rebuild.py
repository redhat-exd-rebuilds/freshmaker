# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
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

from freshmaker import db, log
from freshmaker.models import Event
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import (
    FreshmakerManualRebuildEvent, ErrataAdvisoryStateChangedEvent)
from freshmaker.errata import Errata
from freshmaker.types import EventState

__all__ = ('FreshmakerManualRebuildHandler',)


class FreshmakerManualRebuildHandler(ContainerBuildHandler):
    """Start image rebuild with this compose containing included packages"""

    def can_handle(self, event):
        if not isinstance(event, FreshmakerManualRebuildEvent):
            return False
        return True

    def generate_fake_event(self, manual_rebuild_event):
        """
        Returns fake ErrataAdvisoryStateChangedEvent which will trigger manual
        rebuild of artifacts based on Errata advisory `errata_id`.

        :param manual_rebuild_event: FreshmakerManualRebuildEvent instance.
        :rtype: ErrataAdvisoryStateChangedEvent
        :return: Newly generated ErrataAdvisoryStateChangedEvent.
        """

        # Get additional info from Errata to fill in the needed data.
        errata = Errata()
        advisories = errata.advisories_from_event(manual_rebuild_event)
        if not advisories:
            msg = "Unknown Errata advisory %d" % manual_rebuild_event.errata_id
            self.current_db_event.transition(EventState.FAILED, msg)
            db.session.commit()
            return None

        log.info("Generating ErrataAdvisoryStateChangedEvent for Errata "
                 "advisory %d - manually triggered rebuild.",
                 manual_rebuild_event.errata_id)
        advisory = advisories[0]
        new_event = ErrataAdvisoryStateChangedEvent(
            manual_rebuild_event.msg_id + "." + str(advisory.name), advisory)
        new_event.manual = True
        new_event.dry_run = manual_rebuild_event.dry_run
        msg = ("Generated ErrataAdvisoryStateChangedEvent (%s) for errata: %s"
               % (manual_rebuild_event.msg_id, manual_rebuild_event.errata_id))
        self.current_db_event.transition(EventState.COMPLETE, msg)
        db.session.commit()
        return new_event

    def handle(self, event):
        # We log every manual trigger event to DB.
        db_event = Event.get_or_create_from_event(db.session, event)
        db.session.commit()
        self.set_context(db_event)

        fake_event = self.generate_fake_event(event)
        if not fake_event:
            return []
        return [fake_event]
