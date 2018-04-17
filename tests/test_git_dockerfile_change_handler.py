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

import fedmsg.config

from mock import patch
from mock import MagicMock, PropertyMock

import freshmaker

from freshmaker import models
from freshmaker.consumer import FreshmakerConsumer
from freshmaker.types import ArtifactType
from freshmaker.config import any_
from tests import get_fedmsg, helpers


class BaseTestCase(helpers.ModelsTestCase):

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


class GitDockerfileChangeHandlerTest(BaseTestCase):

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    @patch("freshmaker.config.Config.krb_auth_principal",
           new_callable=PropertyMock, return_value="user@example.com")
    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'GitDockerfileChangeHandler': {
            'image': any_({'name': 'testimage'}, {'branch': 'master'})
        }
    })
    def test_rebuild_if_dockerfile_changed(
            self, auth_principal, ClientSession, read_config):
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
            'weburl': 'https://localhost/koji',
        }

        mock_session = ClientSession.return_value
        mock_session.buildContainer.return_value = 123
        msg = get_fedmsg('git_receive_dockerfile_changed')
        self.consume_fedmsg(msg)

        mock_session.krb_login.assert_called()
        mock_session.buildContainer.assert_called_once_with(
            'git://pkgs.fedoraproject.org/container/testimage.git?#e1f39d43471fc37ec82616f76a119da4eddec787',
            'rawhide-container-candidate',
            {'scratch': True, 'git_branch': 'master'})
        mock_session.logout.assert_called_once()

        events = models.Event.query.all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message_id, msg['body']['msg_id'])
        builds = models.ArtifactBuild.query.all()
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0].name, 'testimage')
        self.assertEqual(builds[0].type, ArtifactType.IMAGE.value)
        self.assertEqual(builds[0].build_id, 123)

    @patch('freshmaker.handlers.git.dockerfile_change.GitDockerfileChangeHandler.build_container')
    def test_not_rebuild_if_dockerfile_not_changed(self, build_container):
        self.consume_fedmsg(get_fedmsg('git_receive_dockerfile_not_changed'))
        build_container.assert_not_called()

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'GitDockerfileChangeHandler': {
            'image': any_({'name': 'testimage'}, {'branch': 'master'})
        }
    })
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
    @patch("freshmaker.config.Config.krb_auth_principal",
           new_callable=PropertyMock, return_value="user@example.com")
    def test_ensure_do_nothing_if_fail_to_login_koji(self, auth_principal, ClientSession, read_config):
        ClientSession.return_value.krb_login.side_effect = RuntimeError
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
            'weburl': 'https://localhost/koji',
        }

        self.consume_fedmsg(get_fedmsg('git_receive_dockerfile_changed'))

        ClientSession.return_value.buildContainer.assert_not_called()
