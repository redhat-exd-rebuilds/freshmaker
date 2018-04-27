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

from freshmaker import db, events
from freshmaker.models import ArtifactBuild, ArtifactType
from freshmaker.models import Event, EventState, EVENT_TYPES, EventDependency
from freshmaker.models import Compose, ArtifactBuildCompose
from freshmaker.types import ArtifactBuildState
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from tests import helpers


class TestModels(helpers.ModelsTestCase):

    def test_creating_event_and_builds(self):
        event = Event.create(db.session, "test_msg_id", "RHSA-2017-284", events.TestingEvent)
        build = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build)
        db.session.commit()
        db.session.expire_all()

        e = db.session.query(Event).filter(event.id == 1).one()
        self.assertEqual(e.message_id, "test_msg_id")
        self.assertEqual(e.search_key, "RHSA-2017-284")
        self.assertEqual(e.event_type, events.TestingEvent)
        self.assertEqual(len(e.builds), 2)

        self.assertEqual(e.builds[0].name, "ed")
        self.assertEqual(e.builds[0].type, 2)
        self.assertEqual(e.builds[0].state, 0)
        self.assertEqual(e.builds[0].build_id, 1234)
        self.assertEqual(e.builds[0].dep_on, None)

        self.assertEqual(e.builds[1].name, "mksh")
        self.assertEqual(e.builds[1].type, 2)
        self.assertEqual(e.builds[1].state, 0)
        self.assertEqual(e.builds[1].build_id, 1235)
        self.assertEqual(e.builds[1].dep_on.name, "ed")

    def test_get_root_dep_on(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        build1 = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
        build2 = ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build1)
        build3 = ArtifactBuild.create(db.session, event, "runtime", "module", 1236, build2)
        build4 = ArtifactBuild.create(db.session, event, "perl-runtime", "module", 1237, build3)
        db.session.commit()
        db.session.expire_all()
        self.assertEqual(build1.get_root_dep_on(), None)
        self.assertEqual(build2.get_root_dep_on(), build1)
        self.assertEqual(build3.get_root_dep_on(), build1)
        self.assertEqual(build4.get_root_dep_on(), build1)

    def test_depending_artifact_builds(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        parent = ArtifactBuild.create(db.session, event, "parent", "module", 1234)
        build2 = ArtifactBuild.create(db.session, event, "mksh", "module", 1235, parent)
        build3 = ArtifactBuild.create(db.session, event, "runtime", "module", 1236, parent)
        ArtifactBuild.create(db.session, event, "perl-runtime", "module", 1237)
        db.session.commit()

        deps = set(parent.depending_artifact_builds())
        self.assertEqual(deps, set([build2, build3]))

    def test_build_transition_recursion(self):
        for i, state in enumerate([ArtifactBuildState.FAILED.value,
                                   ArtifactBuildState.CANCELED.value]):
            event = Event.create(db.session, "test_msg_id_{}".format(i), "test", events.TestingEvent)
            build1 = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
            build2 = ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build1)
            build3 = ArtifactBuild.create(db.session, event, "runtime", "module", 1236, build2)
            build4 = ArtifactBuild.create(db.session, event, "perl-runtime", "module", 1237)
            db.session.commit()

            build1.transition(state, "reason")
            self.assertEqual(build1.state, state)
            self.assertEqual(build1.state_reason, "reason")

            for build in [build2, build3]:
                self.assertEqual(build.state, state)
                self.assertEqual(
                    build.state_reason, "Cannot build artifact, because its "
                    "dependency cannot be built.")

            self.assertEqual(build4.state, ArtifactBuildState.BUILD.value)
            self.assertEqual(build4.state_reason, None)

    def test_build_transition_recursion_not_done_for_ok_states(self):
        for i, state in enumerate([ArtifactBuildState.DONE.value,
                                   ArtifactBuildState.PLANNED.value]):
            event = Event.create(db.session, "test_msg_id_{}".format(i), "test", events.TestingEvent)
            build1 = ArtifactBuild.create(db.session, event, "ed", "module", 1234)
            build2 = ArtifactBuild.create(db.session, event, "mksh", "module", 1235, build1)
            build3 = ArtifactBuild.create(db.session, event, "runtime", "module", 1236, build2)
            build4 = ArtifactBuild.create(db.session, event, "perl-runtime", "module", 1237)
            db.session.commit()

            build1.transition(state, "reason")
            self.assertEqual(build1.state, state)
            self.assertEqual(build1.state_reason, "reason")

            for build in [build2, build3, build4]:
                self.assertEqual(build4.state, ArtifactBuildState.BUILD.value)
                self.assertEqual(build4.state_reason, None)

    def test_get_unreleased(self):
        event1 = Event.create(db.session, "test_msg_id1", "test", events.TestingEvent)
        event1.state = EventState.COMPLETE
        event1.released = False

        event2 = Event.create(db.session, "test_msg_id2", "test", events.TestingEvent)
        event2.state = EventState.COMPLETE
        event2.released = True

        event3 = Event.create(db.session, "test_msg_id3", "test", events.TestingEvent)
        event3.state = EventState.SKIPPED
        event3.released = False

        event4 = Event.create(db.session, "test_msg_id4", "test", events.TestingEvent)
        event4.state = EventState.SKIPPED
        event4.released = True
        db.session.commit()

        # No state means only COMPLETE should be returned
        ret = Event.get_unreleased(db.session)
        self.assertEqual(ret, [event1])

        # No state means only COMPLETE should be returned
        ret = Event.get_unreleased(db.session, states=[EventState.SKIPPED])
        self.assertEqual(ret, [event3])

    def test_str(self):
        event = Event.create(db.session, "test_msg_id1", "test",
                             events.TestingEvent)
        self.assertEqual(str(event), "<TestingEvent, search_key=test>")

    def test_str_unknown_event_type(self):
        event = Event.create(db.session, "test_msg_id1", "test", 1024)
        self.assertEqual(
            str(event), "<UnknownEventType 1024, search_key=test>")


