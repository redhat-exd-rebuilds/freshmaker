# -*- coding: utf-8 -*-

# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Petr Šabata <contyk@redhat.com>
#            Filip Valder <fvalder@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

import imp
import os
import threading

from os import sys
from freshmaker import logger


def any_(*rules):
    """
    Returns list of rules which can be used in HANDLER_MODULE_WHITELIST
    or HANDLER_MODULE_BLACKLIST and is later evaluated as "matched" if *any*
    rule from the `rules` matches.

    :param rules: Each rule is a dict in the same format as other
        dicts in the HANDLER_MODULE_WHITELIST or HANDLER_MODULE_BLACKLIST.
    """
    return ["any", [rule for rule in rules]]


def all_(*rules):
    """
    Returns list of rules which can be used in HANDLER_MODULE_WHITELIST
    or HANDLER_MODULE_BLACKLIST and is later evaluated as "matched" if *all*
    rules from the `rules` matches.

    :param rules: Each rule is a dict in the same format as other
        dicts in the HANDLER_MODULE_WHITELIST or HANDLER_MODULE_BLACKLIST.
    """
    return ["all", [rule for rule in rules]]


def init_config(app):
    """
    Configure Freshmaker
    """
    config_module = None
    config_file = '/etc/freshmaker/config.py'
    config_section = 'DevConfiguration'

    # automagically detect production environment:
    #   - existing and readable config_file presets ProdConfiguration
    if os.path.exists(config_file) and os.access(config_file, os.O_RDONLY):
        config_section = 'ProdConfiguration'

    # try getting config_file from os.environ
    if 'FRESHMAKER_CONFIG_FILE' in os.environ:
        config_file = os.environ['FRESHMAKER_CONFIG_FILE']

    # try getting config_section from os.environ
    if 'FRESHMAKER_CONFIG_SECTION' in os.environ:
        config_section = os.environ['FRESHMAKER_CONFIG_SECTION']

    # TestConfiguration shall only be used for running tests, otherwise...
    if any(['nosetests' in arg or 'noserunner.py' in arg or 'py.test' in arg or 'pytest.py' in arg for arg in sys.argv]):
        config_section = 'TestConfiguration'
        from conf import config
        config_module = config
    # ...FRESHMAKER_DEVELOPER_ENV has always the last word
    # and overrides anything previously set before!
    # In any of the following cases, use configuration directly from Freshmaker
    # package -> /conf/config.py.

    elif ('FRESHMAKER_DEVELOPER_ENV' in os.environ and
          'FRESHMAKER_CONFIG_FILE' not in os.environ and
          os.environ['FRESHMAKER_DEVELOPER_ENV'].lower() in ('1', 'on', 'true', 'y', 'yes')):
        config_section = 'DevConfiguration'
        if 'FRESHMAKER_CONFIG_FILE' in os.environ:
            config_file = os.environ['FRESHMAKER_CONFIG_FILE']
            config_module = None
        else:
            from conf import config
            config_module = config

    # try loading configuration from file
    if not config_module:
        try:
            config_module = imp.load_source('freshmaker_runtime_config',
                                            config_file)
        except IOError:
            raise SystemError("Configuration file {} was not found."
                              .format(config_file))

    # finally configure Freshmaker
    config_section_obj = getattr(config_module, config_section)
    conf = Config(config_section_obj)
    app.config.from_object(config_section_obj)
    return conf


