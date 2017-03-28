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

import requests

from freshmaker import log, conf
from freshmaker.handlers import BaseHandler
from freshmaker.triggers import ModuleBuilt, TestingTrigger, ModuleMetadataUpdated


class MBS(BaseHandler):
    name = "MBS"

    def can_handle(self, trigger):
        # Handle only "ready" state of ModuleBuilt.
        # TODO: Handle only when something depends on
        # this module.
        if (isinstance(trigger, ModuleBuilt) and
                trigger.module_build_state == 5):
            return True

        if isinstance(trigger, ModuleMetadataUpdated):
            return True

        return False

    def rebuild_module(self, scm_url, branch):
        """
        Rebuilds the module defined by scm_url and branch in MBS.
        Returns build id or None in case of error.
        """
        headers = {}
        headers["Authorization"] = "Bearer %s" % conf.mbs_auth_token

        body = {'scmurl': scm_url, 'branch': branch}
        url = "%s/module-build-service/1/module-builds/" % conf.mbs_base_url

        resp = requests.request("POST", url, headers=headers, json=body)
        data = resp.json()
        if 'id' in data:
            log.info("Triggered reubild of %s, MBS build_id=%s", scm_url, data['id'])
            return data['id']
        else:
            log.error("Error when triggering rebuild of %s: %s", scm_url, data)
            return None

    def handle_metadata_update(self, trigger):
        log.info("Triggering rebuild of %s, metadata updated", trigger.scm_url)
        self.rebuild_module(trigger.scm_url, trigger.branch)

        return []

    def handle_module_built(self, trigger):
        log.info("Triggering rebuild of modules depending on %r "
                 "in MBS" % trigger)

        # TODO: Just for initial testing of consumer
        return [TestingTrigger("ModuleBuilt handled")]

    def handle(self, trigger):
        if isinstance(trigger, ModuleMetadataUpdated):
            return self.handle_metadata_update(trigger)
        elif isinstance(trigger, ModuleBuilt):
            return self.handle_module_built(trigger)

        return []
