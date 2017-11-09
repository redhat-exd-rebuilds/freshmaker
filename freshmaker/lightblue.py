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

import json
import os
import re
import requests
import six
import dogpile.cache

from six.moves import http_client
import concurrent.futures
from freshmaker import log, conf
from freshmaker.kojiservice import koji_service


class LightBlueError(Exception):
    """Base class representing errors from LightBlue server"""

    def __init__(self, status_code, error_response):
        """Initialize

        :param int status_code: repsonse status code
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
        # Remove all newlines if there is
        buf = six.StringIO(self.raw)
        html = ''.join((line.strip('\n') for line in buf))
        match = re.search('<title>(.+)</title>', html)
        return match.groups()[0]

    def __str__(self):
        return self._get_error_message()


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
        return image

    def __hash__(self):
        return hash((self['brew']['build']))

    def _get_default_additional_data(self):
        return {"repository": None, "commit": None, "target": None,
                "git_branch": None, "error": None}

    @region.cache_on_arguments()
    def _get_additional_data_from_koji(self, nvr):
        """
        Finds the build defined by `nvr` in Koji and returns dict with
        additional information about this build including "repository",
        "commit", "target" and "git_branch".

        In case of lookup error, the "error" will be set to error string.
        """
        data = self._get_default_additional_data()

        with koji_service(conf.koji_profile, log) as session:
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

            brew_task = session.get_task_request(
                build['task_id'])
            source = brew_task[0]
            data["target"] = brew_task[1]
            extra_data = brew_task[2]
            if "git_branch" in extra_data:
                data["git_branch"] = extra_data["git_branch"]
            else:
                data["git_branch"] = "unknown"

            m = re.match(r".*/(?P<namespace>.*)/(?P<container>.*)#(?P<commit>.*)", source)
            if m:
                namespace = m.group("namespace")
                container = m.group("container")
                data["repository"] = namespace + "/" + container
                data["commit"] = m.group("commit")

        return data

    def resolve_commit(self, srpm_name):
        """
        Uses the ContainerImage data to resolve the information about
        commit from which the Docker image has been built.

        Sets the "repository, "commit" and "srpm_nevra" keys/values if
        available.

        :param str srpm_name: Name of the package because of which the Docker
                              image is rebuilt.
        """
        srpm_nevra = None
        if ("rpm_manifest" in self and len(self['rpm_manifest']) > 0 and
                "rpms" in self["rpm_manifest"]):
            for rpm in self["rpm_manifest"]['rpms']:
                if "srpm_name" in rpm and rpm["srpm_name"] == srpm_name:
                    srpm_nevra = rpm['srpm_nevra']
                    break

        # Find the additional data for Container build in Koji.
        nvr = self["brew"]["build"]
        try:
            data = self._get_additional_data_from_koji(nvr)
        except KojiLookupError as e:
            err = "Cannot get data from Koji for build %s: %s." % (nvr, e)
            log.error(err)
            data = self._get_default_additional_data()
            data["error"] = err

        data["srpm_nevra"] = srpm_nevra
        self.update(data)

    def resolve_content_sets(self, lb_instance):
        """
        Find out the content_sets this image uses and store it as
        "content_sets" key in image.
        """
        # Checking only the first repository is OK, because if an image
        # is in multiple repositories, the content_sets of all of them
        # must be the same by definition.
        if "repositories" not in self or len(self["repositories"]) == 0:
            log.warning("Container image %s does not have 'repositories' set "
                        "in Lightblue, this is suspicious.",
                        self["brew"]["build"])
            self.update({"content_sets": []})
            return

        image_content_sets = lb_instance.find_content_sets_for_repository(
            self["repositories"][0]["repository"])
        log.info("Container image %s uses following content sets: %r",
                 self["brew"]["build"], image_content_sets)
        self.update({"content_sets": image_content_sets})


class LightBlue(object):
    """Interface to query lightblue"""

    def __init__(self, server_url, cert, private_key,
                 verify_ssl=None,
                 entity_versions=None):
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
        if verify_ssl is None:
            self.verify_ssl = True
        else:
            assert isinstance(verify_ssl, bool)
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
        """Make request to lightblue"""

        entity_url = '{}/{}'.format(self.api_root, entity)
        response = requests.post(entity_url,
                                 data=json.dumps(data),
                                 verify=self.verify_ssl,
                                 cert=(self.cert, self.private_key),
                                 headers={'Content-Type': 'application/json'})
        self._raise_expcetion_if_errors_returned(response)
        return response.json()

    def _raise_expcetion_if_errors_returned(self, response):
        """Raise exception when response contains errors

        :param dict response: the response returned from LightBlue, which is
            actually the requests response object.
        :raises LightBlueSystemError or LightBlueRequestError: if response
            status code is not 200. Otherwise, just keep silient.
        """
        status_code = response.status_code

        if status_code == http_client.OK:
            return

        if status_code in (http_client.NOT_FOUND,
                           http_client.INTERNAL_SERVER_ERROR,
                           http_client.UNAUTHORIZED):
            raise LightBlueSystemError(status_code, response.content)

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
        for image_data in response['processed']:
            image = ContainerImage()
            image.update(image_data)
            images.append(image)
        return images

    def find_repositories_with_content_sets(self,
                                            content_sets,
                                            published=True,
                                            deprecated=False,
                                            release_category="Generally Available"):
        """Query lightblue and find containerRepositories which have content
        from at least one of the content_sets. By default ignore unpublished,
        deprecated repos or non-GA repositories

        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages
        :param bool published: whether to limit queries to published
            repositories
        :param bool deprecated: set to True to limit results to deprecated
            repositories
        :param str release_category: filter only repositories with specific
            release category (options: Deprecated, Generally Available, Beta, Tech Preview)
        """
        repo_request = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "$or": [{
                            "field": "content_sets.*",
                            "op": "=",
                            "rvalue": c
                        } for c in content_sets]
                    },
                    {
                        "field": "published",
                        "op": "=",
                        "rvalue": published
                    },
                    {
                        "field": "deprecated",
                        "op": "=",
                        "rvalue": deprecated
                    },
                    {
                        "field": "release_categories.*",
                        "op": "=",
                        "rvalue": release_category
                    }
                ]
            },
            "projection": [
                {"field": "repository", "include": True},
                {"field": "content_sets", "include": True, "recursive": True}
            ]
        }
        return self.find_container_repositories(repo_request)

    def find_content_sets_for_repository(self,
                                         repository,
                                         published=True,
                                         deprecated=False,
                                         release_category="Generally Available"):
        """
        Query lightblue and find content sets which are used for Container
        image in repository `repository`

        :param str repository: name of the repository for which the content
            sets will be returned
        :param bool published: whether to limit queries to published
            repositories
        :param bool deprecated: set to True to limit results to deprecated
            repositories
        :param str release_category: filter only repositories with specific
            release category (options: Deprecated, Generally Available, Beta, Tech Preview)
        :return: list of found content sets, each of which is content set name.
            Empty list is returned if no repository is found.
        :rtype: list
        """
        repo_request = {
            "objectType": "containerRepository",
            "query": {
                "$and": [
                    {
                        "field": "repository",
                        "op": "=",
                        "rvalue": repository
                    },
                    {
                        "field": "published",
                        "op": "=",
                        "rvalue": published
                    },
                    {
                        "field": "deprecated",
                        "op": "=",
                        "rvalue": deprecated
                    },
                    {
                        "field": "release_categories.*",
                        "op": "=",
                        "rvalue": release_category
                    }
                ]
            },
            "projection": [
                {"field": "content_sets", "include": True, "recursive": True}
            ]
        }
        repos = self.find_container_repositories(repo_request)
        if not repos:
            return []

        ret = set()
        for repo in repos:
            ret |= set(repo["content_sets"])

        return sorted(list(ret))

    def _get_default_projection(self):
        return [
            {"field": "brew", "include": True, "recursive": True},
            {"field": "parsed_data.files", "include": True, "recursive": True},
            {"field": "rpm_manifest.*.rpms.*.srpm_nevra", "include": True, "recursive": True},
            {"field": "rpm_manifest.*.rpms.*.srpm_name", "include": True, "recursive": True},
            {"field": "parsed_data.layers.*", "include": True, "recursive": True},
            {"field": "repositories.*.published", "include": True, "recursive": True},
            {"field": "repositories.*.repository", "include": True, "recursive": True},
        ]

    def find_images_with_included_srpm(self, repositories, srpm_name,
                                       published=True):

        """Query lightblue and find containerImages in given
        containerRepositories. By default limit only to images which have been
        published to at least one repository and images which have latest tag.

        :param dict repositories: dictionary with repository names to look inside
        :param str srpm_name: srpm_name (source rpm name) to look for
        :param bool published: whether to limit queries to images with at least
            one published repository
        """
        image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "$or": [{
                            "field": "repositories.*.repository",
                            "op": "=",
                            "rvalue": r['repository']
                        } for r in repositories]
                    },
                    {
                        "field": "repositories.*.published",
                        "op": "=",
                        "rvalue": published
                    },
                    {
                        "field": "repositories.*.tags.*.name",
                        "op": "=",
                        "rvalue": "latest"
                    },
                    {
                        "field": "rpm_manifest.*.rpms.*.srpm_name",
                        "op": "=",
                        "rvalue": srpm_name
                    },
                    {
                        "field": "parsed_data.files.*.key",
                        "op": "=",
                        "rvalue": "buildfile"
                    }
                ]
            },
            "projection": self._get_default_projection()
        }
        return self.find_container_images(image_request)

    def find_unpublished_image_for_build(self, build):
        """
        Returns the unpublished variant of Docker image specified by `build`
        Brew build N-V-R.

        :param str build: Brew build N-V-R.
        :return: Unpublished container image.
        :rtype: ContainerImage.
        """
        image_request = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "field": "brew.build",
                        "op": "=",
                        "rvalue": build
                    },
                    {
                        "$or": [
                            {
                                "field": "repositories.*.published",
                                "op": "=",
                                "rvalue": False
                            },
                            {
                                "field": "repositories#",
                                "op": "=",
                                "rvalue": 0
                            }
                        ]
                    }
                ]
            },
            "projection": self._get_default_projection()
        }
        images = self.find_container_images(image_request)
        if not images:
            return None
        return images[0]

    def get_image_by_layer(self, top_layer, build_layers_count,
                           srpm_name=None):
        """
        Find parent image by layer from either published repository or not

        :param str top_layer: the hash string representing an built image,
            which is usually the top layer in ``parsed_data.layers`` list.
        :param int build_layers_count: the number of build layers an image has.
        :param str srpm_name: name of the package. it is optional. if
            specified, will find image that also contains this package.

        :return: parent ContainerImage object. None is returned if no image is
            found.
        :rtype: ContainerImage
        """
        query = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "field": "parsed_data.layers#",
                        "op": "$eq",
                        "rvalue": build_layers_count
                    },
                    {
                        "field": "parsed_data.layers.*",
                        "op": "$eq",
                        "rvalue": top_layer
                    },
                ],
            },
            "projection": self._get_default_projection()
        }
        if srpm_name:
            query['query']['$and'].append({
                "field": "rpm_manifest.*.rpms.*.srpm_name",
                "op": "=",
                "rvalue": srpm_name
            })

        images = self.find_container_images(query)
        if not images:
            return None
        for image in images:
            # we should prefer published image
            if 'repositories' in image:
                for repository in image['repositories']:
                    if repository['published']:
                        return image

        return images[0]

    def find_parent_images_with_package(self, srpm_name, layers):
        """
        Returns the chain of all parent images of the image with
        parsed_data.layers `layers` which contain the package `srpm_name`
        in their RPM manifest.

        The first item in the list is direct parent of the image in question.
        The last item in the list is the top level parent of the image in
        question.

        Docker images are layered and those layers are identified by its
        checksum in the ContainerImage["parsed_data"]["layers"] list.
        The first layer defined there is the layer defining the image
        itself, the second layer is the layer defining its parent, and so on.

        To find the parent image P of image X, we therefore have to search for
        an image which has P.parsed_data.layers[0] equal to
        X.parsed_data.layers[1]. However, query like this is not possible, so
        we search for any image containing the layer X.parsed_data.layers[1],
        but further limit the query to return only image which have the count
        of the layers equal to `build_layers_count`. For example, layers of an
        image

        [
           "sha256:3341bdf...b8e36168", <- layer of this image
           "sha256:5fc16d0...0e4e587e", <- probably the first parent image A
           "sha256:5d181d2...e6ad6992",
           "sha256:274f5cd...ff8fd6e7", <- parent image of parent image A
           "sha256:3ca89ba...b0ecae0e",
           "sha256:77ed333...a44a147a",
           "sha256:e2ec004...4c1fc873"
        ]

        Parent images will be retrieved though these layers from top to bottom.
        """
        images = []

        for idx, parent_top_layer in enumerate(layers[1:]):
            # `len(layers) - 1 - idx`. We decrement 1, because we skip the
            # first layer in for loop.
            parent_build_layers_count = len(layers) - 1 - idx
            image = self.get_image_by_layer(parent_top_layer,
                                            parent_build_layers_count,
                                            srpm_name=srpm_name)
            if image:
                image.resolve_content_sets(self)
                image.resolve_commit(srpm_name)

            if images:
                if image:
                    images[-1]['parent'] = image
                else:
                    # If we did not find the parent image with the package,
                    # We still want to set the parent of the last image with
                    # the package so we know against which image it has been
                    # built.
                    parent = self.get_image_by_layer(parent_top_layer,
                                                     parent_build_layers_count)

                    children_image_layers_count = parent_build_layers_count + 1
                    if parent is None and children_image_layers_count != 2:
                        err = "Cannot find parent of image %s with layer %s " \
                            "and layer count %d in Lightblue, Lightblue data " \
                            "is probably incomplete" % (
                                image['brew']['build'], parent_top_layer,
                              parent_build_layers_count)
                        log.error(err)
                        if not images[-1]['error']:
                            images[-1]['error'] = err

                    if parent:
                        parent.resolve_content_sets(self)
                        parent.resolve_commit(srpm_name)
                    images[-1]['parent'] = parent
            if not image:
                return images
            images.append(image)

    def find_images_with_package_from_content_set(
            self, srpm_name, content_sets, published=True, deprecated=False,
            release_category="Generally Available", filter_fnc=None):
        """Query lightblue and find containers which contain given
        package from one of content sets

        :param str srpm_name: srpm_name (source rpm name) to look for
        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages
        :param function filter_fnc: Function called as
            filter_fnc(container_image) with container_image being
            ContainerImage instance. If this function returns True, the image
            will not be considered for a rebuild as well as its parent images.
            This function is used to filter out images not allowed by
            Freshmaker configuration.

        :return: a list of dictionaries with three keys - repository, commit and
            srpm_nevra. Repository is a name git repository including the
            namespace. Commit is a git ref - usually a git commit
            hash. srpm_nevra is whole NEVRA of source rpm that is included in
            the given image - can be used for comparisons if needed
        :rtype: list
        """
        repos = self.find_repositories_with_content_sets(content_sets,
                                                         published=published,
                                                         deprecated=deprecated,
                                                         release_category=release_category)
        if not repos:
            return []
        images = self.find_images_with_included_srpm(repos,
                                                     srpm_name,
                                                     published=published)

        # Filter out images based on the filter_fnc.
        if filter_fnc:
            images = [image for image in images if not filter_fnc(image)]

        for image in images:
            image.resolve_content_sets(self)
            image.resolve_commit(srpm_name)
        return images

    def find_images_to_rebuild(
            self, srpm_name, content_sets, published=True, deprecated=False,
            release_category="Generally Available", filter_fnc=None):
        """
        Find images to rebuild through image build layers

        Returns the list of sub-lists in which each sub-list contains
        ContainerImage instances which can be built in parallel. Sub-list N+1
        contains images which depend on images from sub-list N, so building any
        image from N+1 must happen *after* all of the images from sub-list N
        have been rebuilt.

        :param str srpm_name: srpm_name (source rpm name) to look for
        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages
        :param function filter_fnc: Function called as
            filter_fnc(container_image) with container_image being
            ContainerImage instance. If this function returns True, the image
            will not be considered for a rebuild as well as its parent images.
            This function is used to filter out images not allowed by
            Freshmaker configuration.
        """
        images = self.find_images_with_package_from_content_set(
            srpm_name, content_sets, published, deprecated, release_category,
            filter_fnc=filter_fnc)

        def _get_images_to_rebuild(image):
            """
            Find out parent images to rebuild, helper called from threadpool.
            """
            unpublished = self.find_unpublished_image_for_build(
                image['brew']['build'])
            if not unpublished:
                return []

            layers = unpublished["parsed_data"]["layers"]
            rebuild_list = self.find_parent_images_with_package(
                srpm_name, layers)
            if rebuild_list:
                image['parent'] = rebuild_list[0]
            else:
                parent = self.get_image_by_layer(layers[1], len(layers) - 1)
                if parent:
                    parent.resolve_content_sets(self)
                    parent.resolve_commit(srpm_name)
                elif len(layers) != 2:
                    err = "Cannot find parent of image %s with layer %s " \
                          "and layer count %d in Lightblue, Lightblue data " \
                          "is probably incomplete" % (
                              image['brew']['build'], layers[1],
                              len(layers) - 1)
                    log.error(err)
                    if not image['error']:
                        image['error'] = err
                image['parent'] = parent
            rebuild_list.insert(0, image)
            return rebuild_list

        # For every image, find out all its parent images which contain the
        # srpm_name package and store these lists to to_rebuild.
        to_rebuild = []
        max_len = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_get_images_to_rebuild, i): i
                       for i in images}
            concurrent.futures.wait(futures)
            for future in futures:
                rebuild_list = future.result()
                max_len = max(len(rebuild_list), max_len)
                to_rebuild.append(rebuild_list)

        # The to_rebuild list now contains all the images which need to be
        # rebuilt, but there are lot of duplicates there - for example for
        # every RHSCL Docker image, there is s2i-base image (their shared
        # parent image).
        # Therefore, group the same parent images from the same inheritance
        # level to not build them multiple times for each image, but just once.

        # Using dict for each batch to remove duplicate images
        batches = [{} for i in range(max_len)]
        for image_rebuild_list in to_rebuild:
            for image, batch in zip(reversed(image_rebuild_list), batches):
                image_key = '{0}_{1}'.format(image['repository'],
                                             image['commit'])
                if image_key not in batch:
                    batch[image_key] = image

        # Final step to convert batches to list of sub-lists
        # Each sublist contains images in this order
        # [found image containing signed RPMs, parent, grandparent, ...]
        batches = [batch.values() for batch in batches]
        return batches
