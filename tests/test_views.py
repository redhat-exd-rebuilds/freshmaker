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

import unittest
import json
import datetime
import contextlib
import flask

from mock import patch

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
        patched_allowed_clients = {'groups': ['freshmaker-clients'],
                                   'users': ['dev']}
        patched_admins = {'groups': ['admin'], 'users': ['root']}
        self.patch_allowed_clients = patch.object(freshmaker.auth.conf,
                                                  'allowed_clients',
                                                  new=patched_allowed_clients)
        self.patch_admins = patch.object(freshmaker.auth.conf,
                                         'admins',
                                         new=patched_admins)
        self.patch_allowed_clients.start()
        self.patch_admins.start()

        self.patch_oidc_base_namespace = patch.object(
            freshmaker.auth.conf, 'oidc_base_namespace',
            new='http://example.com/')
        self.patch_oidc_base_namespace.start()

        self.client = app.test_client()

        self.setup_test_data()

    def tearDown(self):
        super(ViewBaseTest, self).tearDown()

        self.patch_allowed_clients.stop()
        self.patch_admins.stop()
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
                    sess['user_id'] = user
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
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000001", "RHSA-2018-101", events.TestingEvent)
        build = models.ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build.build_args = '{"key": "value"}'
        models.ArtifactBuild.create(db.session, event, "mksh", "module", 1235)
        models.ArtifactBuild.create(db.session, event, "bash", "module", 1236)
        models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000002", "RHSA-2018-102", events.TestingEvent)
        db.session.commit()
        db.session.expire_all()

    def test_query_build(self):
        resp = self.client.get('/api/1/builds/1')
        data = json.loads(resp.get_data(as_text=True))
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
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)
        for name in ['ed', 'mksh', 'bash']:
            self.assertIn(name, [b['name'] for b in builds])
        for build_id in [1234, 1235, 1236]:
            self.assertIn(build_id, [b['build_id'] for b in builds])

    def test_query_builds_order_by_default(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "RHSA-2018-103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([9, 8, 3, 2, 1], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_id_asc(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "RHSA-2018-103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/?order_by=id')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([1, 2, 3, 8, 9], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_build_id_desc(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "RHSA-2018-103", events.TestingEvent)
        build9 = models.ArtifactBuild.create(db.session, event, "make", "module", 1237)
        build9.id = 9
        db.session.commit()
        build8 = models.ArtifactBuild.create(db.session, event, "attr", "module", 1238)
        build8.id = 8
        db.session.commit()
        db.session.expire_all()
        resp = self.client.get('/api/1/builds/?order_by=-build_id')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 5)
        for id, build in zip([8, 9, 3, 2, 1], builds):
            self.assertEqual(id, build['id'])

    def test_query_builds_order_by_unknown_key(self):
        resp = self.client.get('/api/1/builds/?order_by=-foo')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['status'], 400)
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith(
            "An invalid order_by key was suplied, allowed keys are"))

    def test_query_builds_by_name(self):
        resp = self.client.get('/api/1/builds/?name=ed')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')

        resp = self.client.get('/api/1/builds/?name=mksh')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'mksh')

        resp = self.client.get('/api/1/builds/?name=nonexist')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

    def test_query_builds_by_type(self):
        resp = self.client.get('/api/1/builds/?type=0')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=1')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=2')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?type=module')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_type(self):
        resp = self.client.get('/api/1/builds/?type=100')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data["status"], 400)
        self.assertEqual(data["message"],
                         "An invalid artifact type was supplied")

    def test_query_builds_by_state(self):
        resp = self.client.get('/api/1/builds/?state=0')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_state(self):
        resp = self.client.get('/api/1/builds/?state=100')
        data = json.loads(resp.get_data(as_text=True))
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
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.GitModuleMetadataChangeEvent])
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 2)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.MBSModuleStateChangeEvent])
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 1)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.KojiTaskStateChangeEvent])
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_search_key(self):
        resp = self.client.get('/api/1/builds/?event_search_key=RHSA-2018-101')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_search_key=RHSA-2018-102')
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_type_id_and_search_key(self):
        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=RHSA-2018-101' % models.EVENT_TYPES[events.TestingEvent])
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=RHSA-2018-102' % models.EVENT_TYPES[events.TestingEvent])
        builds = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(builds), 0)

    def test_query_event(self):
        resp = self.client.get('/api/1/events/1')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['message_id'], '2017-00000000-0000-0000-0000-000000000001')
        self.assertEqual(data['search_key'], 'RHSA-2018-101')
        self.assertEqual(data['event_type_id'], models.EVENT_TYPES[events.TestingEvent])
        self.assertEqual(len(data['builds']), 3)

    def test_query_event_without_builds(self):
        resp = self.client.get('/api/1/events/?show_full_json=False')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['items'][0]['id'], 2)
        self.assertRaises(KeyError, lambda: data['items'][0]['builds'])

    def test_query_event_id_without_builds(self):
        resp = self.client.get('/api/1/events/2?show_full_json=False')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['id'], 2)
        self.assertRaises(KeyError, lambda: data['builds'])

    def test_query_event_without_builds_v2(self):
        resp = self.client.get('/api/2/events/')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['items'][0]['id'], 2)
        self.assertRaises(KeyError, lambda: data['items'][0]['builds'])

    def test_query_event_id_without_builds_v2(self):
        resp = self.client.get('/api/2/events/2')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['id'], 2)
        self.assertRaises(KeyError, lambda: data['builds'])

    def test_query_events(self):
        resp = self.client.get('/api/1/events/')
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 2)

    def test_query_event_complete(self):
        event = db.session.query(models.Event).get(1)
        with patch('freshmaker.models.datetime') as datetime_patch:
            datetime_patch.utcnow.return_value = datetime.datetime(2099, 8, 21, 13, 42, 20)
            event.transition(models.EventState.COMPLETE.value)
        resp = self.client.get('/api/1/events/1')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['time_done'], '2099-08-21T13:42:20Z')

    def test_query_event_by_message_id(self):
        resp = self.client.get('/api/1/events/?message_id=2017-00000000-0000-0000-0000-000000000001')
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['message_id'], '2017-00000000-0000-0000-0000-000000000001')

    def test_query_event_by_search_key(self):
        resp = self.client.get('/api/1/events/?search_key=RHSA-2018-101')
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['search_key'], 'RHSA-2018-101')

    def test_query_event_by_state_name(self):
        models.Event.create(db.session,
                            "2018-00000000-0000-0000-0123-000000000001",
                            "0123001",
                            events.MBSModuleStateChangeEvent,
                            state=EventState['COMPLETE'].value)
        resp = self.client.get('/api/1/events/?state=complete')
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['state'], EventState['COMPLETE'].value)

    def test_query_event_with_invalid_state_name(self):
        resp = self.client.get('/api/1/events/?state=invalid')
        data = json.loads(resp.get_data(as_text=True))
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
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 3)
        building_events = [e for e in evs if e['state'] == EventState['BUILDING'].value]
        complete_events = [e for e in evs if e['state'] == EventState['COMPLETE'].value]
        self.assertEqual(len(building_events), 1)
        self.assertEqual(len(complete_events), 2)

    def test_query_event_order_by_default(self):
        resp = self.client.get('/api/1/events/')
        evs = json.loads(resp.get_data(as_text=True))['items']
        for id, build in zip([2, 1], evs):
            self.assertEqual(id, build['id'])

    def test_query_event_order_by_id_asc(self):
        resp = self.client.get('/api/1/events/?order_by=id')
        evs = json.loads(resp.get_data(as_text=True))['items']
        for id, build in zip([1, 2], evs):
            self.assertEqual(id, build['id'])

    def test_query_event_order_by_id_message_id_desc(self):
        resp = self.client.get('/api/1/events/?order_by=-message_id')
        evs = json.loads(resp.get_data(as_text=True))['items']
        for id, build in zip([2, 1], evs):
            self.assertEqual(id, build['id'])

    def test_patch_event_missing_action(self):
        resp = self.client.patch(
            '/api/1/events/1',
            data=json.dumps({}))
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith('Missing action in request.'))

    def test_patch_event_unsupported_action(self):
        resp = self.client.patch(
            '/api/1/events/1',
            data=json.dumps({'action': 'unsupported'}))
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['error'], 'Bad Request')
        self.assertTrue(data['message'].startswith('Unsupported action requested.'))

    def test_patch_event_cancel(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003",
                                    "RHSA-2018-103", events.TestingEvent)
        models.ArtifactBuild.create(db.session, event, "mksh", "module", build_id=1237,
                                    state=ArtifactBuildState.PLANNED.value)
        models.ArtifactBuild.create(db.session, event, "bash", "module", build_id=1238,
                                    state=ArtifactBuildState.PLANNED.value)
        models.ArtifactBuild.create(db.session, event, "dash", "module", build_id=1239,
                                    state=ArtifactBuildState.BUILD.value)
        models.ArtifactBuild.create(db.session, event, "tcsh", "module", build_id=1240,
                                    state=ArtifactBuildState.DONE.value)
        db.session.commit()

        resp = self.client.patch(
            '/api/1/events/{}'.format(event.id),
            data=json.dumps({'action': 'cancel'}))
        data = json.loads(resp.get_data(as_text=True))

        self.assertEqual(data['id'], event.id)
        self.assertEqual(len(data['builds']), 4)
        self.assertEqual(data['state_name'], 'CANCELED')
        self.assertTrue(data['state_reason'].startswith(
            'Event id {} requested for canceling by user '.format(event.id)))
        self.assertEqual(len([b for b in data['builds'] if b['state_name'] == 'CANCELED']), 3)
        self.assertEqual(len([b for b in data['builds'] if b['state_name'] == 'DONE']), 1)

    def test_query_event_types(self):
        resp = self.client.get('/api/1/event-types/')
        event_types = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(event_types), len(models.EVENT_TYPES))

    def test_query_event_type(self):
        for cls, val in models.EVENT_TYPES.items():
            resp = self.client.get('/api/1/event-types/%s' % val)
            event = json.loads(resp.get_data(as_text=True))
            self.assertEqual(event['id'], val)
            self.assertEqual(event['name'], cls.__name__)

    def test_query_nonexist_event_type(self):
        resp = self.client.get('/api/1/event-types/99999')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such event type found.')

    def test_query_build_types(self):
        resp = self.client.get('/api/1/build-types/')
        build_types = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(build_types), len(list(ArtifactType)))

    def test_query_build_type(self):
        for t in list(ArtifactType):
            resp = self.client.get('/api/1/build-types/%s' % t.value)
            build_type = json.loads(resp.get_data(as_text=True))
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_type(self):
        resp = self.client.get('/api/1/build-types/99999')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build type found.')

    def test_query_build_states(self):
        resp = self.client.get('/api/1/build-states/')
        build_types = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(build_types), len(list(ArtifactBuildState)))

    def test_query_build_state(self):
        for t in list(ArtifactBuildState):
            resp = self.client.get('/api/1/build-states/%s' % t.value)
            build_type = json.loads(resp.get_data(as_text=True))
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_state(self):
        resp = self.client.get('/api/1/build-states/99999')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build state found.')

    def test_about_api(self):
        # Since the version is always changing, let's just mock it to be consistent
        with patch('freshmaker.views.version', '1.0.0'):
            resp = self.client.get('/api/1/about/')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['version'], '1.0.0')

    @patch("freshmaker.views.ImageVerifier")
    def test_verify_image(self, verifier):
        verifier.return_value.verify_image.return_value = {"foo-1-1": ["content-set"]}
        resp = self.client.get('/api/1/verify-image/foo-1-1')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data, {
            'images': {'foo-1-1': ['content-set']},
            'msg': 'Found 1 images which are handled by Freshmaker for defined content_sets.'})

    @patch("freshmaker.views.ImageVerifier")
    def test_verify_image_repository(self, verifier):
        verifier.return_value.verify_repository.return_value = {
            "foo-1-1": ["content-set"]}
        resp = self.client.get('/api/1/verify-image-repository/foo/bar')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data, {
            'images': {'foo-1-1': ['content-set']},
            'msg': 'Found 1 images which are handled by Freshmaker for defined content_sets.'})

    def test_dependencies(self):
        event = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000003", "RHSA-2018-103", events.TestingEvent)
        event1 = models.Event.create(db.session, "2017-00000000-0000-0000-0000-000000000004", "RHSA-2018-104", events.TestingEvent)
        db.session.commit()
        event.add_event_dependency(db.session, event1)
        db.session.commit()
        resp = self.client.get('/api/1/events/4')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['id'], event1.id)
        self.assertEqual(data['depends_on_events'], [])
        self.assertEqual(data['depending_events'], [event.id])

        resp = self.client.get('/api/1/events/3')
        data = json.loads(resp.get_data(as_text=True))
        self.assertEqual(data['id'], event.id)
        self.assertEqual(data['depends_on_events'], [event1.id])
        self.assertEqual(data['depending_events'], [])


