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
# Written by Ralph Bean <rbean@redhat.com>
#            Matt Prahl <mprahl@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

"""Generic messaging functions."""

import json

from freshmaker import log, conf
from freshmaker.events import BaseEvent


def publish(topic, msg):
    """
    Publish a single message to a given backend, and return

    :param str topic: the topic of the message (e.g. module.state.change)
    :param dict msg: the message contents of the message (typically JSON)
    :return: the value returned from underlying backend "send" method.
    """
    try:
        handler = _messaging_backends[conf.messaging_sender]['publish']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % conf.messaging)
    return handler(topic, msg)


def _fedmsg_publish(topic, msg):
    # fedmsg doesn't really need access to conf, however other backends do
    import fedmsg
    config = conf.messaging_backends['fedmsg']
    return fedmsg.publish(topic, msg=msg, modname=config['SERVICE'])


def _rhmsg_publish(topic, msg):
    """Send message to Unified Message Bus

    :param str topic: the topic where message will be sent to (e.g.
        images.found)
    :param dict msg: the message that will be sent
    """
    import proton
    from rhmsg.activemq.producer import AMQProducer

    config = conf.messaging_backends['rhmsg']
    producer_config = {
        'urls': config['BROKER_URLS'],
        'certificate': config['CERT_FILE'],
        'private_key': config['KEY_FILE'],
        'trusted_certificates': config['CA_CERT'],
    }
    with AMQProducer(**producer_config) as producer:
        topic = '{0}.{1}'.format(config['TOPIC_PREFIX'], topic)
        producer.through_topic(topic)

        outgoing_msg = proton.Message()
        outgoing_msg.body = json.dumps(msg)
        producer.send(outgoing_msg)


# A counter used for in-memory messages.
_in_memory_msg_id = 0
_initial_messages = []


def _in_memory_publish(topic, msg):
    """ Puts the message into the in memory work queue. """
    # Increment the message ID.
    global _in_memory_msg_id
    _in_memory_msg_id += 1

    config = conf.messaging_backends['in_memory']

    # Create fake fedmsg from the message so we can reuse
    # the BaseEvent.from_fedmsg code to get the particular BaseEvent
    # class instance.
    wrapped_msg = BaseEvent.from_fedmsg(
        config['SERVICE'] + "." + topic,
        {"msg_id": str(_in_memory_msg_id), "msg": msg},
    )

    # Put the message to queue.
    from freshmaker.consumer import work_queue_put
    try:
        work_queue_put(wrapped_msg)
    except ValueError as e:
        log.warn("No FreshmakerConsumer found.  Shutting down?  %r" % e)
    except AttributeError as e:
        # In the event that `moksha.hub._hub` hasn't yet been initialized, we
        # need to store messages on the side until it becomes available.
        # As a last-ditch effort, try to hang initial messages in the config.
        log.warn("Hub not initialized.  Queueing on the side.")
        _initial_messages.append(wrapped_msg)


_messaging_backends = {
    'fedmsg': {
        'publish': _fedmsg_publish
    },
    'in_memory': {
        'publish': _in_memory_publish
    },
    'rhmsg': {
        'publish': _rhmsg_publish
    }
}
