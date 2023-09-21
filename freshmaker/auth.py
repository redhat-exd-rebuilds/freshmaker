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


from functools import wraps
import requests
import ldap
import flask

from flask import g
from flask_login import login_required as _login_required
from werkzeug.exceptions import Unauthorized

from freshmaker import conf, log
from freshmaker.errors import Forbidden
from freshmaker.models import User, commit_on_success


def _validate_kerberos_config():
    """
    Validates the kerberos configuration and raises ValueError in case of
    error.
    """
    errors = []
    if not conf.auth_ldap_server:
        errors.append(
            "kerberos authentication enabled with no LDAP server "
            "configured, check AUTH_LDAP_SERVER in your config."
        )

    if not conf.auth_ldap_user_base:
        errors.append(
            "kerberos authentication enabled with no LDAP user "
            "base configured, check AUTH_LDAP_USER_BASE in your "
            "config."
        )

    if errors:
        for error in errors:
            log.exception(error)
        raise ValueError("Invalid configuration for kerberos authentication.")


@commit_on_success
def load_krb_user_from_request(request):
    """Load Kerberos user from current request

    REMOTE_USER needs to be set in environment variable, that is set by
    frontend Apache authentication module.
    """
    remote_user = request.environ.get("REMOTE_USER")
    if not remote_user:
        raise Unauthorized("REMOTE_USER is not present in request.")

    username, realm = remote_user.split("@")

    user = User.find_user_by_name(username)
    if not user:
        user = User.create_user(username=username)

    try:
        groups = query_ldap_groups(username)
    except ldap.SERVER_DOWN as e:
        log.error("Cannot query groups of %s from LDAP. Error: %s", username, e.args[0]["desc"])
        groups = []

    g.groups = groups
    g.user = user
    return user


@commit_on_success
def load_ssl_user_from_request(request):
    """
    Loads SSL user from current request.

    SSL_CLIENT_VERIFY and SSL_CLIENT_S_DN needs to be set in
    request.environ. This is set by frontend httpd mod_ssl module.
    """
    ssl_client_verify = request.environ.get("SSL_CLIENT_VERIFY")
    if ssl_client_verify != "SUCCESS":
        raise Unauthorized("Cannot verify client: %s" % ssl_client_verify)

    username = request.environ.get("SSL_CLIENT_S_DN")
    if not username:
        raise Unauthorized("Unable to get user information (DN) from client certificate")

    user = User.find_user_by_name(username)
    if not user:
        user = User.create_user(username=username)

    g.groups = []
    g.user = user
    return user


def load_krb_or_ssl_user_from_request(request):
    """
    Loads User using Kerberos or SSL auth.
    """
    if request.environ.get("REMOTE_USER"):
        return load_krb_user_from_request(request)
    else:
        return load_ssl_user_from_request(request)


def query_ldap_groups(uid):
    """
    Get the user's LDAP groups.

    :param str uid: the user's uid LDAP attribute
    :return: a set of distinguished names representing the user's group membership
    :rtype: set
    """
    client = ldap.initialize(conf.auth_ldap_server)
    users = client.search_s(
        conf.auth_ldap_user_base,
        ldap.SCOPE_ONELEVEL,
        attrlist=["memberOf"],
        filterstr=f"(&(uid={uid})(objectClass=posixAccount))",
    )

    group_distinguished_names = set()
    if users:
        # users will only contain one entry if the user exists in the LDAP directory
        # since the LDAP filter is limited to a single user.
        _, user_attributes = users[0]
        group_distinguished_names = {
            # The value of group is the entire distinguished name of the group
            group.decode("utf-8")
            for group in user_attributes.get("memberOf", [])
        }

    return group_distinguished_names


@commit_on_success
def load_openidc_user(request):
    """Load FAS user from current request"""
    username = request.environ.get("REMOTE_USER")
    if not username:
        raise Unauthorized("REMOTE_USER is not present in request.")

    token = request.environ.get("OIDC_access_token")
    if not token:
        raise Unauthorized("Missing token passed to Freshmaker.")

    scope = request.environ.get("OIDC_CLAIM_scope")
    if not scope:
        raise Unauthorized("Missing OIDC_CLAIM_scope.")
    validate_scopes(scope)

    user_info = get_user_info(token)

    user = User.find_user_by_name(username)
    if not user:
        user = User.create_user(username=username)

    g.groups = user_info.get("groups", [])
    g.user = user
    g.oidc_scopes = scope.split(" ")
    return user


