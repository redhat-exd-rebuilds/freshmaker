# -*- coding: utf-8 -*-

import os

from conf import config


class BaseConfiguration(config.BaseConfiguration):
    MESSAGING_TOPIC_PREFIX = [
        # This is the queue name to receive messages from UMB.
        # Generally, it has format Consumer.client-[name].*.VirtualTopic.>
        #
        # - name is deteremined by the certificate requested. For example, a
        # certificate is requested with client name msg-client-bob, then in
        # queue name, it name should be bob, that is Consumer.client-bob.
        #
        # - * is any word you choose, which should be descriptive to this queue
        #
        # - > represents the hierarchy of topic name, e.g. eng.brew.sign.rpm
        os.environ['FRESHMAKER_MESSAGING_TOPIC_PREFIX'],
    ]

    PARSERS = [
        'freshmaker.parsers.brew.sign_rpm:BrewSignRpmParser',
        'freshmaker.parsers.brew:BrewTaskStateChangeParser',
    ]

    HANDLERS = [
        'freshmaker.handlers.brew:BrewSignRPMHandler',
        'freshmaker.handlers.brew:BrewContainerTaskStateChangeHandler',
    ]

    KOJI_PROFILE = 'brew'

    # LightBlue server URL, e.g. http://localhost/
    LIGHTBLUE_SERVER_URL = ''  # replace with default server url
    LIGHTBLUE_VERIFY_SSL = True
    # Path to LightBlue certificate file
    LIGHTBLUE_CERTIFICATE = ''
    # Path to LightBlue private key file
    LIGHTBLUE_PRIVATE_KEY = ''

    # Lookup versions of each entity: /rest/metadata/{entity name}
    LIGHTBLUE_ENTITY_VERSIONS = {
        'containerRepository': '0.0.11',
        'containerImage': '0.0.12',
    }

    # replace with real value when deploy
    ERRATA_TOOL_SERVER_URL = ''

    # Pulp server url, e.g. http://localhost/
    PULP_SERVER_URL = ''

    # Username and password used to query Pulp server
    PULP_USERNAME = ''
    PULP_PASSWORD = ''

    AUTH_BACKEND = 'kerberos'
    # Replace with real ldap server URL
    AUTH_LDAP_SERVER = ''
    AUTH_LDAP_GROUP_BASE = 'ou=groups,dc=redhat,dc=com'

    HANDLER_BUILD_WHITELIST = {
        'BrewSignRPMHandler': {
            'image': [
                {
                    'advisory_state': 'SHIPPED_LIVE',
                },
            ],
        },
        'ErrataAdvisoryStateChangedHandler': {
            'image': [
                {
                    'advisory_state': 'SHIPPED_LIVE',
                },
            ],
        },
    }


class DevConfiguration(BaseConfiguration):
    DEBUG = True
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'

    # Global network-related values, in seconds
    NET_TIMEOUT = 5
    NET_RETRY_INTERVAL = 1

    KOJI_CONTAINER_SCRATCH_BUILD = True

    LIGHTBLUE_VERIFY_SSL = False

    HANDLER_BUILD_WHITELIST = {
        'BrewSignRPMHandler': {
            'image': [
                {
                    'advisory_state': 'REL_PREP|PUSH_READY|IN_PUSH|SHIPPED_LIVE',
                },
            ],
        },
        'ErrataAdvisoryStateChangedHandler': {
            'image': [
                {
                    'advisory_state': 'REL_PREP|PUSH_READY|IN_PUSH|SHIPPED_LIVE',
                },
            ],
        },
    }


class TestConfiguration(BaseConfiguration):
    LOG_BACKEND = 'console'
    LOG_LEVEL = 'debug'
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = 'sqlite:///{0}'.format(
        os.path.join(config.dbdir, 'tests', 'test_freshmaker.db'))

    MESSAGING = 'in_memory'
    PDC_URL = 'http://pdc.fedoraproject.org/rest_api/v1'

    # Global network-related values, in seconds
    NET_TIMEOUT = 3
    NET_RETRY_INTERVAL = 1
    MBS_AUTH_TOKEN = "testingtoken"

    KOJI_CONTAINER_SCRATCH_BUILD = True

    LIGHTBLUE_SERVER_URL = ''  # replace with real dev server url
    LIGHTBLUE_VERIFY_SSL = False
