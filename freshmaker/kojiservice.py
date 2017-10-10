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

import koji

# Unfortunatelly we want to use "parse_NVR" provided by koji
# in freshmaker.handlers __init__.py. We cannot  "import koji" there, because
# it would import freshmaker.handlers.koji, so instead, we import it here
# and in freshmaker.handler do "from freshmaker.kojiservice import parse_NVR".
from koji import parse_NVR # noqa

import contextlib
import re
from freshmaker import log, conf
from freshmaker.consumer import work_queue_put
from freshmaker.events import BrewContainerTaskStateChangeEvent
from freshmaker.utils import krb_context


class KojiService(object):
    """Wrapper of Koji API and profile configuration

    As an interface of Koji profile configuration, KojiService exposes part
    of options that would be used frequently. However, other options are still
    accessible from ``config`` property.

    As a wrapper of Koji API, new APIs could be added as well.
    """

    # Used to generate incremental task id in dry run mode.
    _FAKE_TASK_ID = 1

    def __init__(self, profile=None):
        self._config = koji.read_config(profile or 'koji')

    @property
    def config(self):
        return self._config

    @property
    def weburl(self):
        return self.config['weburl']

    @property
    def server(self):
        return self.config['server']

    @property
    def session(self):
        if not hasattr(self, '_session'):
            self._session = koji.ClientSession(self.config['server'],
                                               self.config)
        return self._session

    def krb_login(self, proxyuser=None):
        # No need to login on dry run, this makes dry run much faster.
        if not conf.dry_run:
            self.session.krb_login(proxyuser=proxyuser)
        else:
            log.info("DRY RUN: Skipping login in dry run mode.")

    @property
    def logged_in(self):
        return self.session.logged_in

    def logout(self):
        self.session.logout()

    def _fake_build_container(self, source_url, build_target, build_opts):
        """
        Fake KojiSession.buildContainer method used dry run mode.

        Logs the arguments and emits BrewContainerTaskStateChangeEvent of
        CLOSED state.

        :rtype: number
        :return: Fake task_id.
        """
        log.info("DRY RUN: Calling fake buildContainer with args: %r",
                 (source_url, build_target, build_opts))

        # Get the task_id
        KojiService._FAKE_TASK_ID += 1
        task_id = KojiService._FAKE_TASK_ID

        # Parse the source_url to get the name of container and generate
        # fake event.
        m = re.match(r".*/(?P<container>[^#]*)", source_url)
        container = m.group('container')
        event = BrewContainerTaskStateChangeEvent(
            "fake_koji_msg_%d" % task_id, container, build_opts["git_branch"],
            build_target, task_id, "BUILDING", "CLOSED")

        # Inject the fake event.
        log.info("DRY RUN: Injecting fake event: %r", event)
        work_queue_put(event)

        return task_id

    def build_container(self, source_url, branch, target,
                        scratch=None, repo_urls=None, isolated=False,
                        release=None, koji_parent_build=None):
        """Build container by buildContainer"""

        build_target = target
        build_opts = {
            'scratch': False if scratch is None else scratch,
            'git_branch': branch,
        }

        if repo_urls:
            build_opts['yum_repourls'] = repo_urls
        if isolated:
            build_opts['isolated'] = True
        if koji_parent_build:
            build_opts['koji_parent_build'] = koji_parent_build
        if release:
            build_opts['release'] = release

        log.debug('Build from target: %s', build_target)
        log.debug('Build options: %s', build_opts)

        if not conf.dry_run:
            task_id = self.session.buildContainer(source_url, build_target,
                                                  build_opts)
        else:
            task_id = self._fake_build_container(source_url, build_target,
                                                 build_opts)

        log.info('Task %s is created to build docker image for %s',
                 task_id, source_url)
        log.info('Task info: %s/taskinfo?taskID=%s', self.weburl, task_id)

        return task_id

    def get_build_rpms(self, build_nvr, arches=None):
        log.info("get_build_rpms %r", build_nvr)
        build_info = self.session.getBuild(build_nvr)
        return self.session.listRPMs(buildID=build_info['id'],
                                     arches=arches)

    def get_build(self, build_nvr):
        log.info("get_build %r", build_nvr)
        return self.session.getBuild(build_nvr)

    def get_task_request(self, task_id):
        log.info("get_task_request %r", task_id)
        return self.session.getTaskRequest(task_id)


@contextlib.contextmanager
def koji_service(profile=None, logger=None, login=True):
    """A Koji service context manager that could be used with with

    Example::

        with KojiService() as service:
            ...

        # if you want it to log something
        with KojiService(logger=logger) as service:
            ...

        # if you want it to use alternative Koji profile rather than the default one koji
        with KojiService(koji='stg', logger=logger) as service:
            ...
    """
    service = KojiService(profile=profile)

    if login:
        if not conf.krb_auth_principal:
            log.error("Cannot login to Koji, krb_auth_principal not set")
        else:
            log.debug('Logging into %s with Kerberos authentication.',
                      service.server)

            proxyuser = conf.koji_build_owner if conf.koji_proxyuser else None

            with krb_context():
                service.krb_login(proxyuser=proxyuser)

            # We are not logged in in dry run mode...
            if not conf.dry_run and not service.logged_in:
                log.error('Could not login server %s', service.server)
                yield None

    try:
        yield service
    finally:
        if service.logged_in:
            if logger:
                logger.debug('Logout Koji session')
            service.logout()
