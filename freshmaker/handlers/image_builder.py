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
from freshmaker.kojiservice import koji_service


class DockerImageRebuildHandler(BaseHandler):

    def can_handle(self, event):
        return isinstance(event, DockerfileChanged)

    def handle(self, event):
        """Rebuild docker image"""
        import koji

        try:
            self.build_image(event)
        except koji.krbV.Krb5Error as e:
            log.exception('Failed to login Koji via Kerberos using GSSAPI. %s', e.args[1])
        except:
            log.exception('Could not create task to build docker image %s', event.repo)

    def build_image(self, event):
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            log.debug('Logging into {0} with Kerberos authentication.'.format(service.server))
            proxyuser = conf.koji_build_owner if conf.koji_proxyuser else None

            service.krb_login(proxyuser=proxyuser)

            if not service.logged_in:
                log.error('Could not login server %s', service.server)
                return

            build_source = '{}#{}'.format(event.repo_url, event.rev)

            log.info('Start to build docker image %s', event.repo)
            log.debug('Build from source: %s', build_source)

            return service.build_container(build_source, event.branch,
                                           namespace=event.namespace,
                                           scratch=conf.koji_container_scratch_build)
