# -*- coding: utf-8 -*-
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

from freshmaker import log, conf, utils, db, models
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.mbs import MBS
from freshmaker.pdc import PDC
from freshmaker.handlers import BaseHandler, fail_event_on_handler_exception
from freshmaker.events import MBSModuleStateChangeEvent


class MBSModuleStateChangeHandler(BaseHandler):
    name = "MBSModuleStateChangeHandler"

    def can_handle(self, event):
        if isinstance(event, MBSModuleStateChangeEvent):
            return True

        return False

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        Update build state in db when module state changed in MBS and the
        build is submitted by Freshmaker (can find that build in db). If
        build state is 'ready', query PDC to get all modules that depends
        on this module, rebuild all these depending modules.
        """
        module_name = event.module
        module_stream = event.stream
        build_id = event.build_id
        build_state = event.build_state

        module_build = None
        # update build state if the build is submitted by Freshmaker
        builds = db.session.query(models.ArtifactBuild).filter_by(build_id=build_id,
                                                                  type=ArtifactType.MODULE.value).all()
        if len(builds) > 1:
            raise RuntimeError("Found duplicate module build '%s' in db" % build_id)
        if len(builds) == 1:
            # we can find this build in DB
            module_build = builds.pop()
            self.set_context(module_build)
            if build_state in [MBS.BUILD_STATES['ready'], MBS.BUILD_STATES['failed']]:
                log.info("Module build '%s' state changed in MBS, updating it in db.", build_id)
            if build_state == MBS.BUILD_STATES['ready']:
                module_build.state = ArtifactBuildState.DONE.value
            if build_state == MBS.BUILD_STATES['failed']:
                module_build.state = ArtifactBuildState.FAILED.value
            db.session.commit()

        # Rebuild depending modules when state of MBSModuleStateChangeEvent is 'ready'
        if build_state == MBS.BUILD_STATES['ready']:
            log.info("Triggering rebuild of modules depending on %s:%s "
                     "in MBS", module_name, module_stream)

            if module_build:
                # we have this build recorded in DB, check to prevent
                # cyclic build loop
                root_dep = module_build.get_root_dep_on()
                if root_dep and root_dep.name == module_name:
                    log.info("Skipping the rebuild triggered by %s:%s as it will"
                             "result in cyclic build loop.", module_name, module_stream)
                    return []

            pdc = PDC(conf)
            modules = pdc.get_latest_modules(build_dep_name=module_name,
                                             build_dep_stream=module_stream,
                                             active='true')

            for mod in modules:
                name = mod['variant_name']
                version = mod['variant_version']
                if not self.allow_build(ArtifactType.MODULE, name=name, branch=version):
                    log.info("Skip rebuild of %s:%s as it's not allowed by configured whitelist/blacklist",
                             name, version)
                    continue
                # bump module repo first
                commit_msg = "Bump to rebuild because of %s update" % module_name
                rev = utils.bump_distgit_repo('modules', name, branch=version, commit_msg=commit_msg, logger=log)
                new_build_id = self.build_module(name, version, rev)
                if new_build_id is not None:
                    self.record_build(event, name, ArtifactType.MODULE, new_build_id, dep_on=module_build)

        return []
