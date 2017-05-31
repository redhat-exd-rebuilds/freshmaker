# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

import unittest

from freshmaker import db
from freshmaker.models import Event, ArtifactBuild
from freshmaker.events import TestingEvent


class TestModels(unittest.TestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_creating_event_and_builds(self):
        event = Event.create(db.session, "test_msg_id", "RHSA-2017-284", TestingEvent)
        build = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build)
        db.session.commit()
        db.session.expire_all()

        e = db.session.query(Event).filter(event.id == 1).one()
        self.assertEqual(e.message_id, "test_msg_id")
        self.assertEqual(e.search_key, "RHSA-2017-284")
        self.assertEqual(e.event_type, TestingEvent)
        self.assertEqual(len(e.builds), 2)

        self.assertEqual(e.builds[0].name, "ed")
        self.assertEqual(e.builds[0].type, 2)
        self.assertEqual(e.builds[0].state, 0)
        self.assertEqual(e.builds[0].build_id, 1234)
        self.assertEqual(e.builds[0].dep_of, None)

        self.assertEqual(e.builds[1].name, "mksh")
        self.assertEqual(e.builds[1].type, 2)
        self.assertEqual(e.builds[1].state, 0)
        self.assertEqual(e.builds[1].build_id, 1235)
        self.assertEqual(e.builds[1].dep_of.name, "ed")

    def test_get_root_dep_of(self):
        event = Event.create(db.session, "test_msg_id", "test", TestingEvent)
        build1 = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build2 = ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build1)
        build3 = ArtifactBuild.create(db.session, event, "runtime", "module", 1236, build2)
        build4 = ArtifactBuild.create(db.session, event, "perl-runtime", "module", 1237, build3)
        db.session.commit()
        db.session.expire_all()
        self.assertEqual(build1.get_root_dep_of(), None)
        self.assertEqual(build2.get_root_dep_of(), build1)
        self.assertEqual(build3.get_root_dep_of(), build1)
        self.assertEqual(build4.get_root_dep_of(), build1)
