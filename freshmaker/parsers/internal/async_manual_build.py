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

from freshmaker.parsers import BaseParser
from freshmaker.events import FreshmakerAsyncManualBuildEvent


class FreshmakerAsyncManualbuildParser(BaseParser):
    """Parser of event async.manual.build"""

    name = 'FreshmakerAsyncManualbuildParser'
    topic_suffixes = ['freshmaker.async.manual.build']

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse(self, topic, msg):
        inner_msg = msg['msg']

        return FreshmakerAsyncManualBuildEvent(
            inner_msg['msg_id'],
            inner_msg['dist_git_branch'],
            inner_msg['container_images'],
            freshmaker_event_id=inner_msg.get('freshmaker_event_id'),
            brew_target=inner_msg.get('brew_target'),
            dry_run=inner_msg.get('dry_run'),
        )
