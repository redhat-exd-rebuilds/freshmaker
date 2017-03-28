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
# Written by Jan Kaluza <jkaluza@redhat.com>

import abc
import fedmsg.utils

from freshmaker import conf


def load_handlers():
    """ Import and instantiate all handlers listed in the given config. """
    for import_path in conf.handlers:
        cls = fedmsg.utils.load_class(import_path)
        handler = cls()
        yield handler


class BaseHandler(object):
    """
    Abstract base class for trigger handlers.
    """
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def can_handle(self, trigger):
        """
        Returns true if this class can handle this type of trigger.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def handle(self, trigger):
        """
        Handles the trigger. Can return another BaseTrigger instances to
        generate another triggers to be used by other local handlers.
        """
        raise NotImplementedError()
