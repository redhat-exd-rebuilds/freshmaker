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
        event = Event.create(db.session, "test_msg_id")
        build = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build)
        db.session.commit()
        db.session.expire_all()

        e = db.session.query(Event).filter(event.id == 1).one()
        self.assertEquals(e.message_id, "test_msg_id")
        self.assertEquals(len(e.builds), 2)

        self.assertEquals(e.builds[0].name, "ed")
        self.assertEquals(e.builds[0].type, 2)
        self.assertEquals(e.builds[0].state, 0)
        self.assertEquals(e.builds[0].build_id, 1234)
        self.assertEquals(e.builds[0].dep_of, None)

        self.assertEquals(e.builds[1].name, "mksh")
        self.assertEquals(e.builds[1].type, 2)
        self.assertEquals(e.builds[1].state, 0)
        self.assertEquals(e.builds[1].build_id, 1235)
        self.assertEquals(e.builds[1].dep_of.name, "ed")
