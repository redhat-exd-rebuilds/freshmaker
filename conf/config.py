# -*- coding: utf-8 -*-

import os


# FIXME: workaround for this moment till confdir, dbdir (installdir etc.) are
# declared properly somewhere/somehow
confdir = os.path.abspath(os.path.dirname(__file__))
# use parent dir as dbdir else fallback to current dir
dbdir = os.path.abspath(os.path.join(confdir, '..')) if confdir.endswith('conf') \
    else confdir


class BaseConfiguration(object):
    # Make this random (used to generate session keys)
    SECRET_KEY = '74d9e9f9cd40e66fc6c4c2e9987dce48df3ce98542529fd0'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(os.path.join(
        dbdir, 'freshmaker.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    HOST = '0.0.0.0'
    PORT = 5001

    DEBUG = False
    # Global network-related values, in seconds
    NET_TIMEOUT = 120
    NET_RETRY_INTERVAL = 30

    SYSTEM = 'koji'
    MESSAGING = 'fedmsg'  # or amq
    PDC_URL = 'http://modularity.fedorainfracloud.org:8080/rest_api/v1'
    PDC_INSECURE = True
    PDC_DEVELOP = True

    # Available backends are: console, file, journal.
    LOG_BACKEND = 'journal'

    # Path to log file when LOG_BACKEND is set to "file".
    LOG_FILE = 'freshmaker.log'

    # Available log levels are: debug, info, warn, error.
    LOG_LEVEL = 'info'

    MESSAGING_TOPIC_PREFIX = ['org.fedoraproject.prod']

    # Parsers defined for parse specific messages
    PARSERS = [
        'freshmaker.parsers.bodhi:BodhiUpdateCompleteStableParser',
        'freshmaker.parsers.git:GitReceiveParser',
        'freshmaker.parsers.koji:KojiTaskStateChangeParser',
        'freshmaker.parsers.mbs:MBSModuleStateChangeParser',
    ]

    # List of enabled composing handlers.
    HANDLERS = [
        "freshmaker.handlers.bodhi:BodhiUpdateCompleteStableHandler",
        "freshmaker.handlers.git:GitDockerfileChangeHandler",
        "freshmaker.handlers.git:GitModuleMetadataChangeHandler",
        "freshmaker.handlers.git:GitRPMSpecChangeHandler",
        "freshmaker.handlers.koji:KojiTaskStateChangeHandler",
        "freshmaker.handlers.mbs:MBSModuleStateChangeHandler",
    ]

    # Base URL of git repository with source artifacts.
    GIT_BASE_URL = "git://pkgs.fedoraproject.org"

    # SSH base URL of git repository
    GIT_SSH_BASE_URL = "ssh://%s@pkgs.fedoraproject.org/"

    # GIT user for cloning and pushing repo
    GIT_USER = ""

    # Base URL of Module Build Service.
    MBS_BASE_URL = "https://mbs.fedoraproject.org"

    # Authorization token to use when communicating with MBS.
    MBS_AUTH_TOKEN = ""

    # PDC API URL
    PDC_URL = 'http://pdc.fedoraproject.org/rest_api/v1'

    # Read Koji configuration from profile instead of reading them from
    # configuration file directly. For staging Koji, it is stg.
    KOJI_PROFILE = 'koji'
    KOJI_PROXYUSER = False
    KOJI_BUILD_OWNER = 'freshmaker'

    # Settings for docker image rebuild handler
    KOJI_CONTAINER_SCRATCH_BUILD = False

    SSL_ENABLED = False

    # whitelist and blacklist for handlers to decide whether an artifact
    # can be built.
    #
    # In format of:
    #
    # { <handler_name> :
    #     { <artifact_type>: <list_of_name_branch_dict> }
    # }
    #
    # Here is an example of allowing MBSModuleStateChangeHandler to build
    # any module that module name matches 'base-.*' but not:
    #   1. module name matches 'base-test-module'
    # or:
    #   2. module from branch 'rawhide'
    #
    # HANDLER_BUILD_WHITELIST = {
    #     "MBSModuleStateChangeHandler": {
    #         "module": [
    #             {
    #                 'name': 'base-.*',
    #             },
    #         ],
    #     },
    # }
    # HANDLER_BUILD_BLACKLIST = {
    #     "MBSModuleStateChangeHandler": {
    #         "module": [
    #             {
    #                 'name': 'base-test-module',
    #             },
    #             {
    #                 'branch': 'rawhide',
    #             },
    #         ],
    #     },
    # }

    # ODCS configs
    # URL to ODCS to call APIs
    ODCS_SERVER_URL = ''

    # Kerberos authentication Settings used to authenticated freshmaker itself
    # by other services

    # Whether to use keytab to acquire credential cache. keytab should be used
    # in a non-devel environment.
    KRB_AUTH_USE_KEYTAB = True
    # Principal used to acquire credential cache. When using a client keytab,
    # this value must be present in that keytab file. Otherwise, principal must
    # match the one in specified ccache file.
    KRB_AUTH_PRINCIPAL = ''
    # Path to freshmaker's client keytab file.
    KRB_AUTH_CLIENT_KEYTAB = ''
    # Path to credential cache file. This optional could be None when not using
    # a client keytab to acquire credential.
    KRB_AUTH_CCACHE_FILE = '/tmp/freshmaker_cc_{}'.format(os.getpid())


class DevConfiguration(BaseConfiguration):
    DEBUG = True
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'

    MESSAGING_TOPIC_PREFIX = ['org.fedoraproject.dev', 'org.fedoraproject.stg']

    # Global network-related values, in seconds
    NET_TIMEOUT = 5
    NET_RETRY_INTERVAL = 1

    KOJI_CONTAINER_SCRATCH_BUILD = True

    LIGHTBLUE_VERIFY_SSL = False

    # During development, we usually don't need a client keytab to acquire
    # credential. Instead, kinit in default ccache with personal principal
    # often.
    KRB_AUTH_USE_KEYTAB = False
    KRB_AUTH_PRINCIPAL = ''  # Should be in form name@REAL
    # Use the default ccache
    KRB_AUTH_CCACHE_FILE = None


class TestConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(
        os.path.join(dbdir, 'tests', 'test_freshmaker.db'))

    MESSAGING = 'in_memory'
    PDC_URL = 'http://pdc.fedoraproject.org/rest_api/v1'

    # Global network-related values, in seconds
    NET_TIMEOUT = 3
    NET_RETRY_INTERVAL = 1
    MBS_AUTH_TOKEN = "testingtoken"

    KOJI_CONTAINER_SCRATCH_BUILD = True

    LIGHTBLUE_SERVER_URL = ''  # replace with real dev server url
    LIGHTBLUE_VERIFY_SSL = False

    # Disable caching for tests
    DOGPILE_CACHE_BACKEND = "dogpile.cache.null"


class ProdConfiguration(BaseConfiguration):
    pass
