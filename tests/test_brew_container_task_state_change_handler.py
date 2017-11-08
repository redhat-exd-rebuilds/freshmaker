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
from freshmaker.types import ArtifactType, ArtifactBuildState


class TestBrewContainerTaskStateChangeHandler(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(BrewTaskStateChangeParser)
        self.handler = BrewContainerTaskStateChangeHandler()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

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

        base_build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE.value, event.task_id)

        build_0 = models.ArtifactBuild.create(db.session, e1, 'docker-up-0', ArtifactType.IMAGE.value, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED.value)
        build_1 = models.ArtifactBuild.create(db.session, e1, 'docker-up-1', ArtifactType.IMAGE.value, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED.value)
        build_2 = models.ArtifactBuild.create(db.session, e1, 'docker-up-2', ArtifactType.IMAGE.value, 0,
                                              dep_on=base_build, state=ArtifactBuildState.PLANNED.value)

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

        base_build = models.ArtifactBuild.create(db.session, e1, 'test-product-docker', ArtifactType.IMAGE.value, event.task_id)

        models.ArtifactBuild.create(db.session, e1, 'docker-up', ArtifactType.IMAGE.value, 0,
                                    dep_on=base_build, state=ArtifactBuildState.PLANNED.value)
        self.handler.handle(event)
        self.assertEqual(base_build.state, ArtifactBuildState.FAILED.value)
        build_image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
