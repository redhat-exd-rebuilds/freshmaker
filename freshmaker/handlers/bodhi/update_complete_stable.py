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
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Chenxiong Qi <cqi@redhat.com>

from itertools import chain

from freshmaker import conf
from freshmaker import log
from freshmaker import utils
from freshmaker.types import ArtifactType
from freshmaker.handlers import BaseHandler
from freshmaker.events import BodhiUpdateCompleteStableEvent
from freshmaker.pdc import PDC
from freshmaker.kojiservice import koji_service


class BodhiUpdateCompleteStableHandler(BaseHandler):
    """Rebuild docker images when RPMs are synced by Bodhi"""
    name = 'BodhiUpdateCompleteStableHandler'

    def can_handle(self, event):
        return isinstance(event, BodhiUpdateCompleteStableEvent)

    def handle(self, event):
        log.info('Rebuild docker images for event %s, msgid: %s',
                 BodhiUpdateCompleteStableEvent.__name__, event.msg_id)

        rpms = self.get_rpms_included_in_bodhi_update(event.builds)
        containers = self.get_containers_including_rpms(rpms)

        log.info('Found docker images to rebuild: %s', containers)

        for container in containers:
            if not self.allow_build(ArtifactType.IMAGE, name=container['name'], branch=container['branch']):
                log.info("Skip rebuild of image %s:%s as it's not allowed by configured whitelist/blacklist",
                         container['name'], container['branch'])
                continue
            try:
                name = container['name']
                branch = container['branch']
                repo_url = '{}/{}/{}'.format(conf.git_base_url, 'container', name)
                rev = utils.get_commit_hash(repo_url, branch=branch, logger=log)

                scm_url = "{}/{}/{}.git?#{}".format(
                    conf.git_base_url, 'container', name, rev)

                build_target = '{}-container-candidate'.format(
                    'rawhide' if branch == 'master' else branch)

                task_id = self.build_container(scm_url, branch, build_target)
                if task_id is not None:
                    self.record_build(event, container['name'], ArtifactType.IMAGE, task_id)
            except:
                log.exception('Error when rebuild %s', container)

        return []

    def get_rpms_included_in_bodhi_update(self, builds):
        build_nvrs = (build['nvr'] for build in builds)
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            return chain(*[service.get_build_rpms(nvr) for nvr in build_nvrs])

    def get_containers_including_rpms(self, rpms):
        containers = {}
        pdc = PDC(conf)
        for rpm in rpms:
            found = pdc.find_containers_by_rpm_name(rpm['name'])
            for container in found:
                id = container['id']
                if id not in containers:
                    container_detail = pdc.get_release_component_by_id(id)
                    container['branch'] = container_detail['dist_git_branch']
                    containers[id] = container

        return containers.values()
