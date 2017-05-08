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

from freshmaker import log, conf
from freshmaker.parsers import BaseParser
from freshmaker.events import ModuleMetadataUpdated
from freshmaker.events import DockerfileChanged
from freshmaker.events import RPMSpecUpdated


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
        rev = commit.get("rev")
        repo = commit.get("repo")
        branch = commit.get("branch")

        log.debug(namespace)

        if namespace == "modules":
            scm_url = "%s/%s/%s.git?#%s" % (conf.git_base_url, namespace, repo, rev)
            log.debug("Parsed ModuleMetadataUpdated fedmsg, scm_url=%s, "
                      "branch=%s", scm_url, branch)
            return ModuleMetadataUpdated(msg_id, scm_url, repo, branch)

        elif namespace == 'container':
            changed_files = msg['msg']['commit']['stats']['files']
            if 'Dockerfile' not in changed_files:
                log.debug('Dockerfile is not changed in repo {}'.format(repo))
                return None

            log.debug('Parsed DockerfileChanged fedmsg')
            repo_url = '{}/{}/{}.git'.format(conf.git_base_url, namespace, repo)
            return DockerfileChanged(msg_id, repo_url=repo_url, branch=branch,
                                     namespace=namespace, repo=repo, rev=rev)
        elif namespace == 'rpms':
            component = commit.get('repo')
            branch = commit.get('branch')
            rev = commit.get('rev')
            changed_files = commit.get('stats', {}).get('files', {}).keys()
            has_spec = any([i.endswith('.spec') for i in changed_files])
            if has_spec:
                return RPMSpecUpdated(msg_id, component, branch, rev=rev)

        return None
