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
from unittest import mock

import freshmaker

from freshmaker.models import Event, ArtifactBuild
from freshmaker import db
from freshmaker.types import ArtifactBuildState
from freshmaker.handlers import fail_event_on_handler_exception
from tests import helpers


class ConsumerTest(helpers.ConsumerBaseTest):
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.can_handle")
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.handle")
    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_processing_message(self, global_consumer, handle, handler_can_handle):
        """
        Tests that consumer parses the message, forwards the event
        to proper handler and is able to get the further work from
        the handler.
        """
        consumer = self.create_consumer()
        global_consumer.return_value = consumer
        handle.return_value = [freshmaker.events.TestingEvent("ModuleBuilt handled")]

        handler_can_handle.return_value = True

        msg = self._compose_state_change_msg()
        consumer.consume(msg)

        event = consumer.incoming.get()
        self.assertEqual(event.msg_id, "ModuleBuilt handled")

    @mock.patch("freshmaker.handlers.koji.RebuildImagesOnODCSComposeDone.can_handle")
    @mock.patch(
        "freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.order",
        new_callable=mock.PropertyMock,
    )
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.can_handle")
    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_handlers_order(self, global_consumer, handler1, handler1_order, handler2):
        """
        Tests that consumer parses the message, forwards the event
        to proper handler and is able to get the further work from
        the handler.
        """
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        for reverse in [False, True]:
            order_lst = []

            def mocked_handler1(*args, **kwargs):
                order_lst.append(1)
                return False

            def mocked_handler2(*args, **kwargs):
                order_lst.append(2)
                return False

            handler1.side_effect = mocked_handler1
            handler2.side_effect = mocked_handler2
            handler1_order.return_value = 100 if reverse else 0

            msg = self._compose_state_change_msg()
            consumer.consume(msg)
            self.assertEqual(order_lst, [2, 1] if reverse else [1, 2])

    @mock.patch("freshmaker.handlers.koji.RebuildImagesOnODCSComposeDone.handle")
    @mock.patch("freshmaker.handlers.koji.RebuildImagesOnODCSComposeDone.can_handle")
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.handle")
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.can_handle")
    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_multiple_handlers_called(
        self, global_consumer, handler1_can_handle, handler1, handler2_can_handle, handler2
    ):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        handler1_can_handle.return_value = True
        handler2_can_handle.return_value = True
        msg = self._compose_state_change_msg()
        consumer.consume(msg)

        handler1.assert_called_once()
        handler2.assert_called_once()

    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_subscribe_to_specified_topics(self, global_consumer):
        """
        Tests consumer will try to subscribe specified topics.
        """
        consumer = self.create_consumer()
        global_consumer.return_value = consumer
        topics = freshmaker.events.BaseEvent.get_parsed_topics()
        callback = consumer._consume_json if consumer.jsonify else consumer.consume
        for topic in topics:
            self.assertIn(mock.call(topic, callback), consumer.hub.subscribe.call_args_list)

    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.can_handle")
    @mock.patch("freshmaker.handlers.internal.UpdateDBOnODCSComposeFail.handle", autospec=True)
    @mock.patch("freshmaker.consumer.get_global_consumer")
    def test_consumer_mark_event_as_failed_on_exception(
        self, global_consumer, handle, handler_can_handle
    ):
        """
        Tests that Consumer.consume marks the DB Event as failed in case there
        is an error in a handler.
        """
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        handler_can_handle.return_value = True

        @fail_event_on_handler_exception
        def mocked_handle(cls, msg):
            event = Event.get_or_create(db.session, "msg_id", "msg_id", 0)
            ArtifactBuild.create(db.session, event, "foo", 0)
            db.session.commit()
            cls.set_context(event)
            raise ValueError("Expected exception")

        handle.side_effect = mocked_handle

        msg = self._compose_state_change_msg()
        consumer.consume(msg)

        db_event = Event.get(db.session, "msg_id")
        for build in db_event.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            self.assertTrue(build.state_reason, "Failed with traceback")


if __name__ == "__main__":
    unittest.main()
