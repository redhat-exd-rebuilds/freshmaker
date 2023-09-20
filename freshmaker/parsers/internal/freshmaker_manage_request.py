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
# Written by Filip Valder <fvalder@redhat.com>

from freshmaker.parsers import BaseParser
from freshmaker.events import FreshmakerManageEvent


class FreshmakerManageRequestParser(BaseParser):
    """Parser parsing freshmaker.manage.* events"""

    name = "FreshmakerManageRequestParser"
    topic_suffixes = ["freshmaker.manage.eventcancel"]

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse(self, topic, msg):
        """
        Parse message and call specific method according to the action
        defined within the message.
        """
        action_from_topic = topic.split(".")[-1]
        inner_msg = msg.get("msg")

        if "action" not in inner_msg:
            raise ValueError("Action is not defined within the message.")

        if inner_msg["action"] != action_from_topic:
            raise ValueError(
                "Last part of 'Freshmaker manage' message topic"
                " must match the action defined within the message."
            )

        if "try" not in inner_msg:
            inner_msg["try"] = 0

        try:
            getattr(self, action_from_topic)(inner_msg)
        except AttributeError:
            raise NotImplementedError("The message contains unsupported action.")

        return FreshmakerManageEvent(inner_msg)

    def eventcancel(self, inner_msg):
        """
        Parse message for event cancelation request
        """
        try:
            inner_msg["event_id"]
            inner_msg["builds_id"]
        except KeyError:
            raise ValueError("Message doesn't contain all required information.")

        return True
