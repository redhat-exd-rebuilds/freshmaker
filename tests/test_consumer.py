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

import freshmaker


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    @mock.patch("freshmaker.handlers.mbs.MBS.handle_module_built")
    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_processing_message(self, global_consumer, handle_module_built):
        """
        Tests that consumer parses the message, forwards the event
        to proper handler and is able to get the further work from
        the handler.
        """
        hub = mock.MagicMock()
        hub.config = fedmsg.config.load_config()
        hub.config['freshmakerconsumer'] = True
        consumer = freshmaker.consumer.FreshmakerConsumer(hub)
        global_consumer.return_value = consumer

        msg = {'body': {
            "msg_id": "2017-7afcb214-cf82-4130-92d2-22f45cf59cf7",
            "topic": "org.fedoraproject.prod.mbs.module.state.change",
            "signature": "qRZ6oXBpKD/q8BTjBNa4MREkAPxT+KzI8Oret+TSKazGq/6gk0uuprdFpkfBXLR5dd4XDoh3NQWp\nyC74VYTDVqJR7IsEaqHtrv01x1qoguU/IRWnzrkGwqXm+Es4W0QZjHisBIRRZ4ywYBG+DtWuskvy\n6/5Mc3dXaUBcm5TnT0c=\n",
            "msg": {
                "state": 5,
                "id": 70,
                "state_name": "ready"
            }
        }}

        handle_module_built.return_value = [freshmaker.events.TestingEvent("ModuleBuilt handled")]
        consumer.consume(msg)

        event = consumer.incoming.get()
        self.assertEqual(event.msg_id, "ModuleBuilt handled")

    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_subscribe_to_specified_topics(self, global_consumer):
        """
        Tests consumer will try to subscribe specified topics.
        """
        hub = mock.MagicMock()
        hub.config = fedmsg.config.load_config()
        consumer = freshmaker.consumer.FreshmakerConsumer(hub)
        global_consumer.return_value = consumer
        topics = freshmaker.events.BaseEvent.get_parsed_topics()
        callback = consumer._consume_json if consumer.jsonify else consumer.consume
        for topic in topics:
            self.assertIn(mock.call(topic, callback), hub.subscribe.call_args_list)


if __name__ == '__main__':
    unittest.main()
