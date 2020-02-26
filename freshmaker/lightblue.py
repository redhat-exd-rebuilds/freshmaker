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
#            Jan Kaluza <jkaluza@redhat.com>
#            Ralph Bean <rbean@redhat.com>

import json
import os
import re
import requests
import io
import dogpile.cache
import kobo.rpmlib
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from itertools import groupby

from freshmaker import log, conf
from freshmaker.kojiservice import koji_service
from freshmaker.utils import sorted_by_nvr, is_pkg_modular
import koji


class LightBlueError(Exception):
    """Base class representing errors from LightBlue server"""

    def __init__(self, status_code, error_response):
        """Initialize

        :param int status_code: response status code
        :param str or dict error_response: response content returned from
            LightBlue server that contains error content. There are two types of
            error. A piece of HTML when error happens in system-wide, for example,
            requested resource does not exists (404), and internal server error (500).
            It could also be a JSON data when error happens while LightBlue handles
            request.
        """
        self._raw = error_response
        self._status_code = status_code

    def __repr__(self):
        return '<{} [{}]>'.format(self.__class__.__name__, self.status_code)

    @property
    def raw(self):
        return self._raw

    @property
    def status_code(self):
        return self._status_code


class LightBlueSystemError(LightBlueError):
    """LightBlue system error"""

    def _get_error_message(self):
        # Try getting the error code from JSON if returned.
        try:
            msg = ""
            json_data = json.loads(self.raw)
            if "errors" in json_data:
                for error in json_data["errors"]:
                    if "msg" not in error or "errorCode" not in error:
                        continue
                    msg += error["errorCode"] + ": " + error["msg"] + "\n"
            if msg:
                return msg
        except ValueError as e:
            log.exception(e)
        # If no JSON is returned, try to get the title of HTML page.
        buf = io.StringIO(self.raw)
        html = ''.join((line.strip('\n') for line in buf))
        match = re.search('<title>(.+)</title>', html)
        return match.groups()[0]

    def __str__(self):
        try:
            return self._get_error_message()
        except Exception as e:
            log.exception(e)
            raise


class LightBlueRequestError(LightBlueError):
    """LightBlue request error"""

    def __str__(self):
        return 'Error{} ({}):\n{}'.format(
            's' if len(self.raw['errors']) > 1 else '',
            len(self.raw['errors']),
            '\n'.join(('    {}'.format(err['msg'])
                      for err in self.raw['errors']))
        )


class KojiLookupError(ValueError):
    """ Koji lookup error """
    pass


class ContainerRepository(dict):
    """Represent a container repository"""

    @classmethod
    def create(cls, data):
        repo = cls()
        repo.update(data)
        return repo


