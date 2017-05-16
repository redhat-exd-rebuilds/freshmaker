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

from freshmaker import events, db, models
from freshmaker.handlers.mbs import MBS
from freshmaker.parsers.mbsmodule import MBSModuleParser
from freshmaker.parsers.gitreceive import GitReceiveParser


class MBSHandlerTest(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(MBSModuleParser)
        events.BaseEvent.register_parser(GitReceiveParser)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_can_handle_module_built_event(self):
        """
        Tests MBS handler can handle module built message
        """
        for state in ['init', 'wait', 'build', 'done', 'failed', 'ready']:
            msg = helpers.ModuleBuiltMessage('testmodule', 'master', state=state).produce()
            event = self.get_event_from_msg(msg)

            handler = MBS()
            self.assertTrue(handler.can_handle(event))

    @mock.patch('freshmaker.pdc.get_modules')
    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_rebuild_depending_modules_on_module_built_event(self, conf, utils, get_modules):
        """
        Tests MBS handler can rebuild all modules which depend on the module
        in module built event.
        """
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready').produce()
        event = self.get_event_from_msg(msg)

        handler = MBS()

        mod2_r1_info = helpers.PDCModuleInfo('testmodule2', 'master', '20170412010101')
        mod2_r1_info.add_build_dep('testmodule', 'master')
        mod2_r1 = mod2_r1_info.produce()

        mod3_r1_info = helpers.PDCModuleInfo('testmodule3', 'master', '20170412010201')
        mod3_r1_info.add_build_dep('testmodule', 'master')
        mod3_r1 = mod3_r1_info.produce()

        def mock_get_modules(pdc_session, **kwargs):
            name = kwargs.get('variant_name', None)
            version = kwargs.get('variant_version', None)

            if name == 'testmodule2' and version == 'master':
                return [mod2_r1]
            elif name == 'testmodule3' and version == 'master':
                return [mod3_r1]
            else:
                return [mod2_r1, mod3_r1]

        get_modules.side_effect = mock_get_modules
        conf.git_base_url = "git://pkgs.fedoraproject.org"
        utils.get_commit_hash.side_effect = [
            "fae7848fa47a854f25b782aa64441040a6d86544",
            "43ec03000d249231bc7135b11b810afc96e90efb",
        ]
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.side_effect = [123, 456]
        handler.handle_module_built(event)

        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule2.git?#fae7848fa47a854f25b782aa64441040a6d86544', u'master'),
                          mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule3.git?#43ec03000d249231bc7135b11b810afc96e90efb', u'master')])

        event_list = models.Event.query.all()
        self.assertEquals(len(event_list), 1)
        self.assertEquals(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 2)
        self.assertEquals(builds[0].name, mod2_r1['variant_name'])
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['module'])
        self.assertEquals(builds[0].build_id, 123)
        self.assertEquals(builds[1].name, mod3_r1['variant_name'])
        self.assertEquals(builds[1].build_id, 456)
        self.assertEquals(builds[1].type, models.ARTIFACT_TYPES['module'])

    @mock.patch('freshmaker.pdc.get_modules')
    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_only_rebuild_latest_depending_modules_on_module_built_event(self, conf, utils, get_modules):
        """
        Tests MBS handler only rebuild latest depending modules. If there is a
        module only has old release depends on the module, it won't be rebuilt.
        """
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready').produce()
        event = self.get_event_from_msg(msg)

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

        def mock_get_modules(pdc_session, **kwargs):
            name = kwargs.get('variant_name', None)
            version = kwargs.get('variant_version', None)

            if name == 'testmodule2' and version == 'master':
                return [mod2_r1]
            elif name == 'testmodule3' and version == 'master':
                return [mod3_r1, mod3_r2]
            else:
                return [mod2_r1, mod3_r1]

        # query for testmodule3 releases, get mod3_r1 and mod3_r2,
        # only mod3_r1 depends on testmodule, and r1 < r2.
        get_modules.side_effect = mock_get_modules
        conf.git_base_url = "git://pkgs.fedoraproject.org"
        utils.get_commit_hash.side_effect = [
            "fae7848fa47a854f25b782aa64441040a6d86544",
            "43ec03000d249231bc7135b11b810afc96e90efb",
        ]
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.return_value = 123
        handler.handle_module_built(event)

        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call(u'git://pkgs.fedoraproject.org/modules/testmodule2.git?#fae7848fa47a854f25b782aa64441040a6d86544', u'master')])

        event_list = models.Event.query.all()
        self.assertEquals(len(event_list), 1)
        self.assertEquals(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        self.assertEquals(builds[0].name, mod2_r1['variant_name'])
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['module'])
        self.assertEquals(builds[0].build_id, 123)

    def test_can_handle_rpm_spec_updated_event(self):
        """
        Tests MBS handler can handle rpm spec updated event
        """
        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = MBS()
        self.assertTrue(handler.can_handle(event))

    def test_can_not_handle_no_spec_updated_dist_git_event(self):
        """
        Tests RPMSpechandler can not handle dist git message that
        spec file is not updated.
        """

        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('test.c', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        handler = MBS()
        self.assertFalse(handler.can_handle(event))

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_trigger_module_rebuild_when_rpm_spec_updated(self, conf, pdc, utils):
        """
        Test RPMSpecHandler can trigger module rebuild when spec
        file of rpm in module updated.
        """
        conf.git_base_url = "git://pkgs.fedoraproject.org"

        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        mod_info = helpers.PDCModuleInfo('testmodule', 'master', '20170412010101')
        mod_info.add_rpm("bash-1.2.3-4.f26.rpm")
        mod = mod_info.produce()
        pdc.get_latest_modules.return_value = [mod]

        commitid = '9287eb8eb4c4c60f73b4a59f228a673846d940c6'
        utils.get_commit_hash.return_value = commitid

        handler = MBS()
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.return_value = 123
        handler.handle(event)
        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call('git://pkgs.fedoraproject.org/modules/testmodule.git?#%s' % commitid, 'master')])

        event_list = models.Event.query.all()
        self.assertEquals(len(event_list), 1)
        self.assertEquals(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        self.assertEquals(builds[0].name, 'testmodule')
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['module'])
        self.assertEquals(builds[0].build_id, 123)

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.mbs.conf')
    def test_update_build_state_in_db(self, conf, pdc, utils):
        """
        Test build state in db will be updated when receives module build
        state change message.
        """

        # trigger a build on rpm spec updated event first
        conf.git_base_url = "git://pkgs.fedoraproject.org"

        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        mod_info = helpers.PDCModuleInfo('testmodule', 'master', '20170412010101')
        mod_info.add_rpm("bash-1.2.3-4.f26.rpm")
        mod = mod_info.produce()
        pdc.get_latest_modules.return_value = [mod]

        commitid = '9287eb8eb4c4c60f73b4a59f228a673846d940c6'
        utils.get_commit_hash.return_value = commitid

        handler = MBS()
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.return_value = 123
        handler.handle(event)
        self.assertEqual(handler.rebuild_module.call_args_list,
                         [mock.call('git://pkgs.fedoraproject.org/modules/testmodule.git?#%s' % commitid, 'master')])

        event_list = models.Event.query.all()
        self.assertEquals(len(event_list), 1)
        self.assertEquals(event_list[0].message_id, event.msg_id)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        self.assertEquals(builds[0].name, 'testmodule')
        self.assertEquals(builds[0].type, models.ARTIFACT_TYPES['module'])
        self.assertEquals(builds[0].build_id, 123)
        self.assertEquals(builds[0].state, models.BUILD_STATES['build'])

        # update build state when receive module built messages
        # build is failed
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='failed', build_id=123).produce()
        event = self.get_event_from_msg(msg)
        handler.handle(event)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        # build state updated to 'failed'
        self.assertEquals(builds[0].state, models.BUILD_STATES['failed'])

        # build is ready
        pdc.get_latest_modules.return_value = []
        msg = helpers.ModuleBuiltMessage('testmodule', 'master', state='ready', build_id=123).produce()
        event = self.get_event_from_msg(msg)
        handler.handle(event)
        builds = models.ArtifactBuild.query.all()
        self.assertEquals(len(builds), 1)
        # build state updated to 'done'
        self.assertEquals(builds[0].state, models.BUILD_STATES['done'])

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.conf')
    def test_module_is_not_allowed_to_be_built_in_whitelist(self, conf, pdc, utils):
        conf.handler_build_whitelist = {
            "MBS": {
                "RPMSpecUpdated": {
                    "module": [
                        {
                            'name': 'test-.*',
                        },
                    ],
                },
            },
        }
        conf.handler_build_blacklist = {}
        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        mod_info = helpers.PDCModuleInfo('testmodule', 'master', '20170412010101')
        mod_info.add_rpm("bash-1.2.3-4.f26.rpm")
        mod = mod_info.produce()
        pdc.get_latest_modules.return_value = [mod]
        event = self.get_event_from_msg(msg)
        handler = MBS()
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.return_value = None
        handler.handle(event)
        handler.rebuild_module.assert_not_called()

    @mock.patch('freshmaker.handlers.mbs.utils')
    @mock.patch('freshmaker.handlers.mbs.pdc')
    @mock.patch('freshmaker.handlers.conf')
    def test_module_is_not_allowed_to_be_built_in_blacklist(self, conf, pdc, utils):
        conf.handler_build_whitelist = {}
        conf.handler_build_blacklist = {
            "MBS": {
                "RPMSpecUpdated": {
                    "module": [
                        {
                            'name': 'testmodule',
                        },
                    ],
                },
            },
        }
        m = helpers.DistGitMessage('rpms', 'bash', 'master', '123')
        m.add_changed_file('bash.spec', 1, 1)
        msg = m.produce()

        event = self.get_event_from_msg(msg)

        mod_info = helpers.PDCModuleInfo('testmodule', 'master', '20170412010101')
        mod_info.add_rpm("bash-1.2.3-4.f26.rpm")
        mod = mod_info.produce()
        pdc.get_latest_modules.return_value = [mod]
        event = self.get_event_from_msg(msg)
        handler = MBS()
        handler.rebuild_module = mock.Mock()
        handler.rebuild_module.return_value = None
        handler.handle(event)
        handler.rebuild_module.assert_not_called()

if __name__ == '__main__':
    unittest.main()
