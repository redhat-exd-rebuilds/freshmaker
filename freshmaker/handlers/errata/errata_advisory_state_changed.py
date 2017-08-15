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

from freshmaker import log
from freshmaker import db
from freshmaker.events import (
    ErrataAdvisoryStateChangedEvent, ErrataAdvisoryRPMsSignedEvent)
from freshmaker.models import Event, EVENT_TYPES
from freshmaker.handlers import BaseHandler


class ErrataAdvisoryStateChangedHandler(BaseHandler):
    """Rebuild container when a dependecy container is built in Brew"""

    name = 'ErrataAdvisoryStateChangedHandler'

    def can_handle(self, event):
        return isinstance(event, ErrataAdvisoryStateChangedEvent)

    def handle(self, event):
        """
        When build container task state changed in brew, update build state in db and
        rebuild containers depend on the success build as necessary.
        """

        errata_id = event.errata_id
        state = event.state
        if state != "SHIPPED_LIVE":
            log.debug("Ignoring Errata advisory %d state change to %s, "
                      "because it is not SHIPPED_LIVE", errata_id, state)
            return []

        # check db to see whether this advisory exists in db
        db_event = db.session.query(Event).filter_by(
            event_type_id=EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            search_key=str(errata_id)).one_or_none()
        if not db_event:
            log.debug("Ignoring Errata advisory %d - it does not exist in "
                      "Freshmaker db.", errata_id)
            return []

        db_event.released = True
        db.session.commit()
        log.info("Errata advisory %d is now marked as released", errata_id)