class ContainerImage(dict):
    """Represent a container image"""

    region = dogpile.cache.make_region().configure(conf.dogpile_cache_backend)

    @classmethod
    def create(cls, data):
        image = cls()
        image.update(data)

        arch = data.get('architecture')
        image['multi_arch_rpm_manifest'] = {}
        rpm_manifest = data.get('rpm_manifest')
        if arch and rpm_manifest:
            image['multi_arch_rpm_manifest'][arch] = rpm_manifest

        return image

    def __hash__(self):
        return hash((self.nvr))

    @property
    def nvr(self):
        return self['brew']['build']

    def log_error(self, err):
        """
        Logs the error associated with this image and sets self["error"].
        If there has been previous call of log_error, new `err` is appended
        to self['error'] with ';' separator.
        """
        prefix = ""
        if 'brew' in self and 'build' in self['brew']:
            prefix = self.nvr + ": "
        log.error("%s%s", prefix, err)
        if 'error' not in self or not self['error']:
            self['error'] = str(err)
        else:
            self['error'] += "; " + str(err)

    def update_multi_arch(self, image):
        """
        Update multi-arch attributes for this image from another image.

        :param ContainerImage image: the container image object to copy multi
            arch attributes from
        :rtype: None
        """
        image_arch = image.get('architecture')
        if not image_arch:
            return

        image_rpm_manifest = image.get('rpm_manifest')
        if not image_rpm_manifest:
            return
        self['multi_arch_rpm_manifest'][image_arch] = image_rpm_manifest

    @property
    def dockerfile(self):
        dockerfile = [file for file in self['parsed_data']['files']
                      if file['filename'] == 'Dockerfile']
        if not dockerfile:
            log.warning('Image %s does not contain a Dockerfile.', self.nvr)
            return None
        return dockerfile[0]

    def _get_default_additional_data(self):
        return {
            "repository": None,
            "commit": None,
            "target": None,
            "git_branch": None,
            "error": None,
            "arches": None,
            "odcs_compose_ids": None,
            "parent_image_builds": None,
            "generate_pulp_repos": True,
        }

    @region.cache_on_arguments()
    def _get_additional_data_from_koji(self, nvr):
        """
        Finds the build defined by `nvr` in Koji and returns dict with
        additional information about this build including "repository",
        "commit", "target" and "git_branch".

        In case of lookup error, the "error" will be set to error string.
        """
        data = self._get_default_additional_data()

        with koji_service(
                conf.koji_profile, log, dry_run=conf.dry_run,
                login=False) as session:
            build = session.get_build(nvr)
            if not build:
                raise KojiLookupError(
                    "Cannot find Koji build with nvr %s in Koji" % nvr)

            if 'task_id' not in build or not build['task_id']:
                if ("extra" in build and
                        "container_koji_task_id" in build["extra"] and
                        build["extra"]["container_koji_task_id"]):
                    build['task_id'] = build["extra"]['container_koji_task_id']
                else:
                    raise KojiLookupError(
                        "Cannot find task_id or container_koji_task_id "
                        "in the Koji build %r" % build)

            # Get the list of ODCS composes used to build the image.
            extra_image = build.get("extra", {}).get("image", {})
            if extra_image.get("odcs", {}).get("compose_ids"):
                data["odcs_compose_ids"] = extra_image["odcs"]["compose_ids"]

            data["parent_build_id"] = extra_image.get("parent_build_id")
            data["parent_image_builds"] = extra_image.get("parent_image_builds")

            brew_task = session.get_task_request(
                build['task_id'])
            source = brew_task[0]
            data["target"] = brew_task[1]
            extra_data = brew_task[2]
            if "git_branch" in extra_data:
                data["git_branch"] = extra_data["git_branch"]
            else:
                data["git_branch"] = "unknown"

            # Some builds do not have "source" attribute filled in, so try
            # both build["source"] and task_request[0] sources.
            sources = [source]
            if "source" in build:
                sources.insert(0, build["source"])
            for src in sources:
                m = re.match(r".*/(?P<namespace>.*)/(?P<container>.*)#(?P<commit>.*)", src)
                if m:
                    namespace = m.group("namespace")
                    # For some Koji tasks, the container part ends with "?" in
                    # source URL. This is just because some custom scripts for
                    # submitting those builds include this character in source URL
                    # to mark the query part of URL. We need to handle that by
                    # stripping that character.
                    container = m.group("container").rstrip("?")
                    data["repository"] = namespace + "/" + container

                    # There might be tasks which have branch name in
                    # "origin/branch_name" format, so detect it set commit
                    # hash only if this is not true.
                    if "/" not in m.group("commit"):
                        data["commit"] = m.group("commit")
                        break

            if not data['commit']:
                raise KojiLookupError(
                    "Cannot find valid source of Koji build %r" % build)

            if not conf.supply_arch_overrides:
                data['arches'] = None
            else:
                data['arches'] = self._get_arches_from_koji(session, build['build_id'])

        return data

    def _get_arches_from_koji(self, koji_session, build_id):
        archives = koji_session.list_archives(build_id=build_id)
        arches = [
            archive['extra']['image']['arch']
            for archive in archives if archive['btype'] == 'image']
        return ' '.join(sorted(arches))

    def resolve_commit(self):
        """
        Uses the ContainerImage data to resolve the information about
        commit from which the Docker image has been built.

        Sets the "repository and "commit" keys/values if available.
        """
        # Find the additional data for Container build in Koji.
        try:
            data = self._get_additional_data_from_koji(self.nvr)
        except KojiLookupError as e:
            err = "Cannot get data from Koji for build %s: %s." % (self.nvr, e)
            log.error(err)
            data = self._get_default_additional_data()
            data["error"] = err

        self.update(data)

    def resolve_content_sets(self, lb_instance, children=None):
        """
        Find out the content_sets this image uses and store it as
        "content_sets" key in image.

        :param LightBlue lb_instance: LightBlue instance to use for additional
            queries.
        :param list[ContainerImage] children: List of children to take the
            content_sets from in case this container image is unpublished and
            therefore without "content_sets" set.
        """

        # ContainerImage now has content_sets field, so use it if available.
        if "content_sets" in self and self["content_sets"]:
            log.info("Container image %s uses following content sets: %r",
                     self.nvr, self["content_sets"])
            if "content_sets_source" not in self:
                self["content_sets_source"] = "lightblue_container_image"
            return

        # In case content_sets are not set directly in this ContainerImage,
        # try to get them from children image.
        self["content_sets_source"] = "child_image"
        if not children:
            log.warning("Container image %s does not have 'content_sets' set "
                        "in Lightblue and also does not have any children, "
                        "this is suspicious.", self.nvr)
            self.update({"content_sets": []})
            return

        for child in children:
            # The child['content_sets'] should be always set for children
            # passed here, but in case it is not, just try it.
            if "content_sets" not in child:
                child.resolve(lb_instance, None)
            if not child["content_sets"]:
                continue

            log.info("Container image %s does not have 'content-sets' set "
                     "in Lightblue. Using child image %s content_sets: %r",
                     self.nvr, child.nvr,
                     child["content_sets"])
            self.update({"content_sets": child["content_sets"]})
            return

        log.warning("Container image %s does not have 'content_sets' set "
                    "in Lightblue as well as its children, this "
                    "is suspicious.", self.nvr)
        self.update({"content_sets": []})

    def resolve_published(self, lb_instance):
        # Get the published version of this image to find out if the image
        # was actually published.
        images = lb_instance.get_images_by_nvrs(
            [self.nvr], published=True, include_rpm_manifest=False)
        if images:
            self["published"] = True
        else:
            self["published"] = False

            # Usually we do not store complete RPM manifest, but when
            # image is unpublished, we need complete RPM manifest in order
            # to check for possible unpublished RPMs.
            # We do not want to get the complete manifest for every container
            # image, because it is relatively big, so fetch it only when needed.
            images = lb_instance.get_images_by_nvrs([self.nvr])
            if images:
                self["rpm_manifest"] = images[0]["rpm_manifest"]
            else:
                log.warning("No image %s found in Lightblue.", self.nvr)

    def resolve(self, lb_instance, children=None):
        """
        Resolves the Container image - populates additional metadata by
        querying Koji and dist-git.

        Calls self.resolve_commit() and self.resolve_content_sets().
        """
        try:
            self.resolve_commit()
            self.resolve_content_sets(lb_instance, children)
            self.resolve_published(lb_instance)
        except Exception as e:
            err = "Cannot resolve the container image: %s" % e
            self.log_error(err)

    def get_rpms(self):
        """
        Extracts the RPMs from the Container image.
        """
        if "rpm_manifest" not in self or not self["rpm_manifest"]:
            # Do not filter if we are not sure what RPMs are in the image.
            log.info(("Not filtering out this image because we "
                      "are not sure what RPMs are in there."))
            return
        # There is always just single "rpm_manifest". Lightblue returns
        # this as a list, because it is reference to
        # containerImageRPMManifest.
        rpm_manifest = self["rpm_manifest"][0]
        if "rpms" not in rpm_manifest:
            # Do not filter if we are not sure what RPMs are in the image.
            log.info(("Not filtering out this image because we "
                      "are not sure what RPMs are in there."))
            return
        return rpm_manifest["rpms"]

    def get_registry_repositories(self, lb_instance):
        if self['repositories']:
            return self['repositories']

        parsed_nvr = kobo.rpmlib.parse_nvr(self.nvr)

        if '.' not in parsed_nvr['release']:
            log.debug('There are no repositories for %s', self.nvr)
            return []

        original_release = parsed_nvr['release'].rsplit('.', 1)[0]
        parsed_nvr['release'] = original_release
        original_nvr = '{name}-{version}-{release}'.format(**parsed_nvr)
        log.debug('Finding repositories for %s through %s', self.nvr, original_nvr)

        previous_images = lb_instance.get_images_by_nvrs(
            [original_nvr], published=None, include_rpm_manifest=False)
        if not previous_images:
            log.warning('original_nvr %s not found in Lightblue', original_nvr)
            return []

        return previous_images[0].get_registry_repositories(lb_instance)


