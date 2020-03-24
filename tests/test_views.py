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

from collections import defaultdict
import unittest
import json
import datetime
import contextlib
import flask

from unittest.mock import patch

from freshmaker import app, db, events, models, login_manager
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState
from freshmaker.errata import ErrataAdvisory
import freshmaker.auth
from tests import helpers


@login_manager.user_loader
def user_loader(username):
    return models.User.find_user_by_name(username=username)


class ViewBaseTest(helpers.ModelsTestCase):
    def setUp(self):
        super(ViewBaseTest, self).setUp()
        patched_permissions = defaultdict(lambda: {'groups': [], 'users': []})
        patched_permissions['admin'] = {'groups': ['admin'], 'users': ['root']}
        patched_permissions['manual_rebuilder'] = {'groups': [], 'users': ['tom_hanks']}
        self.patched_permissions = patch.object(
            freshmaker.auth.conf, 'permissions', new=patched_permissions)
        self.patched_permissions.start()

        self.patch_oidc_base_namespace = patch.object(
            freshmaker.auth.conf, 'oidc_base_namespace',
            new='http://example.com/')
        self.patch_oidc_base_namespace.start()

        self.client = app.test_client()

        self.setup_test_data()

    def tearDown(self):
        super(ViewBaseTest, self).tearDown()

        self.patched_permissions.stop()
        self.patch_oidc_base_namespace.stop()

    @contextlib.contextmanager
    def test_request_context(self, user=None, groups=None, auth_backend=None,
                             oidc_scopes=None, **kwargs):
        with app.test_request_context(**kwargs):
            patch_auth_backend = None
            if user is not None:
                # authentication is disabled with auth_backend=noauth
                patch_auth_backend = patch.object(
                    freshmaker.auth.conf, 'auth_backend',
                    new=auth_backend if auth_backend else "kerberos")
                patch_auth_backend.start()
                if not models.User.find_user_by_name(user):
                    models.User.create_user(username=user)
                    db.session.commit()
                flask.g.user = models.User.find_user_by_name(user)

                if groups is not None:
                    if isinstance(groups, list):
                        flask.g.groups = groups
                    else:
                        flask.g.groups = [groups]
                else:
                    flask.g.groups = []
                with self.client.session_transaction() as sess:
                    # prior to version 0.5, flask_login gets user_id from
                    # session['user_id'], and then in version 0.5, it's
                    # changed to get from session['_user_id'], so we set
                    # both here to make it work for both old and new versions
                    sess['user_id'] = user
                    sess['_user_id'] = user
                    sess['_fresh'] = True

                oidc_scopes = oidc_scopes if oidc_scopes else []
                oidc_namespace = freshmaker.auth.conf.oidc_base_namespace
                flask.g.oidc_scopes = [
                    '{0}{1}'.format(oidc_namespace, scope) for scope in
                    oidc_scopes]
            try:
                yield
            finally:
                if patch_auth_backend is not None:
                    patch_auth_backend.stop()

    def setup_test_data(self):
        """Set up data for running tests"""


