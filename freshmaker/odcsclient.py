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
# Written by Jan Kaluza <jkaluza@redhat.com>

# We have name conflict between two modules here:
#  - "odcs" module provided by python2-odcs-client
#  - "odcs" submodule in freshmaker.handlers.odcs
#
# Unfortunatelly we want to use "odcs" provided by python2-odcs-client
# in freshmaker.handlers __init__.py. We cannot  "import odcs" there, because
# it would import freshmaker.handlers.odcs, so instead, we import it here
# and in freshmaker.handler do "from freshmaker.odcsclient import ODCS".

import koji
import os
import kobo.rpmlib

from odcs.client.odcs import AuthMech, ODCS
from odcs.common.types import COMPOSE_STATES
from requests.exceptions import HTTPError

from freshmaker import conf, log, db
from freshmaker.models import Compose
from freshmaker.errata import Errata
from freshmaker.kojiservice import koji_service
from freshmaker.consumer import work_queue_put
from freshmaker.types import ArtifactBuildState
from freshmaker.utils import krb_context
from freshmaker.events import ODCSComposeStateChangeEvent


class RetryingODCS(ODCS):

    def _make_request(self, *args, **kwargs):
        try:
            return super(RetryingODCS, self)._make_request(*args, **kwargs)
        except HTTPError as e:
            if e.response.status_code == 401:
                log.info("CCache file probably expired, removing it.")
                os.unlink(conf.krb_auth_ccache_file)
                return super(RetryingODCS, self)._make_request(*args, **kwargs)
            else:
                raise


def create_odcs_client():
    """
    Create instance of ODCS according to configured authentication mechasnim
    """
    if conf.odcs_auth_mech == 'kerberos':
        return RetryingODCS(conf.odcs_server_url,
                            auth_mech=AuthMech.Kerberos,
                            verify_ssl=conf.odcs_verify_ssl)
    elif conf.odcs_auth_mech == 'openidc':
        if not conf.odcs_openidc_token:
            raise ValueError('Missing OpenIDC token in configuration.')
        return RetryingODCS(conf.odcs_server_url,
                            auth_mech=AuthMech.OpenIDC,
                            openidc_token=conf.odcs_openidc_token,
                            verify_ssl=conf.odcs_verify_ssl)
    else:
        raise ValueError(
            'Authentication mechanism {0} is not supported yet.'.format(
                conf.odcs_auth_mech))


