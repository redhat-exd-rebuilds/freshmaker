# Copyright (c) 2019  Red Hat, Inc.
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

from unittest.mock import patch, MagicMock

import freshmaker
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import (ErrataAdvisoryStateChangedEvent,
                               ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers.bob import RebuildImagesOnImageAdvisoryChange
from freshmaker import models, db
from tests import helpers


class RebuildImagesOnImageAdvisoryChangeTest(helpers.ModelsTestCase):

    def setUp(self):
        super(RebuildImagesOnImageAdvisoryChangeTest, self).setUp()

        self.event = ErrataAdvisoryStateChangedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "SHIPPED_LIVE", [],
                           security_impact="",
                           product_short_name="product"))
        self.handler = RebuildImagesOnImageAdvisoryChange()
        self.db_event = models.Event.get_or_create(
            db.session, self.event.msg_id, self.event.search_key,
            self.event.__class__)

    def test_can_handle(self):
        self.event.advisory.content_types = ["docker"]
        ret = self.handler.can_handle(self.event)
        self.assertTrue(ret)

    def test_can_handle_manual_event(self):
        event = ManualRebuildWithAdvisoryEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "SHIPPED_LIVE", ["docker"],
                           security_impact="",
                           product_short_name="product"),
            [])
        ret = self.handler.can_handle(event)
        self.assertTrue(ret)

    def test_can_handle_non_docker_advisory(self):
        self.event.advisory.content_types = ["rpm"]
        ret = self.handler.can_handle(self.event)
        self.assertFalse(ret)

    @patch.object(freshmaker.conf, 'handler_build_allowlist', new={
        'RebuildImagesOnImageAdvisoryChange': {
            "image": {"advisory_state": "SHIPPED_LIVE"}
        }
    })
    @patch("freshmaker.handlers.bob.RebuildImagesOnImageAdvisoryChange."
           "rebuild_images_depending_on_advisory")
    def test_handler_allowed(self, rebuild_images):
        self.event.advisory.state = "NEW_FILES"
        self.handler.handle(self.event)
        rebuild_images.assert_not_called()

        self.event.advisory.state = "SHIPPED_LIVE"
        self.handler.handle(self.event)
        rebuild_images.assert_called_once()

    @patch("freshmaker.errata.Errata.get_docker_repo_tags")
    @patch("freshmaker.handlers.bob."
           "rebuild_images_on_image_advisory_change.requests.get")
    @patch.object(freshmaker.conf, 'bob_auth_token', new="x")
    @patch.object(freshmaker.conf, 'bob_server_url', new="http://localhost/")
    def test_rebuild_images_depending_on_advisory(
            self, requests_get, get_docker_repo_tags):
        resp1 = MagicMock()
        resp1.json.return_value = {
            "message": "Foobar",
            "impacted": ["bob/repo1", "bob/repo2"]}
        resp2 = MagicMock()
        resp2.json.return_value = {
            "message": "Foobar",
            "impacted": ["bob/repo3", "bob/repo4"]}
        requests_get.side_effect = [resp1, resp2]

        self.handler.rebuild_images_depending_on_advisory(self.db_event, 123)

        db.session.refresh(self.db_event)

        self.assertEqual(self.db_event.state, models.EventState.COMPLETE.value)

        for build in self.db_event.builds:
            if build in ['bob/repo1', 'bob/repo2']:
                self.assertEqual(build.dep_on.name == "scl/foo-526")
            elif build in ['bob/repo3', 'bob/repo4']:
                self.assertEqual(build.dep_on.name == "scl/bar-526")

    @patch("freshmaker.errata.Errata.get_docker_repo_tags")
    @patch("freshmaker.handlers.bob."
           "rebuild_images_on_image_advisory_change.requests.get")
    @patch.object(freshmaker.conf, 'bob_auth_token', new="x")
    @patch.object(freshmaker.conf, 'bob_server_url', new="http://localhost/")
    def test_rebuild_images_depending_on_advisory_unknown_advisory(
            self, requests_get, get_docker_repo_tags):
        get_docker_repo_tags.return_value = None
        self.handler.rebuild_images_depending_on_advisory(self.db_event, 123)

        get_docker_repo_tags.assert_called_once_with(123)
        requests_get.assert_not_called()

    @patch("freshmaker.errata.Errata.get_docker_repo_tags")
    @patch("freshmaker.handlers.bob."
           "rebuild_images_on_image_advisory_change.requests.get")
    @patch.object(freshmaker.conf, 'bob_auth_token', new="x")
    @patch.object(freshmaker.conf, 'bob_server_url', new="http://localhost/")
    def test_rebuild_images_depending_on_advisory_dry_run(
            self, requests_get, get_docker_repo_tags):
        get_docker_repo_tags.return_value = {
            'foo-container-1-1': {'foo-526': ['5.26', 'latest']}}
        self.handler.force_dry_run()
        self.handler.rebuild_images_depending_on_advisory(self.db_event, 123)

        get_docker_repo_tags.assert_called_once_with(123)
        requests_get.assert_not_called()
