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
        models.ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        models.ArtifactBuild.create(db.session, event, "mksh", "module", 1235)
        models.ArtifactBuild.create(db.session, event, "bash", "module", 1236)
        db.session.commit()
        db.session.expire_all()

    def test_query_build(self):
        resp = self.client.get('/freshmaker/1/builds/1')
        data = json.loads(resp.data.decode('utf8'))
        self.assertEqual(data['id'], 1)
        self.assertEqual(data['name'], 'ed')
        self.assertEqual(data['type'], ArtifactType.MODULE.value)
        self.assertEqual(data['state'], ArtifactBuildState.BUILD.value)
        self.assertEqual(data['event_id'], 1)
        self.assertEqual(data['build_id'], 1234)

    def test_query_builds(self):
        resp = self.client.get('/freshmaker/1/builds/')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)
        for name in ['ed', 'mksh', 'bash']:
            self.assertIn(name, [b['name'] for b in builds])
        for build_id in [1234, 1235, 1236]:
            self.assertIn(build_id, [b['build_id'] for b in builds])

    def test_query_builds_by_name(self):
        resp = self.client.get('/freshmaker/1/builds/?name=ed')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'ed')

        resp = self.client.get('/freshmaker/1/builds/?name=mksh')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]['name'], 'mksh')

        resp = self.client.get('/freshmaker/1/builds/?name=nonexist')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

    def test_query_builds_by_type(self):
        resp = self.client.get('/freshmaker/1/builds/?type=0')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/freshmaker/1/builds/?type=1')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 0)

        resp = self.client.get('/freshmaker/1/builds/?type=2')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

        resp = self.client.get('/freshmaker/1/builds/?type=module')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_type(self):
        with self.assertRaises(ValueError) as ctx:
            self.client.get('/freshmaker/1/builds/?type=100')
        self.assertEqual(str(ctx.exception), 'An invalid artifact type was supplied')

    def test_query_builds_by_state(self):
        resp = self.client.get('/freshmaker/1/builds/?state=0')
        builds = json.loads(resp.data.decode('utf8'))['items']
        self.assertEqual(len(builds), 3)

    def test_query_builds_by_invalid_state(self):
        with self.assertRaises(ValueError) as ctx:
            self.client.get('/freshmaker/1/builds/?state=100')
        self.assertEqual(str(ctx.exception), 'An invalid state was supplied')


if __name__ == '__main__':
    unittest.main()