class LightBlue(object):
    """Interface to query lightblue"""

    region = dogpile.cache.make_region().configure(
        conf.dogpile_cache_backend, expiration_time=120)

    def __init__(self, server_url, cert, private_key,
                 verify_ssl=None,
                 entity_versions=None,
                 event_id=None):
        """Initialize LightBlue instance

        :param str server_url: URL used to call LightBlue APIs. It is
            unnecessary to include path part, which will be handled
            automatically. For example, https://lightblue.example.com/.
        :param str cert: path to certificate file.
        :param str private_key: path to private key file.
        :param bool verify_ssl: whether to verify SSL over HTTP. Enabled by
            default.
        :param dict entity_versions: a mapping from entity to what version
            should be used to request data. If no such a mapping appear , it
            means the default version will be used. You should choose versions
            explicitly. If entity_versions is omitted entirely, default version
            will be used on each entity.
        """
        self.server_url = server_url.rstrip('/')
        self.api_root = '{}/rest/data'.format(self.server_url)
        self.event_id = event_id
        if verify_ssl is None:
            self.verify_ssl = True
        else:
            self.verify_ssl = verify_ssl

        if not os.path.exists(cert):
            raise IOError('Certificate file {} does not exist.'.format(cert))
        else:
            self.cert = cert

        if not os.path.exists(private_key):
            raise IOError('Private key file {} does not exist.'.format(private_key))
        else:
            self.private_key = private_key

        self.entity_versions = entity_versions or {}

    def _get_entity_version(self, entity_name):
        """Lookup configured entity's version

        :param str entity_name: entity name to get its version.
        :return: version configured for the entity name. If there is no
            corresponding version, emtpy string is returned, which can be used
            to construct request URL directly that means to use default
            version.
        :rtype: str
        """
        return self.entity_versions.get(entity_name, '')

    def _make_request(self, entity, data):
        """Make a request to query data from LightBlue

        :param str entity: the entity part to construct a full URL sent to
            LightBlue. Refer to callers of ``_make_request`` to learn what
            entities this argument accepts.
        :param dict data: LightBlue query metadata and criteria.
        :return: a mapping containing result returned from LightBlue.
        :rtype: dict
        :raises LightBlueSystemError: if requested resource does not exist,
            something wrong internally inside LightBlue to fail to response
            the query, or the request is unauthorized.
        :raises LightBlueRequestError: if LightBlue responses any other type
            of errors.
        """
        entity_url = '{}/{}'.format(self.api_root, entity)
        response = requests.post(entity_url,
                                 data=json.dumps(data),
                                 verify=self.verify_ssl,
                                 cert=(self.cert, self.private_key),
                                 headers={'Content-Type': 'application/json'})

        status_code = response.status_code

        if status_code == HTTPStatus.OK:
            return response.json()

        # Warn early, in case there is an error in the error handling code below
        log.warning("Request to %s gave %r", response.request.url, response)

        if status_code in (HTTPStatus.NOT_FOUND,
                           HTTPStatus.INTERNAL_SERVER_ERROR,
                           HTTPStatus.UNAUTHORIZED):
            raise LightBlueSystemError(status_code, response.content)
        else:
            raise LightBlueRequestError(status_code, response.json())

    def find_container_repositories(self, request):
        """Query via entity containerRepository

        :param dict request: a map containing complete query expression.
            This query will be sent to LightBlue in a POST request. Refer to
            https://jewzaam.gitbooks.io/lightblue-specifications/content/language_specification/query.html
            to know more detail about how to write a query.
        :return: a list of ContainerRepository objects
        :rtype: list
        """

        url = 'find/containerRepository/{}'.format(
            self._get_entity_version('containerRepository'))
        response = self._make_request(url, request)

        repos = []
        for repo_data in response['processed']:
            if not repo_data.get('auto_rebuild_tags'):
                log.info('"auto_rebuild_tags" not set for %s repository, ignoring repository',
                         repo_data["repository"])
                continue
            repo = ContainerRepository()
            repo.update(repo_data)
            repos.append(repo)
        return repos

    def find_container_images(self, request):
        """Query via entity containerImage

        :param dict request: a map containing complete query expression.
            This query will be sent to LightBlue in a POST request. Refer to
            https://jewzaam.gitbooks.io/lightblue-specifications/content/language_specification/query.html
            to know more detail about how to write a query.
        :return: a list of ContainerImage objects
        :rtype: list
        """

        url = 'find/containerImage/{}'.format(
            self._get_entity_version('containerImage'))
        response = self._make_request(url, request)

        images = []
        nvr_to_arches = {}
        for image_data in response['processed']:
            image = ContainerImage.create(image_data)
            images.append(image)

            # TODO: In the future, we may want to combine different ContainerImage
            # objects into a single object. For now, ensure that whichever object
            # is used by caller contains multi-arch information.
            nvr = image.nvr
            nvr_to_arches.setdefault(nvr, [])
            nvr_to_arches[nvr].append(image)
            for arch_image in nvr_to_arches[nvr][:-1]:
                arch_image.update_multi_arch(image)
                image.update_multi_arch(arch_image)

        return images

    def _set_container_repository_filters(
            self, request, published=True,
            release_categories=conf.lightblue_release_categories):
        """
        Sets the additional filters to containerRepository request
        based on the self.published, self.release_categories attributes.
        :param bool published: whether to limit queries to published
            repositories
        :param release_categories: filter only repositories with specific
            release categories (options: Deprecated, Generally Available, Beta, Tech Preview)
        :type release_categories: tuple[str] or list[str]
        """
        if published is not None:
            request["query"]["$and"].append({
                "field": "published",
                "op": "=",
                "rvalue": published
            })

        if release_categories:  # Check if release_categories is None or empty
            request["query"]["$and"].append({
                "$or": [{
                    "field": "release_categories.*",
                    "op": "=",
                    "rvalue": category
                } for category in release_categories]
            })

        return request

    def find_all_container_repositories(
            self, published=True,
            release_categories=conf.lightblue_release_categories):
        """
        Returns dict with repository name as key and ContainerRepository as
        value.

        :param bool published: whether to limit queries to published
            repositories
        :param release_categories: filter only repositories with specific
            release categories (options: Deprecated, Generally Available, Beta,
            Tech Preview)
        :type release_categories: tuple[str] or list[str]
        :rtype: dict
        :return: Dict with repository name as key and ContainerRepository as
            value.
        """
        repo_request = {
            "objectType": "containerRepository",
            "query": {
                "$and": []  # filled by _set_container_repository_filters().
            },
            "projection": [
                {"field": "repository", "include": True},
                {"field": "auto_rebuild_tags", "include": True, "recursive": True},
                {"field": "release_categories", "include": True, "recursive": True},
            ]
        }
        repo_request = self._set_container_repository_filters(
            repo_request, published, release_categories)
        repositories = self.find_container_repositories(repo_request)
        return {r["repository"]: r for r in repositories}

    def _get_default_projection(self, srpm_names=None, include_rpm_manifest=True):
        """
        Returns the default projection list for containerImage objects.

        :param list srpm_names: When not None, defines the SRPM names which
            are returned in "rpm_manifest" field of containerImage.;
        :param bool include_rpm_manifest: indicate whether to include
            "rpm_manifest" in the query result. Default is True.
        """
        projection = [
            {"field": "brew", "include": True, "recursive": True},
            {"field": "parsed_data.files", "include": True, "recursive": True},
            {"field": "parsed_data.layers.*", "include": True, "recursive": True},
            {"field": "repositories.*.published", "include": True, "recursive": True},
            {"field": "repositories.*.repository", "include": True, "recursive": True},
            {"field": "repositories.*.tags.*.name", "include": True, "recursive": True},
            {"field": "content_sets", "include": True, "recursive": True},
            {"field": "parent_brew_build", "include": True, "recursive": False},
            {"field": "architecture", "include": True, "recursive": False},
        ]
        if include_rpm_manifest:
            if srpm_names:
                projection += [
                    {"field": "rpm_manifest.*.rpms", "include": True, "recursive": True,
                     "match": {
                         "$or": [{
                             "field": "srpm_name",
                             "op": "=",
                             "rvalue": srpm_name
                         } for srpm_name in srpm_names]}}]
            else:
                projection += [
                    {"field": "rpm_manifest.*.rpms", "include": True, "recursive": True},
                    {"field": "rpm_manifest.*.rpms.*.srpm_name", "include": True, "recursive": True},
                ]
        return projection

    def filter_out_images_with_higher_srpm_nvr(self, images, srpm_name_to_nvrs):
        """
        Checks whether the input NVRs defined in `srpm_name_to_nvrs` dict are
        newer than the matching SRPM NVRs in the container image.

        If all the SRPM NVRs in the container image are newer than matching
        input NVRs, the container image is filtered out from the `images`
        list.

        For example: The httpd-2.4-1 RPM is released together with
        httpd-container. In this case, Freshmaker would try to rebuild
        httpd-container, because it contains httpd package. But this is not
        needed, because latest httpd-container already contains that updated
        package. Therefore we filter it out in this method.

        :param list images: List of ContainerImage instances.
        :param dict srpm_name_to_nvrs: Dict with SRPM name as a key and list
            of NVRs as a value.
        :rtype: list
        :return: List of ContainerImage instances without the filtered images.
        """
        ret = []
        for image in images:
            rpms = image.get_rpms()
            if rpms is None:
                ret.append(image)
            image_included = False
            for rpm in rpms or []:
                image_srpm_nvr = kobo.rpmlib.parse_nvr(rpm["srpm_nevra"])
                for srpm_nvr in srpm_name_to_nvrs.get(rpm.get("srpm_name"), []):
                    input_srpm_nvr = kobo.rpmlib.parse_nvr(srpm_nvr)
                    # compare_nvr return values:
                    #   - nvr1 newer than nvr2: 1
                    #   - same nvrs: 0
                    #   - nvr1 older: -1
                    # We want to rebuild only images with SRPM NVR lower than
                    # input SRPM NVR, therefore we check for -1.
                    if kobo.rpmlib.compare_nvr(
                            image_srpm_nvr, input_srpm_nvr, ignore_epoch=True) == -1:
                        ret.append(image)
                        image_included = True
                        break
                if image_included:
                    break
            else:
                # Oh-no, the mighty for/else block!
                # The else clause executes after the loop completes normally.
                # This means that the loop did not encounter a break statement.
                # In our case, this means that we filtered out the image.
                log.info("Will not rebuild %s, because it does not contain "
                         "older version of any input package: %r" % (
                             image.nvr, srpm_name_to_nvrs.values()))
        return ret

    def filter_out_modularity_mismatch(self, images, srpm_name_to_nvrs):
        """
        Filter out container images which have a modularity mismatch with ``srpm_name_to_nvrs``.

        If an advisory has a modular RPM, then the container image's RPM of the same name should
        also be modular. The opposite should also be true. If not, the container image is filtered
        out from the ``images`` list.

        :param list images: List of ContainerImage instances.
        :param dict srpm_name_to_nvrs: Dict with SRPM name as a key and list
            of NVRs as a value.
        :rtype: list
        :return: List of ContainerImage instances without the filtered images.
        """
        ret = []
        for image in images:
            rpms = image.get_rpms()
            if rpms is None:
                ret.append(image)
            image_included = False
            # Include the image if the SRPM from the advisory is modular, and the SRPM of the same
            # name in the image is also modular. Also, include the image if the opposite is true.
            for rpm in rpms or []:
                for srpm_nvr in srpm_name_to_nvrs.get(rpm.get("srpm_name"), []):
                    if ((is_pkg_modular(srpm_nvr) and is_pkg_modular(rpm["srpm_nevra"])) or
                            (not is_pkg_modular(srpm_nvr) and not is_pkg_modular(rpm["srpm_nevra"]))):
                        ret.append(image)
                        image_included = True
                        break
                if image_included:
                    break
            else:
                log.info(
                    "Will not rebuild %s because there is a modularity mismatch between the RPMs "
                    "from the image and the advisory: %r" % (
                        image.nvr, srpm_name_to_nvrs.values()))
        return ret

    def filter_out_images_based_on_content_set(self, images, content_sets):
        """
        Filter out container images based on the content_set.

        Freshmaker queries Lightblue to get images containing affected RPMs installed from a
        particular content_set. At the same time Freshmaker asks to Lightblue also all the images
        with enabled the auto_rebuild_tags tag (when not enabled the rebuilds of images in this
        repository are disabled).
        This gets done only because the Lightblue query will be easier and cleaner this way.
        But because of that some images returned by that query will not have the correct
        content_sets, for this reason we need to filter out images based on the content_sets.

        :param list images: List of ContainerImage instances.
        :param set content_sets: List of content_sets the image includes RPMs
            from.
        :rtype: list
        :return: List of ContainerImage instances without the filtered images.
        """
        ret = []
        for image in images:
            if not content_sets & set(image["content_sets"]):
                log.info(f"Will not rebuild {image.nvr} because its content_sets "
                         "({image['content_sets']}) are not related to the requested content_sets"
                         " ({content_sets})")
            else:
                ret.append(image)
        return ret

    def find_images_with_included_srpms(
            self, content_sets, srpm_nvrs, repositories, published=True,
            include_rpm_manifest=True):
        """
        Query lightblue and find the containerImages in the given containerRepositories.

        By default, limit this only to images which have been published to at least one repository
        and have an auto-rebuild tag.

        If the same image is built for multiple arches, then only one of the arches will be
        returned.

        :param list content_sets: List of content_sets the image includes RPMs
            from.
        :param list srpm_nvrs: list of SRPM NVRs to look for
        :param dict repositories: List of repository names to look for.
        :param bool published: whether to limit queries to published
            repositories
        :param bool include_rpm_manifest: whether to include the RPMs in the result.
        """
        auto_rebuild_tags = set()
        for repo in repositories.values():
            auto_rebuild_tags |= set(repo["auto_rebuild_tags"])

        # Lightblue cannot compare NVRs, so just ask for all the container
        # images with any version/release of SRPM we are interested in and
        # compare it on client side.
        srpm_name_to_nvrs = {}
        for srpm_nvr in srpm_nvrs:
            name = koji.parse_NVR(srpm_nvr)["name"]
            srpm_name_to_nvrs.setdefault(name, []).append(srpm_nvr)

        image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [{
                            "field": "repositories.*.tags.*.name",
                            "op": "=",
                            "rvalue": tag
                        } for tag in auto_rebuild_tags]
                    },
                    {
                        "field": "parsed_data.files.*.key",
                        "op": "=",
                        "rvalue": "buildfile"
                    },
                ]
            },
            "projection": self._get_default_projection(
                srpm_names=srpm_name_to_nvrs.keys(),
                include_rpm_manifest=include_rpm_manifest)
        }

        if content_sets:
            image_request["query"]["$and"].append(
                {
                    "$or": [{
                        "field": "content_sets.*",
                        "op": "=",
                        "rvalue": r
                    } for r in content_sets]
                })

        if srpm_nvrs:
            image_request["query"]["$and"].append(
                {
                    "$or": [{
                        "field": "rpm_manifest.*.rpms.*.srpm_name",
                        "op": "=",
                        "rvalue": srpm_name
                    } for srpm_name in srpm_name_to_nvrs.keys()]
                })

        if published is not None:
            image_request["query"]["$and"].append(
                {
                    "field": "repositories.*.published",
                    "op": "=",
                    "rvalue": published
                })

        images = self.find_container_images(image_request)
        if not images:
            return images

        # The image_request returns container images which are in the
        # right repository and are latest in *some* repository. But we need
        # those images to be latest in one of the `repositories`. It is not
        # trivial to generate LB query like this, so filter this client-side
        # for now.
        image_nvr_to_image = {}
        for image in images:
            nvr = image.nvr
            if nvr in image_nvr_to_image:
                # This image for another architecture has already been seen
                continue

            for repository in image["repositories"]:
                if repository["repository"] not in repositories:
                    continue

                published_repo = repositories[repository["repository"]]
                tag_names = [tag["name"] for tag in repository["tags"]]

                for auto_rebuild_tag in published_repo["auto_rebuild_tags"]:
                    if auto_rebuild_tag in tag_names:
                        image["release_categories"] = published_repo["release_categories"]
                        image_nvr_to_image[nvr] = image
                        break
                else:
                    # If no match is found, continue to the next repository
                    continue

                # If a match was found, continue to the next image
                break

        # Reassign the filtered values to `images`
        images = list(image_nvr_to_image.values())
        images = self.filter_out_images_with_higher_srpm_nvr(images, srpm_name_to_nvrs)
        images = self.filter_out_modularity_mismatch(images, srpm_name_to_nvrs)
        if content_sets:
            images = self.filter_out_images_based_on_content_set(images, set(content_sets))
        return images

    def get_images_by_nvrs(self, nvrs, published=True, content_sets=None,
                           srpm_nvrs=None, include_rpm_manifest=True,
                           srpm_names=None):
        """Query lightblue and returns containerImages defined by list of
        `nvrs`.

        :param list nvrs: List of NVRs defining the containerImages to return.
        :param bool published: whether to limit queries to published images
        :param list content_sets: List of content_sets the image includes RPMs
            from.
        :param list srpm_nvrs: list of SRPM NVRs to look for
        :param bool include_rpm_manifest: When True, the rpm_manifest is
            included in the returned ContainerImages.
        :param list srpm_names: list of SRPM names to look for.
        :return: List of containerImages.
        :rtype: list of ContainerImages.
        """
        image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [{
                            "field": "brew.build",
                            "op": "=",
                            "rvalue": nvr
                        } for nvr in nvrs]
                    },
                    {
                        "field": "parsed_data.files.*.key",
                        "op": "=",
                        "rvalue": "buildfile"
                    },
                ]
            },
            "projection": self._get_default_projection(
                include_rpm_manifest=include_rpm_manifest)
        }

        if content_sets is not None:
            image_request["query"]["$and"].append(
                {
                    "$or": [{
                        "field": "content_sets.*",
                        "op": "=",
                        "rvalue": r
                    } for r in content_sets]
                }
            )

        if srpm_nvrs is not None:
            # Lightblue cannot compare NVRs, so just ask for all the container
            # images with any version/release of SRPM we are interested in and
            # compare it on client side.
            srpm_name_to_nvrs = {}
            for srpm_nvr in srpm_nvrs:
                name = koji.parse_NVR(srpm_nvr)["name"]
                srpm_name_to_nvrs.setdefault(name, []).append(srpm_nvr)
            image_request["query"]["$and"].append(
                {
                    "$or": [{
                        "field": "rpm_manifest.*.rpms.*.srpm_name",
                        "op": "=",
                        "rvalue": srpm_name
                    } for srpm_name in srpm_name_to_nvrs.keys()]
                }
            )

        if published is not None:
            image_request["query"]["$and"].append(
                {
                    "field": "repositories.*.published",
                    "op": "=",
                    "rvalue": published
                })

        if srpm_names:
            image_request["query"]["$and"].append(
                {
                    "$or": [{
                        "field": "rpm_manifest.*.rpms.*.srpm_name",
                        "op": "=",
                        "rvalue": srpm_name
                    } for srpm_name in srpm_names]
                }
            )

        images = self.find_container_images(image_request)
        if srpm_nvrs is not None:
            images = self.filter_out_images_with_higher_srpm_nvr(images, srpm_name_to_nvrs)
        return images

    def get_images_by_brew_package(self, names):
        """
        Query Lightblue to get all the images for a specific list of names.
        :param names list: list of names we want to find images for.
        :return: list of container images matching the requested names.
        :rtype: list of ContainerImages
        """

        query = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "field": "repositories.*.published",
                        "op": "=",
                        "rvalue": True
                    },
                    {
                        "$or": [{
                            "field": "brew.package",
                            "op": "=",
                            "rvalue": name,
                        } for name in names]
                    }
                ]
            },
            "projection": self._get_default_projection(include_rpm_manifest=False)
        }
        return self.find_container_images(query)

    def find_parent_brew_build_nvr_from_child(self, child_image):
        """
        Returns the parent brew build NVR of the input image. If the parent is not found it returns None.

        :param ContainerImage child_image: ContainerImage object, image for which we need to find the parent.

        :return: parent brew build NVR of the input image.
        :rtype: str

        """
        parent_brew_build = child_image.get("parent_brew_build")
        if parent_brew_build:
            return parent_brew_build
        # We need to resolve the image in here because "parent_image_builds" needs to be there
        # and it gets populated when the image gets resolved.
        child_image.resolve(self)
        # If the parent is not in `parent_brew_build` we can try to look for the parent in Brew,
        # using the field `parent_image_builds` (searching for the nvr), which should always be there.
        # In case parent_brew_build is None and child_image["parent_image_builds"] == {},
        # it means we found a base image and there's no parent image.
        if child_image["parent_image_builds"]:
            parent_brew_build = [
                i["nvr"] for i in child_image["parent_image_builds"].values()
                if i["id"] == child_image["parent_build_id"]][0]

        return parent_brew_build

    def find_parent_images_with_package(self, child_image, srpm_name, images=None):
        """
        Returns the chain of all parent images of the image which contain the
        package `srpm_name` in their RPM manifest.

        The first item in the list is the direct parent of the image in question.
        The last item in the list is the top level parent of the image in
        question.

        This method is recursive.
        """
        if not images:
            images = []
        parent_image = None

        # We first try to find the parent from the `parent_brew_build` field in Lightblue.
        parent_brew_build = self.find_parent_brew_build_nvr_from_child(child_image)
        # We've reached the base image, stop recursion
        if not parent_brew_build:
            return images
        parent_image = self.get_images_by_nvrs([parent_brew_build], srpm_names=[srpm_name], published=None)

        if parent_image:
            # In some cases, an image may not have its content sets defined. To
            # circumvent this gap, we use the list of child images when calling
            # resolve so their content sets can be used.
            children = images if images else [child_image]
            parent_image = parent_image[0]
            parent_image.resolve(self, children)

        if images:
            if parent_image:
                images[-1]['parent'] = parent_image
            else:
                # If we did not find the parent image with the package,
                # we still want to set the parent of the last image with
                # the package so we know against which image it has been
                # built.
                # Let's try first with the "parent_brew_build" field.
                parent = self.get_images_by_nvrs([parent_brew_build], published=None)
                if parent:
                    parent = parent[0]
                    parent.resolve(self, images)
                else:
                    err = "Couldn't find parent image %s. Lightblue data is probably incomplete" % (
                        parent_brew_build)
                    log.error(err)
                    if not images[-1]['error']:
                        images[-1]['error'] = err
                images[-1]['parent'] = parent

        if not parent_image:
            return images
        images.append(parent_image)
        return self.find_parent_images_with_package(parent_image, srpm_name, images)

    def find_images_with_packages_from_content_set(
            self, srpm_nvrs, content_sets, filter_fnc=None, published=True,
            release_categories=conf.lightblue_release_categories,
            leaf_container_images=None):
        """Query lightblue and find containers which contain given
        package from one of content sets

        :param list srpm_nvrs: list of SRPM NVRs to look for
        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages
        :param function filter_fnc: Function called as
            filter_fnc(container_image) with container_image being
            ContainerImage instance. If this function returns True, the image
            will not be considered for a rebuild as well as its parent images.
            This function is used to filter out images not allowed by
            Freshmaker configuration.
        :param bool published: whether to limit queries to published
            repositories
        :param release_categories: filter only repositories with specific
            release categories (options: Deprecated, Generally Available, Beta, Tech Preview)
        :type release_categories: tuple[str] or list[str]
        :param list leaf_container_images: List of NVRs of leaf images to
            consider for the rebuild. If not set, all images found in
            Lightblue will be considered for rebuild.

        :return: a list of dictionaries with three keys - repository, commit and
            srpm_nevra. Repository is a name git repository including the
            namespace. Commit is a git ref - usually a git commit
            hash. srpm_nevra is whole NEVRA of source rpm that is included in
            the given image - can be used for comparisons if needed
        :rtype: list
        """

        repos = self.find_all_container_repositories(published, release_categories)
        if not repos:
            return []
        if not leaf_container_images:
            images = self.find_images_with_included_srpms(
                content_sets, srpm_nvrs, repos, published)
        else:
            # The `leaf_container_images` can contain unpublished container image,
            # therefore set `published` to None.
            images = self.get_images_by_nvrs(
                leaf_container_images, None, content_sets, srpm_nvrs)
            # There can be multi-arch images which share the same
            # image['brew']['build']. Freshmaker is not interested in the image
            # architecture, it is only interested in NVR, so group the images
            # by the same image['brew']['build'] and include just first one in the
            # image list.
            sorted_images = sorted_by_nvr(images, reverse=True)
            images = []

            # We must combine content_sets with same image NVR
            # but different architectures into one content_sets field
            for k, temp_images in groupby(sorted_images, key=lambda item: item.nvr):
                temp_images = list(temp_images)
                img = temp_images[0]
                if 'content_sets' in img and len(temp_images) > 1:
                    new_content_sets = set(img.get('content_sets'))
                    for i in temp_images[1:]:
                        new_content_sets.update(i.get('content_sets', []))
                    img["content_sets"] = list(new_content_sets)
                images.append(img)

        # In case we query for unpublished images, we need to return just
        # the latest NVR for given name-version, otherwise images would
        # contain all the versions which ever containing the srpm_name.
        if not published:

            def _name_version_key(item):
                nvr = koji.parse_NVR(item.nvr)
                return f"{nvr['name']}-{nvr['version']}"

            images = [
                next(grouped_images) for _, grouped_images in groupby(
                    sorted_by_nvr(images, reverse=True),
                    key=_name_version_key
                )
            ]

        # Filter out images based on the filter_fnc.
        if filter_fnc:
            images = [image for image in images if not filter_fnc(image)]

        def _resolve_image(image):
            # We do not set "children" here in resolve_content_sets call, because
            # published images should have the content_set set.
            image.resolve(self, None)

            # Mark as latest_released only images which are not Beta or Tech Preview.
            # This is important, because "latest_released" is used in deduplication
            # code to mark the image to which the other images with same name-version
            # but lower release can be upgraded.
            release_categories = image.get("release_categories", [])
            if "Beta" not in release_categories and "Tech Preview" not in release_categories:
                image["latest_released"] = True
            image["directly_affected"] = True
            return image

        with ThreadPoolExecutor(max_workers=conf.max_thread_workers) as executor:
            return list(executor.map(_resolve_image, images))

    def _deduplicate_images_to_rebuild(self, to_rebuild):
        """
        Deduplicates the images to rebuild in `to_rebuild` in-place.

        The `to_rebuild` list is a list in following format:
            [
                [child_image, parent_of_child_image, parent_of_parent, ...],
                ...
            ]

        This methods goes through all the images in `to_rebuild` list and
        changes the list in a way that only single image with the highest
        release will exist for the given image name-version.

        For example, if there are three images in a list - foo-1-2, foo-1-3
        and foo-2-2, the foo-1-3 will be used instead of foo-1-2 on every
        occurrence in a list, because the NVR is higher than NVR of foo-1-2.
        The foo-2-2 will be kept unchanged in a list, because it is the
        single record for the foo image in version 2.
        """

        # We need to deduplicate images in two phases:
        #
        # 1) "handle_parent_change" - During this phase, we find out if update
        #    to latest image changes also the parent images.
        #    For example, foo-1-1 can be built against x-1-1, but foo-1-2 can
        #    be built against y-1-1. If we simply replace "foo-1-1" by "foo-1-2"
        #    while keeping the original parent image, the "foo-1-2" will be built
        #    against x-1-1 instead of y-1-1. This would be wrong.
        #
        #    To fix that, we therefore find out that the parent image changed in
        #    the latest release of foo-1-2 and we replace also the parent images
        #    according to latest release foo-1-2.
        #
        # 2) "update_to_latest". During this phase, we simply find out old releases
        #    of images in `to_rebuild` and update them to latest released NVR.
        for phase in ["handle_parent_change", "update_to_latest"]:
            # Temporary dict mapping the NVR of image to coordinates in the
            # `to_rebuild` list. For example
            # nvr_to_coordinates["nvr"] = [[0, 3], ...] means that the image with
            # nvr "nvr" is 4th image in the to_rebuild[0] list, ...
            nvr_to_coordinates = {}
            # Temporary dict mapping the NV-repository_key to list of NVRs.
            # The List of NVRs is always sorted descending.
            image_group_to_nvrs = {}
            # Temporary dict mapping the NVR to image.
            nvr_to_image = {}
            # Temporary dict mapping image_group to latest released NVR for that image_group.
            image_group_to_latest_released_nvr = {}

            # Constructs the temporary dicts as described above.
            for image_id, images in enumerate(to_rebuild):
                for parent_id, image in enumerate(images):
                    nvr = image.nvr
                    image_group = self.describe_image_group(image)
                    if image_group not in image_group_to_nvrs:
                        image_group_to_nvrs[image_group] = []
                    if nvr not in image_group_to_nvrs[image_group]:
                        image_group_to_nvrs[image_group].append(nvr)
                    if nvr not in nvr_to_coordinates:
                        nvr_to_coordinates[nvr] = []
                    nvr_to_coordinates[nvr].append([image_id, parent_id])
                    nvr_to_image[nvr] = image
                    if "latest_released" in image and image["latest_released"]:
                        image_group_to_latest_released_nvr[image_group] = nvr

            # Sort the lists in image_group_to_nvrs dict.
            for image_group in image_group_to_nvrs.keys():
                image_group_to_nvrs[image_group] = sorted_by_nvr(image_group_to_nvrs[image_group], reverse=True)

                # There might be container image NVRs which are not released yet,
                # but some released image is already built on top of them.
                # The issue is that such unreleased container image won't be in
                # its containerRepository and therefore won't have proper
                # content_sets set.
                # In this case, we copy the content_sets from the released image.
                # This might bring issue in case the content_sets changed
                # dramatically between released and unreleased release of such
                # image, but it's still the best guess we can do.
                # This is also used only as fallback in case "content_sets.yml"
                # does not exists in the dist-git repo, which should be rare
                # situation.
                latest_content_sets = []
                for nvr in reversed(image_group_to_nvrs[image_group]):
                    image = nvr_to_image[nvr]
                    if ("content_sets" not in image or
                            not image["content_sets"] or
                            "content_sets_source" not in image):
                        image["content_sets"] = latest_content_sets
                    elif image["content_sets_source"] == "child_image":
                        if latest_content_sets:
                            image["content_sets"] = latest_content_sets
                    else:
                        latest_content_sets = image["content_sets"]

            # Iterate through list of NVs.
            for image_group, nvrs in image_group_to_nvrs.items():
                # We want to replace NVRs which are lower than the latest released
                # NVR with latest released NVR. If there are some higher NVRs, we
                # want to keep them, because we don't want to rebuild the image
                # against older NVR than the one it is currently built against.
                if image_group in image_group_to_latest_released_nvr:
                    latest_released_nvr = image_group_to_latest_released_nvr[image_group]
                else:
                    latest_released_nvr = nvrs[0]

                # The latest_released_nvr_index points to the latest released NVR
                # in the `nvrs` list. Because `nvrs` list is desc sorted, every NVR
                # with higher index is lower and therefore we need to replace it.
                if not conf.lightblue_released_dependencies_only:
                    latest_released_nvr_index = nvrs.index(latest_released_nvr)
                else:
                    # In case we want to use only released versions of images,
                    # replace all the images with the latest released one.
                    latest_released_nvr_index = -1

                if phase == "handle_parent_change":
                    # Find out the name of parent image of latest release image.
                    latest_image = nvr_to_image[latest_released_nvr]
                    if "parent" not in latest_image or not latest_image["parent"]:
                        continue
                    latest_parent_name = koji.parse_NVR(
                        latest_image["parent"].nvr)["name"]

                    # Go through the older images and in case the parent image differs,
                    # update its parents according to latest image parents.
                    for nvr in nvrs[latest_released_nvr_index + 1:]:
                        image = nvr_to_image[nvr]
                        if "parent" not in image or not image["parent"]:
                            continue
                        parent_name = koji.parse_NVR(image["parent"].nvr)["name"]
                        if parent_name != latest_parent_name:
                            for image_id, parent_id in nvr_to_coordinates[nvr]:
                                latest_image_id, latest_parent_id = nvr_to_coordinates[latest_released_nvr][0]
                                to_rebuild[image_id][parent_id:] = to_rebuild[latest_image_id][latest_parent_id:]
                elif phase == "update_to_latest":
                    for nvr in nvrs[latest_released_nvr_index + 1:]:
                        for image_id, parent_id in nvr_to_coordinates[nvr]:
                            # At first replace the image in to_rebuild based
                            # on the coordinates from temp dict.
                            to_rebuild[image_id][parent_id] = nvr_to_image[latest_released_nvr]

                            # And in case this image is not the the leaf image, also replace
                            # the ["parent"] record for the child image to point to the image
                            # with highest NVR.
                            if parent_id != 0:
                                to_rebuild[image_id][parent_id - 1]["parent"] = nvr_to_image[latest_released_nvr]

        return to_rebuild

    # Cache to avoid multiple calls. We want one call per nvr, not one per arch
    @region.cache_on_arguments(to_str=lambda image: image.nvr)
    def describe_image_group(self, image):
        # Also include the sorted names of repositories in the image group
        # to handle the case when different releases of single name-version are
        # included in different container repositories.
        repositories = image.get_registry_repositories(self)
        repository_key = sorted([r["repository"] for r in repositories])
        parsed_nvr = koji.parse_NVR(image.nvr)
        return "%s-%s-%s" % (parsed_nvr["name"], parsed_nvr["version"], repository_key)

    def _images_to_rebuild_to_batches(self, to_rebuild, directly_affected_nvrs):
        """
        Creates batches with images as defined by `find_images_to_rebuild`
        output from the `to_rebuild` list in following format:

            [
                [child_image, parent_of_child_image, parent_of_parent, ...],
                ...
            ]

        :param list to_rebuild: the list of images to rebuild
        :param set directly_affected_nvrs: the set of NVRs that were detected as directly affected
            and that should have `directly_affected` value set.
        :return: a list of batches with each batch having a list of images
        :rtype: list
        """
        # At first get the max length of list in to_rebuild list.
        max_len = 0
        for rebuild_list in to_rebuild:
            max_len = max(len(rebuild_list), max_len)

        # Now create the batches with images. We still might find duplicate
        # images in to_rebuild lists in two cases:
        #
        # 1) A depends on X and also B depends on X. The X then would be
        #    added to first batch twice. This is simple to fix by just
        #    adding same image to batch once.
        # 2) A depends on X and A is also standalone image to rebuild. In this
        #    case, A would be in the second batch, because A must be built
        #    before X, but it is also standalone image to be rebuilt, so it
        #    would appear also in the first batch.
        #    To fix this, we at first add images with the longest dependency
        #    chains, so A will be added to second batch. Once we try to add
        #    standalone version of A, we won't add it, because it already
        #    exists in some batch.
        #
        # Both of these cases are handled by adding the image to `seen` set
        # and checking if it exists there already before adding it again.
        batches = [[] for i in range(max_len)]
        seen = set()
        for image_rebuild_list in sorted(to_rebuild, key=lambda lst: len(lst), reverse=True):
            for image, batch in zip(reversed(image_rebuild_list), batches):
                image_key = image.nvr
                # If one of the parents is directly affected but not marked, mark it explicitly
                if image_key in directly_affected_nvrs and not image.get("directly_affected"):
                    image["directly_affected"] = True
                if image_key in seen:
                    continue
                seen.add(image_key)
                batch.append(image)
        return batches

    def find_images_to_rebuild(
            self, srpm_nvrs, content_sets, published=True,
            release_categories=conf.lightblue_release_categories,
            filter_fnc=None, leaf_container_images=None):
        """
        Find images to rebuild through image build layers

        Returns the list of sub-lists in which each sub-list contains
        ContainerImage instances which can be built in parallel. Sub-list N+1
        contains images which depend on images from sub-list N, so building any
        image from N+1 must happen *after* all of the images from sub-list N
        have been rebuilt.

        :param list srpm_nvrs: List of SRPM NVRs to look for
        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages
        :param bool published: whether to limit queries to published
            repositories
        :param tuple release_categories: filter only repositories with specific
            release categories (options: Deprecated, Generally Available, Beta, Tech Preview)
        :param function filter_fnc: Function called as
            filter_fnc(container_image) with container_image being
            ContainerImage instance. If this function returns True, the image
            will not be considered for a rebuild as well as its parent images.
            This function is used to filter out images not allowed by
            Freshmaker configuration.
        :param list leaf_container_images: List of NVRs of leaf images to
            consider for the rebuild. If not set, all images found in
            Lightblue will be considered for rebuild. Note that `published`
            is not respected when `leaf_container_images` are used.
        """
        images = self.find_images_with_packages_from_content_set(
            srpm_nvrs, content_sets, filter_fnc, published,
            release_categories, leaf_container_images=leaf_container_images)

        srpm_names = [koji.parse_NVR(srpm_nvr)["name"] for srpm_nvr in srpm_nvrs]

        def _get_images_to_rebuild(image):
            """
            Find out parent images to rebuild, helper called from threadpool.
            """
            rebuild_list = {}  # per srpm-name rebuild list.
            for srpm_name in srpm_names:
                for rpm in image["rpm_manifest"][0]["rpms"]:
                    if rpm["srpm_name"] == srpm_name:
                        break
                else:
                    # This `srpm_name` is not in image.
                    continue

                rebuild_list[srpm_name] = self.find_parent_images_with_package(
                    image, srpm_name, [])
                if rebuild_list[srpm_name]:
                    image['parent'] = rebuild_list[srpm_name][0]
                else:
                    parent_brew_build = self.find_parent_brew_build_nvr_from_child(image)
                    if parent_brew_build:
                        parent = self.get_images_by_nvrs([parent_brew_build], published=None)
                        if parent:
                            parent = parent[0]
                            parent.resolve(self, images)
                            image['parent'] = parent
                rebuild_list[srpm_name].insert(0, image)
            return rebuild_list

        # For every image, find out all its parent images which contain the
        # srpm_name package and store these lists to to_rebuild.
        to_rebuild = []
        with ThreadPoolExecutor(max_workers=conf.max_thread_workers) as executor:
            for result in executor.map(_get_images_to_rebuild, images):
                to_rebuild.extend(result.values())

        # The to_rebuild list now contains all the images which need to be
        # rebuilt, but there are lot of duplicates there.

        # At first remove duplicated images which share the same name and
        # version, but different release.
        to_rebuild = self._deduplicate_images_to_rebuild(to_rebuild)

        # Get all the directly affected images so that any parents that are not marked as
        # directly affected can be set in _images_to_rebuild_to_batches
        directly_affected_nvrs = {
            image.nvr for image in images if image.get("directly_affected")
        }
        # Now generate batches from deduplicated list and return it.
        return self._images_to_rebuild_to_batches(to_rebuild, directly_affected_nvrs)