class Config(object):
    """Class representing the freshmaker configuration."""
    _defaults = {
        'debug': {
            'type': bool,
            'default': False,
            'desc': 'Debug mode'},
        'pdc_url': {
            'type': str,
            'default': '',
            'desc': 'PDC URL.'},
        'pdc_insecure': {
            'type': bool,
            'default': False,
            'desc': 'Allow insecure connection to PDC.'},
        'pdc_develop': {
            'type': bool,
            'default': False,
            'desc': 'PDC Development mode, basically noauth.'},
        'log_backend': {
            'type': str,
            'default': None,
            'desc': 'Log backend'},
        'log_file': {
            'type': str,
            'default': '',
            'desc': 'Path to log file'},
        'log_level': {
            'type': str,
            'default': 0,
            'desc': 'Log level'},
        'messaging': {
            'type': str,
            'default': 'fedmsg',
            'desc': 'The messaging system to use.'},
        'messaging_sender': {
            'type': str,
            'default': 'fedmsg',
            'desc': 'The messaging system to use for sending msgs.'},
        'messaging_topic_prefix': {
            'type': list,
            'default': ['org.fedoraproject.prod'],
            'desc': 'The messaging system topic prefixes which we are interested in.'},
        'net_timeout': {
            'type': int,
            'default': 120,
            'desc': 'Global network timeout for read/write operations, in seconds.'},
        'net_retry_interval': {
            'type': int,
            'default': 30,
            'desc': 'Global network retry interval for read/write operations, in seconds.'},
        'parsers': {
            'type': list,
            'default': [],
            'desc': 'Parsers defined for parse specific messages.'},
        'handlers': {
            'type': list,
            'default': ["freshmaker.handlers.mbs:MBSModuleStateChangeHandler"],
            'desc': 'List of enabled handlers.'},
        'git_base_url': {
            'type': str,
            'default': "git://pkgs.fedoraproject.org",
            'desc': 'Dist-git base URL.'},
        'git_ssh_base_url': {
            'type': str,
            'default': "ssh://%s@pkgs.fedoraproject.org/",
            'desc': 'Dist-git ssh base URL.'},
        'git_user': {
            'type': str,
            'default': '',
            'desc': 'User for git operations.'},
        'git_author': {
            'type': str,
            'default': 'Freshmaker <freshmaker-owner@fedoraproject.org>',
            'desc': 'Author for git commit.'},
        'mbs_base_url': {
            'type': str,
            'default': "https://mbs.fedoraproject.org",
            'desc': 'MBS Base URL'},
        'mbs_auth_token': {
            'type': str,
            'default': '',
            'desc': "OpenIDC token to use when communicating with MBS."},
        'koji_profile': {
            'type': str,
            'default': 'koji',
            'desc': 'Koji Profile from where to load Koji configuration.'},
        'koji_container_scratch_build': {
            'type': bool,
            'default': False,
            'desc': 'Whether to make a scratch build to rebuild the image.'},
        'dry_run': {
            'type': bool,
            'default': False,
            'desc': 'When True, no builds will be submitted and only log '
                    'messages will be logged instead. Freshmaker will also '
                    'generate fake "build succeeded" events to mark fake '
                    'artifact rebuild as done.',
        },
        'handler_build_whitelist': {
            'type': dict,
            'default': {},
            'desc': 'Whitelist for build targets of handlers',
        },
        'handler_build_blacklist': {
            'type': dict,
            'default': {},
            'desc': 'Blacklist for build targets of handlers',
        },
        'image_extra_repo': {
            'type': dict,
            'default': {},
            'desc': 'Dict with base container "name-version" as key and URL '
                    'to extra .repo file to include in a rebuild',
        },
        'security_data_server_url': {
            'type': str,
            'default': 'https://access.redhat.com/labs/securitydataapi',
            'desc': 'Server URL of SecurityDataAPI.'},
        'lightblue_server_url': {
            'type': str,
            'default': '',
            'desc': 'Server URL of LightBlue.'},
        'lightblue_verify_ssl': {
            'type': bool,
            'default': True,
            'desc': 'Whether to enable SSL verification over HTTP with lightblue.'},
        'lightblue_certificate': {
            'type': str,
            'default': '',
            'desc': 'Path to LightBlue certificate file.'},
        'lightblue_private_key': {
            'type': str,
            'default': '',
            'desc': 'Path to LightBlue private key file.'},
        'errata_tool_server_url': {
            'type': str,
            'default': '',
            'desc': 'Server URL of Errata Tool.'},
        'errata_rhel_release_prefix': {
            'type': str,
            'default': '',
            'desc': 'When set, only builds based on this RHEL release '
                    'will be included in rebuilds.'},
        'pulp_server_url': {
            'type': str,
            'default': '',
            'desc': 'Server URL of Pulp.'},
        'pulp_username': {
            'type': str,
            'default': '',
            'desc': 'Username to login Pulp.'},
        'pulp_password': {
            'type': str,
            'default': '',
            'desc': 'Password to login Pulp.'},
        'odcs_server_url': {
            'type': str,
            'default': '',
            'desc': 'Server URL to ODCS'},
        'odcs_auth_mech': {
            'type': str,
            'default': 'kerberos',
            'desc': 'ODCS authentication mechanism.'},
        'odcs_verify_ssl': {
            'type': bool,
            'default': True,
            'desc': 'Whether to enable SSL verification over HTTP with ODCS.'},
        'odcs_openidc_token': {
            'type': str,
            'default': '',
            'desc': 'OpenIDC token used to access ODCS.'},
        'odcs_sigkeys': {
            'type': list,
            'default': [],
            'desc': 'List of sigkeys IDs to use when requesting compose.'},
        'krb_auth_using_keytab': {
            'type': bool,
            'default': True,
            'desc': 'Whether to acquire credential cache from a client keytab.'},
        'krb_auth_principal': {
            'type': str,
            'default': "",
            'desc': 'Principal used to acquire credential cache, which must be'
                    ' present in specified client keytab.'},
        'krb_auth_client_keytab': {
            'type': str,
            'default': '',
            'desc': 'Path to a client keytab.'},
        'krb_auth_ccache_file': {
            'type': str,
            'default': '',
            'desc': 'Path to credential cache file. '
                    'The "$pid" is replaced by process ID. '
                    'The "$tid" is replaced by thread ID'},
        'oidc_base_namespace': {
            'type': str,
            'default': 'https://pagure.io/freshmaker/',
            'desc': 'Base namespace of OIDC scopes.'},
        'dogpile_cache_backend': {
            'type': str,
            'default': 'dogpile.cache.memory',
            'desc': 'Name of dogpile.cache backend to use.'},
        'messaging_backends': {
            'type': dict,
            'default': {},
            'desc': 'Configuration for each supported messaging backend.'},
        'max_thread_workers': {
            'type': int,
            'default': 10,
            'desc': 'Maximum number of thread workers used by Freshmaker.'},
    }

    def __init__(self, conf_section_obj):
        """
        Initialize the Config object with defaults and then override them
        with runtime values.
        """

        # set defaults
        for name, values in self._defaults.items():
            self.set_item(name, values['default'])

        # override defaults
        for key in dir(conf_section_obj):
            # skip keys starting with underscore
            if key.startswith('_'):
                continue
            # set item (lower key)
            self.set_item(key.lower(), getattr(conf_section_obj, key))

    def set_item(self, key, value):
        """
        Set value for configuration item. Creates the self._key = value
        attribute and self.key property to set/get/del the attribute.
        """
        if key == 'set_item' or key.startswith('_'):
            raise Exception("Configuration item's name is not allowed: %s" % key)

        # Create the empty self._key attribute, so we can assign to it.
        setattr(self, "_" + key, None)

        # Create self.key property to access the self._key attribute.
        # Use the setifok_func if available for the attribute.
        setifok_func = '_setifok_{}'.format(key)
        if hasattr(self, setifok_func):
            setx = lambda self, val: getattr(self, setifok_func)(val)
        else:
            setx = lambda self, val: setattr(self, "_" + key, val)
        get_func = '_get_{}'.format(key)
        if hasattr(self, get_func):
            getx = lambda self: getattr(self, get_func)()
        else:
            getx = lambda self: getattr(self, "_" + key)
        delx = lambda self: delattr(self, "_" + key)
        setattr(Config, key, property(getx, setx, delx))

        # managed/registered configuration items
        if key in self._defaults:
            # type conversion for configuration item
            convert = self._defaults[key]['type']
            if convert in [bool, int, list, str, set, dict]:
                try:
                    # Do no try to convert None...
                    if value is not None:
                        value = convert(value)
                except (TypeError, ValueError):
                    raise TypeError("Configuration value conversion failed for name: %s" % key)
            # unknown type/unsupported conversion
            elif convert is not None:
                raise TypeError("Unsupported type %s for configuration item name: %s" % (convert, key))

        # Set the attribute to the correct value
        setattr(self, key, value)

    #
    # Register your _setifok_* handlers here
    #

    def _setifok_log_backend(self, s):
        if s is None:
            self._log_backend = "console"
        elif s not in logger.supported_log_backends():
            raise ValueError("Unsupported log backend")
        self._log_backend = str(s)

    def _setifok_log_file(self, s):
        if s is None:
            self._log_file = ""
        else:
            self._log_file = str(s)

    def _setifok_log_level(self, s):
        level = str(s).lower()
        self._log_level = logger.str_to_log_level(level)

    def _setifok_messaging(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq", "in_memory", "rhmsg"):
            raise ValueError("Unsupported messaging system.")
        self._messaging = s

    def _setifok_messaging_sender(self, s):
        s = str(s)
        if s not in ("fedmsg", "amq", "in_memory", "rhmsg"):
            raise ValueError("Unsupported messaging system.")
        self._messaging_sender = s

    def _get_krb_auth_ccache_file(self):
        if not self._krb_auth_ccache_file:
            return self._krb_auth_ccache_file
        ccache_file = str(self._krb_auth_ccache_file)
        ccache_file = ccache_file.replace(
            "$tid", str(threading.current_thread().ident))
        ccache_file = ccache_file.replace(
            "$pid", str(os.getpid()))
        return ccache_file
