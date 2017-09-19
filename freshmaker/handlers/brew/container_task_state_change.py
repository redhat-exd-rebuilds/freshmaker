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

from freshmaker import log
from freshmaker import db
from freshmaker.events import BrewContainerTaskStateChangeEvent
from freshmaker.models import ArtifactBuild
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.types import ArtifactType, ArtifactBuildState


class BrewContainerTaskStateChangeHandler(ContainerBuildHandler):
    """Rebuild container when a dependecy container is built in Brew"""

    name = 'BrewContainerTaskStateChangeHandler'

    def can_handle(self, event):
        return isinstance(event, BrewContainerTaskStateChangeEvent)

    def handle(self, event):
        """
        When build container task state changed in brew, update build state in db and
        rebuild containers depend on the success build as necessary.
        """

        build_id = event.task_id

        # check db to see whether this build exists in db
        found_build = db.session.query(ArtifactBuild).filter_by(type=ArtifactType.IMAGE.value,
                                                                build_id=build_id).one_or_none()
        if found_build is not None:
            # update build state in db
            if event.new_state == 'CLOSED':
                found_build.state = ArtifactBuildState.DONE.value
            if event.new_state == 'FAILED':
                found_build.state = ArtifactBuildState.FAILED.value
            db.session.commit()

            if found_build.state == ArtifactBuildState.DONE.value:
                # check db to see whether there is any planned image build depends on this build
                planned_builds = db.session.query(ArtifactBuild).filter_by(type=ArtifactType.IMAGE.value,
                                                                           state=ArtifactBuildState.PLANNED.value,
                                                                           dep_on=found_build).all()
                repo_urls = self.get_repo_urls(found_build.event)
                for build in planned_builds:
                    log.info("Build %r depends on build %r" % (build, found_build))
                    self.build_image_artifact_build(build, repo_urls)