class FreshmakerODCSClient(object):
    """
    Class wrapping ODCS providing high-level methods to generate ODCS composes.
    This class is intended to be used in the BaseHandler scope.
    """

    def __init__(self, handler):
        """
        Creates new FreshmakerODCSClient.

        :param BaseHandler handler: Handler with which is the newly created
            instance associated.
        """
        self.handler = handler

    def _fake_odcs_new_compose(
            self, compose_source, tag, packages=None, results=[],
            builds=None):
        """
        Fake odcs.new_compose(...) method used in the dry run mode.

        Logs the arguments and emits fake ODCSComposeStateChangeEvent

        :rtype: dict
        :return: Fake odcs.new_compose dict.
        """
        self.handler.log_info(
            "DRY RUN: Calling fake odcs.new_compose with args: %r",
            (compose_source, tag, packages, results))

        # In case we run in DRY_RUN mode, we need to initialize
        # FAKE_COMPOSE_ID to the id of last ODCS compose to give the IDs
        # increasing and unique even between Freshmaker restarts.
        fake_compose_id = Compose.get_lowest_compose_id(db.session) - 1
        if fake_compose_id >= 0:
            fake_compose_id = -1

        new_compose = {}
        new_compose['id'] = fake_compose_id
        new_compose['result_repofile'] = "http://localhost/%d.repo" % (
            new_compose['id'])
        new_compose['state'] = COMPOSE_STATES['done']
        if results:
            new_compose['results'] = ['boot.iso']
        if builds:
            new_compose['builds'] = builds

        # Generate and inject the ODCSComposeStateChangeEvent event.
        event = ODCSComposeStateChangeEvent(
            "fake_compose_msg", new_compose)
        event.dry_run = True
        self.handler.log_info("Injecting fake event: %r", event)
        work_queue_put(event)

        return new_compose

    def _get_packages_for_compose(self, nvr):
        """Get RPMs of current build NVR

        :param str nvr: build NVR.
        :return: list of RPM names built from given build.
        :rtype: list
        """
        with koji_service(
                conf.koji_profile, log, dry_run=self.handler.dry_run) as session:
            rpms = session.get_build_rpms(nvr)
        return list(set([rpm['name'] for rpm in rpms]))

    def _get_compose_source(self, nvr):
        """Get tag from which to collect packages to compose
        :param str nvr: build NVR used to find correct tag.
        :return: found tag. None is returned if build is not the latest build
            of found tag.
        :rtype: str
        """
        with koji_service(
                conf.koji_profile, log, dry_run=self.handler.dry_run) as service:
            # Get the list of *-candidate tags, because packages added into
            # Errata should be tagged into -candidate tag.
            tags = service.session.listTags(nvr)
            candidate_tags = [tag['name'] for tag in tags
                              if tag['name'].endswith('-candidate')]

            # Candidate tags may include unsigned packages and ODCS won't
            # allow generating compose from them, so try to find out final
            # version of candidate tag (without the "-candidate" suffix).
            final_tags = []
            for candidate_tag in candidate_tags:
                final = candidate_tag[:-len("-candidate")]
                final_tags += [tag['name'] for tag in tags
                               if tag['name'] == final]

            # Prefer final tags over candidate tags.
            tags_to_try = final_tags + candidate_tags
            for tag in tags_to_try:
                latest_build = service.session.listTagged(
                    tag,
                    latest=True,
                    package=koji.parse_NVR(nvr)['name'])
                if latest_build and latest_build[0]['nvr'] == nvr:
                    self.handler.log_info(
                        "Package %r is latest version in tag %r, "
                        "will use this tag", nvr, tag)
                    return tag
                elif not latest_build:
                    self.handler.log_info(
                        "Could not find package %r in tag %r, "
                        "skipping this tag", nvr, tag)
                else:
                    self.handler.log_info(
                        "Package %r is not he latest in the tag %r ("
                        "latest is %r), skipping this tag",
                        nvr, tag, latest_build[0]['nvr'])

    def prepare_yum_repos_for_rebuilds(self, db_event):
        repo_urls = []
        db_composes = []

        compose = self.prepare_yum_repo(db_event)
        db_composes.append(Compose(odcs_compose_id=compose['id']))
        db.session.add(db_composes[-1])
        repo_urls.append(compose['result_repofile'])

        for dep_event in db_event.find_dependent_events():
            compose = self.prepare_yum_repo(dep_event)
            db_composes.append(Compose(odcs_compose_id=compose['id']))
            db.session.add(db_composes[-1])
            repo_urls.append(compose['result_repofile'])

        # commit all new composes
        db.session.commit()

        for build in db_event.builds:
            build.add_composes(db.session, db_composes)
        db.session.commit()

        # Remove duplicates from repo_urls.
        return list(set(repo_urls))

    def prepare_yum_repo(self, db_event):
        """
        Request a compose from ODCS for builds included in Errata advisory

        Run a compose in ODCS to contain required RPMs for rebuilding images
        later.

        :param Event db_event: current event being handled that contains errata
            advisory to get builds containing updated RPMs.
        :return: a mapping returned from ODCS that represents the request
            compose.
        :rtype: dict
        """
        errata_id = int(db_event.search_key)

        packages = []
        errata = Errata()
        builds = errata.get_builds(errata_id)
        compose_source = None
        for nvr in builds:
            packages += self._get_packages_for_compose(nvr)
            source = self._get_compose_source(nvr)
            if compose_source and compose_source != source:
                # TODO: Handle this by generating two ODCS composes
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value, "Packages for errata "
                    "advisory %d found in multiple different tags."
                    % (errata_id))
                return
            else:
                compose_source = source

        if compose_source is None:
            db_event.builds_transition(
                ArtifactBuildState.FAILED.value, 'None of builds %s of '
                'advisory %d is the latest build in its candidate tag.'
                % (builds, errata_id))
            return

        self.handler.log_info(
            'Generating new compose for rebuild: '
            'source: %s, source type: %s, packages: %s',
            compose_source, 'tag', packages)

        if not self.handler.dry_run:
            with krb_context():
                new_compose = create_odcs_client().new_compose(
                    compose_source, 'tag', packages=packages,
                    sigkeys=conf.odcs_sigkeys, flags=["no_deps"])
        else:
            new_compose = self._fake_odcs_new_compose(
                compose_source, 'tag', packages=packages)

        return new_compose

    def prepare_pulp_repo(self, build, content_sets):
        """
        Prepares .repo file containing the repositories matching
        the content_sets by creating new ODCS compose of PULP type.

        This currently blocks until the compose is done or failed.

        :param build: models.ModuleBuild instance associated with this compose.
        :param list content_sets: List of content sets.
        :rtype: dict
        :return: ODCS compose dictionary.
        """
        self.handler.log_info(
            'Generating new PULP type compose for content_sets: %r',
            content_sets)

        odcs = create_odcs_client()
        if not self.handler.dry_run:
            with krb_context():
                new_compose = odcs.new_compose(
                    ' '.join(content_sets), 'pulp')
        else:
            new_compose = self._fake_odcs_new_compose(
                content_sets, 'pulp')

        return new_compose

    def prepare_odcs_compose_with_image_rpms(self, image):
        """
        Request a compose from ODCS for builds included in Errata advisory

        Run a compose in ODCS to contain required RPMs for rebuilding images
        later.

        :param dict image: Container image representation as returned by
            LightBlue class.
        :return: a mapping returned from ODCS that represents the request
            compose.
        :rtype: dict
        """

        if not image.get('rpm_manifest'):
            self.handler.log_warn('"rpm_manifest" not set in image.')
            return

        rpm_manifest = image["rpm_manifest"][0]
        if not rpm_manifest.get('rpms'):
            return

        builds = set()
        packages = set()
        for rpm in rpm_manifest["rpms"]:
            parsed_nvr = kobo.rpmlib.parse_nvra(rpm["srpm_nevra"])
            srpm_nvr = "%s-%s-%s" % (parsed_nvr["name"], parsed_nvr["version"],
                                     parsed_nvr["release"])
            builds.add(srpm_nvr)
            parsed_nvr = kobo.rpmlib.parse_nvra(rpm["nvra"])
            packages.add(parsed_nvr["name"])

        # ODCS client expects list and not set for packages/builds, so convert
        # them to lists. Sorting the lists to make them easy to look up, e.g.
        # in logs, and easy to test.
        builds = sorted(builds)
        packages = sorted(packages)

        if not self.handler.dry_run:
            with krb_context():
                new_compose = create_odcs_client().new_compose(
                    "", 'build', packages=packages, builds=builds,
                    sigkeys=conf.odcs_sigkeys, flags=["no_deps"])
        else:
            new_compose = self._fake_odcs_new_compose(
                "", 'build', packages=packages,
                builds=builds)

        self.handler.log_info(
            "Started generating ODCS 'build' type compose %d." % (
                new_compose["id"]))

        return new_compose
