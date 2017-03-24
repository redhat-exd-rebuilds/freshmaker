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

from coco import log, conf, messaging
from coco.handlers import BaseHandler
from coco.triggers import ModuleBuilt, TestingTrigger

class MBS(BaseHandler):
    name = "MBS"

    def can_handle(self, trigger):
        # Handle only "ready" state of ModuleBuilt.
        # TODO: Handle only when something depends on
        # this module.
        if (isinstance(trigger, ModuleBuilt)
            and trigger.module_build_state == 5):
            return True

            
        return False

    def handle(self, trigger):
        log.info("Triggering rebuild of modules depending on %r "
                 "in MBS" % trigger)

        # TODO: Just for initial testing of consumer
        return [TestingTrigger("ModuleBuilt handled")]
