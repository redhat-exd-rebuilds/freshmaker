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

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # noqa
from tests import helpers

from freshmaker import events, db, models
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.handlers.koji import KojiTaskStateChangeHandler
from freshmaker.parsers.koji import KojiTaskStateChangeParser


class KojiTaskStateChangeHandlerTest(helpers.ModelsTestCase):
    def setUp(self):
        super(KojiTaskStateChangeHandlerTest, self).setUp()
        events.BaseEvent.register_parser(KojiTaskStateChangeParser)

    def test_can_handle_koji_task_state_change_message(self):
        """
        Tests buildsys handler can handle koji task state changed message
        """
        m = helpers.KojiTaskStateChangeMessage(123, 'OPEN', 'FAILED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)
        handler = KojiTaskStateChangeHandler()
        self.assertTrue(handler.can_handle(event))

    def test_update_build_state_on_koji_task_state_change_event(self):
        """
        Tests build state will be updated when receives koji task state changed message
        """
        task_id = 123
        ev = models.Event.create(db.session, 'test_msg_id', "event-name",
                                 events.KojiTaskStateChangeEvent)
        build = models.ArtifactBuild.create(db.session,
                                            ev,
                                            'testimage',
                                            ArtifactType.IMAGE.value,
                                            task_id)
        db.session.add(ev)
        db.session.add(build)
        db.session.commit()

        m = helpers.KojiTaskStateChangeMessage(task_id, 'OPEN', 'FAILED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)

        handler = KojiTaskStateChangeHandler()

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        build = models.ArtifactBuild.query.all()[0]
        self.assertEqual(build.state, ArtifactBuildState.FAILED.value)

        m = helpers.KojiTaskStateChangeMessage(task_id, 'OPEN', 'CLOSED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        build = models.ArtifactBuild.query.all()[0]
        self.assertEqual(build.state, ArtifactBuildState.DONE.value)


if __name__ == '__main__':
    unittest.main()
