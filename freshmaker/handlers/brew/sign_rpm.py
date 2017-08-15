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

import json
import koji
import time

from itertools import chain

from freshmaker import conf
from freshmaker import log
from freshmaker import db
from freshmaker.events import BrewSignRPMEvent, ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import BaseHandler
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.models import Event

from odcs.client.odcs import ODCS
from odcs.client.odcs import AuthMech


class BrewSignRPMHandler(BaseHandler):
    """
    Checks whether all RPMs in Errata advisories for signed package are signed
    and in case they are, generates ErrataAdvisoryRPMsSignedEvent events for
    each advisory.
    """

    name = 'BrewSignRPMHandler'

    def can_handle(self, event):
        return isinstance(event, BrewSignRPMEvent)

    def handle(self, event):
        # When get a signed RPM, first step is to find out advisories
        # containing that RPM and ensure all builds are signed.
        errata = Errata(conf.errata_tool_server_url)
        advisories = errata.advisories_from_event(event)

        # Filter out advisories which are not allowed by configuration.
        advisories = [advisory for advisory in advisories
                      if self.allow_build(
                          ArtifactType.IMAGE, advisory_name=advisory.name,
                          advisory_security_impact=advisory.security_impact)]
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
                event.msg_id + "." + str(advisory.name), advisory.name,
                advisory.errata_id, advisory.security_impact)
            new_events.append(new_event)
        return new_events
