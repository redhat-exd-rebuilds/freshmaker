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

from freshmaker import log, conf, utils
from freshmaker.types import ArtifactType
from freshmaker.pdc import PDC
from freshmaker.handlers import BaseHandler
from freshmaker.events import GitRPMSpecChangeEvent


class GitRPMSpecChangeHandler(BaseHandler):
    name = "GitRPMSpecChangeHandler"

    def can_handle(self, event):
        if isinstance(event, GitRPMSpecChangeEvent):
            return True

        return False

    def handle(self, event):
        """
        Rebuild module when spec file of rpm in module is updated.
        """
        rpm = event.rpm
        branch = event.branch
        rev = event.rev

        log.info("Triggering rebuild of modules on event of rpm (%s:%s) spec updated, rev: %s.",
                 rpm, branch, rev)

        pdc = PDC(conf)
        modules = pdc.get_latest_modules(component_name=rpm,
                                         component_branch=branch,
                                         active='true')

        for module in modules:
            name = module['name']
            version = module['stream']
            if not self.allow_build(ArtifactType.MODULE, name=name, branch=version):
                log.info("Skip rebuild of %s:%s as it's not allowed by configured whitelist",
                         name, version)
                continue
            log.info("Going to rebuild module '%s:%s'.", name, version)
            commit_msg = "Bump to rebuild because of %s rpm spec update (%s)." % (rpm, rev)
            rev = utils.bump_distgit_repo('modules', name, branch=version, commit_msg=commit_msg, logger=log)
            build_id = self.build_module(name, version, rev)
            if build_id is not None:
                self.record_build(event, name, ArtifactType.MODULE, build_id)

        return []
