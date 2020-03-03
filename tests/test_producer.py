# -*- coding: utf-8 -*-
#
# Copyright (c) 2018  Red Hat, Inc.
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

import koji

from unittest.mock import patch, MagicMock
import queue

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.models import ArtifactBuild, Event
from freshmaker.types import EventState, ArtifactBuildState
from freshmaker.producer import FreshmakerProducer
from tests import helpers


class TestCheckUnfinishedKojiTasks(helpers.ModelsTestCase):

    def setUp(self):
        super(TestCheckUnfinishedKojiTasks, self).setUp()

        self.koji_read_config_patcher = patch(
            'koji.read_config', return_value={'server': 'http://localhost/'})
        self.koji_read_config_patcher.start()

        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent)
        db_event.state = EventState.BUILDING
        self.build = ArtifactBuild.create(db.session, db_event, "parent1-1-4",
                                          "image")
        self.build.state = ArtifactBuildState.BUILD
        self.build.build_id = 10
        db.session.commit()

    def tearDown(self):
        self.koji_read_config_patcher.stop()

    @patch('freshmaker.kojiservice.KojiService.get_task_info')
    @patch("freshmaker.consumer.get_global_consumer")
    def test_koji_task_failed(self, global_consumer, get_task_info):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        get_task_info.return_value = {'state': koji.TASK_STATES['FAILED']}

        hub = MagicMock()
        producer = FreshmakerProducer(hub)
        producer.check_unfinished_koji_tasks(db.session)
        event = consumer.incoming.get()
        self.assertEqual(event.task_id, 10)
        self.assertEqual(event.new_state, "FAILED")

    @patch('freshmaker.kojiservice.KojiService.get_task_info')
    @patch("freshmaker.consumer.get_global_consumer")
    def test_koji_task_closed(self, global_consumer, get_task_info):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        get_task_info.return_value = {'state': koji.TASK_STATES['CLOSED']}

        hub = MagicMock()
        producer = FreshmakerProducer(hub)
        producer.check_unfinished_koji_tasks(db.session)
        event = consumer.incoming.get()
        self.assertEqual(event.task_id, 10)
        self.assertEqual(event.new_state, "CLOSED")

    @patch('freshmaker.kojiservice.KojiService.get_task_info')
    @patch("freshmaker.consumer.get_global_consumer")
    def test_koji_task_dry_run(self, global_consumer, get_task_info):
        self.build.build_id = -10
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        get_task_info.return_value = {'state': koji.TASK_STATES['CLOSED']}

        hub = MagicMock()
        producer = FreshmakerProducer(hub)
        producer.check_unfinished_koji_tasks(db.session)
        self.assertRaises(queue.Empty, consumer.incoming.get, block=False)

    @patch('freshmaker.kojiservice.KojiService.get_task_info')
    @patch("freshmaker.consumer.get_global_consumer")
    def test_koji_task_open(self, global_consumer, get_task_info):
        self.build.build_id = -10
        consumer = self.create_consumer()
        global_consumer.return_value = consumer

        get_task_info.return_value = {'state': koji.TASK_STATES['OPEN']}

        hub = MagicMock()
        producer = FreshmakerProducer(hub)
        producer.check_unfinished_koji_tasks(db.session)
        self.assertRaises(queue.Empty, consumer.incoming.get, block=False)
