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
# Written by Jan Kaluza <jkaluza@redhat.com>

from freshmaker import log
from freshmaker.parsers import BaseParser
from freshmaker.events import GitDockerfileChangeEvent
from freshmaker.events import GitModuleMetadataChangeEvent
from freshmaker.events import GitRPMSpecChangeEvent


class GitReceiveParser(BaseParser):
    """
    Parser parsing message from dist-git.
    """
    name = "GitReceiveParser"
    topic_suffixes = ["git.receive"]

    def can_parse(self, topic, msg):
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

        commit = msg_inner_msg.get('commit')
        if not commit:
            log.debug(('Skipping message without commit with the '
                       'topic "{0}"').format(topic))
            return None

        namespace = commit.get("namespace")
        repo = commit.get("repo")
        branch = commit.get("branch")
        rev = commit.get("rev")

        log.debug(namespace)

        if namespace == "modules":
            log.debug("Parsed GitModuleMetadataChangeEvent fedmsg, repo=%s, "
                      "branch=%s, rev=%s", repo, branch, rev)
            return GitModuleMetadataChangeEvent(msg_id, repo, branch, rev)

        elif namespace == 'container':
            changed_files = msg['msg']['commit']['stats']['files']
            if 'Dockerfile' in changed_files:
                log.debug("Parsed GitDockerfileChangeEvent fedmsg, repo=%s, "
                          "branch=%s, rev=%s", repo, branch, rev)
                return GitDockerfileChangeEvent(msg_id, repo, branch, rev)

        elif namespace == 'rpms':
            changed_files = commit.get('stats', {}).get('files', {}).keys()
            has_spec = any([i.endswith('.spec') for i in changed_files])
            if has_spec:
                log.debug("Parsed GitRPMSpecChangeEvent fedmsg, repo=%s, "
                          "branch=%s, rev=%s", repo, branch, rev)
                return GitRPMSpecChangeEvent(msg_id, repo, branch, rev)

        return None
