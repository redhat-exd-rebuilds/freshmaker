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
import requests
import json

from six.moves import http_client


class LightBlueRequestFailure(Exception):
    """Exception when fail to request from LightBlue"""

    def __init__(self, json_response, status_code):
        """Initialize

        :param dict json_response: the JSON data returned from LightBlue
            which contains all error information.
        :param int status_code: repsonse status code
        """
        self._raw = json_response
        self._status_code = status_code

    def __repr__(self):
        return '<{} [{}]>'.format(self.__class__.__name__, self.status_code)

    def __str__(self):
        return 'Error{} ({}):\n{}'.format(
            's' if len(self.errors) > 1 else '',
            len(self.errors),
            '\n'.join(('    {}'.format(err['msg']) for err in self.errors))
        )

    @property
    def raw(self):
        return self._raw

    @property
    def errors(self):
        return self.raw['errors']

    @property
    def status_code(self):
        return self._status_code


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
        self.api_root = '{}/rest/data'.format(server_url)
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
        :raises LightBlueRequestFailure: if response status code is not 200.
            Otherwise, just keep silient.
        """
        if response.status_code == http_client.OK:
            return
        raise LightBlueRequestFailure(response.json(), response.status_code)

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
            self._get_entity_version('entityRespository'))
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
            "projection": [
                {"field": "brew", "include": True, "recursive": True},
                {"field": "parsed_data.files", "include": True, "recursive": True},
                {"field": "parsed_data.rpm_manifest.*.srpm_nevra", "include": True, "recursive": True},
                {"field": "parsed_data.rpm_manifest.*.srpm_name", "include": True, "recursive": True}
            ]
        }
        return self.find_container_images(image_request)

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
                print(rpm)
                if rpm["srpm_name"] == srpm_name:
                    srpm_nevra = rpm['srpm_nevra']
                    break

            dockerfile, _, commit = dockerfile_url.partition("?id=")
            _, _, reponame = dockerfile.partition("/cgit/")
            reponame = reponame.replace("/plain/Dockerfile", "")
            commits.append({"repository": reponame,
                            "commit": commit,
                            "srpm_nevra": srpm_nevra})
        return commits
