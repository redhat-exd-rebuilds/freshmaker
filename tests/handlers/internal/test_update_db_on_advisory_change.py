# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Chenxiong Qi <cqi@redhat.com>

from unittest.mock import patch, Mock

from freshmaker import conf, db
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.events import ErrataAdvisoryStateChangedEvent
from freshmaker.handlers.internal import UpdateDBOnAdvisoryChange
from freshmaker.models import Event
from freshmaker.types import EventState
from tests import helpers


class TestUpdateDBOnAdvisoryChange(helpers.ModelsTestCase):

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists(self, advisories_from_event):
        handler = UpdateDBOnAdvisoryChange()

        for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
            advisories_from_event.return_value = [
                ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, "RHSA-2017", state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 1)
            self.assertEqual(ret[0].advisory.errata_id, 123)
            self.assertEqual(ret[0].advisory.security_impact, "Critical")
            self.assertEqual(ret[0].advisory.name, "RHSA-2017")

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch.object(conf, 'handler_build_whitelist', new={
        'UpdateDBOnAdvisoryChange': {
            'image': {
                'advisory_state': r'REL_PREP|SHIPPED_LIVE',
            }
        }
    })
    def test_rebuild_if_not_exists_unknown_states(
            self, advisories_from_event):
        handler = UpdateDBOnAdvisoryChange()

        for state in ["NEW_FILES", "QE", "UNKNOWN"]:
            advisories_from_event.return_value = [
                ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 0)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch.object(conf, 'handler_build_whitelist', new={
        'UpdateDBOnAdvisoryChange': {
            'image': {
                'advisory_state': '.*',
            }
        }
    })
    def test_rebuild_if_not_exists_already_exists(
            self, advisories_from_event):
        handler = UpdateDBOnAdvisoryChange()

        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent)
        db.session.commit()

        for manual in [True, False]:
            for db_event_state in [
                    EventState.INITIALIZED, EventState.BUILDING,
                    EventState.COMPLETE, EventState.FAILED,
                    EventState.SKIPPED]:
                db_event.state = db_event_state
                db.session.commit()
                for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
                    advisories_from_event.return_value = [
                        ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
                    ev = ErrataAdvisoryStateChangedEvent(
                        "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
                    ev.manual = manual
                    ev.dry_run = manual  # use also manual just for the sake of test.
                    ret = handler.handle(ev)

                    if db_event_state == EventState.FAILED or ev.manual:
                        self.assertEqual(len(ret), 1)
                        self.assertEqual(ret[0].manual, manual)
                        self.assertEqual(ret[0].dry_run, manual)
                    else:
                        self.assertEqual(len(ret), 0)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists_unknown_errata_id(
            self, advisories_from_event):
        advisories_from_event.return_value = []
        handler = UpdateDBOnAdvisoryChange()

        for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 0)

    def test_passing_dry_run(self):
        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]),
            dry_run=True)
        self.assertEqual(ev.dry_run, True)

        ev = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"),
            dry_run=True)
        self.assertEqual(ev.dry_run, True)

    def test_mark_as_released(self):
        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        self.assertEqual(db_event.released, False)

        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]))

        handler = UpdateDBOnAdvisoryChange()
        handler.handle(ev)

        db.session.refresh(db_event)
        self.assertEqual(db_event.released, True)

    def test_mark_as_released_wrong_advisory_status(self):
        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        for state in ["NEW_FILES", "QE", "REL_PREP", "PUSH_READY", "IN_PUSH"]:
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, "name", state, ['rpm']))

            handler = UpdateDBOnAdvisoryChange()
            handler.handle(ev)

            db.session.refresh(db_event)
            self.assertEqual(db_event.released, False)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_mark_as_released_unknown_event(self, advisories_from_event):
        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]))

        handler = UpdateDBOnAdvisoryChange()
        handler.handle(ev)

    @patch('freshmaker.handlers.internal.UpdateDBOnAdvisoryChange'
           '.rebuild_if_not_exists')
    @patch.object(conf, 'handler_build_whitelist', new={
        'UpdateDBOnAdvisoryChange': {
            'image': {
                'advisory_state': r'REL_PREP',
            }
        }
    })
    def test_not_rebuild_if_errata_state_is_not_allowed(
            self, rebuild_if_not_exists):
        rebuild_if_not_exists.return_value = [Mock(), Mock()]

        Event.create(db.session, "msg-id-123", "123456",
                     ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-123',
            ErrataAdvisory(123456, 'name', 'SHIPPED_LIVE', ['rpm']))
        handler = UpdateDBOnAdvisoryChange()
        msgs = handler.handle(event)

        self.assertEqual([], msgs)

    @patch('freshmaker.handlers.internal.UpdateDBOnAdvisoryChange'
           '.rebuild_if_not_exists')
    @patch.object(conf, 'handler_build_whitelist', new={
        'UpdateDBOnAdvisoryChange': {
            'image': {
                'advisory_state': r'SHIPPED_LIVE',
            }
        }
    })
    def test_rebuild_if_errata_state_is_not_allowed_but_manual_is_true(
            self, rebuild_if_not_exists):
        rebuild_if_not_exists.return_value = [Mock()]

        Event.create(db.session, "msg-id-123", "123456",
                     ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-123',
            ErrataAdvisory(123456, "name", 'SHIPPED_LIVE', ['rpm']))
        event.manual = True
        handler = UpdateDBOnAdvisoryChange()
        msgs = handler.handle(event)

        self.assertEqual(len(msgs), 1)


class TestSkipNonRPMAdvisory(helpers.FreshmakerTestCase):

    def test_ensure_to_handle_rpm_and_module_adivsory(self):
        for content_type in ['rpm', 'module']:
            event = ErrataAdvisoryStateChangedEvent(
                'msg-id-1',
                ErrataAdvisory(123, 'name', 'REL_PREP', [content_type, 'jar', 'pom']))
            handler = UpdateDBOnAdvisoryChange()
            self.assertTrue(handler.can_handle(event))

    def test_not_handle_non_rpm_advisory(self):
        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-1', ErrataAdvisory(123, 'name', 'REL_PREP', ['docker']))
        handler = UpdateDBOnAdvisoryChange()
        self.assertFalse(handler.can_handle(event))
