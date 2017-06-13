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
import requests


class Pulp(object):
    """Interface to Pulp"""

    def __init__(self, server_url, username, password):
        self.username = username
        self.password = password
        self.server_url = server_url
        self.rest_api_root = '{0}/pulp/api/v2/'.format(self.server_url.rstrip('/'))

    def _rest_post(self, endpoint, post_data):
        r = requests.post(
            '{0}{1}'.format(self.rest_api_root, endpoint.lstrip('/')),
            post_data,
            auth=(self.username, self.password))
        r.raise_for_status()
        return r.json()

    def get_content_set_by_repo_ids(self, repo_ids):
        """Get content_sets by repository IDs

        :param list repo_ids: list of repository IDs.
        :return: list of names of content_sets.
        :rtype: list
        """
        query_data = {
            'criteria': {
                'filters': {
                    'id': {'$in': repo_ids},
                },
                'fields': ['notes.content_set'],
            }
        }
        repos = self._rest_post('repositories/search/', json.dumps(query_data))
        return [repo['notes']['content_set'] for repo in repos
                if 'content_set' in repo['notes']]
