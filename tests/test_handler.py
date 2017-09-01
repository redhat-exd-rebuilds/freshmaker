# -*- coding: utf-8 -*-
#
# Copyright (c) 2017  Red Hat, Inc.
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
#
# Written by Chenxiong Qi <cqi@redhat.com>


from mock import patch
from unittest import TestCase

from freshmaker.handlers import BaseHandler


class MyHandler(BaseHandler):
    """Handler for running tests to test things defined in BaseHandler"""

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestKrbContextPreparedForBuildContainer(TestCase):
    """Test krb_context for BaseHandler.build_container"""

    def setUp(self):
        self.koji_service = patch('freshmaker.handlers.koji_service')
        self.koji_service.start()

    def tearDown(self):
        self.koji_service.stop()

    @patch('freshmaker.handlers.conf')
    @patch('freshmaker.handlers.krbContext')
    def test_prepare_with_keytab(self, krbContext, conf):
        conf.krb_auth_use_keytab = True
        conf.krb_auth_principal = 'freshmaker/hostname@REALM'
        conf.krb_auth_client_keytab = '/etc/freshmaker.keytab'
        conf.krb_auth_ccache_file = '/tmp/freshmaker_cc'

        handler = MyHandler()
        handler.build_container('image-name', 'f26', '1234')

        krbContext.assert_called_once_with(
            using_keytab=True,
            principal='freshmaker/hostname@REALM',
            keytab_file='/etc/freshmaker.keytab',
            ccache_file='/tmp/freshmaker_cc',
        )

    @patch('freshmaker.handlers.conf')
    @patch('freshmaker.handlers.krbContext')
    def test_prepare_with_normal_user_credential(self, krbContext, conf):
        conf.krb_auth_use_keytab = False
        conf.krb_auth_principal = 'somebody@REALM'
        conf.krb_auth_ccache_file = '/tmp/freshmaker_cc'

        handler = MyHandler()
        handler.build_container('image-name', 'f26', '1234')

        krbContext.assert_called_once_with(
            principal='somebody@REALM',
            ccache_file='/tmp/freshmaker_cc',
        )
