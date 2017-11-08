# -*- coding: utf-8 -*-
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

from freshmaker import db
from freshmaker.models import Event
from freshmaker.handlers import (
    ContainerBuildHandler, fail_event_on_handler_exception)
from freshmaker.events import ODCSComposeStateChangeEvent

from odcs.common.types import COMPOSE_STATES

__all__ = ('ComposeStateChangeHandler',)


class ComposeStateChangeHandler(ContainerBuildHandler):
    """Start image rebuild with this compose containing included packages"""

    def can_handle(self, event):
        if not isinstance(event, ODCSComposeStateChangeEvent):
            return False
        return event.compose['state'] == COMPOSE_STATES['done']

    @fail_event_on_handler_exception
    def handle(self, event):
        errata_signed_events = db.session.query(Event).filter(
            Event.compose_id == event.compose['id']).all()
        for db_event in errata_signed_events:
            self.set_context(db_event)
            self._build_first_batch(db_event)
