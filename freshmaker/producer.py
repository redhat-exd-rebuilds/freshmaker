# -*- coding: utf-8 -*-
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
from moksha.hub.api.producer import PollingProducer
from datetime import timedelta, datetime

from freshmaker import conf, models, log, db
from freshmaker.types import EventState, ArtifactBuildState
from freshmaker.kojiservice import koji_service
from freshmaker.events import BrewContainerTaskStateChangeEvent
from freshmaker.consumer import work_queue_put

try:
    # SQLAlchemy 1.4
    from sqlalchemy.exc import StatementError, PendingRollbackError

    _sa_disconnect_exceptions = (StatementError, PendingRollbackError)
except ImportError:
    from sqlalchemy.exc import StatementError

    _sa_disconnect_exceptions = (StatementError,)  # type: ignore


class FreshmakerProducer(PollingProducer):
    frequency = timedelta(seconds=conf.polling_interval)

    def poll(self):
        try:
            self.check_unfinished_koji_tasks(db.session)
        except _sa_disconnect_exceptions as ex:
            db.session.rollback()
            log.error("Invalid request, session is rolled back: %s", ex.orig)
        except Exception:
            msg = "Error in poller execution:"
            log.exception(msg)

        log.info('Poller will now sleep for "{}" seconds'.format(conf.polling_interval))

    def check_unfinished_koji_tasks(self, session):
        stale_date = datetime.utcnow() - timedelta(days=7)
        db_events = (
            session.query(models.Event)
            .filter(
                models.Event.state == EventState.BUILDING.value,
                models.Event.time_created >= stale_date,
            )
            .all()
        )

        for db_event in db_events:
            for build in db_event.builds:
                if build.state != ArtifactBuildState.BUILD.value:
                    continue
                if build.build_id <= 0:
                    continue
                with koji_service(conf.koji_profile, log, login=False) as koji_session:
                    task = koji_session.get_task_info(build.build_id)
                    task_states = {v: k for k, v in koji.TASK_STATES.items()}
                    new_state = task_states[task["state"]]
                    if new_state not in ["FAILED", "CLOSED"]:
                        continue
                    event = BrewContainerTaskStateChangeEvent(
                        "fake event", build.name, None, None, build.build_id, "BUILD", new_state
                    )
                    work_queue_put(event)
