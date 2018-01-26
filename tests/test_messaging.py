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


import six
import unittest

from mock import patch

from freshmaker import conf
from freshmaker import messaging
from freshmaker.messaging import publish
from tests import helpers

try:
    import rhmsg
except ImportError:
    rhmsg = None


class BaseMessagingTest(helpers.FreshmakerTestCase):
    """ Base class for messaging related tests """

    def setUp(self):
        super(BaseMessagingTest, self).setUp()
        messaging._in_memory_msg_id = 0

    def tearDown(self):
        super(BaseMessagingTest, self).tearDown()
        messaging._in_memory_msg_id = 0


class TestSelectMessagingBackend(BaseMessagingTest):
    """Test messaging backend is selected correctly in publish method"""

    @patch('freshmaker.messaging._fedmsg_publish')
    @patch('freshmaker.messaging._rhmsg_publish')
    @patch('freshmaker.messaging._in_memory_publish')
    def test_select_backend(
            self, _in_memory_publish, _rhmsg_publish, _fedmsg_publish):
        fake_msg = {'build': 'n-v-r'}

        mock_messaging_backends = {
            'fedmsg': {'publish': _fedmsg_publish},
            'rhmsg': {'publish': _rhmsg_publish},
            'in_memory': {'publish': _in_memory_publish},
        }
        with patch.dict('freshmaker.messaging._messaging_backends',
                        mock_messaging_backends):
            with patch.object(conf, 'messaging_sender', new='fedmsg'):
                publish('images.ready', fake_msg)
                _fedmsg_publish.assert_called_once_with(
                    'images.ready', fake_msg)

            with patch.object(conf, 'messaging_sender', new='rhmsg'):
                publish('images.ready', fake_msg)
                _rhmsg_publish.assert_called_once_with(
                    'images.ready', fake_msg)

            with patch.object(conf, 'messaging_sender', new='in_memory'):
                publish('images.ready', fake_msg)
                _in_memory_publish.assert_called_once_with(
                    'images.ready', fake_msg)

    def test_raise_error_if_backend_not_exists(self):
        messaging_patcher = patch.object(conf, 'messaging_sender', new='XXXX')
        six.assertRaisesRegex(
            self, ValueError, 'Unsupported messaging system',
            messaging_patcher.start)


class TestPublishToFedmsg(BaseMessagingTest):
    """Test publish message to fedmsg using _fedmsg_publish backend"""

    @patch.object(conf, 'messaging_sender', new='fedmsg')
    @patch.object(conf, 'messaging_backends',
                  new={'fedmsg': {'SERVICE': 'freshmaker'}})
    @patch('fedmsg.publish')
    def test_publish(self, fedmsg_publish):
        fake_msg = {}
        publish('images.ready', fake_msg)

        fedmsg_publish.assert_called_once_with(
            'images.ready', msg=fake_msg, modname='freshmaker')


@unittest.skipUnless(rhmsg, 'rhmsg is not available in Fedora yet.')
@unittest.skipIf(six.PY3, 'rhmsg has no Python 3 package so far.')
class TestPublishToRhmsg(BaseMessagingTest):
    """Test publish message to UMB using _rhmsg_publish backend"""

    @patch.object(conf, 'messaging_sender', new='rhmsg')
    @patch('rhmsg.activemq.producer.AMQProducer')
    @patch('proton.Message')
    def test_publish(self, Message, AMQProducer):
        fake_msg = {}
        rhmsg_config = {
            'rhmsg': {
                'BROKER_URLS': ['amqps://localhost:5671'],
                'CERT_FILE': '/path/to/cert',
                'KEY_FILE': '/path/to/key',
                'CA_CERT': '/path/to/ca-cert',
                'TOPIC_PREFIX': 'VirtualTopic.eng.freshmaker',
            }
        }
        with patch.object(conf, 'messaging_backends', new=rhmsg_config):
            publish('images.ready', fake_msg)

        AMQProducer.assert_called_with(**{
            'urls': ['amqps://localhost:5671'],
            'certificate': '/path/to/cert',
            'private_key': '/path/to/key',
            'trusted_certificates': '/path/to/ca-cert',
        })
        producer = AMQProducer.return_value.__enter__.return_value
        producer.through_topic.assert_called_once_with(
            'VirtualTopic.eng.freshmaker.images.ready')
        producer.send.assert_called_once_with(
            Message.return_value)


class TestInMemoryPublish(BaseMessagingTest):
    """Test publish message in memory using _in_memory_publish backend"""

    @patch('freshmaker.consumer.work_queue_put')
    @patch('freshmaker.events.BaseEvent.from_fedmsg')
    def test_publish(self, from_fedmsg, work_queue_put):
        fake_msg = {}
        in_memory_config = {
            'in_memory': {'SERVICE': 'freshmaker'}
        }

        with patch.object(conf, 'messaging_backends', new=in_memory_config):
            publish('images.ready', fake_msg)

        from_fedmsg.assert_called_once_with(
            'freshmaker.images.ready',
            {'msg_id': '1', 'msg': fake_msg})
        work_queue_put.assert_called_once_with(from_fedmsg.return_value)
