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


import flask
import unittest

from mock import patch, Mock

import freshmaker.auth

from freshmaker.auth import init_auth
from freshmaker.auth import load_krb_user_from_request
from freshmaker.auth import load_openidc_user
from freshmaker.auth import query_ldap_groups
from freshmaker.errors import Unauthorized
from freshmaker import app, db
from freshmaker.models import User


class TestLoadKrbUserFromRequest(unittest.TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.user = User(username='tester1')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.auth.query_ldap_groups')
    def test_create_new_user(self, query_ldap_groups):
        query_ldap_groups.return_value = ['devel', 'admins']

        environ_base = {
            'REMOTE_USER': 'newuser@EXAMPLE.COM'
        }

        with app.test_request_context(environ_base=environ_base):
            load_krb_user_from_request(flask.request)

            expected_user = db.session.query(User).filter(
                User.username == 'newuser')[0]

            self.assertEqual(expected_user.id, flask.g.user.id)
            self.assertEqual(expected_user.username, flask.g.user.username)

            # Ensure user's groups are created
            self.assertEqual(2, len(flask.g.groups))
            self.assertEqual(['admins', 'devel'], sorted(flask.g.groups))

    @patch('freshmaker.auth.query_ldap_groups')
    def test_return_existing_user(self, query_ldap_groups):
        query_ldap_groups.return_value = ['devel', 'admins']
        original_users_count = db.session.query(User.id).count()

        environ_base = {
            'REMOTE_USER': '{0}@EXAMPLE.COM'.format(self.user.username)
        }

        with app.test_request_context(environ_base=environ_base):
            load_krb_user_from_request(flask.request)

            self.assertEqual(original_users_count,
                             db.session.query(User.id).count())
            self.assertEqual(self.user.id, flask.g.user.id)
            self.assertEqual(self.user.username, flask.g.user.username)
            self.assertEqual(['admins', 'devel'], sorted(flask.g.groups))

    def test_401_if_remote_user_not_present(self):
        with app.test_request_context():
            with self.assertRaises(Unauthorized) as ctx:
                load_krb_user_from_request(flask.request)
            self.assertTrue(
                'REMOTE_USER is not present in request.' in ctx.exception.args)


class TestLoadOpenIDCUserFromRequest(unittest.TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.user = User(username='tester1')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.auth.requests.get')
    def test_create_new_user(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'groups': ['tester', 'admin'],
            'name': 'new_user',
        }

        environ_base = {
            'REMOTE_USER': 'new_user',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }

        with app.test_request_context(environ_base=environ_base):
            load_openidc_user(flask.request)

            new_user = db.session.query(User).filter(
                User.username == 'new_user')[0]

            self.assertEqual(new_user, flask.g.user)
            self.assertEqual('new_user', flask.g.user.username)
            self.assertEqual(sorted(['admin', 'tester']),
                             sorted(flask.g.groups))

    @patch('freshmaker.auth.requests.get')
    def test_return_existing_user(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'groups': ['testers', 'admins'],
            'name': self.user.username,
        }

        environ_base = {
            'REMOTE_USER': self.user.username,
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }

        with app.test_request_context(environ_base=environ_base):
            original_users_count = db.session.query(User.id).count()

            load_openidc_user(flask.request)

            users_count = db.session.query(User.id).count()
            self.assertEqual(original_users_count, users_count)

            # Ensure existing user is set in g
            self.assertEqual(self.user.id, flask.g.user.id)
            self.assertEqual(['admins', 'testers'], sorted(flask.g.groups))

    def test_401_if_remote_user_not_present(self):
        environ_base = {
            # Missing REMOTE_USER here
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user, flask.request)

    def test_401_if_access_token_not_present(self):
        environ_base = {
            'REMOTE_USER': 'tester1',
            # Missing OIDC_access_token here
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user, flask.request)

    def test_401_if_scope_not_present(self):
        environ_base = {
            'REMOTE_USER': 'tester1',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            # Missing OIDC_CLAIM_scope here
        }
        with app.test_request_context(environ_base=environ_base):
            self.assertRaises(Unauthorized, load_openidc_user, flask.request)

    def test_401_if_required_scope_not_present_in_token_scope(self):
        environ_base = {
            'REMOTE_USER': 'new_user',
            'OIDC_access_token': '39283',
            'OIDC_CLAIM_iss': 'https://iddev.fedorainfracloud.org/openidc/',
            'OIDC_CLAIM_scope': 'openid https://id.fedoraproject.org/scope/groups',
        }

        with patch.object(freshmaker.auth.conf,
                          'auth_openidc_required_scopes', ['new-compose']):
            with app.test_request_context(environ_base=environ_base):
                with self.assertRaises(Unauthorized) as ctx:
                    load_openidc_user(flask.request)
                self.assertTrue(
                    'Required OIDC scope new-compose not present.' in
                    ctx.exception.args)


class TestQueryLdapGroups(unittest.TestCase):
    """Test auth.query_ldap_groups"""

    @patch('freshmaker.auth.ldap.initialize')
    def test_get_groups(self, initialize):
        initialize.return_value.search_s.return_value = [
            ('cn=odcsdev,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['5523'], 'cn': ['odcsdev']}),
            ('cn=freshmakerdev,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['17861'], 'cn': ['freshmakerdev']}),
            ('cn=devel,ou=Groups,dc=example,dc=com',
             {'gidNumber': ['5781'], 'cn': ['devel']})
        ]

        groups = query_ldap_groups('me')
        self.assertEqual(sorted(['odcsdev', 'freshmakerdev', 'devel']),
                         sorted(groups))


class TestInitAuth(unittest.TestCase):
    """Test init_auth"""

    def setUp(self):
        self.login_manager = Mock()

    def test_select_kerberos_auth_backend(self):
        init_auth(self.login_manager, 'kerberos')
        self.login_manager.request_loader.assert_called_once_with(
            load_krb_user_from_request)

    def test_select_openidc_auth_backend(self):
        init_auth(self.login_manager, 'openidc')
        self.login_manager.request_loader.assert_called_once_with(
            load_openidc_user)

    def test_not_use_auth_backend(self):
        init_auth(self.login_manager, 'noauth')
        self.login_manager.request_loader.assert_not_called()

    def test_error_if_select_an_unknown_backend(self):
        self.assertRaises(ValueError, init_auth, self.login_manager, 'xxx')
        self.assertRaises(ValueError, init_auth, self.login_manager, '')
        self.assertRaises(ValueError, init_auth, self.login_manager, None)

    def test_init_auth_no_ldap_server(self):
        with patch.object(freshmaker.auth.conf, 'auth_ldap_server', ''):
            self.assertRaises(ValueError, init_auth, self.login_manager,
                              'kerberos')

    def test_init_auths_no_ldap_group_base(self):
        with patch.object(freshmaker.auth.conf, 'auth_ldap_group_base', ''):
            self.assertRaises(ValueError, init_auth, self.login_manager,
                              'kerberos')
