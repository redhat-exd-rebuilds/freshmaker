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

from mock import call, patch

from freshmaker import conf
from freshmaker.pdc import PDC


class TestGetLatestModules(unittest.TestCase):
    """Test PDC.get_latest_modules"""

    @patch('freshmaker.pdc.PDC.get_modules')
    def test_exclude_modules_that_doesnt_depend_on_built_module(self, get_modules):
        get_modules.side_effect = [
            # modules returned from first call
            [{'name': '389-ds', 'stream': '1.2', 'version': '20171009091843'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171012150041'},
             {'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'}],

            # modules returned from call for name 386-ds and stream 1.2
            [{'name': '389-ds', 'stream': '1.2', 'version': '20171009105405'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171012150041'},

             # *** This is a new version module that already depends on other module.
             {'name': '389-ds', 'stream': '1.2', 'version': '20171120124934'}],

            # modules returned from call for name apache-commons and stream f27
            [{'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'}]
        ]

        pdc = PDC(conf)
        modules = pdc.get_latest_modules(build_dep_name='rebuilt module',
                                         build_dep_stream='1.7',
                                         active=True)

        expected_modules = [
            {'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'},
        ]
        self.assertEqual(expected_modules, modules)

    @patch('freshmaker.pdc.PDC.get_modules')
    def test_found_latest_modules(self, get_modules):
        get_modules.side_effect = [
            # modules returned from first call
            [{'name': '389-ds', 'stream': '1.2', 'version': '20171009091843'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171012150041'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171120124934'},
             {'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'}],

            # modules returned from call for name 386-ds and stream 1.2
            [{'name': '389-ds', 'stream': '1.2', 'version': '20171009105405'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171012150041'},
             {'name': '389-ds', 'stream': '1.2', 'version': '20171120124934'}],

            # modules returned from call for name apache-commons and stream f27
            [{'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'}]
        ]

        pdc = PDC(conf)
        modules = pdc.get_latest_modules(build_dep_name='rebuilt module',
                                         build_dep_stream='1.7',
                                         active=True)

        modules = sorted(modules, key=lambda m: m['name'])
        expected_modules = [
            {'name': '389-ds', 'stream': '1.2', 'version': '20171120124934'},
            {'name': 'apache-commons', 'stream': 'f27', 'version': '20171010111836'},
        ]
        self.assertEqual(expected_modules, modules)

        get_modules.assert_has_calls([
            call(build_dep_name='rebuilt module',
                 build_dep_stream='1.7',
                 active=True),
            call(name='389-ds', stream='1.2', active=True),
            call(name='apache-commons', stream='f27', active=True),
        ], any_order=True)
