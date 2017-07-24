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

from six.moves import http_client


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


class ContainerRepository(dict):
    """Represent a container repository"""

    @classmethod
    def create(cls, data):
        repo = cls()
        repo.update(data)
        return repo


class ContainerImage(dict):
    """Represent a container image"""

    @classmethod
    def create(cls, data):
        image = cls()
        image.update(data)
        return image


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

    def _get_default_projection(self):
        return [
            {"field": "brew", "include": True, "recursive": True},
            {"field": "parsed_data.files", "include": True, "recursive": True},
            {"field": "parsed_data.rpm_manifest.*.srpm_nevra", "include": True, "recursive": True},
            {"field": "parsed_data.rpm_manifest.*.srpm_name", "include": True, "recursive": True},
            {"field": "parsed_data.layers.*", "include": True, "recursive": True},
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
                        "field": "parsed_data.rpm_manifest.*.srpm_name",
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

    def get_parent_image_with_package(
            self, srpm_name, top_layer, expected_layer_count):
        """
        Find parent image by layers.

        Docker images are layered and those layers are identified by its
        checksum in the ContainerImage["parsed_data"]["layers"] list.
        The first layer defined there is the layer defining the image
        itself, the second layer is the layer defining its parent, and so on.

        To find the parent image P of image X, we therefore have to search for
        an image which has P.parsed_data.layers[0] equal to
        X.parsed_data.layers[1]. However, query like this is not possible, so
        we search for any image containing the layer X.parsed_data.layers[1],
        but further limit the query to return only image which have the count
        of the layers equal to `expected_layer_count`.

        :param srpm_name str: Name of the package which should be included in
            the rpm manifest of returned image.
        :param top_layer str: parent's top most layer (parsed_data.layers[1]).
        :param expected_layer_count str: parent should has one less layer
            than child (len(parsed_data.layers) - 1)
        :return: parent ContainerImage object
        :rtype: ContainerImage
        """
        query = {
            "objectType": "containerImage",
            "query": {
                "$and": [
                    {
                        "field": "parsed_data.layers#",
                        "op": "$eq",
                        "rvalue": expected_layer_count
                    },
                    {
                        "field": "parsed_data.layers.*",
                        "op": "$eq",
                        "rvalue": top_layer
                    },
                    {
                        "field": "parsed_data.rpm_manifest.*.srpm_name",
                        "op": "=",
                        "rvalue": srpm_name
                    },
                ],
            },
            "projection": self._get_default_projection()
        }

        images = self.find_container_images(query)
        if not images:
            return None
        return images[0]

    def find_parent_images_with_package(self, srpm_name, layers):
        """
        Returns the chain of all parent images of the image with
        parsed_data.layers `layers` which contain the package `srpm_name`
        in their RPM manifest.

        The first item in the list is direct parent of the image in question.
        The last item in the list is the top level parent of the image in
        question.
        """
        images = []

        for idx, layer in enumerate(layers[1:]):
            # `len(layers) - 1 - idx`. We decrement 1, because we skip the
            # first layer in for loop.
            image = self.get_parent_image_with_package(
                srpm_name, layer, len(layers) - 1 - idx)
            if not image:
                return images
            images.append(image)

    def find_images_with_package_from_content_set(
            self, srpm_name, content_sets, published=True, deprecated=False,
            release_category="Generally Available"):
        """Query lightblue and find containers which contain given
        package from one of content sets

        :param str srpm_name: srpm_name (source rpm name) to look for
        :param list content_sets: list of strings (content sets) to consider
            when looking for the packages

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
        commits = []
        for image in images:
            for f in image["parsed_data"]["files"]:
                if f['key'] == 'buildfile':
                    dockerfile_url = f['content_url']
                    break

            for rpm in image["parsed_data"]["rpm_manifest"]:
                if rpm["srpm_name"] == srpm_name:
                    srpm_nevra = rpm['srpm_nevra']
                    break

            dockerfile, _, commit = dockerfile_url.partition("?id=")
            _, _, reponame = dockerfile.partition("/cgit/")
            reponame = reponame.replace("/plain/Dockerfile", "")
            commits.append({"repository": reponame,
                            "commit": commit,
                            "srpm_nevra": srpm_nevra,
                            "brew": image["brew"]})
        return commits
