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

from freshmaker import events, db, models
from freshmaker.types import ArtifactType
from freshmaker.handlers.git import GitRPMSpecChangeHandler
from freshmaker.parsers.git import GitReceiveParser


class GitRPMSpecChangeHandlerTest(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(GitReceiveParser)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_can_handle_dist_git_message_with_rpm_spec_changed(self):
        """
        Tests handler can handle rpm spec change event
        """
        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = GitRPMSpecChangeHandler()
        self.assertTrue(handler.can_handle(event))

    def test_can_not_handle_dist_git_message_without_rpm_spec_changed(self):
        """
        Tests can not handle dist git message that spec file is not changed.
        """

        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('test.c', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = GitRPMSpecChangeHandler()
        self.assertFalse(handler.can_handle(event))

    @mock.patch('freshmaker.handlers.git.rpm_spec_change.PDC')
    @mock.patch('freshmaker.handlers.git.rpm_spec_change.utils')
    @mock.patch('freshmaker.handlers.git.rpm_spec_change.conf')
    def test_can_rebuild_modules_has_rpm_included(self, conf, utils, PDC):
        """
        Test handler can rebuild modules which include the rpm.
        """
        conf.git_base_url = "git://pkgs.fedoraproject.org"

        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        mod_info = helpers.PDCModuleInfo('testmodule', 'master', '20170412010101')
        mod_info.add_rpm("bash-1.2.3-4.f26.rpm")
        mod = mod_info.produce()
        pdc = PDC.return_value
        pdc.get_latest_modules.return_value = [mod]

        commitid = '9287eb8eb4c4c60f73b4a59f228a673846d940c6'
        utils.bump_distgit_repo.return_value = commitid

        handler = GitRPMSpecChangeHandler()
        handler.build_module = mock.Mock()
        handler.build_module.return_value = 123

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        handler.build_module.assert_called_with('testmodule', 'master', commitid)

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
