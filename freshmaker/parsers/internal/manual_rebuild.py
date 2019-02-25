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

import time
from freshmaker.parsers import BaseParser
from freshmaker.events import ManualRebuildWithAdvisoryEvent
from freshmaker.errata import Errata, ErrataAdvisory


class FreshmakerManualRebuildParser(BaseParser):
    """Parser parsing freshmaker.manual.rebuild"""

    name = "FreshmakerManualRebuildParser"
    topic_suffixes = ["freshmaker.manual.rebuild"]

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse_post_data(self, data):
        """
        Method shared between Frontend and Backend to parse the POST data
        of manual rebuild JSON and generate the BaseEvent representation
        of the rebuild request.

        :param dict data: Dict generated from JSON from HTTP POST or parsed
            from the UMB message sent from Frontend to Backend.
        """
        msg_id = data.get('msg_id', "manual_rebuild_%s" % (str(time.time())))
        errata_id = data.get('errata_id')
        dry_run = data.get('dry_run', False)

        errata = Errata()
        advisory = ErrataAdvisory.from_advisory_id(errata, errata_id)

        event = ManualRebuildWithAdvisoryEvent(
            msg_id, advisory, data.get("container_images", []), data.get("metadata", None),
            manual=True, dry_run=dry_run)

        return event

    def parse(self, topic, msg):
        inner_msg = msg.get('msg')
        return self.parse_post_data(inner_msg)
