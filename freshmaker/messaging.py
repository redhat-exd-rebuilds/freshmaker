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

from freshmaker import log
from freshmaker.triggers import BaseTrigger


def publish(topic, msg, conf, service):
    """
    Publish a single message to a given backend, and return
    :param topic: the topic of the message (e.g. module.state.change)
    :param msg: the message contents of the message (typically JSON)
    :param conf: a Config object from the class in config.py
    :param service: the system that is publishing the message (e.g. mbs)
    :return:
    """
    try:
        handler = _messaging_backends[conf.messaging]['publish']
    except KeyError:
        raise KeyError("No messaging backend found for %r" % conf.messaging)
    return handler(topic, msg, conf, service)


def _fedmsg_publish(topic, msg, conf, service):
    # fedmsg doesn't really need access to conf, however other backends do
    import fedmsg
    return fedmsg.publish(topic, msg=msg, modname=service)


# A counter used for in-memory messages.
_in_memory_msg_id = 0
_initial_messages = []


def _in_memory_publish(topic, msg, conf, service):
    """ Puts the message into the in memory work queue. """
    # Increment the message ID.
    global _in_memory_msg_id
    _in_memory_msg_id += 1

    # Create fake fedmsg from the message so we can reuse
    # the BaseTrigger.from_fedmsg code to get the particular BaseTrigger
    # class instance.
    wrapped_msg = BaseTrigger.from_fedmsg(
        service + "." + topic,
        {"msg_id": str(_in_memory_msg_id), "msg": msg},
    )

    # Put the message to queue.
    from freshmaker.scheduler.consumer import work_queue_put
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
    }
}
