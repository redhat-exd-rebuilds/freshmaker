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


from freshmaker import log
from freshmaker.types import ArtifactType
from freshmaker.handlers import BaseHandler
from freshmaker.events import GitModuleMetadataChangeEvent


class GitModuleMetadataChangeHandler(BaseHandler):
    name = "GitModuleMetadataChangeHandler"

    def can_handle(self, event):
        if isinstance(event, GitModuleMetadataChangeEvent):
            return True

        return False

    def handle(self, event):
        log.info("Triggering rebuild of module %s:%s, metadata updated (%s).",
                 event.module, event.branch, event.rev)
        if not self.allow_build(ArtifactType.MODULE, name=event.module, branch=event.branch):
            log.info("Skip rebuild of %s:%s as it's not allowed by configured whitelist/blacklist",
                     event.module, event.branch)
            return []

        build_id = self.build_module(event.module, event.branch, event.rev)
        if build_id is not None:
            self.record_build(event, event.module, ArtifactType.MODULE, build_id)

        return []