class TestViewsMultipleFilterValues(helpers.ModelsTestCase):
    def setUp(self):
        super(TestViewsMultipleFilterValues, self).setUp()

        self._init_data()

        self.client = app.test_client()

    def _init_data(self):
        event = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000001",
            "RHSA-2018-101", events.TestingEvent)
        event.state = EventState.BUILDING.value
        build = models.ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build.build_args = '{"key": "value"}'
        models.ArtifactBuild.create(db.session, event, "mksh", "module", 1235)
        models.ArtifactBuild.create(db.session, event, "bash", "module", 1236)
        event2 = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000002",
            "RHSA-2018-102", events.GitModuleMetadataChangeEvent)
        event2.state = EventState.SKIPPED.value
        event3 = models.Event.create(
            db.session, "2017-00000000-0000-0000-0000-000000000003",
            "RHSA-2018-103", events.MBSModuleStateChangeEvent)
        event3.state = EventState.FAILED.value
        db.session.commit()
        db.session.expire_all()

    def test_query_event_multiple_states(self):
        resp = self.client.get('/api/1/events/?state=%d&state=%d' % (
            EventState.SKIPPED.value, EventState.BUILDING.value))
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 2)

    def test_query_event_multiple_event_type_ids(self):
        resp = self.client.get('/api/1/events/?event_type_id=%d&event_type_id=%d' % (
            models.EVENT_TYPES[events.TestingEvent],
            models.EVENT_TYPES[events.GitModuleMetadataChangeEvent]))
        evs = json.loads(resp.get_data(as_text=True))['items']
        self.assertEqual(len(evs), 2)


