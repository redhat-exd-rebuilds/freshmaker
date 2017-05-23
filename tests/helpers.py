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

import random
import six
import string
import time
import uuid
import unittest

from freshmaker import events


BUILD_STATES = {
    "init": 0,
    "wait": 1,
    "build": 2,
    "done": 3,
    "failed": 4,
    "ready": 5,
}


class FreshmakerTestCase(unittest.TestCase):
    def get_event_from_msg(self, message):
        event = events.BaseEvent.from_fedmsg(message['body']['topic'], message['body'])
        return event


class FedMsgFactory(object):
    def __init__(self, *args, **kwargs):
        self.msg_id = "%s-%s" % (time.strftime("%Y"), uuid.uuid4())
        self.msg = {}
        self.signature = '123'
        self.source_name = 'unittest'
        self.source_version = '0.1.1'
        self.timestamp = time.time()
        self.topic = ''
        self.username = 'freshmaker'
        self.i = random.randint(0, 100)

    @property
    def inner_msg(self):
        return {}

    def produce(self):
        message_body = {
            'i': self.i,
            'msg_id': self.msg_id,
            'topic': self.topic,
            'username': self.username,
            'timestamp': self.timestamp,
            'signature': self.signature,
            'source_name': self.source_name,
            'source_version': self.source_version,
            'msg': self.inner_msg,
        }
        return {
            'body': message_body,
            'topic': self.topic
        }


class ModuleStateChangeMessage(FedMsgFactory):
    def __init__(self, name, stream, state='ready', build_id=None, *args, **kwargs):
        super(ModuleStateChangeMessage, self).__init__(*args, **kwargs)
        self.topic = 'org.fedoraproject.prod.mbs.module.state.change'
        self.name = name
        self.stream = stream
        self.state = state
        self.build_id = build_id if build_id else random.randint(0, 1000)
        self.scmurl = "git://pkgs.fedoraproject.org/modules/%s?#%s" % (self.name, '123')

        self._states_dict = {}
        for state, code in six.iteritems(BUILD_STATES):
            self._states_dict[state] = {'state_name': state, 'state': code}

    @property
    def inner_msg(self):
        return {
            'component_builds': [],
            'id': self.build_id,
            'modulemd': '',
            'name': self.name,
            'owner': 'freshmaker',
            'scmurl': self.scmurl,
            'state': self._states_dict[self.state]['state'],
            'state_name': self.state,
            'state_reason': None,
            'state_trace': [],
            'state_url': u'/module-build-service/1/module-builds/%s' % self.build_id,
            'stream': u'master',
            'tasks': {},
            'time_completed': None,
            'time_modified': None,
            'time_submitted': time.time(),
            'version': time.strftime("%Y%m%d%H%M%S"),
        }


class DistGitMessage(FedMsgFactory):
    def __init__(self, namespace, repo, branch, rev, *args, **kwargs):
        super(DistGitMessage, self).__init__(*args, **kwargs)
        self.topic = 'org.fedoraproject.prod.git.receive'
        self.namespace = namespace
        self.repo = repo
        self.branch = branch
        self.rev = rev
        self.stats = {
            'files': {},
            'total': {
                'additions': 0,
                'deletions': 0,
                'files': 0,
                'lines': 0,
            }
        }

    @property
    def inner_msg(self):
        return {
            'commit': {
                'repo': self.repo,
                'namespace': self.namespace,
                'branch': self.branch,
                'rev': self.rev,
                'agent': 'freshmaker',
                'name': 'freshmaker',
                'username': 'freshmaker',
                'email': 'freshmaker@example.com',
                'message': 'test message',
                'summary': 'test',
                'path': "/srv/git/repositories/%s/%s.git" % (self.namespace, self.repo),
                'seen': False,
                'stats': self.stats,
            }
        }

    def add_changed_file(self, filename, additions, deletions):
        self.stats['files'].setdefault(filename, {})['additions'] = additions
        self.stats['files'][filename]['deletions'] = deletions
        self.stats['files'][filename]['lines'] = additions + deletions
        self.stats['total']['additions'] += additions
        self.stats['total']['deletions'] += deletions
        self.stats['total']['files'] += 1
        self.stats['total']['lines'] += self.stats['files'][filename]['lines']


class KojiTaskStateChangeMessage(FedMsgFactory):
    def __init__(self, task_id, old_state, new_state, *args, **kwargs):
        super(KojiTaskStateChangeMessage, self).__init__(*args, **kwargs)
        self.topic = 'org.fedoraproject.prod.buildsys.task.state.change'
        self.attribute = 'state'
        self.task_id = task_id
        self.old_state = old_state
        self.new_state = new_state
        self.owner = 'freshmaker'
        self.method = 'build'

    @property
    def inner_msg(self):
        return {
            'attribute': self.attribute,
            'id': self.task_id,
            'method': self.method,
            'new': self.new_state,
            'old': self.old_state,
            'owner': self.owner,
        }


class PDCModuleInfoFactory(object):
    def __init__(self, name, version, release, active=True):
        self.variant_name = name
        self.variant_version = version
        self.variant_release = release
        self.active = active
        self.variant_uid = "%s-%s-%s" % (name, version, release)
        self.variant_id = name
        self.variant_type = 'module'
        self.modulemd = ''
        self.build_deps = []
        self.runtime_deps = []
        self.koji_tag = 'module-%s' % ''.join([random.choice(string.ascii_letters[:6] + string.digits) for n in range(16)])
        self.rpms = []

    def produce(self):
        module = {
            'active': self.active,
            'variant_type': self.variant_type,
            'variant_id': self.variant_id,
            'variant_name': self.variant_name,
            'variant_version': self.variant_version,
            'variant_release': self.variant_release,
            'variant_uid': self.variant_uid,
            'modulemd': self.modulemd,
            'koji_tag': self.koji_tag,
            'build_deps': self.build_deps,
            'runtime_deps': self.runtime_deps,
            'rpms': self.rpms,
        }
        return module


class PDCModuleInfo(PDCModuleInfoFactory):
    def add_build_dep(self, name, stream):
        self.build_deps.append({'dependency': name, 'stream': stream})

    def add_rpm(self, rpm):
        self.rpms.append(rpm)