def validate_scopes(scope):
    """Validate if request scopes are all in required scope

    :param str scope: scope passed in from.
    :raises: Unauthorized if any of required scopes is not present.
    """
    scopes = scope.split(" ")
    required_scopes = conf.auth_openidc_required_scopes
    for scope in required_scopes:
        if scope not in scopes:
            raise Unauthorized("Required OIDC scope {0} not present.".format(scope))


def require_oidc_scope(scope):
    """Check if required scopes is in OIDC scopes within request"""
    full_scope = "{0}{1}".format(conf.oidc_base_namespace, scope)
    if conf.auth_backend == "openidc" and full_scope not in g.oidc_scopes:
        message = "Request does not have required scope %s" % scope
        log.error(message)
        raise Forbidden(message)


def require_scopes(*scopes):
    """Check if required scopes is in OIDC scopes within request"""

    def wrapper(f):
        @wraps(f)
        def decorator(*args, **kwargs):
            for scope in scopes:
                require_oidc_scope(scope)
            return f(*args, **kwargs)

        return decorator

    return wrapper


def get_user_info(token):
    """Query FAS groups from Fedora"""
    headers = {"authorization": "Bearer {0}".format(token)}
    r = requests.get(conf.auth_openidc_userinfo_uri, headers=headers, timeout=conf.requests_timeout)
    if r.status_code != 200:
        raise Unauthorized(
            "Cannot get user information from {0} endpoint.".format(conf.auth_openidc_userinfo_uri)
        )

    return r.json()


def init_auth(login_manager, backend):
    """Initialize authentication backend

    Enable and initialize authentication backend to work with frontend
    authentication module running in Apache.
    """
    if backend == "noauth":
        # Do not enable any authentication backend working with frontend
        # authentication module in Apache.
        log.warning("Authorization is disabled in Freshmaker configuration.")
        return
    if backend == "kerberos":
        _validate_kerberos_config()
        global load_krb_user_from_request
        load_krb_user_from_request = login_manager.request_loader(load_krb_user_from_request)
    elif backend == "openidc":
        global load_openidc_user
        load_openidc_user = login_manager.request_loader(load_openidc_user)
    elif backend == "kerberos_or_ssl":
        _validate_kerberos_config()
        global load_krb_or_ssl_user_from_request
        load_krb_or_ssl_user_from_request = login_manager.request_loader(
            load_krb_or_ssl_user_from_request
        )
    elif backend == "ssl":
        global load_ssl_user_from_request
        load_ssl_user_from_request = login_manager.request_loader(load_ssl_user_from_request)
    else:
        raise ValueError("Unknown backend name {0}.".format(backend))


def user_has_role(role):
    """
    Check if the current user has the role.

    :param str role: the role to check
    :return: a boolean determining if the user has the role
    :rtype: bool
    """
    if conf.auth_backend == "noauth":
        return True

    groups = conf.permissions[role]["groups"]
    users = conf.permissions[role]["users"]
    in_groups = bool(set(flask.g.groups) & set(groups))
    in_users = flask.g.user.username in users
    return in_groups or in_users


def requires_roles(roles):
    """
    Assert the user has one of the required roles.

    :param list roles: the list of role names to verify
    :raises freshmaker.errors.Forbidden: if the user is not in the role
    """

    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if any(user_has_role(role) for role in roles):
                return f(*args, **kwargs)

            raise Forbidden(
                f"User {flask.g.user.username} does not have any of the following "
                f'roles: {", ".join(roles)}'
            )

        return wrapped

    return wrapper


def login_required(f):
    """
    Wrapper of flask_login's login_required to ingore auth check when auth
    backend is 'noauth'.
    """

    @wraps(f)
    def wrapped(*args, **kwargs):
        if conf.auth_backend == "noauth":
            return f(*args, **kwargs)
        return _login_required(f)(*args, **kwargs)

    return wrapped
