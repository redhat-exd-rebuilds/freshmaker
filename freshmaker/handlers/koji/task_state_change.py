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

from freshmaker import log, db, models
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.handlers import BaseHandler, fail_event_on_handler_exception
from freshmaker.events import KojiTaskStateChangeEvent


class KojiTaskStateChangeHandler(BaseHandler):
    name = "KojiTaskStateChangeHandler"

    def can_handle(self, event):
        if isinstance(event, KojiTaskStateChangeEvent):
            return True

        return False

    @fail_event_on_handler_exception
    def handle(self, event):
        task_id = event.task_id
        task_state = event.task_state

        # check whether the task exists in db as image build
        builds = db.session.query(models.ArtifactBuild).filter_by(build_id=task_id,
                                                                  type=ArtifactType.IMAGE.value).all()
        if len(builds) > 1:
            raise RuntimeError("Found duplicate image build '%s' in db" % task_id)
        if len(builds) == 1:
            build = builds.pop()
            self.set_context(build)
            if task_state in ['CLOSED', 'FAILED']:
                log.info("Image build '%s' state changed in koji, updating it in db.", task_id)
            if task_state == 'CLOSED':
                build.state = ArtifactBuildState.DONE.value
                db.session.commit()
            if task_state == 'FAILED':
                build.state = ArtifactBuildState.FAILED.value
                db.session.commit()

        return []
