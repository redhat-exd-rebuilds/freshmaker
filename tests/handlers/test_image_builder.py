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
import pytest
import six
import unittest

from mock import patch
from mock import MagicMock
from freshmaker.consumer import FreshmakerConsumer
from tests import get_fedmsg


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestImageBuilderHandler(unittest.TestCase):

    def create_consumer(self):
        hub = MagicMock()
        hub.config = fedmsg.config.load_config()
        return FreshmakerConsumer(hub)

    @patch("requests.request")
    @patch('freshmaker.consumer.get_global_consumer')
    def consume_git_receive_msg(self, msg, global_consumer, request):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer
        consumer.consume(msg)

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_rebuild_if_Dockerfile_changed(self, ClientSession, read_config):
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
        }

        self.consume_git_receive_msg(get_fedmsg("git_receive_dockerfile_changed"))

        mock_session = ClientSession.return_value
        mock_session.krb_login.assert_called_once_with(proxyuser=None)
        mock_session.buildContainer.assert_called_once_with(
            'git://pkgs.fedoraproject.org/container/testimage.git#e1f39d43471fc37ec82616f76a119da4eddec787',
            'rawhide-container-candidate',
            {'scratch': True, 'git_branch': 'master'})
        mock_session.logout.assert_called_once()

    @patch('freshmaker.handlers.image_builder.DockerImageRebuildHandler.build_image')
    def test_not_rebuild_if_Dockerfile_not_changed(self, build_image):
        self.consume_git_receive_msg(get_fedmsg("git_receive_dockerfile_not_changed"))
        build_image.assert_not_called()

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_ensure_logout_in_whatever_case(self, ClientSession, read_config):
        ClientSession.return_value.buildContainer.side_effect = RuntimeError
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
        }

        self.consume_git_receive_msg(get_fedmsg("git_receive_dockerfile_changed"))

        ClientSession.return_value.logout.assert_called_once()

    @patch('koji.read_config')
    @patch('koji.ClientSession')
    def test_ensure_do_nothing_if_fail_to_login_koji(self, ClientSession, read_config):
        ClientSession.return_value.krb_login.side_effect = RuntimeError
        read_config.return_value = {
            'server': 'https://localhost/kojihub',
            'krb_rdns': False,
        }

        self.consume_git_receive_msg(get_fedmsg("git_receive_dockerfile_changed"))

        ClientSession.return_value.buildContainer.assert_not_called()
