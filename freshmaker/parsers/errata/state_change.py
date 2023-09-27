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

from freshmaker.parsers import BaseParser
from freshmaker.events import (
    BotasErrataShippedEvent,
    ErrataRPMAdvisoryShippedEvent,
    FlatpakModuleAdvisoryReadyEvent,
)
from freshmaker.errata import Errata, ErrataAdvisory


class ErrataAdvisoryStateChangedParser(BaseParser):
    """
    Parses errata.activity.status messages (advisory changes state).

    Creates BotasErrataShippedEvent if BOTAS-created advisory is moved to
    SHIPPED_LIVE.

    Creates FlatpakModuleAdvisoryReadyEvent if a new flatpak advisory can be
    created for module security advisory.

    Creates ErrataAdvisoryStateChangedEvent in other cases.
    """

    name = "ErrataAdvisoryStateChangedParser"
    topic_suffixes = ["errata.activity.status"]

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse(self, topic, msg):
        msg_id = msg.get("msg_id")
        inner_msg = msg.get("msg")
        errata_id = int(inner_msg.get("errata_id"))
        new_state = inner_msg.get("to")

        errata = Errata()
        advisory = ErrataAdvisory.from_advisory_id(errata, errata_id)
        # When there is message delay, state change messages can arrive after
        # advisory has been changed to a different state other than the one
        # in message, so we override advisory state with the state in message
        advisory.state = new_state
        # Append advisory name to message id, this makes it easier to check which
        # type of advisory triggered the event without opening Errata tool.
        msg_id = f"{msg_id}.{str(advisory.name)}"

        if advisory.state == "SHIPPED_LIVE":
            # If advisory created by BOTAS and it's shipped,
            # then return BotasErrataShippedEvent event
            if advisory.reporter.startswith("botas"):
                return BotasErrataShippedEvent(msg_id, advisory)
            # If advisory is shipped, but not created by BOTAS,
            # return ErrataRPMAdvisoryShippedEvent event
            return ErrataRPMAdvisoryShippedEvent(msg_id, advisory)

        if advisory.is_flatpak_module_advisory_ready():
            return FlatpakModuleAdvisoryReadyEvent(msg_id, advisory)