class TestManualTriggerRebuild(helpers.ModelsTestCase):
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
            resp = self.client.post('/api/1/builds/',
                                    data=json.dumps({'errata_id': 1}),
                                    content_type='application/json')
        data = json.loads(resp.get_data(as_text=True))

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
            u'requester': 'tester1',
            u'requested_rebuilds': [],
            u'requester_metadata': {}})
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_dry_run(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        resp = self.client.post('/api/1/builds/',
                                data=json.dumps({'errata_id': 1, 'dry_run': True}),
                                content_type='application/json')
        data = json.loads(resp.get_data(as_text=True))

        # Other fields are predictible.
        self.assertEqual(data['dry_run'], True)
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1, 'dry_run': True})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_container_images(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        resp = self.client.post(
            '/api/1/builds/', data=json.dumps({
                'errata_id': 1, 'container_images': ["foo-1-1", "bar-1-1"]}),
            content_type='application/json')
        data = json.loads(resp.get_data(as_text=True))

        # Other fields are predictible.
        self.assertEqual(data['requested_rebuilds'], ["foo-1-1", "bar-1-1"])
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'container_images': ["foo-1-1", "bar-1-1"]})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    def test_manual_rebuild_metadata(self, time, from_advisory_id, publish):
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        resp = self.client.post(
            '/api/1/builds/', data=json.dumps({
                'errata_id': 1, 'metadata': {"foo": ["bar"]}}),
            content_type='application/json')
        data = json.loads(resp.get_data(as_text=True))

        # Other fields are predictible.
        self.assertEqual(data['requester_metadata'], {"foo": ["bar"]})
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'metadata': {"foo": ["bar"]}})

    @patch('freshmaker.messaging.publish')
    @patch('freshmaker.parsers.internal.manual_rebuild.ErrataAdvisory.'
           'from_advisory_id')
    @patch('freshmaker.parsers.internal.manual_rebuild.time.time')
    @patch('freshmaker.models.Event.add_event_dependency')
    def test_dependent_manual_rebuild_on_existing_event(self, add_dependency, time,
                                                        from_advisory_id, publish):
        models.Event.create(db.session,
                            "2017-00000000-0000-0000-0000-000000000003",
                            "RHSA-2018-103", events.TestingEvent)
        db.session.commit()
        time.return_value = 123
        from_advisory_id.return_value = ErrataAdvisory(
            123, 'name', 'REL_PREP', ['rpm'])

        resp = self.client.post(
            '/api/1/builds/', data=json.dumps({
                'errata_id': 1, 'container_images': ["foo-1-1"],
                'freshmaker_event_id': 1}),
            content_type='application/json')
        data = json.loads(resp.get_data(as_text=True))
        # Other fields are predictible.
        self.assertEqual(data['requested_rebuilds'], ["foo-1-1"])
        assert add_dependency.call_count == 1
        assert "RHSA-2018-103" == add_dependency.call_args[0][1].search_key
        publish.assert_called_once_with(
            'manual.rebuild',
            {'msg_id': 'manual_rebuild_123', u'errata_id': 1,
             'container_images': ["foo-1-1"], 'freshmaker_event_id': 1})


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
