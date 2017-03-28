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

""" The FedmsgConsumer class that acts as a consumer entry point for fedmsg-hub.
This class reads and processes messages from the message bus it is configured
to use.
"""

import fedmsg.consumers
import moksha.hub
import freshmaker.handlers
import freshmaker.parsers.mbsmodule
import freshmaker.parsers.gitreceive

from freshmaker import log, conf, messaging, triggers


class FreshmakerConsumer(fedmsg.consumers.FedmsgConsumer):
    """
    This is triggered by running fedmsg-hub. This class is responsible for
    ingesting and processing messages from the message bus.
    """
    config_key = 'freshmakerconsumer'

    def __init__(self, hub):
        super(FreshmakerConsumer, self).__init__(hub)

        self.handlers = list(freshmaker.handlers.load_handlers())
        self.register_parsers()

        # These two values are typically provided either by the unit tests or
        # by the local build command.  They are empty in the production environ
        self.stop_condition = hub.config.get('freshmaker.stop_condition')
        initial_messages = hub.config.get('freshmaker.initial_messages', [])
        for msg in initial_messages:
            self.incoming.put(msg)

        # Furthermore, extend our initial messages with any that were queued up
        # in the test environment before our hub was initialized.
        while messaging._initial_messages:
            msg = messaging._initial_messages.pop(0)
            self.incoming.put(msg)

    def register_parsers(self):
        triggers.BaseTrigger.register_parser(freshmaker.parsers.mbsmodule.MBSModuleParser)
        triggers.BaseTrigger.register_parser(freshmaker.parsers.gitreceive.GitReceiveParser)
        log.debug("Parser classes: %r", triggers.BaseTrigger._parsers)

        self.topic = triggers.BaseTrigger.get_parsing_topics()
        log.debug('Setting topics: {}'.format(', '.join(self.topic)))

    def shutdown(self):
        log.info("Scheduling shutdown.")
        from moksha.hub.reactor import reactor
        reactor.callFromThread(self.hub.stop)
        reactor.callFromThread(reactor.stop)

    def validate(self, message):
        if conf.messaging == 'fedmsg':
            # If this is a faked internal message, don't bother.
            if isinstance(message, triggers.BaseTrigger):
                log.info("Skipping crypto validation for %r" % message)
                return
            # Otherwise, if it is a real message from the network, pass it
            # through crypto validation.
            super(FreshmakerConsumer, self).validate(message)

    def consume(self, message):
        log.debug("Received %r" % message)

        # Sometimes, the messages put into our queue are artificially put there
        # by other parts of our own codebase.  If they are already abstracted
        # messages, then just use them as-is.  If they are not already
        # instances of our message abstraction base class, then first transform
        # them before proceeding.
        if isinstance(message, triggers.BaseTrigger):
            msg = message
        else:
            msg = self.get_abstracted_msg(message['body'])

        # Primary work is done here.
        try:
            self.process_trigger(msg)
        except Exception:
            log.exception('Failed while handling {0!r}'.format(msg))

        if self.stop_condition and self.stop_condition(message):
            self.shutdown()

    def get_abstracted_msg(self, message):
        # Convert the message to an abstracted message
        if conf.messaging == 'fedmsg' or conf.messaging == 'in_memory':
            msg = triggers.BaseTrigger.from_fedmsg(
                message['topic'], message)
        else:
            raise ValueError('The messaging format "{0}" is not supported'
                             .format(conf.messaging))
        return msg

    def process_trigger(self, msg):
        log.debug('Received a message with an ID of "{0}" and of type "{1}"'
                  .format(getattr(msg, 'msg_id', None), type(msg).__name__))

        for handler in self.handlers:
            if not handler.can_handle(msg):
                continue

            idx = "%s: %s, %s" % (type(handler).__name__, type(msg).__name__, msg.msg_id)
            log.debug("Calling %s" % idx)
            further_work = []
            try:
                further_work = handler.handle(msg) or []
            except Exception:
                msg = 'Could not process message handler. See the traceback.'
                log.exception(msg)

            log.debug("Done with %s" % idx)

            # Handlers can *optionally* return a list of fake messages that
            # should be re-inserted back into the main work queue. We can use
            # this (for instance) when we submit a new component build but (for
            # some reason) it has already been built, then it can fake its own
            # completion back to the scheduler so that work resumes as if it
            # was submitted for real and koji announced its completion.
            for event in further_work:
                log.info("  Scheduling faked event %r" % event)
                self.incoming.put(event)


def get_global_consumer():
    """ Return a handle to the active consumer object, if it exists. """
    hub = moksha.hub._hub
    if not hub:
        raise ValueError("No global moksha-hub obj found.")

    for consumer in hub.consumers:
        if isinstance(consumer, FreshmakerConsumer):
            return consumer

    raise ValueError("No FreshmakerConsumer found among %r." % len(hub.consumers))


def work_queue_put(msg):
    """ Artificially put a message into the work queue of the consumer. """
    consumer = get_global_consumer()
    consumer.incoming.put(msg)
