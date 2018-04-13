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

from freshmaker import db, log
from freshmaker.events import BrewSignRPMEvent, ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import BaseHandler
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType
from freshmaker.models import Event


class BrewSignRPMHandler(BaseHandler):
    """
    Checks whether all RPMs in Errata advisories for signed package are signed
    and in case they are, generates ErrataAdvisoryRPMsSignedEvent events for
    each advisory.
    """

    name = 'BrewSignRPMHandler'

    def can_handle(self, event):
        return isinstance(event, BrewSignRPMEvent)

    def _filter_out_existing_advisories(self, advisories):
        """
        Filter out all advisories which have been already handled by
        Freshmaker.

        :param advisories: List of ErrataAdvisory instances.
        :rtype: List of ErrataAdvisory
        :return: List of ErrataAdvisory instances without already handled
                 advisories.
        """
        ret = []
        for advisory in advisories:
            if (db.session.query(Event).filter_by(
                    search_key=str(advisory.errata_id)).count() != 0):
                log.info("Skipping advisory %s (%d), already handled by "
                         "Freshmaker", advisory.name, advisory.errata_id)
                continue
            ret.append(advisory)
        return ret

    def handle(self, event):
        log.info("Finding out all advisories including %s", event.nvr)

        # When get a signed RPM, first step is to find out advisories
        # containing that RPM and ensure all builds are signed.
        errata = Errata()
        advisories = errata.advisories_from_event(event)

        # Filter out advisories which are not allowed by configuration.
        advisories = [
            advisory for advisory in advisories
            if self.allow_build(
                ArtifactType.IMAGE,
                advisory_name=advisory.name,
                advisory_security_impact=advisory.security_impact,
                advisory_highest_cve_severity=advisory.highest_cve_severity,
                advisory_state=advisory.state)]

        # Filter out advisories which are already in Freshmaker DB.
        advisories = self._filter_out_existing_advisories(advisories)

        if not advisories:
            log.info("No advisories found suitable for rebuilding Docker "
                     "images")
            return []

        if not all((errata.builds_signed(advisory.errata_id)
                    for advisory in advisories)):
            log.info('Not all builds in %s are signed. Do not rebuild any '
                     'docker image until signed.', advisories)
            return []

        # Now we know that all advisories with this signed RPM have also other
        # RPMs signed. We can then proceed and generate
        # ErrataAdvisoryRPMsSignedEvent.
        new_events = []
        for advisory in advisories:
            new_event = ErrataAdvisoryRPMsSignedEvent(
                event.msg_id + "." + str(advisory.name), advisory)
            db_event = Event.create(
                db.session, new_event.msg_id, new_event.search_key,
                new_event.__class__, released=False)
            db.session.add(db_event)
            new_events.append(new_event)
        db.session.commit()
        return new_events
