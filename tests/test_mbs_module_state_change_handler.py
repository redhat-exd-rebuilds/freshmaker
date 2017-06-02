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
from freshmaker.handlers.mbs import MBSModuleStateChangeHandler
from freshmaker.parsers.mbs import MBSModuleStateChangeParser


class MBSModuleStateChangeHandlerTest(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(MBSModuleStateChangeParser)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_can_handle_module_state_change_event(self):
        """
        Tests MBS handler can handle module built message
        """
        for state in ['init', 'wait', 'build', 'done', 'failed', 'ready']:
            msg = helpers.ModuleStateChangeMessage('testmodule', 'master', state=state).produce()
            event = self.get_event_from_msg(msg)

            handler = MBSModuleStateChangeHandler()
            self.assertTrue(handler.can_handle(event))

    @mock.patch('freshmaker.handlers.mbs.module_state_change.PDC')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.utils')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.conf')
    def test_can_rebuild_depending_modules(self, conf, utils, PDC):
        """
        Tests handler can rebuild all modules which depend on the module
        in module state change event.
        """
        msg = helpers.ModuleStateChangeMessage('testmodule', 'master', state='ready').produce()
        event = self.get_event_from_msg(msg)

        mod2_r1_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_r1_info.add_build_dep('testmodule', 'master')
        mod2_r1 = mod2_r1_info.produce()

        mod3_r1_info = helpers.PDCModuleInfo('testmodule3', 'master', '20170412010201')
        mod3_r1_info.add_build_dep('testmodule', 'master')
        mod3_r1 = mod3_r1_info.produce()

        pdc = PDC.return_value
        pdc.get_latest_modules.return_value = [mod2_r1, mod3_r1]

        conf.git_base_url = "git://pkgs.fedoraproject.org"
        utils.bump_distgit_repo.side_effect = [
            "fae7848fa47a854f25b782aa64441040a6d86544",
            "43ec03000d249231bc7135b11b810afc96e90efb",
        ]

        handler = MBSModuleStateChangeHandler()
        handler.build_module = mock.Mock()
        handler.build_module.side_effect = [123, 456]

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        self.assertEqual(handler.build_module.call_args_list,
                         [mock.call('testmodule2', 'master', 'fae7848fa47a854f25b782aa64441040a6d86544'),
                          mock.call('testmodule3', 'master', '43ec03000d249231bc7135b11b810afc96e90efb')])

        event_list = models.Event.query.all()
        self.assertEqual(len(event_list), 1)
        self.assertEqual(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEqual(len(builds), 2)
        self.assertEqual(builds[0].name, mod2_r1['variant_name'])
        self.assertEqual(builds[0].type, models.ARTIFACT_TYPES['module'])
        self.assertEqual(builds[0].build_id, 123)
        self.assertEqual(builds[1].name, mod3_r1['variant_name'])
        self.assertEqual(builds[1].build_id, 456)
        self.assertEqual(builds[1].type, models.ARTIFACT_TYPES['module'])

    @mock.patch('freshmaker.handlers.mbs.module_state_change.PDC')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.utils')
    @mock.patch('freshmaker.handlers.conf')
    def test_module_is_not_allowed_in_whitelist(self, conf, utils, PDC):
        conf.handler_build_whitelist = {
            "MBSModuleStateChangeHandler": {
                "module": [
                    {
                        'name': 'base.*',
                    },
                ],
            },
        }
        conf.handler_build_blacklist = {}

        msg = helpers.ModuleStateChangeMessage('testmodule', 'master', state='ready').produce()
        event = self.get_event_from_msg(msg)

        mod2_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_info.add_build_dep('testmodule', 'master')
        mod2 = mod2_info.produce()

        pdc = PDC.return_value
        pdc.get_latest_modules.return_value = [mod2]

        handler = MBSModuleStateChangeHandler()
        handler.build_module = mock.Mock()
        handler.record_build = mock.Mock()

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        handler.build_module.assert_not_called()

    @mock.patch('freshmaker.handlers.mbs.module_state_change.PDC')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.utils')
    @mock.patch('freshmaker.handlers.conf')
    def test_module_is_not_allowed_in_blacklist(self, conf, utils, PDC):
        conf.handler_build_whitelist = {}
        conf.handler_build_blacklist = {
            "MBSModuleStateChangeHandler": {
                "module": [
                    {
                        'name': 'test.*',
                    },
                ],
            },
        }
        msg = helpers.ModuleStateChangeMessage('testmodule', 'master', state='ready').produce()
        event = self.get_event_from_msg(msg)

        mod2_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_info.add_build_dep('testmodule', 'master')
        mod2 = mod2_info.produce()

        pdc = PDC.return_value
        pdc.get_latest_modules.return_value = [mod2]

        handler = MBSModuleStateChangeHandler()
        handler.build_module = mock.Mock()
        handler.record_build = mock.Mock()

        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        handler.build_module.assert_not_called()


if __name__ == '__main__':
    unittest.main()
