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

import os

from itertools import chain

import freshmaker.pdc as pdc

from freshmaker import log, conf
from freshmaker.handlers import BaseHandler
from freshmaker.events import DockerfileChanged
from freshmaker.events import BodhiUpdateCompleteStable
from freshmaker.utils import temp_dir
from freshmaker.utils import _run_command
from freshmaker.utils import get_commit_hash
from freshmaker.kojiservice import koji_service


class DockerImageRebuildHandler(BaseHandler):
    name = 'DockerImageRebuildHandler'

    def can_handle(self, event):
        return isinstance(event, DockerfileChanged)

    def handle(self, event):
        """Rebuild docker image"""
        import koji

        log.info('Start to rebuild docker image %s', event.repo)

        if not self.allow_build(event, 'image', event.repo, event.branch):
            log.info("Skip rebuild of %s:%s as it's not allowed by configured whitelist/blacklist",
                     event.repo, event.branch)
            return []

        try:
            task_id = self.build_image(repo_url=event.repo_url,
                                       rev=event.rev,
                                       branch=event.branch,
                                       namespace=event.namespace)

            self.record_build(event, event.repo, 'image', task_id)

        except koji.krbV.Krb5Error as e:
            log.exception('Failed to login Koji via Kerberos using GSSAPI. %s', e.args[1])
        except:
            log.exception('Could not create task to build docker image %s', event.repo)

        return []

    def build_image(self, repo_url, rev, branch, namespace=None):
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            log.debug('Logging into {0} with Kerberos authentication.'.format(service.server))
            proxyuser = conf.koji_build_owner if conf.koji_proxyuser else None
            service.krb_login(proxyuser=proxyuser)

            if not service.logged_in:
                log.error('Could not login server %s', service.server)
                return

            build_source = '{}?#{}'.format(repo_url, rev)

            log.debug('Build from source: %s', build_source)

            return service.build_container(build_source,
                                           branch,
                                           namespace=namespace,
                                           scratch=conf.koji_container_scratch_build)


class DockerImageRebuildHandlerForBodhi(DockerImageRebuildHandler):
    """Rebuild docker images when RPMs are synced by Bodhi"""
    name = 'DockerImageRebuildForBodhiHandler'

    def __init__(self):
        self.pdc_session = pdc.get_client_session(conf)

    def can_handle(self, event):
        return isinstance(event, BodhiUpdateCompleteStable)

    def handle(self, event):
        log.info('Rebuild docker images for event %s, msgid: %s',
                 BodhiUpdateCompleteStable.__name__, event.msg_id)

        rpms = self.get_rpms_included_in_bodhi_update(event.builds)
        containers = self.get_containers_including_rpms(rpms)

        log.info('Found docker images to rebuild: %s', containers)

        for container in containers:
            if not self.allow_build(event, 'image', container['name'], container['branch']):
                log.info("Skip rebuild of image %s:%s as it's not allowed by configured whitelist/blacklist",
                         container['name'], container['branch'])
                continue
            try:
                task_id = self.handle_image_build(container)
                self.record_build(event, container['name'], 'image', task_id)
            except:
                log.exception('Error when rebuild %s', container)

    def handle_image_build(self, container_info):
        name = container_info['name']
        branch = container_info['branch']
        repo_url = '{}/{}/{}'.format(conf.git_base_url, 'container', name)

        log.info('Start to rebuild docker image %s from branch %s', name, branch)

        with temp_dir(suffix='-rebuild-docker-image') as working_dir:
            self.clone_repository(repo_url, branch, working_dir)

            last_commit_hash = get_commit_hash(
                os.path.join(working_dir, name))

            return self.build_image(repo_url=repo_url,
                                    branch=branch,
                                    rev=last_commit_hash)

    def clone_repository(self, url, branch, working_dir):
        cmd = ['git', 'clone', '-b', branch, url]
        log.debug('Clone repository: %s', cmd)
        _run_command(cmd, rundir=working_dir)

    def get_rpms_included_in_bodhi_update(self, builds):
        build_nvrs = (build['nvr'] for build in builds)
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            return chain(*[service.get_build_rpms(nvr) for nvr in build_nvrs])

    def get_containers_including_rpms(self, rpms):
        containers = {}
        for rpm in rpms:
            found = pdc.find_containers_by_rpm_name(self.pdc_session, rpm['name'])
            for container in found:
                id = container['id']
                if id not in containers:
                    container_detail = pdc.get_release_component(self.pdc_session, id)
                    container['branch'] = container_detail['dist_git_branch']
                    containers[id] = container

        return containers.values()
