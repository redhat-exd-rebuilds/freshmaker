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

from freshmaker import log


class MBS(object):
    BUILD_STATES = {
        "init": 0,
        "wait": 1,
        "build": 2,
        "done": 3,
        "failed": 4,
        "ready": 5,
    }

    def __init__(self, config):
        """
        :param config: config which has mbs_base_url, mbs_auth_token and git_base_url.
                       can just be an instance of freshmaker.config.Config
        """
        self.base_url = config.mbs_base_url
        self.auth_token = config.mbs_auth_token
        self.git_base_url = config.git_base_url

    def build_module(self, name, branch, rev):
        """
        Build module defined by name, branch and rev in MBS.

        :param name: module name.
        :param branch: module branch.
        :param rev: git revision.
        :return: Build id or None in case of error.
        """
        scm_url = self.git_base_url + '/modules/%s.git?#%s' % (name, rev)

        headers = {}
        headers["Authorization"] = "Bearer %s" % self.auth_token

        body = {'scmurl': scm_url, 'branch': branch}
        url = "%s/module-build-service/1/module-builds/" % self.base_url

        resp = requests.request("POST", url, headers=headers, json=body)
        data = resp.json()
        if 'id' in data:
            log.info("Triggered build of %s, MBS build_id=%s", scm_url, data['id'])
            return data['id']
        else:
            log.error("Error when triggering build of %s: %s", scm_url, data)

        return None
