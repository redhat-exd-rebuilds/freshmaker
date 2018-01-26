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
#
# Written by Chenxiong Qi <cqi@redhat.com>

import six

from mock import patch
from odcs.client.odcs import AuthMech

from freshmaker import conf
from freshmaker.odcsclient import create_odcs_client
from tests import helpers


class TestCreateODCSClient(helpers.FreshmakerTestCase):
    """Test odcsclient.create_odcs_client"""

    @patch.object(conf, 'odcs_auth_mech', new='kerberos')
    @patch('freshmaker.odcsclient.ODCS')
    def test_create_with_kerberos_auth(self, ODCS):
        odcs = create_odcs_client()

        self.assertEqual(ODCS.return_value, odcs)
        ODCS.assert_called_once_with(
            conf.odcs_server_url,
            auth_mech=AuthMech.Kerberos,
            verify_ssl=conf.odcs_verify_ssl)

    @patch.object(conf, 'odcs_auth_mech', new='fas')
    def test_error_if_unsupported_auth_configured(self):
        six.assertRaisesRegex(
            self, ValueError, r'.*fas is not supported yet.',
            create_odcs_client)

    @patch.object(conf, 'odcs_auth_mech', new='openidc')
    @patch.object(conf, 'odcs_openidc_token', new='12345')
    @patch('freshmaker.odcsclient.ODCS')
    def test_create_with_openidc_auth(self, ODCS):
        odcs = create_odcs_client()

        self.assertEqual(ODCS.return_value, odcs)
        ODCS.assert_called_once_with(
            conf.odcs_server_url,
            auth_mech=AuthMech.OpenIDC,
            openidc_token='12345',
            verify_ssl=conf.odcs_verify_ssl)

    @patch.object(conf, 'odcs_auth_mech', new='openidc')
    def test_error_if_missing_openidc_token(self):
        six.assertRaisesRegex(
            self, ValueError, r'Missing OpenIDC token.*',
            create_odcs_client)
