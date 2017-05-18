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
# Written by Chenxiong Qi <cqi@redhat.com>

import tempfile
import unittest

import fedmsg.config
import pytest
import six

from mock import patch
from mock import MagicMock
from mock import call

from freshmaker import conf, db, models
from freshmaker.consumer import FreshmakerConsumer
from freshmaker.handlers.image_builder import DockerImageRebuildHandlerForBodhi
from tests import get_fedmsg


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def create_consumer(self):
        hub = MagicMock()
        hub.config = fedmsg.config.load_config()
        return FreshmakerConsumer(hub)

    @patch("requests.request")
    @patch('freshmaker.consumer.get_global_consumer')
    def consume_fedmsg(self, msg, global_consumer, request):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer
        consumer.consume(msg)


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestImageBuilderHandler(BaseTestCase):

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_rebuild_if_Dockerfile_changed(self, ClientSession, read_config):
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
            'weburl': 'https://localhost/koji',
        }

        mock_session = ClientSession.return_value
        mock_session.buildContainer.return_value = 123
        msg = get_fedmsg('git_receive_dockerfile_changed')
        self.consume_fedmsg(msg)

        mock_session.krb_login.assert_called_once_with(proxyuser=None)
        mock_session.buildContainer.assert_called_once_with(
            'git://pkgs.fedoraproject.org/container/testimage.git?#e1f39d43471fc37ec82616f76a119da4eddec787',
            'rawhide-container-candidate',
            {'scratch': True, 'git_branch': 'master'})
        mock_session.logout.assert_called_once()

        events = models.Event.query.all()
        self.assertEquals(len(events), 1)
        self.assertEquals(events[0].message_id, msg['body']['msg_id'])
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        self.assertEquals(builds[0].name, 'testimage')
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['image'])
        self.assertEquals(builds[0].build_id, 123)

    @patch('freshmaker.handlers.image_builder.DockerImageRebuildHandler.build_image')
    def test_not_rebuild_if_Dockerfile_not_changed(self, build_image):
        self.consume_fedmsg(get_fedmsg('git_receive_dockerfile_not_changed'))
        build_image.assert_not_called()

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_ensure_logout_in_whatever_case(self, ClientSession, read_config):
        ClientSession.return_value.buildContainer.side_effect = RuntimeError
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
            'weburl': 'https://localhost/koji',
        }

        self.consume_fedmsg(get_fedmsg('git_receive_dockerfile_changed'))

        ClientSession.return_value.logout.assert_called_once()

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_ensure_do_nothing_if_fail_to_login_koji(self, ClientSession, read_config):
        ClientSession.return_value.krb_login.side_effect = RuntimeError
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
            'weburl': 'https://localhost/koji',
        }

        self.consume_fedmsg(get_fedmsg('git_receive_dockerfile_changed'))

        ClientSession.return_value.buildContainer.assert_not_called()


mock_found_containers = [
    {
        'release': 'fedora-25-updates',
        'id': 5430,
        'name': 'testimage1',
        'branch': 'f25',
    },
    {
        'release': 'fedora-25-updates',
        'id': 5431,
        'name': 'testimage2',
        'branch': 'f25',
    },
]

mock_release_components = {
    5430: {
        'id': 5430,
        'release': {
            'active': True,
            'release_id': 'fedora-25-updates'
        },
        'bugzilla_component': None,
        'brew_package': None,
        'global_component': 'testimage1',
        'name': 'testimage1',
        'dist_git_branch': 'f25',
        'dist_git_web_url': 'http://pkgs.example.com/cgit/container/testimage1',
        'active': True,
        'type': 'container',
        'srpm': None,
    },
    5431: {
        'id': 5431,
        'release': {
            'active': True,
            'release_id': 'fedora-25-updates'
        },
        'bugzilla_component': None,
        'brew_package': None,
        'global_component': 'testimage2',
        'name': 'testimage2',
        'dist_git_branch': 'f25',
        'dist_git_web_url': 'http://pkgs.example.com/cgit/container/testimage2',
        'active': True,
        'type': 'container',
        'srpm': None,
    }
}


