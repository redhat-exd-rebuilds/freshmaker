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

from freshmaker import log, conf, utils, pdc, db, models
from freshmaker.handlers import BaseHandler
from freshmaker.events import ModuleBuilt, ModuleMetadataUpdated, RPMSpecUpdated


MBS_BUILD_STATES = {
    "init": 0,
    "wait": 1,
    "build": 2,
    "done": 3,
    "failed": 4,
    "ready": 5,
}


class MBS(BaseHandler):
    name = "MBS"

    def can_handle(self, event):
        # TODO: Handle only when something depends on
        # this module.
        if isinstance(event, ModuleBuilt):
            return True

        if isinstance(event, ModuleMetadataUpdated):
            return True

        if isinstance(event, RPMSpecUpdated):
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
            log.info("Triggered rebuild of %s, MBS build_id=%s", scm_url, data['id'])
            return data['id']
        else:
            log.error("Error when triggering rebuild of %s: %s", scm_url, data)
            return None

    def bump_and_rebuild_module(self, name, branch, commit_msg=None):
        """Bump module repo with an empty commit and submit a module build request to MBS"""
        commitid = None
        with utils.temp_dir(prefix='freshmaker-%s-' % name) as repodir:
            try:
                utils.clone_module_repo(name, repodir, branch=branch, user=conf.git_user, logger=log)
                msg = commit_msg or "Bump"
                utils.add_empty_commit(repodir, msg=msg, logger=log)
                commitid = utils.get_commit_hash(repodir)
                utils.push_repo(repodir, logger=log)
            except Exception:
                log.exception("Failed to update module repo of '%s-%s'.", name, branch)

        if commitid is not None:
            scm_url = conf.git_base_url + '/modules/%s.git?#%s' % (name, commitid)
            return self.rebuild_module(scm_url, branch)

    def handle_metadata_update(self, event):
        log.info("Triggering rebuild of %s, metadata updated", event.scm_url)
        build_id = self.rebuild_module(event.scm_url, event.branch)
        if build_id is not None:
            self.record_build(event, event.name, 'module', build_id)

        return []

    def handle_module_built(self, event):
        """
        When there is any module built and state is 'ready', query PDC to get
        all modules that depends on this module, rebuild all these depending
        modules.
        """
        module_name = event.module_name
        module_stream = event.module_stream
        build_id = event.module_build_id
        build_state = event.module_build_state

        # update build state if the build is submitted by Freshmaker
        builds = db.session.query(models.ArtifactBuild).filter_by(build_id=build_id,
                                                                  type=models.ARTIFACT_TYPES['module']).all()
        if len(builds) > 1:
            raise RuntimeError("Found duplicate module build '%s' in db" % build_id)
        if len(builds) == 1:
            build = builds[0]
            if build_state in [MBS_BUILD_STATES['ready'], MBS_BUILD_STATES['failed']]:
                log.info("Module build '%s' state changed in MBS, updating it in db.", build_id)
            if build_state == MBS_BUILD_STATES['ready']:
                build.state = models.BUILD_STATES['done']
            if build_state == MBS_BUILD_STATES['failed']:
                build.state = models.BUILD_STATES['failed']
            db.session.commit()

        # Rebuild depending modules when state of ModuleBuilt is 'ready'
        if build_state == MBS_BUILD_STATES['ready']:
            log.info("Triggering rebuild of modules depending on %s:%s "
                     "in MBS", module_name, module_stream)

            pdc_session = pdc.get_client_session(conf)
            modules = pdc.get_latest_modules(pdc_session,
                                             build_dep_name=module_name,
                                             build_dep_stream=module_stream,
                                             active='true')
            for mod in modules:
                name = mod['variant_name']
                version = mod['variant_version']
                commit_msg = "Bump to rebuild because of %s update" % module_name
                build_id = self.bump_and_rebuild_module(name, version, commit_msg=commit_msg)
                if build_id is not None:
                    self.record_build(event, name, 'module', build_id)

    def handle_rpm_spec_updated(self, event):
        """
        Rebuild module when spec file of rpm in module is updated.
        """
        rpm = event.rpm
        branch = event.branch
        rev = event.rev

        log.info("Triggering rebuild of modules on event of rpm (%s:%s) spec updated, rev: %s.",
                 rpm, branch, rev)

        pdc_session = pdc.get_client_session(conf)
        modules = pdc.get_latest_modules(pdc_session,
                                         component_name=rpm,
                                         component_branch=branch,
                                         active='true')
        for mod in modules:
            module_name = mod['variant_name']
            module_branch = mod['variant_version']
            log.info("Going to rebuild module '%s:%s'.", module_name, module_branch)
            commit_msg = "Bump to rebuild because of %s rpm spec update (%s)." % (rpm, rev)
            build_id = self.bump_and_rebuild_module(module_name, module_branch, commit_msg=commit_msg)
            if build_id is not None:
                self.record_build(event, module_name, 'module', build_id)

        return []

    def handle(self, event):
        if isinstance(event, ModuleMetadataUpdated):
            return self.handle_metadata_update(event)
        elif isinstance(event, ModuleBuilt):
            return self.handle_module_built(event)
        elif isinstance(event, RPMSpecUpdated):
            return self.handle_rpm_spec_updated(event)

        return []
