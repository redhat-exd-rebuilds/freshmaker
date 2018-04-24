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

import mock
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # noqa
from tests import get_fedmsg, helpers

from freshmaker import db, events, models
from freshmaker.parsers.brew import BrewTaskStateChangeParser
from freshmaker.handlers.brew import BrewContainerTaskStateChangeHandler
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState


class TestBrewContainerTaskStateChangeHandler(helpers.ModelsTestCase):
    def setUp(self):
        super(TestBrewContainerTaskStateChangeHandler, self).setUp()
        events.BaseEvent.register_parser(BrewTaskStateChangeParser)
        self.handler = BrewContainerTaskStateChangeHandler()

    def test_can_handle_brew_container_task_closed_event(self):
        """
        Tests handler can handle brew build container task closed event.
        """
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_closed'))
        self.assertTrue(self.handler.can_handle(event))

    def test_can_handle_brew_container_task_failed_event(self):
        """
        Tests handler can handle brew build container task failed event.
        """
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_failed'))
        self.assertTrue(self.handler.can_handle(event))

    @mock.patch('freshmaker.handlers.ContainerBuildHandler.build_image_artifact_build')
    @mock.patch('freshmaker.handlers.ContainerBuildHandler.get_repo_urls')
    @mock.patch('freshmaker.handlers.ContainerBuildHandler.set_context')
    def test_build_containers_when_dependency_container_is_built(self, set_context, repo_urls, build_image):
        """
        Tests when dependency container is built, rebuild containers depend on it.
        """
        build_image.side_effect = [1, 2, 3]
        repo_urls.return_value = ["url"]
        e1 = models.Event.create(db.session, "test_msg_id", "RHSA-2018-001", events.TestingEvent)
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_closed'))

        base_build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE, event.task_id)

        build_0 = models.ArtifactBuild.create(db.session, e1, 'docker-up-0', ArtifactType.IMAGE, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED)
        build_1 = models.ArtifactBuild.create(db.session, e1, 'docker-up-1', ArtifactType.IMAGE, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED)
        build_2 = models.ArtifactBuild.create(db.session, e1, 'docker-up-2', ArtifactType.IMAGE, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED)

        self.handler.handle(event)
        self.assertEqual(base_build.state, ArtifactBuildState.DONE.value)
        build_image.assert_has_calls([
            mock.call(build_0, ['url']), mock.call(build_1, ['url']),
            mock.call(build_2, ['url']),
        ])

        set_context.assert_has_calls([
            mock.call(build_0), mock.call(build_1), mock.call(build_2)])

        self.assertEqual(build_0.build_id, 1)
        self.assertEqual(build_1.build_id, 2)
        self.assertEqual(build_2.build_id, 3)

    @mock.patch('freshmaker.handlers.ContainerBuildHandler.build_image_artifact_build')
    @mock.patch('freshmaker.handlers.ContainerBuildHandler.get_repo_urls')
    def test_not_build_containers_when_dependency_container_build_task_failed(self, repo_urls, build_image):
        """
        Tests when dependency container build task failed in brew, only update build state in db.
        """
        repo_urls.return_value = ["url"]
        e1 = models.Event.create(db.session, "test_msg_id", "RHSA-2018-001", events.TestingEvent)
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_failed'))

        base_build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE, event.task_id)

        models.ArtifactBuild.create(db.session, e1, 'docker-up', ArtifactType.IMAGE, 0,
                                    dep_on=base_build, state=ArtifactBuildState.PLANNED)
        self.handler.handle(event)
        self.assertEqual(base_build.state, ArtifactBuildState.FAILED.value)
        build_image.assert_not_called()

    @mock.patch('freshmaker.models.messaging.publish')
    def test_mark_event_COMPLETE_if_all_builds_done(self, publish):
        self.db_advisory_rpm_signed_event = models.Event.create(
            db.session, 'msg-id-123', '12345',
            events.ErrataAdvisoryStateChangedEvent,
            state=EventState.BUILDING.value)

        self.image_a_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-a-0.1-1', ArtifactType.IMAGE,
            state=ArtifactBuildState.DONE.value)

        self.image_b_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-b-0.1-1', ArtifactType.IMAGE,
            dep_on=self.image_a_build,
            state=ArtifactBuildState.DONE.value)

        self.image_c_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-c-0.1-1', ArtifactType.IMAGE,
            dep_on=self.image_b_build,
            state=ArtifactBuildState.FAILED.value)

        self.image_d_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-d-0.1-1', ArtifactType.IMAGE,
            dep_on=self.image_a_build,
            build_id=12345,
            state=ArtifactBuildState.BUILD.value)

        db.session.commit()

        state_changed_event = events.BrewContainerTaskStateChangeEvent(
            'msg-id-890', 'image-d', 'branch', 'target', 12345,
            'BUILD', 'CLOSED')

        handler = BrewContainerTaskStateChangeHandler()
        handler.handle(state_changed_event)

        self.assertEqual(EventState.COMPLETE.value,
                         self.db_advisory_rpm_signed_event.state)
        self.assertEqual("1 of 4 container image(s) failed to rebuild.",
                         self.db_advisory_rpm_signed_event.state_reason)

    @mock.patch('freshmaker.handlers.ContainerBuildHandler.build_image_artifact_build')
    @mock.patch('freshmaker.handlers.ContainerBuildHandler.get_repo_urls')
    def test_not_change_state_if_not_all_builds_done(
            self, get_repo_urls, build_image_artifact_build):
        build_image_artifact_build.return_value = 67890

        self.db_advisory_rpm_signed_event = models.Event.create(
            db.session, 'msg-id-123', '12345',
            events.ErrataAdvisoryStateChangedEvent,
            state=EventState.BUILDING.value)

        self.image_a_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-a-0.1-1', ArtifactType.IMAGE,
            build_id=12345,
            state=ArtifactBuildState.BUILD.value)

        self.image_b_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-b-0.1-1', ArtifactType.IMAGE,
            dep_on=self.image_a_build,
            state=ArtifactBuildState.PLANNED.value)

        self.image_c_build = models.ArtifactBuild.create(
            db.session, self.db_advisory_rpm_signed_event,
            'image-c-0.1-1', ArtifactType.IMAGE,
            dep_on=self.image_b_build,
            state=ArtifactBuildState.FAILED.value)

        db.session.commit()

        state_changed_event = events.BrewContainerTaskStateChangeEvent(
            'msg-id-890', 'image-a', 'branch', 'target', 12345,
            'BUILD', 'CLOSED')

        handler = BrewContainerTaskStateChangeHandler()
        handler.handle(state_changed_event)

        # As self.image_b_build starts to be rebuilt, not all images are
        # rebuilt yet.
        self.assertEqual(EventState.BUILDING.value,
                         self.db_advisory_rpm_signed_event.state)

    @mock.patch('freshmaker.kojiservice.KojiService')
    @mock.patch('freshmaker.errata.Errata.get_builds')
    def test_mark_build_done_when_container_has_latest_rpms_from_advisory(self, errata_get_builds, KojiService):
        """
        Tests when dependency container build task failed in brew, only update build state in db.
        """
        errata_get_builds.return_value = set(['foo-1.2.1-22.el7'])

        koji_service = KojiService.return_value
        koji_service.get_build_rpms.return_value = [
            {'build_id': 634904, 'nvr': 'foo-debuginfo-1.2.1-22.el7', 'name': 'foo-debuginfo'},
            {'build_id': 634904, 'nvr': 'foo-1.2.1-22.el7', 'name': 'foo'},
            {'build_id': 634904, 'nvr': 'foo-debuginfo-1.1.1-22.el7', 'name': 'foo-debuginfo'},
            {'build_id': 634904, 'nvr': 'foo-1.1.1-22.el7', 'name': 'foo'},
        ]
        koji_service.get_rpms_in_container.return_value = set(
            ['foo-1.2.1-22.el7', 'bar-1.2.3-1.el7']
        )

        e1 = models.Event.create(db.session, "test_msg_id", "2018001", events.ErrataAdvisoryRPMsSignedEvent)
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_closed'))
        build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE, event.task_id)

        self.handler.handle(event)

        self.assertEqual(build.state, ArtifactBuildState.DONE.value)
        self.assertEqual(build.state_reason, 'Built successfully.')

    @mock.patch('freshmaker.kojiservice.KojiService')
    @mock.patch('freshmaker.errata.Errata.get_builds')
    def test_mark_build_fail_when_container_not_has_latest_rpms_from_advisory(self, errata_get_builds, KojiService):
        """
        Tests when dependency container build task failed in brew, only update build state in db.
        """
        errata_get_builds.return_value = set(['foo-1.2.1-23.el7'])

        koji_service = KojiService.return_value
        koji_service.get_build_rpms.return_value = [
            {'build_id': 634904, 'nvr': 'foo-debuginfo-1.2.1-23.el7', 'name': 'foo-debuginfo'},
            {'build_id': 634904, 'nvr': 'foo-1.2.1-23.el7', 'name': 'foo'},
            {'build_id': 634904, 'nvr': 'foo-debuginfo-1.1.1-22.el7', 'name': 'foo-debuginfo'},
            {'build_id': 634904, 'nvr': 'foo-1.1.1-22.el7', 'name': 'foo'},
        ]
        koji_service.get_rpms_in_container.return_value = set(
            ['foo-1.2.1-22.el7', 'bar-1.2.3-1.el7']
        )

        e1 = models.Event.create(db.session, "test_msg_id", "2018001", events.ErrataAdvisoryRPMsSignedEvent)
        event = self.get_event_from_msg(get_fedmsg('brew_container_task_closed'))
        build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE, event.task_id)

        self.handler.handle(event)
        self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
        self.assertRegexpMatches(build.state_reason, r"The following RPMs in container build.*")


if __name__ == '__main__':
    unittest.main()
