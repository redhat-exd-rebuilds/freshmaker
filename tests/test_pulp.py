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

import unittest

from mock import patch

from freshmaker.pulp import Pulp


class TestPulp(unittest.TestCase):
    """Test interface to Pulp"""

    def setUp(self):
        self.server_url = 'http://localhost/'
        self.username = 'qa'
        self.password = 'qa'

    @patch('freshmaker.pulp.requests.get')
    def test_query_content_set_by_repo_id(self, get):
        get.return_value.json.return_value = {
            'id': 'rhel-7-desktop-debug-rpms__7Client__x86_64',
            '_ns': 'repos',
            'content_unit_counts': {
                'erratum': 1420,
                'rpm': 4773
            },
            '_id': {
                '$oid': '5384ee687bc9f619942a8b47'
            },
            'last_unit_added': '2017-06-02T15:01:06Z',
            'notes': {
                'arch': 'x86_64',
                'content_set': 'rhel-7-desktop-debug-rpms',
                'platform_full_version': '7',
            },
            'display_name': 'rhel-7-desktop-debug-rpms__7Client__x86_64',
            'description': None,
        }

        pulp = Pulp(self.server_url, username=self.username, password=self.password)
        repo_id = 'rhel-7-desktop-debug-rpms__7Client__x86_64'
        content_set = pulp.get_content_set_by_repo_id(repo_id)

        get.assert_called_once_with(
            '{}pulp/api/v2/repositories/{}/'.format(self.server_url, repo_id),
            auth=(self.username, self.password))

        self.assertEqual('rhel-7-desktop-debug-rpms', content_set)
