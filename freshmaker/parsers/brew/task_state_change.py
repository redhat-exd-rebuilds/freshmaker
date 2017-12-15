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

import re

from freshmaker.parsers import BaseParser
from freshmaker.events import BrewContainerTaskStateChangeEvent


class BrewTaskStateChangeParser(BaseParser):
    """
    Parser parsing task state change message from Brew.

    Unlike koji, Brew sends such messages with topics of 'brew.task.closed'
    and 'brew.task.failed'.
    """

    name = "BrewTaskStateChangeParser"
    topic_suffixes = ["brew.task.closed", 'brew.task.failed']

    def can_parse(self, topic, msg):
        return any([topic.endswith(s) for s in self.topic_suffixes])

    def parse(self, topic, msg):
        msg_id = msg.get('msg_id')
        inner_msg = msg.get('msg')
        old_state = inner_msg.get('old')
        new_state = inner_msg.get('new')
        task_info = inner_msg.get('info', {})
        task_id = task_info.get('id')
        task_method = task_info.get('method')

        if task_method == 'buildContainer':
            request = task_info.get('request')
            (git_url, target, opts) = request
            branch = opts.get('git_branch', None)
            m = re.match(r".*/(?P<container>[^#]*)", git_url)
            container = m.group('container')
            return BrewContainerTaskStateChangeEvent(msg_id, container, branch, target, task_id, old_state, new_state)
