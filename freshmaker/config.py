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

from os import sys
from freshmaker import logger


def init_config():
    """
    Configure Freshmaker
    """
    config_module = None
    config_file = '/etc/freshmaker/config.py'
    config_section = 'DevConfiguration'

    # automagically detect production environment:
    #   - existing and readable config_file presets ProdConfiguration
    try:
        with open(config_file):
            config_section = 'ProdConfiguration'
    except:
        pass

    # try getting config_file from os.environ
    if 'FRESHMAKER_CONFIG_FILE' in os.environ:
        config_file = os.environ['FRESHMAKER_CONFIG_FILE']
    # try getting config_section from os.environ
    if 'FRESHMAKER_CONFIG_SECTION' in os.environ:
        config_section = os.environ['FRESHMAKER_CONFIG_SECTION']
    # TestConfiguration shall only be used for running tests, otherwise...
    if any(['py.test' in arg or 'pytest.py' in arg for arg in sys.argv]):
        config_section = 'TestConfiguration'
        from conf import config
        config_module = config
    # ...FRESHMAKER_DEVELOPER_ENV has always the last word
    # and overrides anything previously set before!
    # In any of the following cases, use configuration directly from Freshmaker
    # package -> /conf/config.py.

    elif ('FRESHMAKER_DEVELOPER_ENV' in os.environ and
          os.environ['FRESHMAKER_DEVELOPER_ENV'].lower() in (
            '1', 'on', 'true', 'y', 'yes')):
        config_section = 'DevConfiguration'
        from conf import config
        config_module = config
    # try loading configuration from file
    if not config_module:
        try:
            config_module = imp.load_source('freshmaker_runtime_config',
                                            config_file)
        except:
            raise SystemError("Configuration file {} was not found."
                              .format(config_file))

    # finally configure Freshmaker
    config_section_obj = getattr(config_module, config_section)
    conf = Config(config_section_obj)
    return conf


class Config(object):
    """Class representing the orchestrator configuration."""
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
        'handlers': {
            'type': list,
            'default': ["freshmaker.handlers.mbs:MBS"],
            'desc': 'List of enabled handlers.'},
        'git_base_url': {
            'type': str,
            'default': "git://pkgs.fedoraproject.org",
            'desc': 'Dist-git base URL.'},
        'mbs_base_url': {
            'type': str,
            'default': "https://mbs.fedoraproject.org",
            'desc': 'MBS Base URL'},
        'mbs_auth_token': {
            'type': str,
            'default': '',
            'desc': "OpenIDC token to use when communicating with MBS."},
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
        getx = lambda self: getattr(self, "_" + key)
        delx = lambda self: delattr(self, "_" + key)
        setattr(Config, key, property(getx, setx, delx))

        # managed/registered configuration items
        if key in self._defaults:
            # type conversion for configuration item
            convert = self._defaults[key]['type']
            if convert in [bool, int, list, str, set]:
                try:
                    # Do no try to convert None...
                    if value is not None:
                        value = convert(value)
                except:
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
        if s not in ("fedmsg", "amq", "in_memory"):
            raise ValueError("Unsupported messaging system.")
        self._messaging = s