class TestFindDependentEvents(helpers.ModelsTestCase):
    """Test Event.find_dependent_events"""

    def setUp(self):
        super(TestFindDependentEvents, self). setUp()

        self.event_1 = Event.create(
            db.session, 'msg-1', 'search-key-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.INITIALIZED,
            released=False)
        ArtifactBuild.create(
            db.session, self.event_1, 'build-1', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_1, 'build-2', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_1, 'build-3', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_1, 'build-4', ArtifactType.IMAGE)

        self.event_2 = Event.create(
            db.session, 'msg-2', 'search-key-2',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.BUILDING,
            released=False)
        ArtifactBuild.create(
            db.session, self.event_2, 'build-2', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_2, 'build-5', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_2, 'build-6', ArtifactType.IMAGE)

        self.event_3 = Event.create(
            db.session, 'msg-3', 'search-key-3',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.COMPLETE,
            released=False)
        ArtifactBuild.create(
            db.session, self.event_3, 'build-2', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_3, 'build-4', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_3, 'build-7', ArtifactType.IMAGE)
        ArtifactBuild.create(
            db.session, self.event_3, 'build-8', ArtifactType.IMAGE)

        # Some noises

        # Failed events should not be included
        self.event_4 = Event.create(
            db.session, 'msg-4', 'search-key-4',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.FAILED,
            released=False)
        ArtifactBuild.create(
            db.session, self.event_4, 'build-3', ArtifactType.IMAGE)

        # Manual triggered rebuild should not be included as well
        self.event_5 = Event.create(
            db.session, 'msg-5', 'search-key-5',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.BUILDING,
            released=False, manual=True)
        ArtifactBuild.create(
            db.session, self.event_5, 'build-4', ArtifactType.IMAGE)

        # Released event should not be included also
        self.event_6 = Event.create(
            db.session, 'msg-6', 'search-key-6',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.COMPLETE,
            released=True)
        ArtifactBuild.create(
            db.session, self.event_5, 'build-4', ArtifactType.IMAGE)

        db.session.commit()

    def test_find_dependent_events(self):
        dep_events = self.event_1.find_dependent_events()
        self.assertEqual([self.event_2.id, self.event_3.id],
                         sorted([event.id for event in dep_events]))

        dep_rels = db.session.query(EventDependency).all()
        dep_rels = [(rel.event_id, rel.event_dependency_id) for rel in dep_rels]

        self.assertEqual(2, len(dep_rels))
        self.assertIn((self.event_1.id, self.event_2.id), dep_rels)
        self.assertIn((self.event_1.id, self.event_3.id), dep_rels)


