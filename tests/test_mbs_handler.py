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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests import helpers

from freshmaker import events
from freshmaker.handlers.mbs import MBS
from freshmaker.parsers.mbsmodule import MBSModuleParser


class MBSHandlerTest(unittest.TestCase):
    def setUp(self):
        events.BaseEvent.register_parser(MBSModuleParser)

    def _get_event(self, message):
        event = events.BaseEvent.from_fedmsg(message['body']['topic'], message['body'])
        return event

    def test_can_handle_module_built_ready_event(self):
        """
        Tests MBS handler can handle modult build ready message
        """

        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready').produce()
        event = self._get_event(msg)

        handler = MBS()
        self.assertTrue(handler.can_handle(event))

    def test_can_not_handle_module_built_non_ready_event(self):
        """
        Tests MBS handler cannot handle modult build message which is not with
        'ready' state.
        """
        for s in ['init', 'wait', 'build', 'done', 'failed']:
            msg = helpers.ModuleBuiltMessage('testmodule', 'master', state=s).produce()
            event = self._get_event(msg)

            handler = MBS()
            self.assertFalse(handler.can_handle(event))

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_rebuild_depending_modules_on_module_built_event(self, conf, pdc, utils):
        """
        Tests MBS handler can rebuild all modules which depend on the module
        in module built event.
        """
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready').produce()
        event = self._get_event(msg)

        handler = MBS()

        mod2_r1_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_r1_info.add_build_dep('testmodule', 'master')
        mod2_r1 = mod2_r1_info.produce()

        mod3_r1_info = helpers.PDCModuleInfo('testmodule3', 'master', '20170412010201')
        mod3_r1_info.add_build_dep('testmodule', 'master')
        mod3_r1 = mod3_r1_info.produce()

        def get_modules(pdc_session, name=None, version=None, build_dep_name=None, build_dep_stream=None, active=True):

            if name == 'testmodule2' and version == 'master':
                return [mod2_r1]
            elif name == 'testmodule3' and version == 'master':
                return [mod3_r1]
            else:
                return [mod2_r1, mod3_r1]

        pdc.get_modules.side_effect = get_modules
        conf.git_base_url = "git://pkgs.fedoraproject.org"
        utils.get_commit_hash.side_effect = [
            "fae7848fa47a854f25b782aa64441040a6d86544",
            "43ec03000d249231bc7135b11b810afc96e90efb",
        ]
        handler.rebuild_module = mock.Mock()
        handler.handle_module_built(event)

        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule2.git?#fae7848fa47a854f25b782aa64441040a6d86544', u'master'),
                          mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule3.git?#43ec03000d249231bc7135b11b810afc96e90efb', u'master')])

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_only_rebuild_latest_depending_modules_on_module_built_event(self, conf, pdc, utils):
        """
        Tests MBS handler only rebuild latest depending modules. If there is a
        module only has old release depends on the module, it won't be rebuilt.
        """
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready').produce()
        event = self._get_event(msg)

        handler = MBS()

        mod2_r1_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_r1_info.add_build_dep('testmodule', 'master')
        mod2_r1 = mod2_r1_info.produce()

        mod3_r1_info = helpers.PDCModuleInfo('testmodule3', 'master', '20170412010101')
        mod3_r1_info.add_build_dep('testmodule', 'master')
        mod3_r1 = mod3_r1_info.produce()

        mod3_r2_info = helpers.PDCModuleInfo('testmodule3', 'master', '20170412010201')
        mod3_r2_info.add_build_dep('testmodule', 'master')
        mod3_r2 = mod3_r2_info.produce()

        def get_modules(pdc_session, name=None, version=None, build_dep_name=None, build_dep_stream=None, active=True):

            if name == 'testmodule2' and version == 'master':
                return [mod2_r1]
            elif name == 'testmodule3' and version == 'master':
                return [mod3_r1, mod3_r2]
            else:
                return [mod2_r1, mod3_r1]

        # query for testmodule3 releases, get mod3_r1 and mod3_r2,
        # only mod3_r1 depends on testmodule, and r1 < r2.
        pdc.get_modules.side_effect = get_modules
        conf.git_base_url = "git://pkgs.fedoraproject.org"
        utils.get_commit_hash.side_effect = [
            "fae7848fa47a854f25b782aa64441040a6d86544",
            "43ec03000d249231bc7135b11b810afc96e90efb",
        ]
        handler.rebuild_module = mock.Mock()
        handler.handle_module_built(event)

        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule2.git?#fae7848fa47a854f25b782aa64441040a6d86544', u'master')])


if __name__ == '__main__':
    unittest.main()
