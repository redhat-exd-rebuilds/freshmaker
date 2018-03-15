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
import koji

from mock import patch
from functools import wraps

from freshmaker import events
from freshmaker import db
from freshmaker.models import User


BUILD_STATES = {
    "init": 0,
    "wait": 1,
    "build": 2,
    "done": 3,
    "failed": 4,
    "ready": 5,
}


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


class Patcher(object):
    def __init__(self, prefix=None):
        self.prefix = prefix or ""
        self.patchers = []

    def patch(self, name, *args, **kwargs):
        if name.startswith("freshmaker."):
            prefix = ""
        else:
            prefix = self.prefix
        patcher = patch("%s%s" % (prefix, name), *args, **kwargs)
        self.patchers.append(patcher)
        patched_object = patcher.start()
        return patched_object

    def patch_dict(self, name, new):
        if name.startswith("freshmaker."):
            prefix = ""
        else:
            prefix = self.prefix
        patcher = patch.dict("%s%s" % (prefix, name), new)
        self.patchers.append(patcher)
        patched_object = patcher.start()
        return patched_object

    def unpatch_all(self):
        for patcher in self.patchers:
            patcher.stop()


class FreshmakerTestCase(unittest.TestCase):

    def setUp(self):
        # We don't have any valid Kerberos context during the tests, so disable
        # it by default by patching it.
        self.krb_context_patcher = patch('freshmaker.utils.krbContext')
        self.krb_context_patcher.start()

    def tearDown(self):
        self.krb_context_patcher.stop()

    def get_event_from_msg(self, message):
        event = events.BaseEvent.from_fedmsg(message['body']['topic'], message['body'])
        return event


class ModelsTestCase(FreshmakerTestCase):

    def setUp(self):
        super(ModelsTestCase, self).setUp()
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.user = User(username='tester1')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        super(ModelsTestCase, self).tearDown()

        db.session.remove()
        db.drop_all()
        db.session.commit()


class MockedKoji(object):
    def __init__(self):
        self._koji_service = None

        # {"tag_name": ["build1_nvr", "build2_nvr", ...], ...}
        # The list of build NVRs is kept sorted.
        self.tags = {}
        # ["build_nvr": [{"rpm_nvr": nvr, ...}, ...], ...]
        self.rpms = {}

    def add_tag(self, tag_name):
        """
        Adds new tag to Mocked Koji.
        """
        if tag_name in self.tags:
            return
        self.tags[tag_name] = []

    def tag_build(self, tag_name, nvr):
        """
        Tags the build `nvr` to tag `tag_name`.
        """
        self.tags[tag_name].append(nvr)
        self.tags[tag_name].sort()

    def add_build(self, nvr, tags=None):
        """
        Adds build `nvr` to Mocked Koji. Tags the build into `tags`. If tags
        are not defined, ["tag-candidate", "tag-pending", "tag-alpha-1.0-set"]
        is used. If the tags do not exist in Mocked Koji, they are added
        automatically.
        """
        if not tags:
            tags = ["tag-candidate", "tag-pending", "tag-alpha-1.0-set"]

        for tag in tags:
            self.add_tag(tag)
            self.tag_build(tag, nvr)

    def add_build_rpms(self, build_nvr, rpm_nvrs=None, arches=None):
        """
        Adds list of RPMs defined as NVRs in `rpms_nvrs` list into build
        defined by `build_nvr` NVR.
        If `rpm_nvrs` is not defined, build_nvr is used as default NVR.
        If `arches` is not defined, ["src", "ppc", "i686", "x86_64"] is used as
        default list of arches.
        """
        if build_nvr not in self.rpms:
            self.rpms[build_nvr] = []

        if not rpm_nvrs:
            rpm_nvrs = [build_nvr]

        if not arches:
            arches = ["src", "ppc", "i686", "x86_64"]

        for nvr in rpm_nvrs:
            for arch in arches:
                parsed_nvr = koji.parse_NVR(nvr)
                self.rpms[build_nvr].append({
                    'arch': arch,
                    'name': parsed_nvr["name"],
                    'release': parsed_nvr["release"],
                    'version': parsed_nvr["version"],
                    'nvr': nvr,
                })

    def _get_build_rpms(self, build_nvr, arches=None):
        """
        Mocks the KojiService.get_build_rpms.
        """
        if not arches:
            return self.rpms[build_nvr]

        return [rpm for rpm in self.rpms[build_nvr] if rpm["arch"] in arches]

    def _get_build_target(self, build_target):
        """
        Mocks the KojiService.get_build_target.
        """
        if build_target == "guest-rhel-7.4-docker":
            return {
                'build_tag': 10052,
                'build_tag_name': 'guest-rhel-7.4-docker-build',
                'dest_tag': 10051,
                'dest_tag_name': 'guest-rhel-7.4-candidate',
                'id': 3205,
                'name': 'guest-rhel-7.4-docker'
            }
        return None

    def _session_list_tags(self, nvr):
        """
        Mocks KojiService.session.listTags.
        """
        ret = []
        for tag_name, nvrs in self.tags.items():
            if nvr in nvrs:
                ret.append({
                    "name": tag_name
                })
        return ret

    def _session_list_tagged(self, tag, **kwargs):
        """
        Mocks KojiService.session.listTagged.
        """
        if "latest" in kwargs and kwargs["latest"]:
            return_latest = True
        else:
            return_latest = False

        ret = []
        packages = []
        for nvr in self.tags[tag]:
            package = koji.parse_NVR(nvr)["name"]
            if return_latest and package in packages:
                continue

            packages.append(package)
            ret.append({
                'nvr': nvr,
            })

        return ret

    def start(self):
        """
        Starts the Koji mocking.
        """
        self._mocked_koji_service_patch = patch(
            'freshmaker.kojiservice.KojiService')
        self._koji_service = self._mocked_koji_service_patch.start().return_value

        self._koji_service.get_build_target.side_effect = self._get_build_target
        self._koji_service.get_build_rpms.side_effect = self._get_build_rpms

        self._koji_session = self._koji_service.session
        self._koji_session.listTags.side_effect = self._session_list_tags
        self._koji_session.listTagged.side_effect = self._session_list_tagged

        return self

    def stop(self):
        """
        Stops the Koji mocking.
        """
        if self._koji_service:
            self._mocked_koji_service_patch.stop()
            self._koji_service = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()


def mock_koji(f):
    """
    Wrapper which mocks the Koji. It adds MockedKoji instance as the last
    *arg of original ufnction.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        with MockedKoji() as mocked_koji:
            return f(*args + (mocked_koji, ), **kwargs)

    return wrapped


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
    def __init__(self, name, stream, version, active=True):
        self.name = name
        self.stream = stream
        self.version = version
        self.active = active
        self.uid = "%s-%s-%s" % (name, stream, version)
        self.modulemd = ''
        self.build_deps = []
        self.runtime_deps = []
        self.koji_tag = 'module-%s' % ''.join([random.choice(string.ascii_letters[:6] + string.digits) for n in range(16)])
        self.rpms = []

    def produce(self):
        module = {
            'active': self.active,
            'name': self.name,
            'stream': self.stream,
            'version': self.version,
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