class TestArtifactBuildComposesRel(helpers.ModelsTestCase):
    """Test m2m relationship between ArtifactBuild and Compose"""

    def setUp(self):
        super(TestArtifactBuildComposesRel, self). setUp()

        self.compose_1 = Compose(odcs_compose_id=-1)
        self.compose_2 = Compose(odcs_compose_id=2)
        self.compose_3 = Compose(odcs_compose_id=3)
        self.compose_4 = Compose(odcs_compose_id=4)
        db.session.add(self.compose_1)
        db.session.add(self.compose_2)
        db.session.add(self.compose_3)
        db.session.add(self.compose_4)

        self.event = Event.create(
            db.session, 'msg-1', 'search-key-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.INITIALIZED,
            released=False)
        self.build_1 = ArtifactBuild.create(
            db.session, self.event, 'build-1', ArtifactType.IMAGE)
        self.build_1.build_id = 3
        self.build_2 = ArtifactBuild.create(
            db.session, self.event, 'build-2', ArtifactType.IMAGE)
        self.build_2.build_id = -2
        self.build_3 = ArtifactBuild.create(
            db.session, self.event, 'build-3', ArtifactType.IMAGE)
        self.build_3.build_id = None

        db.session.commit()

        rels = (
            (self.build_1.id, self.compose_1.id),
            (self.build_1.id, self.compose_2.id),
            (self.build_1.id, self.compose_3.id),
            (self.build_2.id, self.compose_2.id),
            (self.build_2.id, self.compose_4.id),
        )

        for build_id, compose_id in rels:
            db.session.add(
                ArtifactBuildCompose(
                    build_id=build_id, compose_id=compose_id))

        db.session.commit()

    def test_get_lowest_compose_id(self):
        compose_id = Compose.get_lowest_compose_id(db.session)
        self.assertEqual(compose_id, -1)

    def test_get_lowest_build_id(self):
        build_id = ArtifactBuild.get_lowest_build_id(db.session)
        self.assertEqual(build_id, -2)

    def test_build_composes(self):
        self.assertEqual(3, len(self.build_1.composes))
        self.assertEqual(
            [self.compose_1.id, self.compose_2.id, self.compose_3.id],
            sorted([rel.compose.id for rel in self.build_1.composes]))

        self.assertEqual(2, len(self.build_2.composes))
        self.assertEqual(
            [self.compose_2.id, self.compose_4.id],
            sorted([rel.compose.id for rel in self.build_2.composes]))

        self.assertEqual([], self.build_3.composes)

    def test_compose_builds(self):
        expected_rels = (
            (self.compose_1, 1, [self.build_1.id]),
            (self.compose_2, 2, [self.build_1.id, self.build_2.id]),
            (self.compose_3, 1, [self.build_1.id]),
            (self.compose_4, 1, [self.build_2.id]),
        )

        for compose, builds_count, builds in expected_rels:
            self.assertEqual(builds_count, len(compose.builds))
            self.assertEqual(
                builds,
                sorted([rel.build.id for rel in compose.builds]))


class TestEventDependency(helpers.ModelsTestCase):
    """Test Event.add_event_dependency"""

    def test_event_dependencies(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        db.session.commit()
        self.assertEqual(event.event_dependencies, [])

    def test_add_a_dependent_event(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        event1 = Event.create(db.session, "test_msg_id2", "test2", events.TestingEvent)
        db.session.commit()

        event.add_event_dependency(db.session, event1)
        db.session.commit()

        self.assertEqual(event.event_dependencies, [event1])
        self.assertEqual(event.event_dependencies[0].search_key, "test2")
        self.assertEqual(event1.event_dependencies, [])

    def test_add_existing_dependent_event(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        event1 = Event.create(db.session, "test_msg_id2", "test2", events.TestingEvent)
        db.session.commit()
        event.add_event_dependency(db.session, event1)
        db.session.commit()

        rel = event.add_event_dependency(db.session, event1)

        self.assertIsNone(rel)
        self.assertEqual(event.event_dependencies, [event1])

    def test_return_added_dependency_relationship(self):
        event = Event.create(db.session, "test_msg_id", "test", events.TestingEvent)
        event1 = Event.create(db.session, "test_msg_id2", "test2", events.TestingEvent)
        db.session.commit()

        dep_rel = event.add_event_dependency(db.session, event1)
        db.session.commit()

        self.assertEqual(event.id, dep_rel.event_id)
        self.assertEqual(event1.id, dep_rel.event_dependency_id)