class TestViews(helpers.ModelsTestCase):
    def setUp(self):
        super(TestViews, self).setUp()
        self._init_data()

        self.client = app.test_client()

    def _init_data(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000001", "101", events.TestingEvent)
        build = models.ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build.build_args = '{"key": "value"}'
        models.ArtifactBuild.create(db.session, event, "mksh", "module", 1235)
        models.ArtifactBuild.create(db.session, event, "bash", "module", 1236)
        models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000002", "102", events.TestingEvent)
        db.session.commit()
        db.session.expire_all()

    def test_query_build(self):
        resp = self.client.get('/api/1/builds/1')
        data = resp.json
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['name'], 'ed')
        self.assertEqual(data['type'], ArtifactType.MODULE.value)
        self.assertEqual(data['state'], ArtifactBuildState.BUILD.value)
        self.assertEqual(data['event_id'], 1)
        self.assertEqual(data['build_id'], 1234)
        self.assertEqual(data['build_args'], {"key": "value"})
        self.assertEqual(data['rebuild_reason'], "unknown")

    def test_query_builds(self):
        resp = self.client.get('/api/1/builds/')
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)
        for name in ['ed', 'mksh', 'bash']:
            self.assertIn(name, [b['name'] for b in builds])
        for build_id in [1234, 1235, 1236]:
            self.assertIn(build_id, [b['build_id'] for b in builds])

    def test_query_builds_order_by_default(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/')
        builds = resp.json['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([9, 8, 3, 2, 1], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_id_asc(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/?order_by=id')
        builds = resp.json['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([1, 2, 3, 8, 9], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_build_id_desc(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/?order_by=-build_id')
        builds = resp.json['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([8, 9, 3, 2, 1], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_unknown_key(self):
        resp = self.client.get('/api/1/builds/?order_by=-foo')
        data = resp.json
        self.assertEqual(data['status'], 400)
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith(
            "An invalid order_by key was suplied, allowed keys are"))

    def test_query_builds_by_name(self):
        resp = self.client.get('/api/1/builds/?name=ed')
        builds = resp.json['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')

        resp = self.client.get('/api/1/builds/?name=mksh')
        builds = resp.json['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'mksh')

        resp = self.client.get('/api/1/builds/?name=nonexist')
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

    def test_query_builds_by_type(self):
        resp = self.client.get('/api/1/builds/?type=0')
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=1')
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=2')
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?type=module')
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_type(self):
        resp = self.client.get('/api/1/builds/?type=100')
        data = resp.json
        self.assertEqual(data["status"], 400)
        self.assertEqual(data["message"],
                         "An invalid artifact type was supplied")

    def test_query_builds_by_state(self):
        resp = self.client.get('/api/1/builds/?state=0')
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_state(self):
        resp = self.client.get('/api/1/builds/?state=100')
        data = resp.json
        self.assertEqual(data["status"], 400)
        self.assertEqual(data["message"],
                         "An invalid state was supplied")

    def test_query_build_by_event_type_id(self):
        event1 = models.Event.create(db.session,
                                     "2018-00000000-0000-0000-0000-000000000001",
                                     "testmodule/master/?#0000000000000000000000000000000000000001",
                                     events.GitModuleMetadataChangeEvent)
        build1 = models.ArtifactBuild.create(db.session, event1, "testmodule", "module", 2345)
        event2 = models.Event.create(db.session,
                                     "2018-00000000-0000-0000-0000-000000000002",
                                     "2345",
                                     events.MBSModuleStateChangeEvent)
        models.ArtifactBuild.create(db.session, event2, "testmodule2", "module", 2346, build1)

        event3 = models.Event.create(db.session,
                                     "2018-00000000-0000-0000-0000-000000000003",
                                     "testmodule3/master/?#0000000000000000000000000000000000000001",
                                     events.GitModuleMetadataChangeEvent)
        models.ArtifactBuild.create(db.session, event3, "testmodule3", "module", 2347, build1)
        db.session.commit()

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.TestingEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.GitModuleMetadataChangeEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 2)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.MBSModuleStateChangeEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 1)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.KojiTaskStateChangeEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_search_key(self):
        resp = self.client.get('/api/1/builds/?event_search_key=101')
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_search_key=102')
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_type_id_and_search_key(self):
        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=101' % models.EVENT_TYPES[events.TestingEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=102' % models.EVENT_TYPES[events.TestingEvent])
        builds = resp.json['items']
        self.assertEqual(len(builds), 0)

    def test_query_builds_pagination_includes_query_params(self):
        event = models.Event.create(db.session, '2018-00000000-0000-0000-0000-000000000001', '101', events.TestingEvent)
        models.ArtifactBuild.create(db.session, event, 'ed', 'module', 20081234)
        models.ArtifactBuild.create(db.session, event, 'ed', 'module', 20081235)
        resp = self.client.get('/api/1/builds/?name=ed&per_page=1&page=2')
        data = resp.json
        builds = data['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')
        meta = data['meta']
        for page in ['first', 'last', 'prev', 'next']:
            for query in ['name=ed', 'per_page=1']:
                self.assertTrue(query in meta[page])

    def test_query_builds_pagination_includes_prev_and_next_page(self):
        resp = self.client.get('/api/1/builds/?name=ed')
        data = resp.json
        builds = data['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')
        meta = data['meta']
        self.assertTrue(meta['prev'] is None)
        self.assertTrue(meta['next'] is None)

    def test_query_event(self):
        resp = self.client.get('/api/1/events/1')
        data = resp.json
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['message_id'], '2017-00000000-0000-0000-0000-000000000001')
        self.assertEqual(data['search_key'], '101')
        self.assertEqual(data['event_type_id'], models.EVENT_TYPES[events.TestingEvent])
        self.assertEqual(len(data['builds']), 3)

    def test_query_event_without_builds(self):
        resp = self.client.get('/api/1/events/?show_full_json=False')
        data = resp.json
        self.assertEqual(data['items'][0]['id'], 2)
        self.assertRaises(KeyError, lambda: data['items'][0]['builds'])

    def test_query_event_id_without_builds(self):
        resp = self.client.get('/api/1/events/2?show_full_json=False')
        data = resp.json
        self.assertEqual(data['id'], 2)
        self.assertRaises(KeyError, lambda: data['builds'])

    def test_query_event_without_builds_v2(self):
        resp = self.client.get('/api/2/events/')
        data = resp.json
        self.assertEqual(data['items'][0]['id'], 2)
        self.assertRaises(KeyError, lambda: data['items'][0]['builds'])

    def test_query_event_id_without_builds_v2(self):
        resp = self.client.get('/api/2/events/2')
        data = resp.json
        self.assertEqual(data['id'], 2)
        self.assertRaises(KeyError, lambda: data['builds'])

    def test_query_events(self):
        resp = self.client.get('/api/1/events/')
        evs = resp.json['items']
        self.assertEqual(len(evs), 2)

    def test_query_event_complete(self):
        event = db.session.query(models.Event).get(1)
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2099, 8, 21, 13, 42, 20)
            event.transition(models.EventState.COMPLETE.value)
        resp = self.client.get('/api/1/events/1')
        data = resp.json
        self.assertEqual(data['time_done'], '2099-08-21T13:42:20Z')

    def test_query_event_by_message_id(self):
        resp = self.client.get('/api/1/events/?message_id=2017-00000000-0000-0000-0000-000000000001')
        evs = resp.json['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['message_id'], '2017-00000000-0000-0000-0000-000000000001')

    def test_query_event_by_search_key(self):
        resp = self.client.get('/api/1/events/?search_key=101')
        evs = resp.json['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['search_key'], '101')

    def test_query_event_by_state_name(self):
        models.Event.create(db.session,
                            "2018-00000000-0000-0000-0123-000000000001",
                            "0123001",
                            events.MBSModuleStateChangeEvent,
                            state=EventState['COMPLETE'].value)
        resp = self.client.get('/api/1/events/?state=complete')
        evs = resp.json['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['state'], EventState['COMPLETE'].value)

    def test_query_event_with_invalid_state_name(self):
        resp = self.client.get('/api/1/events/?state=invalid')
        data = resp.json
        self.assertEqual(data['status'], 400)
        self.assertEqual(data['message'], "Invalid state was supplied: invalid")

    def test_query_event_by_multiple_state_names(self):
        models.Event.create(db.session,
                            "2018-00000000-0000-0000-0123-000000000001",
                            "0123001",
                            events.MBSModuleStateChangeEvent,
                            state=EventState['BUILDING'].value)
        models.Event.create(db.session,
                            "2018-00000000-0000-0000-0123-000000000002",
                            "0123002",
                            events.MBSModuleStateChangeEvent,
                            state=EventState['COMPLETE'].value)
        models.Event.create(db.session,
                            "2018-00000000-0000-0000-0123-000000000003",
                            "0123003",
                            events.MBSModuleStateChangeEvent,
                            state=EventState['COMPLETE'].value)
        resp = self.client.get('/api/1/events/?state=building&state=complete')
        evs = resp.json['items']
        self.assertEqual(len(evs), 3)
        building_events = [e for e in evs if e['state'] == EventState['BUILDING'].value]
        complete_events = [e for e in evs if e['state'] == EventState['COMPLETE'].value]
        self.assertEqual(len(building_events), 1)
        self.assertEqual(len(complete_events), 2)

    def test_query_event_by_requester(self):
        ev1 = models.Event.create(
            db.session,
            "2018-00000000-0000-0000-0123-000000000001",
            "0123001",
            events.ManualRebuildWithAdvisoryEvent,
            state=EventState['COMPLETE'].value,
            requester="bob",
            requested_rebuilds="foo-1-1 bar-1-1"
        )
        resp = self.client.get('/api/1/events/?requester=bob')
        evs = resp.json['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['requester'], ev1.requester)
        self.assertEqual(evs[0]['search_key'], ev1.search_key)

        resp = self.client.get('/api/1/events/?requester=alice')
        evs = resp.json['items']
        self.assertEqual(len(evs), 0)

    def test_query_event_by_multiple_requesters(self):
        models.Event.create(
            db.session,
            "2018-00000000-0000-0000-0123-000000000001",
            "0123001",
            events.ManualRebuildWithAdvisoryEvent,
            state=EventState['COMPLETE'].value,
            requester="bob",
            requested_rebuilds="foo-1-1 bar-1-1"
        ),
        models.Event.create(
            db.session,
            "2018-00000000-0000-0000-0123-000000000002",
            "0123002",
            events.ManualRebuildWithAdvisoryEvent,
            state=EventState['COMPLETE'].value,
            requester="alice",
            requested_rebuilds="foo-1-2 bar-1-2"
        ),
        resp = self.client.get('/api/1/events/?requester=alice&requester=bob')
        evs = resp.json['items']
        self.assertEqual(len(evs), 2)
        self.assertTrue(('bob', '0123001') in [(e['requester'], e['search_key']) for e in evs])
        self.assertTrue(('alice', '0123002') in [(e['requester'], e['search_key']) for e in evs])

    def test_query_event_order_by_default(self):
        resp = self.client.get('/api/1/events/')
        evs = resp.json['items']
        for id, build in zip([2, 1], evs):
            self.assertEqual(id, build['id'])

    def test_query_event_order_by_id_asc(self):
        resp = self.client.get('/api/1/events/?order_by=id')
        evs = resp.json['items']
        for id, build in zip([1, 2], evs):
            self.assertEqual(id, build['id'])

    def test_query_event_order_by_id_message_id_desc(self):
        resp = self.client.get('/api/1/events/?order_by=-message_id')
        evs = resp.json['items']
        for id, build in zip([2, 1], evs):
            self.assertEqual(id, build['id'])

    def test_query_event_pagination_includes_query_params(self):
        models.Event.create(db.session, '2018-00000000-0000-0000-0000-000000000001', '101', events.TestingEvent)
        models.Event.create(db.session, '2018-00000000-0000-0000-0000-000000000002', '101', events.TestingEvent)
        resp = self.client.get('/api/1/events/?search_key=101&per_page=1&page=2')
        data = resp.json
        evs = data['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['search_key'], '101')
        meta = data['meta']
        for page in ['first', 'last', 'prev', 'next']:
            for query in ['search_key=101', 'per_page=1']:
                self.assertTrue(query in meta[page])

    def test_query_event_pagination_includes_prev_and_next_page(self):
        resp = self.client.get('/api/1/events/?search_key=101')
        data = resp.json
        evs = data['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['search_key'], '101')
        meta = data['meta']
        self.assertTrue(meta['prev'] is None)
        self.assertTrue(meta['next'] is None)

    def test_patch_event_missing_action(self):
        resp = self.client.patch(
            '/api/1/events/1',
            data=json.dumps({}))
        data = resp.json
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith('Missing action in request.'))

    def test_patch_event_unsupported_action(self):
        resp = self.client.patch(
            '/api/1/events/1',
            data=json.dumps({'action': 'unsupported'}))
        data = resp.json
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith('Unsupported action requested.'))

    def test_query_event_types(self):
        resp = self.client.get('/api/1/event-types/')
        event_types = resp.json['items']
        self.assertEqual(len(event_types), len(models.EVENT_TYPES))

    def test_query_event_type(self):
        for cls, val in models.EVENT_TYPES.items():
            resp = self.client.get('/api/1/event-types/%s' % val)
            event = resp.json
            self.assertEqual(event['id'], val)
            self.assertEqual(event['name'], cls.__name__)

    def test_query_nonexist_event_type(self):
        resp = self.client.get('/api/1/event-types/99999')
        data = resp.json
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such event type found.')

    def test_query_build_types(self):
        resp = self.client.get('/api/1/build-types/')
        build_types = resp.json['items']
        self.assertEqual(len(build_types), len(list(ArtifactType)))

    def test_query_build_type(self):
        for t in list(ArtifactType):
            resp = self.client.get('/api/1/build-types/%s' % t.value)
            build_type = resp.json
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_type(self):
        resp = self.client.get('/api/1/build-types/99999')
        data = resp.json
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build type found.')

    def test_query_build_states(self):
        resp = self.client.get('/api/1/build-states/')
        build_types = resp.json['items']
        self.assertEqual(len(build_types), len(list(ArtifactBuildState)))

    def test_query_build_state(self):
        for t in list(ArtifactBuildState):
            resp = self.client.get('/api/1/build-states/%s' % t.value)
            build_type = resp.json
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_state(self):
        resp = self.client.get('/api/1/build-states/99999')
        data = resp.json
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build state found.')

    def test_about_api(self):
        # Since the version is always changing, let's just mock it to be consistent
        with patch('freshmaker.views.version', '1.0.0'):
            resp = self.client.get('/api/1/about/')
        data = resp.json
        self.assertEqual(data['version'], '1.0.0')

    @patch("freshmaker.views.ImageVerifier")
    def test_verify_image(self, verifier):
        verifier.return_value.verify_image.return_value = {"foo-1-1": ["content-set"]}
        resp = self.client.get('/api/1/verify-image/foo-1-1')
        data = resp.json
        self.assertEqual(data, {
            'images': {'foo-1-1': ['content-set']},
            'msg': 'Found 1 images which are handled by Freshmaker for defined content_sets.'})

    @patch("freshmaker.views.ImageVerifier")
    def test_verify_image_repository(self, verifier):
        verifier.return_value.verify_repository.return_value = {
            "foo-1-1": ["content-set"]}
        resp = self.client.get('/api/1/verify-image-repository/foo/bar')
        data = resp.json
        self.assertEqual(data, {
            'images': {'foo-1-1': ['content-set']},
            'msg': 'Found 1 images which are handled by Freshmaker for defined content_sets.'})

    def test_dependencies(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "103", events.TestingEvent)
        event1 = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000004", "104", events.TestingEvent)
        db.session.commit()
        event.add_event_dependency(db.session, event1)
        db.session.commit()
        resp = self.client.get('/api/1/events/4')
        data = resp.json
        self.assertEqual(data['id'], event1.id)
        self.assertEqual(data['depends_on_events'], [])
        self.assertEqual(data['depending_events'], [event.id])

        resp = self.client.get('/api/1/events/3')
        data = resp.json
        self.assertEqual(data['id'], event.id)
        self.assertEqual(data['depends_on_events'], [event1.id])
        self.assertEqual(data['depending_events'], [])

    def test_trailing_slash(self):
        urls = ('/api/2/builds', '/api/2/builds/',
                '/api/2/events', '/api/2/events/')
        for url in urls:
            response = self.client.get(url, follow_redirects=True)
            self.assertEqual(response.status_code, 200)


class TestViewsMultipleFilterValues(helpers.ModelsTestCase):
    def setUp(self):
        super(TestViewsMultipleFilterValues, self).setUp()

        self._init_data()

        self.client = app.test_client()

    def _init_data(self):
        event = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000001",
            "101", events.TestingEvent)
        event.state = EventState.BUILDING.value
        build = models.ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build.build_args = '{"key": "value"}'
        models.ArtifactBuild.create(db.session, event, "mksh", "module", 1235)
        models.ArtifactBuild.create(db.session, event, "bash", "module", 1236)
        event2 = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000002",
            "102", events.GitModuleMetadataChangeEvent)
        event2.state = EventState.SKIPPED.value
        event3 = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000003",
            "103", events.MBSModuleStateChangeEvent)
        event3.state = EventState.FAILED.value
        db.session.commit()
        db.session.expire_all()

    def test_query_event_multiple_states(self):
        resp = self.client.get('/api/1/events/?state=%d&state=%d' % (
            EventState.SKIPPED.value, EventState.BUILDING.value))
        evs = resp.json['items']
        self.assertEqual(len(evs), 2)

    def test_query_event_multiple_event_type_ids(self):
        resp = self.client.get('/api/1/events/?event_type_id=%d&event_type_id=%d' % (
            models.EVENT_TYPES[events.TestingEvent],
            models.EVENT_TYPES[events.GitModuleMetadataChangeEvent]))
        evs = resp.json['items']
        self.assertEqual(len(evs), 2)


class TestManualTriggerRebuild(ViewBaseTest):
    def setUp(self):
        super(TestManualTriggerRebuild, self).setUp()
        self.client = app.test_client()

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2017, 8, 21, 13, 42, 20)

            with self.test_request_context(user='root'):
                resp = self.client.post(
                    '/api/1/builds/',
                    data=json.dumps({'errata_id': 1}),
                    content_type='application/json',
                )
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data, {
            u'builds': [],
            u'depending_events': [],
            u'depends_on_events': [],
            u'event_type_id': 13,
            u'id': 1,
            u'message_id': u'manual_rebuild_123',
            u'search_key': u'123',
            u'state': 0,
            u'state_name': u'INITIALIZED',
            u'state_reason': None,
            u'time_created': u'2017-08-21T13:42:20Z',
            u'time_done': None,
            u'url': u'/api/1/events/1',
            u'dry_run': False,
            u'requester': 'root',
            u'requested_rebuilds': [],
            u'requester_metadata': {}})
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_dry_run(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        payload = {'errata_id': 1, 'dry_run': True}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data['dry_run'], True)
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1, 'dry_run': True,
             'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_container_images(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        payload = {
            'errata_id': 1,
            'container_images': ['foo-1-1', 'bar-1-1'],
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data['requested_rebuilds'], ["foo-1-1", "bar-1-1"])
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'container_images': ["foo-1-1", "bar-1-1"], 'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_metadata(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        payload = {
            'errata_id': 1,
            'metadata': {'foo': ['bar']},
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data['requester_metadata'], {"foo": ["bar"]})
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'metadata': {"foo": ["bar"]}, 'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_requester(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        payload = {
            'errata_id': 1,
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data['requester'], "root")
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    @patch('freshmaker.models.Event.add_event_dependency')
    def test_dependent_manual_rebuild_on_existing_event(self, add_dependency, time,
                                                        from_advisory_id, publish):
        models.Event.create(db.session,
                            "2017-00000000-0000-0000-0000-000000000003",
                            "103", events.TestingEvent)
        db.session.commit()
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            103, 'name', 'REL_PREP', ['rpm'])

        payload = {
            'errata_id': 103,
            'container_images': ['foo-1-1'],
            'freshmaker_event_id': 1,
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')
        data = resp.json

        # Other fields are predictible.
        self.assertEqual(data['requested_rebuilds'], ["foo-1-1"])
        assert add_dependency.call_count == 1
        assert "103" == add_dependency.call_args[0][1].search_key
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 103,
             'container_images': ["foo-1-1"], 'freshmaker_event_id': 1,
             'requester': 'root'})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    @patch('freshmaker.models.Event.add_event_dependency')
    def test_dependent_manual_rebuild_on_existing_event_no_errata_id(
        self, add_dependency, time, from_advisory_id, publish,
    ):
        models.Event.create(
            db.session, '2017-00000000-0000-0000-0000-000000000003', '1', events.TestingEvent,
        )
        db.session.commit()
        from_advisory_id.return_value = ErrataAdvisory(1, 'name', 'REL_PREP', ['rpm'])

        payload = {
            'container_images': ['foo-1-1'],
            'freshmaker_event_id': 1,
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['search_key'], '1')

    def test_dependent_manual_rebuild_on_existing_event_errata_id_mismatch(self):
        models.Event.create(
            db.session, '2017-00000000-0000-0000-0000-000000000003', '1', events.TestingEvent,
        )
        db.session.commit()

        payload = {
            'container_images': ['foo-1-1'],
            'errata_id': 2,
            'freshmaker_event_id': 1,
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json['message'],
            'The provided "errata_id" doesn\'t match the Advisory ID associated with the input '
            '"freshmaker_event_id".',
        )

    def test_dependent_manual_rebuild_on_existing_event_invalid_dependent(self):
        payload = {
            'container_images': ['foo-1-1'],
            'freshmaker_event_id': 1,
        }
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], 'The provided "freshmaker_event_id" is invalid.')

    def test_manual_rebuild_missing_errata_id(self):
        payload = {'container_images': ['foo-1-1']}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json['message'],
            'You must at least provide "errata_id" or "freshmaker_event_id" in the request.',
        )

    def test_manual_rebuild_invalid_type_errata_id(self):
        payload = {'errata_id': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"errata_id" must be an integer.')

    def test_manual_rebuild_invalid_type_freshmaker_event_id(self):
        payload = {'freshmaker_event_id': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"freshmaker_event_id" must be an integer.')

    def test_manual_rebuild_invalid_type_container_images(self):
        payload = {'container_images': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"container_images" must be an array of strings.')

    def test_manual_rebuild_invalid_type_dry_run(self):
        payload = {'dry_run': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post('/api/1/builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"dry_run" must be a boolean.')

    def test_manual_rebuild_with_async_event(self):
        models.Event.create(
            db.session, '2017-00000000-0000-0000-0000-000000000003', '123',
            events.FreshmakerAsyncManualBuildEvent
        )
        db.session.commit()
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2017, 8, 21, 13, 42, 20)

            payload = {
                'container_images': ['foo-1-1', 'bar-1-1'],
                'freshmaker_event_id': 1,
            }
            with self.test_request_context(user='root'):
                resp = self.client.post(
                    '/api/1/builds/',
                    data=json.dumps(payload),
                    content_type='application/json',
                )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json['message'],
            'The event (id=1) is an async build event, can not be used for this build.')


class TestAsyncBuild(ViewBaseTest):
    def setUp(self):
        super(TestAsyncBuild, self).setUp()
        self.client = app.test_client()

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.koji.async_manual_build.time.time')
    def test_async_build(self, time, publish):
        time.return_value = 123
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2017, 8, 21, 13, 42, 20)

            payload = {
                'dist_git_branch': 'master',
                'container_images': ['foo-1-1', 'bar-1-1']
            }
            with self.test_request_context(user='root'):
                resp = self.client.post(
                    '/api/1/async-builds/',
                    data=json.dumps(payload),
                    content_type='application/json',
                )
        data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(data, {
            u'builds': [],
            u'depending_events': [],
            u'depends_on_events': [],
            u'dry_run': False,
            u'event_type_id': 14,
            u'id': 1,
            u'message_id': 'async_build_123',
            u'requested_rebuilds': ['foo-1-1-container', 'bar-1-1-container'],
            u'requester': 'root',
            u'requester_metadata': {},
            u'search_key': 'async_build_123',
            u'state': 0,
            u'state_name': 'INITIALIZED',
            u'state_reason': None,
            u'time_created': '2017-08-21T13:42:20Z',
            u'time_done': None,
            u'url': '/api/1/events/1'})

        publish.assert_called_once_with(
            'async.manual.build',
            {
                'msg_id': 'async_build_123',
                'dist_git_branch': 'master',
                'container_images': ['foo-1-1-container', 'bar-1-1-container'],
                'requester': 'root'
            })

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.koji.async_manual_build.time.time')
    def test_async_build_dry_run(self, time, publish):
        time.return_value = 123

        payload = {
            'dist_git_branch': 'master',
            'container_images': ['foo-1-1', 'bar-1-1'],
            'dry_run': True
        }
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(data['dry_run'], True)
        publish.assert_called_once_with(
            'async.manual.build',
            {
                'msg_id': 'async_build_123',
                'dist_git_branch': 'master',
                'container_images': ['foo-1-1-container', 'bar-1-1-container'],
                'dry_run': True,
                'requester': 'root',
            })

    def test_async_build_with_non_async_event(self):
        models.Event.create(
            db.session, '2017-00000000-0000-0000-0000-000000000003', '123', events.TestingEvent,
        )
        db.session.commit()
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2017, 8, 21, 13, 42, 20)

            payload = {
                'dist_git_branch': 'master',
                'container_images': ['foo-1-1', 'bar-1-1'],
                'freshmaker_event_id': 1,
            }
            with self.test_request_context(user='root'):
                resp = self.client.post(
                    '/api/1/async-builds/',
                    data=json.dumps(payload),
                    content_type='application/json',
                )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], 'The event (id=1) is not an async build event.')

    def test_async_build_invalid_dist_git_branch(self):
        payload = {'dist_git_branch': 123}
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"dist_git_branch" must be a string.')

    def test_async_build_invalid_type_freshmaker_event_id(self):
        payload = {'freshmaker_event_id': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"freshmaker_event_id" must be an integer.')

    def test_async_build_invalid_type_container_images(self):
        payload = {'container_images': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"container_images" must be an array of strings.')

    def test_async_build_invalid_type_brew_target(self):
        payload = {'brew_target': 123}
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"brew_target" must be a string.')

    def test_async_build_invalid_type_dry_run(self):
        payload = {'dry_run': '123'}
        with self.test_request_context(user='root'):
            resp = self.client.post(
                '/api/1/async-builds/', json=payload, content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['message'], '"dry_run" must be a boolean.')


class TestPatchAPI(ViewBaseTest):
    def test_patch_event_cancel(self):
        event = models.Event.create(
            db.session,
            '2017-00000000-0000-0000-0000-000000000003',
            '103',
            events.TestingEvent,
            # Tests that admins can cancel any event, regardless of the requester
            requester='tom_hanks',
        )
        models.ArtifactBuild.create(db.session, event, "mksh", "module", build_id=1237,
                                    state=ArtifactBuildState.PLANNED.value)
        models.ArtifactBuild.create(db.session, event, "bash", "module", build_id=1238,
                                    state=ArtifactBuildState.PLANNED.value)
        models.ArtifactBuild.create(db.session, event, "dash", "module", build_id=1239,
                                    state=ArtifactBuildState.BUILD.value)
        models.ArtifactBuild.create(db.session, event, "tcsh", "module", build_id=1240,
                                    state=ArtifactBuildState.DONE.value)
        db.session.commit()

        with self.test_request_context(user='root'):
            resp = self.client.patch(f'/api/1/events/{event.id}', json={'action': 'cancel'})
        data = resp.json

        self.assertEqual(data['id'], event.id)
        self.assertEqual(len(data['builds']), 4)
        self.assertEqual(data['state_name'], 'CANCELED')
        self.assertTrue(data['state_reason'].startswith(
            'Event id {} requested for canceling by user '.format(event.id)))
        self.assertEqual(len([b for b in data['builds'] if b['state_name'] == 'CANCELED']), 3)
        self.assertEqual(len([b for b in data['builds'] if b['state_name'] == 'DONE']), 1)

    def test_patch_event_cancel_user(self):
        event = models.Event.create(
            db.session,
            '2017-00000000-0000-0000-0000-000000000003',
            '123',
            events.TestingEvent,
            requester='tom_hanks',
        )
        db.session.commit()

        with self.test_request_context(user='tom_hanks'):
            resp = self.client.patch(f'/api/1/events/{event.id}', json={'action': 'cancel'})
        assert resp.status_code == 200

    def test_patch_event_cancel_user_not_their_event(self):
        event = models.Event.create(
            db.session,
            '2017-00000000-0000-0000-0000-000000000003',
            '103',
            events.TestingEvent,
            requester='han_solo',
        )
        db.session.commit()

        with self.test_request_context(user='tom_hanks'):
            resp = self.client.patch(f'/api/1/events/{event.id}', json={'action': 'cancel'})
        assert resp.status_code == 403
        assert resp.json['message'] == 'You must be an admin to cancel someone else\'s event.'

    def test_patch_event_not_allowed(self):
        with self.test_request_context(user='john_smith'):
            resp = self.client.patch('/api/1/events/1', json={'action': 'cancel'})
        assert resp.status_code == 403
        assert resp.json['message'] == (
            'User john_smith does not have any of the following roles: admin, manual_rebuilder'
        )


class TestOpenIDCLogin(ViewBaseTest):
    """Test that OpenIDC login"""

    def setUp(self):
        super(TestOpenIDCLogin, self).setUp()
        self.patch_auth_backend = patch.object(
            freshmaker.auth.conf, 'auth_backend', new='openidc')
        self.patch_auth_backend.start()

    def tearDown(self):
        super(TestOpenIDCLogin, self).tearDown()
        self.patch_auth_backend.stop()

    def test_openidc_manual_trigger_unauthorized(self):
        rv = self.client.post('/api/1/builds/',
                              data=json.dumps({'errata_id': 1}),
                              content_type='application/json')
        self.assertEqual(rv.status, '401 UNAUTHORIZED')

    def test_openidc_manual_trigger_authorized(self):
        with self.test_request_context(user='dev', auth_backend="openidc",
                                       oidc_scopes=["submit-build"]):
            rv = self.client.post('/api/1/builds/',
                                  data=json.dumps({'errata_id': 1}),
                                  content_type='application/json')
            self.assertEqual(rv.status, '403 FORBIDDEN')


if __name__ == '__main__':
    unittest.main()
