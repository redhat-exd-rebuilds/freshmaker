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

from freshmaker import events, db, models
from freshmaker.types import ArtifactType
from freshmaker.handlers.mbs import MBSModuleStateChangeHandler
from freshmaker.parsers.mbs import MBSModuleStateChangeParser
from freshmaker.config import any_


class MBSModuleStateChangeHandlerTest(helpers.ModelsTestCase):
    def setUp(self):
        super(MBSModuleStateChangeHandlerTest, self).setUp()
        events.BaseEvent.register_parser(MBSModuleStateChangeParser)

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
    @mock.patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MBSModuleStateChangeHandler': {
            'module': any_({'name': r'testmodule\d*'}, {'branch': 'master'}),
        }
    })
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
        self.assertEqual(builds[0].name, mod2_r1['name'])
        self.assertEqual(builds[0].type, ArtifactType.MODULE.value)
        self.assertEqual(builds[0].build_id, 123)
        self.assertEqual(builds[1].name, mod3_r1['name'])
        self.assertEqual(builds[1].build_id, 456)
        self.assertEqual(builds[1].type, ArtifactType.MODULE.value)

    @mock.patch('freshmaker.handlers.mbs.module_state_change.PDC')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.utils')
    @mock.patch('freshmaker.handlers.conf')
    def test_module_is_not_allowed_in_whitelist(self, conf, utils, PDC):
        conf.handler_build_whitelist = {
            "MBSModuleStateChangeHandler": {
                "module": any_(
                    {
                        'name': 'base.*',
                    },
                ),
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

    @mock.patch('freshmaker.handlers.mbs.module_state_change.PDC')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.utils')
    @mock.patch('freshmaker.handlers.mbs.module_state_change.log')
    @mock.patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MBSModuleStateChangeHandler': {
            'module': any_({'name': r'module\d+'}, {'branch': 'master'})
        }
    })
    def test_handler_not_fall_into_cyclic_rebuild_loop(self, log, utils, PDC):
        """
        Tests handler will not fall into cyclic rebuild loop when there is
        build dep loop of modules.
        """
        # in this case, we have:
        # 1. module2 depends on module1
        # 2. module3 depends on module2
        # 3. module1 depends on module3
        #
        # when we receives a modult built event of module1, the expect result is:
        # 1. module2 get rebuild because module1 is built
        # 2. module3 get rebuild because module2 is built
        # 3. module1 get rebuild because module3 is built
        # 4. stop here

        utils.bump_distgit_repo.return_value = 'abcd'

        mod1_info = helpers.PDCModuleInfo('module1', 'master', '20170412010101')
        mod1_info.add_build_dep('module3', 'master')
        mod1 = mod1_info.produce()

        mod2_info = helpers.PDCModuleInfo('module2', 'master', '20170412010102')
        mod2_info.add_build_dep('module1', 'master')
        mod2 = mod2_info.produce()

        mod3_info = helpers.PDCModuleInfo('module3', 'master', '20170412010103')
        mod3_info.add_build_dep('module2', 'master')
        mod3 = mod3_info.produce()

        pdc = PDC.return_value
        handler = MBSModuleStateChangeHandler()

        # Assume we have build of module1 recorded in DB already, it doesn't has
        # any dep_on as it was initial triggered by an event which is not
        # associated with any build in our DB.
        event = models.Event.create(db.session, "initial_msg_id", "test", events.TestingEvent)
        models.ArtifactBuild.create(db.session, event, "module1", "module", '123')
        db.session.commit()

        # we received module built event of module1
        msg = helpers.ModuleStateChangeMessage('module1', 'master', state='ready', build_id=123).produce()
        event = self.get_event_from_msg(msg)
        pdc.get_latest_modules.return_value = [mod2]
        handler.build_module = mock.Mock()
        handler.build_module.return_value = 124

        # this will trigger module rebuild of module2
        handler.handle(event)
        handler.build_module.assert_called_once_with('module2', 'master', 'abcd')

        # we received module built event of module2
        msg = helpers.ModuleStateChangeMessage('module2', 'master', state='ready', build_id=124).produce()
        event = self.get_event_from_msg(msg)
        pdc.get_latest_modules.return_value = [mod3]
        handler.build_module = mock.Mock()
        handler.build_module.return_value = 125

        # this will trigger module rebuild of module3
        handler.handle(event)
        handler.build_module.assert_called_once_with('module3', 'master', 'abcd')

        # we received module built event of module3
        msg = helpers.ModuleStateChangeMessage('module3', 'master', state='ready', build_id=125).produce()
        event = self.get_event_from_msg(msg)
        pdc.get_latest_modules.return_value = [mod1]
        handler.build_module = mock.Mock()
        handler.build_module.return_value = 126

        # this will trigger module rebuild of module1
        handler.handle(event)
        handler.build_module.assert_called_once_with('module1', 'master', 'abcd')

        # we received module built event of module1
        msg = helpers.ModuleStateChangeMessage('module1', 'master', state='ready', build_id=126).produce()
        event = self.get_event_from_msg(msg)
        pdc.get_latest_modules.return_value = [mod2]
        handler.build_module = mock.Mock()

        # but this time we should not rebuild module2
        handler.handle(event)
        handler.build_module.assert_not_called()
        log.info.assert_has_calls([mock.call('Skipping the rebuild triggered by %s:%s as it willresult in cyclic build loop.', 'module1', u'master')])


if __name__ == '__main__':
    unittest.main()
