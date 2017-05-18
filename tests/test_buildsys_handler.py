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
from freshmaker.handlers.buildsys import BuildsysHandler
from freshmaker.parsers.buildsys import BuildsysParser


class BuildsysHandlerTest(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(BuildsysParser)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_can_handle_koji_task_state_changed_event(self):
        """
        Tests buildsys handler can handle koji task state changed message
        """
        m = helpers.BuildsysTaskStateChangeMessage(123, 'OPEN', 'FAILED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)
        handler = BuildsysHandler()
        self.assertTrue(handler.can_handle(event))

    def test_update_build_state_on_koji_task_state_changed_event(self):
        """
        Tests build state will be updated when receives koji task state changed message
        """
        task_id = 123
        ev = models.Event.create(db.session, 'test_msg_id')
        build = models.ArtifactBuild.create(db.session,
                                            ev,
                                            'testimage',
                                            models.ARTIFACT_TYPES['image'],
                                            task_id)
        db.session.add(ev)
        db.session.add(build)
        db.session.commit()

        m = helpers.BuildsysTaskStateChangeMessage(task_id, 'OPEN', 'FAILED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)

        handler = BuildsysHandler()
        handler.handle(event)
        build = models.ArtifactBuild.query.all()[0]
        self.assertEqual(build.state, models.BUILD_STATES['failed'])

        m = helpers.BuildsysTaskStateChangeMessage(task_id, 'OPEN', 'CLOSED')
        msg = m.produce()
        event = self.get_event_from_msg(msg)

        handler = BuildsysHandler()
        handler.handle(event)
        build = models.ArtifactBuild.query.all()[0]
        self.assertEqual(build.state, models.BUILD_STATES['done'])


if __name__ == '__main__':
    unittest.main()
