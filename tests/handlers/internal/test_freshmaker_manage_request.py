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
# Written by Filip Valder <fvalder@redhat.com>

import unittest

from unittest.mock import patch

from freshmaker import events, models, db
from freshmaker.handlers.internal import CancelEventOnFreshmakerManageRequest
from freshmaker.parsers.internal import FreshmakerManageRequestParser
from freshmaker.types import ArtifactBuildState

from tests import helpers, get_fedmsg


class ErroneousFreshmakerManageRequestsTest(helpers.ModelsTestCase):
    def setUp(self):
        super(ErroneousFreshmakerManageRequestsTest, self).setUp()
        events.BaseEvent.register_parser(FreshmakerManageRequestParser)

    def test_freshmaker_manage_mismatched_action(self):
        msg = get_fedmsg('freshmaker_manage_mismatched_action')
        with self.assertRaises(ValueError) as err:
            self.get_event_from_msg(msg)
        self.assertEqual(
            err.exception.args[0], 'Last part of \'Freshmaker manage\' message'
            ' topic must match the action defined within the message.')

    def test_freshmaker_manage_missing_action(self):
        msg = get_fedmsg('freshmaker_manage_missing_action')
        with self.assertRaises(ValueError) as err:
            self.get_event_from_msg(msg)
        self.assertEqual(
            err.exception.args[0], 'Action is not defined within the message.')

    def test_more_than_max_tries_on_freshmaker_manage_request(self):
        msg = get_fedmsg('freshmaker_manage_eventcancel')
        msg['body']['msg']['try'] = events.FreshmakerManageEvent._max_tries
        event = self.get_event_from_msg(msg)

        handler = CancelEventOnFreshmakerManageRequest()
        self.assertFalse(handler.can_handle(event))


class CancelEventOnFreshmakerManageRequestTest(helpers.ModelsTestCase):
    def setUp(self):
        super(CancelEventOnFreshmakerManageRequestTest, self).setUp()
        events.BaseEvent.register_parser(FreshmakerManageRequestParser)

        self.koji_read_config_patcher = patch(
            'koji.read_config', return_value={'server': 'http://localhost/'})
        self.koji_read_config_patcher.start()

        self.db_event = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000003", "RHSA-2018-103",
            events.TestingEvent)
        models.ArtifactBuild.create(
            db.session, self.db_event, "mksh", "module", build_id=1237,
            state=ArtifactBuildState.CANCELED.value)
        models.ArtifactBuild.create(
            db.session, self.db_event, "bash", "module", build_id=1238,
            state=ArtifactBuildState.CANCELED.value)

    def tearDown(self):
        self.koji_read_config_patcher.stop()

    @patch('freshmaker.kojiservice.KojiService.cancel_build')
    def test_cancel_event_on_freshmaker_manage_request(self, mocked_cancel_build):
        msg = get_fedmsg('freshmaker_manage_eventcancel')
        event = self.get_event_from_msg(msg)

        handler = CancelEventOnFreshmakerManageRequest()
        self.assertTrue(handler.can_handle(event))
        retval = handler.handle(event)
        self.assertEqual(retval, [])

        mocked_cancel_build.assert_any_call(1237)
        mocked_cancel_build.assert_any_call(1238)
        self.assertEqual([b.state_reason for b in self.db_event.builds.all()].count(
            "Build canceled in external build system."), 2)

    def test_can_not_handle_other_action_than_eventcancel(self):
        msg = get_fedmsg('freshmaker_manage_eventcancel')
        msg['body']['topic'] = 'freshmaker.manage.someotheraction'
        msg['body']['msg']['action'] = 'someotheraction'
        event = self.get_event_from_msg(msg)

        handler = CancelEventOnFreshmakerManageRequest()
        self.assertFalse(handler.can_handle(event))

    @patch('freshmaker.kojiservice.KojiService.cancel_build', side_effect=[False, False])
    def test_max_tries_reached_on_cancel_event(self, mocked_cancel_build):
        msg = get_fedmsg('freshmaker_manage_eventcancel')
        msg['body']['msg']['try'] = events.FreshmakerManageEvent._max_tries - 1
        event = self.get_event_from_msg(msg)

        handler = CancelEventOnFreshmakerManageRequest()
        retval = handler.handle(event)
        self.assertEqual(retval, [])

        self.assertEqual([b.state_reason for b in self.db_event.builds.all()].count(
            "Build was NOT canceled in external build system. Max number of tries reached!"), 2)

    @patch('freshmaker.kojiservice.KojiService.cancel_build',
           side_effect=[False, False, True, True])
    def test_retry_failed_cancel_event_with_success(self, mocked_cancel_build):
        msg = get_fedmsg('freshmaker_manage_eventcancel')
        event = self.get_event_from_msg(msg)

        handler = CancelEventOnFreshmakerManageRequest()
        new_event = handler.handle(event)
        self.assertTrue(isinstance(new_event, list) and len(new_event))
        retval = handler.handle(new_event[0])
        self.assertEqual(retval, [])

        self.assertEqual([b.state_reason for b in self.db_event.builds.all()].count(
            "Build canceled in external build system."), 2)


if __name__ == '__main__':
    unittest.main()
