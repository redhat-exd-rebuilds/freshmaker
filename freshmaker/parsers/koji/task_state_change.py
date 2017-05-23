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
from freshmaker.parsers import BaseParser
from freshmaker.events import KojiTaskStateChangeEvent


class KojiTaskStateChangeParser(BaseParser):
    """
    Parser parsing task state change message from buildsys (koji), generating
    KojiTaskStateChanged event.
    """
    name = "KojiTaskStateChangeParser"
    topic_suffixes = ["buildsys.task.state.change"]

    def can_parse(self, topic, msg):
        log.debug(topic)
        if not any([topic.endswith(s) for s in self.topic_suffixes]):
            return False
        return True

    def parse(self, topic, msg):
        msg_id = msg.get('msg_id')
        msg_inner_msg = msg.get('msg')

        # If there isn't a msg dict in msg then this message can be skipped
        if not msg_inner_msg:
            log.debug(('Skipping message without any content with the '
                      'topic "{0}"').format(topic))
            return None

        return KojiTaskStateChangeEvent(msg_id,
                                        msg_inner_msg.get('id'),
                                        msg_inner_msg.get('new'))
