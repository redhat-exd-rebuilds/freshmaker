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

from freshmaker import log, conf, pdc, utils
from freshmaker.handlers import BaseHandler
from freshmaker.events import ModuleBuilt, ModuleMetadataUpdated


class MBS(BaseHandler):
    name = "MBS"

    def can_handle(self, event):
        # Handle only "ready" state of ModuleBuilt.
        # TODO: Handle only when something depends on
        # this module.
        if (isinstance(event, ModuleBuilt) and
                event.module_build_state == 5):
            return True

        if isinstance(event, ModuleMetadataUpdated):
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

    def handle_metadata_update(self, event):
        log.info("Triggering rebuild of %s, metadata updated", event.scm_url)
        self.rebuild_module(event.scm_url, event.branch)

        return []

    def handle_module_built(self, event):
        """
        When there is any module built and state is 'ready', query PDC to get
        all modules that depends on this module, rebuild all these depending
        modules.
        """
        module_name = event.module_name
        module_stream = event.module_stream

        log.info("Triggering rebuild of modules depending on %s:%s "
                 "in MBS", module_name, module_stream)

        pdc_session = pdc.get_client_session(conf)
        depending_modules = pdc.get_modules(pdc_session,
                                            build_dep_name=module_name,
                                            build_dep_stream=module_stream,
                                            active=True)

        # only rebuild the latest (by cmp variant_release) modules of
        # (variant_name, variant_version)
        latest_modules = []
        for (name, version) in set([(m.get('variant_name'), m.get('variant_version')) for m in depending_modules]):
            mods = pdc.get_modules(pdc_session, name=name, version=version, active=True)
            latest_modules.append(sorted(mods, key=lambda x: x['variant_release']).pop())

        rebuild_modules = list(filter(lambda x: x in latest_modules, depending_modules))
        for mod in rebuild_modules:
            module_name = mod['variant_name']
            module_stream = mod['variant_version']
            commitid = None
            with utils.temp_dir(prefix='freshmaker-%s-' % module_name) as repodir:
                try:
                    utils.clone_module_repo(module_name, repodir, branch=module_stream, user=conf.git_user, logger=log)
                    utils.add_empty_commit(repodir, msg="Bumped to rebuild because of %s update" % module_name, logger=log)
                    commitid = utils.get_commit_hash(repodir)
                    utils.push_repo(repodir)
                except Exception:
                    log.exception("Failed to update module repo for '%s-%s'.", module_name, module_stream)

            if commitid is not None:
                scm_url = conf.git_base_url + '/modules/%s.git?#%s' % (module_name, commitid)
                self.rebuild_module(scm_url, module_stream)

        return []

    def handle(self, event):
        if isinstance(event, ModuleMetadataUpdated):
            return self.handle_metadata_update(event)
        elif isinstance(event, ModuleBuilt):
            return self.handle_module_built(event)

        return []
