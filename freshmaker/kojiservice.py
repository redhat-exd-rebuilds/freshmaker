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

# Unfortunately we want to use "parse_NVR" provided by koji
# in freshmaker.handlers __init__.py. We cannot  "import koji" there, because
# it would import freshmaker.handlers.koji, so instead, we import it here
# and in freshmaker.handler do "from freshmaker.kojiservice import parse_NVR".
from koji import parse_NVR # noqa
from kobo import rpmlib
from io import BytesIO
from zipfile import ZipFile

import contextlib
import dogpile.cache
import re
import requests
import yaml
import freshmaker.utils
from freshmaker import log, conf, db
from freshmaker.consumer import work_queue_put
from freshmaker.events import BrewContainerTaskStateChangeEvent
from freshmaker.models import ArtifactBuild


class KojiService(object):
    """Wrapper of Koji API and profile configuration

    As an interface of Koji profile configuration, KojiService exposes part
    of options that would be used frequently. However, other options are still
    accessible from ``config`` property.

    As a wrapper of Koji API, new APIs could be added as well.
    """
    region = dogpile.cache.make_region().configure(conf.dogpile_cache_backend)

    # Used to generate incremental task id in dry run mode.
    _FAKE_TASK_ID = 0

    def __init__(self, profile=None, dry_run=False):
        self._config = koji.read_config(profile or 'koji')
        self.dry_run = dry_run

        # In case we run in DRY_RUN mode, we need to initialize
        # _FAKE_TASK_ID to the id of last ODCS builds to have the IDs
        # increasing and unique even between Freshmaker restarts.
        if self.dry_run:
            KojiService._FAKE_TASK_ID = \
                ArtifactBuild.get_lowest_build_id(db.session) - 1
            if KojiService._FAKE_TASK_ID >= 0:
                KojiService._FAKE_TASK_ID = -1

    @property
    def config(self):
        return self._config

    @property
    def weburl(self):
        return self.config['weburl']

    @property
    def topurl(self):
        return self.config['topurl']

    @property
    def server(self):
        return self.config['server']

    @property
    def session(self):
        if not hasattr(self, '_session'):
            self._session = koji.ClientSession(self.config['server'],
                                               self.config)
        return self._session

    def krb_login(self):
        # No need to login on dry run, this makes dry run much faster.
        if not self.dry_run:
            self.session.gssapi_login(
                principal=conf.krb_auth_principal,
                keytab=conf.krb_auth_client_keytab,
                ccache=conf.krb_auth_ccache_file
            )
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
        KojiService._FAKE_TASK_ID -= 1
        task_id = KojiService._FAKE_TASK_ID

        # Parse the source_url to get the name of container and generate
        # fake event.
        m = re.match(r".*/(?P<container>[^#]*)", source_url)
        container = m.group('container')
        event = BrewContainerTaskStateChangeEvent(
            "fake_koji_msg_%d" % task_id, container, build_opts["git_branch"],
            build_target, task_id, "BUILDING", "CLOSED")
        event.dry_run = self.dry_run

        # Inject the fake event.
        log.info("DRY RUN: Injecting fake event: %r", event)
        work_queue_put(event)

        return task_id

    def build_container(self, source_url, branch, target,
                        scratch=None, repo_urls=None, flatpak=False, isolated=False,
                        release=None, koji_parent_build=None,
                        arch_override=None, compose_ids=None,
                        operator_csv_modifications_url=None):
        """Build container by buildContainer

        :param str source_url: the container repository URL.
        :param str target: specify a specific build target.
        :param str branch: a build option passed to ``buildContainer``.
        :param bool scratch: a build option passed to ``buildContainer``.
        :param list[str] repo_urls: a build option passed to ``buildContainer``.
        :param bool flatpak: a build option passed to ``buildContainer``.
        :param bool isolated: a build option passed to ``buildContainer``.
        :param str release: a build option passed to ``buildContainer``.
        :param str koji_parent_build: a build option passed to ``buildContainer``.
        :param str arch_override: a build option passed to ``buildContainer``.
        :param list[str] compose_ids: a build option passed to ``buildContainer``.
            For details of these build options, please refer to
            ``PARAMS_SCHEMA`` defined inside ``BuildContainerTask`` in the
            koji-containerbuild plugin.
        :param str operator_csv_modifications_url: a build option passed to ``buildContainer``.
            This is necessary for bundle image rebuilds.
        :return: the container build task ID returned from ``buildContainer``.
        :rtype: int
        """

        build_target = target
        build_opts = {
            'scratch': False if scratch is None else scratch,
            'git_branch': branch,
        }

        if repo_urls:
            build_opts['yum_repourls'] = repo_urls
        if compose_ids:
            build_opts['compose_ids'] = compose_ids
        if flatpak:
            build_opts['flatpak'] = True
        if isolated:
            build_opts['isolated'] = True
        if koji_parent_build:
            build_opts['koji_parent_build'] = koji_parent_build
        # arch-override is only allowed for isolated or scratch builds
        if arch_override and (isolated or scratch):
            build_opts['arch_override'] = arch_override
        if release:
            build_opts['release'] = release
        if operator_csv_modifications_url:
            build_opts['operator_csv_modifications_url'] = operator_csv_modifications_url

        log.debug('Build from target: %s', build_target)
        log.debug('Build options: %s', build_opts)

        if not self.dry_run:
            task_id = self.session.buildContainer(source_url, build_target,
                                                  build_opts)
        else:
            task_id = self._fake_build_container(source_url, build_target,
                                                 build_opts)

        log.info('Task %s is created to build docker image for %s',
                 task_id, source_url)
        log.info('Task info: %s/taskinfo?taskID=%s', self.weburl, task_id)

        return task_id

    def cancel_build(self, build_id):
        return self.session.cancelBuild(build_id)

    @region.cache_on_arguments()
    def get_build_rpms(self, build_nvr, arches=None):
        build_info = self.session.getBuild(build_nvr)
        return self.session.listRPMs(buildID=build_info['id'],
                                     arches=arches)

    @region.cache_on_arguments()
    def get_build(self, buildinfo):
        """
        Return information about a build.

        buildinfo may be either a int ID, a string NVR, or a map containing
        'name', 'version' and 'release.
        """
        return self.session.getBuild(buildinfo)

    @region.cache_on_arguments()
    def get_build_id(self, build_nvr):
        return self.session.findBuildID(build_nvr)

    def get_task_request(self, task_id):
        return self.session.getTaskRequest(task_id)

    def get_build_target(self, target_name):
        return self.session.getBuildTarget(target_name)

    def get_task_info(self, task_id):
        return self.session.getTaskInfo(task_id)

    def list_archives(self, build_id, archive_type=None):
        return self.session.listArchives(build_id, type=archive_type)

    def get_container_build_id_from_task(self, task_id):
        """
        Return container build id by check 'koji_builds' in build
        task result. If not found, return None.
        """
        # We cannot get the build_id from task_id in dry_run mode...
        if self.dry_run:
            return None

        build_id = None
        subtasks = self.session.getTaskChildren(task_id)
        if subtasks:
            for task in subtasks:
                task_result = self.session.getTaskResult(task['id'])
                builds = task_result.get('koji_builds', None)
                if builds:
                    build_id = int(builds.pop())
                    break
        else:
            task_result = self.session.getTaskResult(task_id)
            builds = task_result.get('koji_builds', None)
            if builds:
                build_id = int(builds.pop())
        return build_id

    def get_cg_metadata_url(self, buildinfo):
        """
        Return url of the CG metadata.json

        buildinfo may be either a int ID, a string NVR, or a map containing
        'name', 'version' and 'release.

        Note: it doesn't check whether the metadata.json exists or not.
        """
        build_info = self.get_build(buildinfo)
        return koji.PathInfo(topdir=self.topurl).build(build_info) + '/metadata.json'

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=log)
    def load_cg_metadata(self, buildinfo):
        """
        Fetch CG metadata.json and load the json.

        buildinfo may be either a int ID, a string NVR, or a map containing
        'name', 'version' and 'release.
        """
        cg_metadata_url = None
        try:
            cg_metadata_url = self.get_cg_metadata_url(buildinfo)
            resp = requests.get(cg_metadata_url, timeout=conf.requests_timeout)
            # url is redirected
            if resp.history:
                cg_metadata_url = resp.url
            return requests.get(cg_metadata_url, timeout=conf.requests_timeout).json()
        except requests.ConnectionError:
            raise
        except Exception as e:
            if cg_metadata_url:
                log.error("Unable to load CG metadata for build (%r) from url (%s): %s",
                          buildinfo, cg_metadata_url, str(e))
            else:
                log.error("Unable to load CG metadata for build (%r): %s", str(e))
            raise

    @region.cache_on_arguments()
    def get_rpms_in_container(self, buildinfo):
        """
        Get rpms in a koji container build.

        buildinfo may be either a int ID, a string NVR, or a map containing
        'name', 'version' and 'release.

        Return a set of rpm NVRs.
        """
        rpms = set()
        cg_metadata = self.load_cg_metadata(buildinfo)
        outputs = cg_metadata['output']
        for out in outputs:
            if out['type'] == 'docker-image':
                components = out['components']
                rpms = set([rpmlib.make_nvr(rpm) for rpm in components if rpm['type'] == 'rpm'])
        return rpms

    @region.cache_on_arguments()
    def get_odcs_compose_ids(self, build_nvr):
        """
        Get ODCS compose ids used in image build task

        Return a list of compose ids
        """
        build = self.get_build(build_nvr)
        # Get the list of ODCS composes used to build the image.
        extra_image = build.get("extra", {}).get("image", {})
        compose_ids = extra_image.get("odcs", {}).get("compose_ids")
        if not compose_ids:
            compose_ids = []
        return compose_ids

    @region.cache_on_arguments()
    def get_ocp_versions_range(self, build_nvr):
        """
        Get bundle image's OpenShift versions range value

        :param str build_nvr: NVR of image build.
        :return: OpenShift versions range of image.
        :rtype: str
        """
        ocp_versions_range = None

        build = self.get_build(build_nvr)
        archives = self.list_archives(build["id"], archive_type="image")
        for archive in archives:
            try:
                ocp_versions_range = archive["extra"]["docker"]["config"]["config"]["Labels"][
                    "com.redhat.openshift.versions"
                ]
            except KeyError:
                continue
            # different arches should have same metadata, stop checking
            # when ocp_version_range has been fetched
            if ocp_versions_range is not None:
                break

        return ocp_versions_range

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=log)
    def get_bundle_csv(self, build_nvr):
        """
        Return CSV(cluster service version) data of operator bundle build

        :param str build_nvr: NVR of operator bundle build.
        :return: CSV data or None when build is not bundle nor CSV data doesn't exist
        :rtype: dict or None
        """
        try:
            build_info = self.get_build(build_nvr)
            manifest_name = build_info.get('extra', {}).get('operator_manifests_archive')
            if not manifest_name:
                log.error("Operator manifests archive is unavaiable for build %s", build_nvr)
                return None

            build_url = koji.PathInfo(topdir=self.topurl).build(build_info).rstrip("/")
            manifest_url = f"{build_url}/files/operator-manifests/{manifest_name}"
            resp = requests.get(manifest_url)
        except Exception as e:
            log.error("Unable to get bundle CSV for build %s: %s", build_nvr, str(e))
            raise

        if not resp.ok:
            log.error("Unable to get bundle CSV for build %s: %s", build_nvr, resp.reason)
            return None

        zipfile = ZipFile(BytesIO(resp.content))
        files = zipfile.namelist()
        csv_files = [fn for fn in files if fn.endswith('.clusterserviceversion.yaml')]
        if not csv_files:
            log.error("CSV file not found in operator manifest of build %s", build_nvr)
            return None

        with zipfile.open(csv_files[0]) as f:
            return yaml.safe_load(f)


@contextlib.contextmanager
def koji_service(profile=None, logger=None, login=True, dry_run=False):
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
    service = KojiService(profile=profile, dry_run=dry_run)

    if login:
        if not conf.krb_auth_principal:
            log.error("Cannot login to Koji, krb_auth_principal not set")
        else:
            log.debug('Logging into %s with Kerberos authentication.',
                      service.server)

            service.krb_login()

            # We are not logged in in dry run mode...
            if not dry_run and not service.logged_in:
                log.error('Could not login server %s', service.server)
                yield None

    try:
        yield service
    finally:
        if service.logged_in:
            if logger:
                logger.debug('Logout Koji session')
            service.logout()
