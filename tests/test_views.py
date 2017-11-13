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
import six

from mock import patch

from freshmaker import app, db, events, models
from freshmaker.types import ArtifactType, ArtifactBuildState


class TestViews(unittest.TestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

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
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['name'], 'ed')
        self.assertEqual(data['type'], ArtifactType.MODULE.value)
        self.assertEqual(data['state'], ArtifactBuildState.BUILD.value)
        self.assertEqual(data['event_id'], 1)
        self.assertEqual(data['build_id'], 1234)
        self.assertEqual(data['build_args'], {"key": "value"})

    def test_query_builds(self):
        resp = self.client.get('/api/1/builds/')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)
        for name in ['ed', 'mksh', 'bash']:
            self.assertIn(name, [b['name'] for b in builds])
        for build_id in [1234, 1235, 1236]:
            self.assertIn(build_id, [b['build_id'] for b in builds])

    def test_query_builds_by_name(self):
        resp = self.client.get('/api/1/builds/?name=ed')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')

        resp = self.client.get('/api/1/builds/?name=mksh')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'mksh')

        resp = self.client.get('/api/1/builds/?name=nonexist')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

    def test_query_builds_by_type(self):
        resp = self.client.get('/api/1/builds/?type=0')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=1')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/api/1/builds/?type=2')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?type=module')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_type(self):
        with self.assertRaises(ValueError) as ctx:
            self.client.get('/api/1/builds/?type=100')
        self.assertEqual(str(ctx.exception), 'An invalid artifact type was supplied')

    def test_query_builds_by_state(self):
        resp = self.client.get('/api/1/builds/?state=0')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_state(self):
        with self.assertRaises(ValueError) as ctx:
            self.client.get('/api/1/builds/?state=100')
        self.assertEqual(str(ctx.exception), 'An invalid state was supplied')

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
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.GitModuleMetadataChangeEvent])
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 2)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.MBSModuleStateChangeEvent])
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 1)

        resp = self.client.get('/api/1/builds/?event_type_id=%s' % models.EVENT_TYPES[events.KojiTaskStateChangeEvent])
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_search_key(self):
        resp = self.client.get('/api/1/builds/?event_search_key=RHSA-2018-101')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_search_key=RHSA-2018-102')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

    def test_query_build_by_event_type_id_and_search_key(self):
        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=RHSA-2018-101' % models.EVENT_TYPES[events.TestingEvent])
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/api/1/builds/?event_type_id=%s&event_search_key=RHSA-2018-102' % models.EVENT_TYPES[events.TestingEvent])
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

    def test_query_event(self):
        resp = self.client.get('/api/1/events/1')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['message_id'], '2017-00000000-0000-0000-0000-000000000001')
        self.assertEqual(data['search_key'], 'RHSA-2018-101')
        self.assertEqual(data['event_type_id'], models.EVENT_TYPES[events.TestingEvent])
        self.assertEqual(len(data['builds']), 3)

    def test_query_events(self):
        resp = self.client.get('/api/1/events/')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 2)

    def test_query_event_by_message_id(self):
        resp = self.client.get('/api/1/events/?message_id=2017-00000000-0000-0000-0000-000000000001')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['message_id'], '2017-00000000-0000-0000-0000-000000000001')

    def test_query_event_by_search_key(self):
        resp = self.client.get('/api/1/events/?search_key=RHSA-2018-101')
        evs = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]['search_key'], 'RHSA-2018-101')

    def test_query_event_types(self):
        resp = self.client.get('/api/1/event-types/')
        event_types = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(event_types), len(models.EVENT_TYPES))

    def test_query_event_type(self):
        for cls, val in six.iteritems(models.EVENT_TYPES):
            resp = self.client.get('/api/1/event-types/%s' % val)
            event = json.loads(resp.data.decode('utf8'))
            self.assertEqual(event['id'], val)
            self.assertEqual(event['name'], cls.__name__)

    def test_query_nonexist_event_type(self):
        resp = self.client.get('/api/1/event-types/99999')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such event type found.')

    def test_query_build_types(self):
        resp = self.client.get('/api/1/build-types/')
        build_types = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(build_types), len(list(ArtifactType)))

    def test_query_build_type(self):
        for t in list(ArtifactType):
            resp = self.client.get('/api/1/build-types/%s' % t.value)
            build_type = json.loads(resp.data.decode('utf8'))
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_type(self):
        resp = self.client.get('/api/1/build-types/99999')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build type found.')

    def test_query_build_states(self):
        resp = self.client.get('/api/1/build-states/')
        build_types = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(build_types), len(list(ArtifactBuildState)))

    def test_query_build_state(self):
        for t in list(ArtifactBuildState):
            resp = self.client.get('/api/1/build-states/%s' % t.value)
            build_type = json.loads(resp.data.decode('utf8'))
            self.assertEqual(build_type['id'], t.value)
            self.assertEqual(build_type['name'], t.name)

    def test_query_nonexist_build_state(self):
        resp = self.client.get('/api/1/build-states/99999')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['status'], 404)
        self.assertEqual(data['error'], 'Not Found')
        self.assertEqual(data['message'], 'No such build state found.')


class TestManualTriggerRebuild(unittest.TestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.client = app.test_client()

    def tearDown(self):

        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.messaging.publish')
    def test_manual_rebuild(self, publish):
        resp = self.client.post('/api/1/builds/',
                                data=json.dumps({'errata_id': 1}),
                                content_type='application/json')
        data = json.loads(resp.data.decode('utf-8'))

        self.assertEqual(data["errata_id"], 1)
        publish.assert_called_once_with('manual.rebuild', {u'errata_id': 1})


if __name__ == '__main__':
    unittest.main()
