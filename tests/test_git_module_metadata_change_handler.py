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
import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # noqa
from tests import helpers

import freshmaker

from freshmaker import events, models
from freshmaker.types import ArtifactType
from freshmaker.handlers.git import GitModuleMetadataChangeHandler
from freshmaker.parsers.git import GitReceiveParser
from freshmaker.config import any_


class GitModuleMetadataChangeHandlerTest(helpers.ModelsTestCase):
    def setUp(self):
        super(GitModuleMetadataChangeHandlerTest, self).setUp()
        events.BaseEvent.register_parser(GitReceiveParser)

    def test_can_handle_module_metadata_change_event(self):
        """
        Tests handler can handle module metadata change message
        """
        m = helpers.DistGitMessage('modules', 'testmodule', 'master', '123')
        m.add_changed_file('testmodule.yaml', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = GitModuleMetadataChangeHandler()
        self.assertTrue(handler.can_handle(event))

    @mock.patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'GitModuleMetadataChangeHandler': {
            'module': any_({'name': 'testmodule'}, {'branch': 'master'})
        }
    })
    def test_can_rebuild_module_when_module_metadata_changed(self):
        """
        Tests handler can rebuild module when module metadata is changed in dist-git
        """
        m = helpers.DistGitMessage('modules', 'testmodule', 'master', '12345')
        m.add_changed_file('testmodule.yaml', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = GitModuleMetadataChangeHandler()
        handler.build_module = mock.Mock()
        handler.build_module.return_value = 123

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        self.assertEqual(handler.build_module.call_args_list,
                         [mock.call('testmodule', 'master', '12345')])

        event_list = models.Event.query.all()
        self.assertEqual(len(event_list), 1)
        self.assertEqual(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0].name, 'testmodule')
        self.assertEqual(builds[0].type, ArtifactType.MODULE.value)
        self.assertEqual(builds[0].build_id, 123)


if __name__ == '__main__':
    unittest.main()
