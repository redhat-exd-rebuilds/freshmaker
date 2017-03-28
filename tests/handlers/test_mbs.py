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

import unittest
import mock
import fedmsg.config

from mock import patch
from freshmaker.consumer import FreshmakerConsumer
from tests import get_fedmsg


@patch("freshmaker.consumer.get_global_consumer")
class TestMBS(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    @patch("requests.request")
    def test_consumer_git_receive_module_updated(self, request, global_consumer):
        """
        Tests that MBS triggers the rebuild of module as a result of GitReceive
        fedmsg message.
        """
        hub = mock.MagicMock()
        hub.config = fedmsg.config.load_config()
        consumer = FreshmakerConsumer(hub)
        global_consumer.return_value = consumer

        consumer.consume(get_fedmsg("git_receive_module"))

        request.assert_called_once_with(
            'POST', 'https://mbs.fedoraproject.org/module-build-service/1/module-builds/',
            headers={'Authorization': 'Bearer testingtoken'},
            json={'scmurl': u'git://pkgs.fedoraproject.org/modules/testmodule.git?#e1f39d43471fc37ec82616f76a119da4eddec787',
                  'branch': u'master'})
