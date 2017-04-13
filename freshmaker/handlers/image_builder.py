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

from freshmaker import log, conf
from freshmaker.handlers import BaseHandler
from freshmaker.events import DockerfileChanged


class DockerImageRebuildHandler(BaseHandler):

    def can_handle(self, event):
        return isinstance(event, DockerfileChanged)

    def handle(self, event):
        """Rebuild docker image"""
        self.build_image(event)

    def build_image(self, event):
        import koji

        config = koji.read_config(conf.koji_profile)
        koji_server = config['server']

        session = koji.ClientSession(koji_server, {'krb_rdns': config['krb_rdns']})

        log.debug('Logging into {0} with Kerberos authentication.'.format(koji_server))
        proxyuser = conf.koji_build_owner if conf.koji_proxyuser else None

        try:
            session.krb_login(proxyuser=proxyuser)
        except Exception as e:
            log.error('Failed to login Koji via Kerberos using GSSAPI')
            log.error('Error message from Koji: %s', e)
            return

        if not session.logged_in:
            log.error('Could not login server %s', koji_server)
            return

        build_opts = {
            'scratch': conf.koji_container_scratch_build,
            'git_branch': event.branch,
        }

        try:
            build_target = '{}-{}-candidate'.format(
                'rawhide' if event.branch == 'master' else event.branch,
                event.namespace)
            build_source = '{}#{}'.format(event.repo_url, event.rev)

            log.info('Start to build docker image %s', event.repo)
            log.debug('Build from source: %s', build_source)
            log.debug('Build in target: %s', build_target)
            log.debug('Build options: %s', build_opts)

            task_id = session.buildContainer(build_source, build_target, build_opts)
        except Exception as e:
            log.exception('Could not create task to build docker image %s', event.repo)
        else:
            log.info('Task %s is created to build docker image for repo %s', task_id, event.repo)
            log.info('Task info: %s/taskinfo?taskID=%s', config['weburl'], task_id)
        finally:
            log.debug('Logout Koji session')
            session.logout()
