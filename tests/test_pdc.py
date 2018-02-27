# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import unittest

from mock import patch
from freshmaker import conf
from freshmaker.pdc import PDC


class TestGetLatestModules(unittest.TestCase):
    """Test PDC.get_latest_modules"""

    def mock_is_latest_module(self, module):
        fake_results = {
            '389-ds': True,
            'apache-commons': True,
            'nodejs': False
        }
        return fake_results[module['name']]

    @patch('freshmaker.pdc.PDC.get_modules')
    @patch('freshmaker.pdc.PDC.is_latest_module')
    def test_get_latest_modules(self, is_latest_module, get_modules):
        is_latest_module.side_effect = self.mock_is_latest_module
        get_modules.side_effect = [
            [
                {
                    'uid': '389-ds-1.2-20171120124934',
                    'name': '389-ds',
                    'stream': '1.2',
                    'version': '20171120124934'
                },
                {
                    'uid': '389-ds-1.2-20171012150041',
                    'name': '389-ds',
                    'stream': '1.2',
                    'version': '20171012150041'
                },
                {
                    'uid': '389-ds-1.2-20171009091843',
                    'name': '389-ds',
                    'stream': '1.2',
                    'version': '20171009091843'
                },
                {
                    'uid': 'apache-commons-f27-20171010111836',
                    'name': 'apache-commons',
                    'stream': 'f27',
                    'version': '20171010111836'
                },
                {
                    'uid': 'nodejs:9:20180213214624:c2c572ec',
                    'name': 'nodejs',
                    'stream': '9',
                    'version': '20180213214624'
                },
                {
                    'uid': 'nodejs-9-20180205182158',
                    'name': 'nodejs',
                    'stream': '9',
                    'version': '20180205182158'
                },
            ],
        ]

        pdc = PDC(conf)
        modules = pdc.get_latest_modules(build_dep_name='rebuilt module',
                                         build_dep_stream='1.7',
                                         active=True)
        modules = sorted(modules, key=lambda m: m['name'])

        # Module nodejs should not be included because the its fake data aims
        # to test the nodejs:9:20180213214624:c2c572ec is not latest module.
        expected_modules = [
            {
                'uid': '389-ds-1.2-20171120124934',
                'name': '389-ds',
                'stream': '1.2',
                'version': '20171120124934'
            },
            {
                'uid': 'apache-commons-f27-20171010111836',
                'name': 'apache-commons',
                'stream': 'f27',
                'version': '20171010111836'
            },
        ]
        self.assertEqual(expected_modules, modules)