def mock_get_release_component(pdc_session, id):
    return mock_release_components[id]


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestRebuildWhenBodhiUpdateStable(BaseTestCase):

    def setUp(self):
        super(TestRebuildWhenBodhiUpdateStable, self).setUp()
        # Use to return a temporary directory from temp_dir method. So, no need
        # to delete this directory, since temp_dir ensures to do that.
        self.working_dir = tempfile.mkdtemp(prefix='test-image-rebuild-')

    @patch('koji.ClientSession')
    @patch('tempfile.mkdtemp')
    @patch('freshmaker.handlers.image_builder._run_command')
    @patch('freshmaker.handlers.image_builder.get_commit_hash')
    @patch('freshmaker.handlers.image_builder.'
           'DockerImageRebuildHandlerForBodhi.get_rpms_included_in_bodhi_update')
    @patch('freshmaker.handlers.image_builder.'
           'DockerImageRebuildHandlerForBodhi.get_containers_including_rpms')
    @patch('freshmaker.pdc.get_release_component', new=mock_get_release_component)
    def test_rebuild(self,
                     get_containers_including_rpms,
                     get_rpms_included_in_bodhi_update,
                     get_commit_hash,
                     _run_command,
                     mkdtemp,
                     ClientSession):
        last_commit_hash = 'dea19c748434ec962f13d680682eee87393a4d8e'

        # A repository is not cloned actually, so just use a fake commit hash
        # to construct build source URL.
        get_commit_hash.return_value = last_commit_hash

        # temp_dir creates a temporary file using mkdtemp that is used for
        # working directory for everything related to rebuild docker image.
        # It is difficult to catch that temporary directory, so mock mkdtemp
        # and use this test's own directory.
        mkdtemp.return_value = self.working_dir

        get_containers_including_rpms.return_value = mock_found_containers

        session = ClientSession.return_value
        session.buildContainer.side_effect = [123, 456]

        msg = get_fedmsg('bodhi_update_stable')
        self.consume_fedmsg(msg)

        self.assertEqual(2, _run_command.call_count)

        _run_command.assert_has_calls([
            call(['git', 'clone', '-b', 'f25',
                  '{}/container/{}'.format(conf.git_base_url, 'testimage1')],
                 rundir=self.working_dir),
            call(['git', 'clone', '-b', 'f25',
                  '{}/container/{}'.format(conf.git_base_url, 'testimage2')],
                 rundir=self.working_dir)
        ])

        self.assertEqual(2, session.krb_login.call_count)

        buildContainer = session.buildContainer
        self.assertEqual(2, buildContainer.call_count)
        buildContainer.assert_has_calls([
            call('{}/container/{}?#{}'.format(conf.git_base_url,
                                              'testimage1',
                                              last_commit_hash),
                 'f25-container-candidate',
                 {'scratch': True, 'git_branch': 'f25'}),
            call('{}/container/{}?#{}'.format(conf.git_base_url,
                                              'testimage2',
                                              last_commit_hash),
                 'f25-container-candidate',
                 {'scratch': True, 'git_branch': 'f25'}),
        ], any_order=True)

        events = models.Event.query.all()
        self.assertEquals(len(events), 1)
        self.assertEquals(events[0].message_id, msg['body']['msg_id'])
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 2)
        self.assertEquals(builds[0].name, 'testimage1')
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['image'])
        self.assertEquals(builds[0].build_id, 123)
        self.assertEquals(builds[1].name, 'testimage2')
        self.assertEquals(builds[1].type, models.ARTIFACT_TYPES['image'])
        self.assertEquals(builds[1].build_id, 456)


class TestContainersIncludingRPMs(unittest.TestCase):

    @patch('freshmaker.pdc.get_release_component', new=mock_get_release_component)
    @patch('freshmaker.handlers.image_builder.pdc.find_containers_by_rpm_name')
    def test_get_containers(self, find_containers_by_rpm_name):
        expected_found_containers = [
            {
                'release': 'fedora-24-updates',
                'id': 5430,
                'name': 'testimage1',
                'branch': 'f25',
            },
            {
                'release': 'fedora-24-updates',
                'id': 5431,
                'name': 'testimage2',
                'branch': 'f25',
            },
        ]
        find_containers_by_rpm_name.return_value = expected_found_containers

        handler = DockerImageRebuildHandlerForBodhi()
        rpms = [
            {'id': 9515683,
             'name': 'community-mysql-devel',
             'nvr': 'community-mysql-devel-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
            {'id': 9515682,
             'name': 'community-mysql-libs',
             'nvr': 'community-mysql-libs-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
            {'id': 9515681,
             'name': 'community-mysql-server',
             'nvr': 'community-mysql-server-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
        ]

        containers = handler.get_containers_including_rpms(rpms)

        self.assertEqual(3, find_containers_by_rpm_name.call_count)
        found_containers = sorted(containers, key=lambda item: item['id'])
        self.assertEqual(expected_found_containers, found_containers)


def mock_get_build_rpms(self, nvr):
    """Used to patch KojiService.get_build_rpms"""

    rpms = {
        'community-mysql-5.7.18-2.fc25': [
            {
                'id': 9515683,
                'name': 'community-mysql-devel',
                'nvr': 'community-mysql-devel-5.7.18-2.fc25',
                'release': '2.fc25',
                'version': '5.7.18',
            },
            {
                'id': 9515682,
                'name': 'community-mysql-libs',
                'nvr': 'community-mysql-libs-5.7.18-2.fc25',
                'release': '2.fc25',
                'version': '5.7.18',
            },
            {
                'id': 9515681,
                'name': 'community-mysql-server',
                'nvr': 'community-mysql-server-5.7.18-2.fc25',
                'release': '2.fc25',
                'version': '5.7.18',
            },
        ],
        'qt5-qtwebengine-5.8.0-11.fc25': [
            {
                'id': 9571317,
                'name': 'qt5-qtwebengine-devel',
                'nvr': 'qt5-qtwebengine-devel-5.8.0-11.fc25',
                'release': '11.fc25',
                'version': '5.8.0',
            },
            {
                'id': 9571316,
                'name': 'qt5-qtwebengine-examples',
                'nvr': 'qt5-qtwebengine-examples-5.8.0-11.fc25',
                'release': '11.fc25',
                'version': '5.8.0',
            }
        ],
    }

    return rpms[nvr]


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestGetRpmsIncludedInBodhiUpdate(unittest.TestCase):
    """Test case for get_rpms_included_in_bodhi_update"""

    @patch('freshmaker.kojiservice.KojiService.get_build_rpms',
           new=mock_get_build_rpms)
    def test_get_rpms(self):
        builds = [
            {
                'build_id': 884455,
                'name': 'qt5-qtwebengine',
                'nvr': 'qt5-qtwebengine-5.8.0-11.fc25',
                'release': '11.fc25',
                'version': '5.8.0',
            },
            {
                'build_id': 881597,
                'name': 'community-mysql',
                'nvr': 'community-mysql-5.7.18-2.fc25',
                'release': '2.fc25',
                'version': '5.7.18',
            }
        ]
        handler = DockerImageRebuildHandlerForBodhi()
        rpms = list(handler.get_rpms_included_in_bodhi_update(builds))

        self.assertEqual(5, len(rpms))

        rpm = filter(lambda item: item['id'] == 9515681, rpms)
        self.assertEqual(1, len(rpm))
