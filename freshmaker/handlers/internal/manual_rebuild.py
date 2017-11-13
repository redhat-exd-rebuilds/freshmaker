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
from freshmaker.models import Event, EVENT_TYPES
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.events import (
    FreshmakerManualRebuildEvent, ErrataAdvisoryRPMsSignedEvent)
from freshmaker.errata import Errata

__all__ = ('FreshmakerManualRebuildHandler',)


class FreshmakerManualRebuildHandler(ContainerBuildHandler):
    """Start image rebuild with this compose containing included packages"""

    def can_handle(self, event):
        if not isinstance(event, FreshmakerManualRebuildEvent):
            return False
        return True

    def rebuild_advisory_if_not_exists(self, event, errata_id):
        """
        Initiates rebuild of artifacts based on Errata advisory with
        `errata_id` id.

        :rtype: List of ErrataAdvisoryRPMsSignedEvent instances.
        :return: List of extra events generated to initiate the rebuild.
        """

        db_event = db.session.query(Event).filter_by(
            event_type_id=EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            search_key=str(errata_id)).first()
        if db_event:
            log.info("Ignoring Errata advisory %d - it already exists in "
                      "Freshmaker db.", errata_id)
            return []

        # Get additional info from Errata to fill in the needed data.
        errata = Errata()
        advisories = errata.advisories_from_event(event)
        if not advisories:
            log.error("Unknown Errata advisory %d" % errata_id)
            return []

        log.info("Generating ErrataAdvisoryRPMsSignedEvent for Errata "
                 "advisory %d - manually triggered rebuild.", errata_id)
        advisory = advisories[0]
        new_event = ErrataAdvisoryRPMsSignedEvent(
            event.msg_id + "." + str(advisory.name), advisory.name,
            advisory.errata_id, advisory.security_impact)
        new_event.manual = True
        return [new_event]

    def handle(self, event):
        extra_events = []

        if event.errata_id:
            extra_events += self.rebuild_advisory_if_not_exists(event, event.errata_id)

        return extra_events
