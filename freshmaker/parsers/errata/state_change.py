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
from freshmaker.events import ErrataAdvisoryStateChangedEvent, BotasErrataShippedEvent
from freshmaker.errata import Errata, ErrataAdvisory


class ErrataAdvisoryStateChangedParser(BaseParser):
    """
    Parser parsing errata.activity.status.
    If event produced by BOTAS we will generate specific type of event
    """

    name = "ErrataAdvisoryStateChangedParser"
    topic_suffixes = ["errata.activity.status"]

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse(self, topic, msg):
        msg_id = msg.get('msg_id')
        inner_msg = msg.get('msg')
        errata_id = int(inner_msg.get('errata_id'))

        errata = Errata()
        advisory = ErrataAdvisory.from_advisory_id(errata, errata_id)
        # If advisory created by BOTAS and it's shipped,
        # then return BotasErrataShippedEvent event
        if advisory.state == "SHIPPED_LIVE" and \
           advisory.reporter.startswith('botas'):
            event = BotasErrataShippedEvent(msg_id, advisory)
        else:
            event = ErrataAdvisoryStateChangedEvent(msg_id, advisory)
        return event
