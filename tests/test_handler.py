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

from mock import patch, PropertyMock

import freshmaker

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.models import (
    ArtifactBuild, ArtifactBuildState, ArtifactBuildCompose,
    Compose, Event, EVENT_TYPES
)
from freshmaker.errors import UnprocessableEntity, ProgrammingError
from freshmaker.types import ArtifactType, EventState
from freshmaker.config import any_, all_
from tests import helpers


class MyHandler(ContainerBuildHandler):
    """Handler for running tests to test things defined in parents"""

    name = "MyHandler"

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestKrbContextPreparedForBuildContainer(helpers.FreshmakerTestCase):
    """Test krb_context for BaseHandler.build_container"""

    def setUp(self):
        super(TestKrbContextPreparedForBuildContainer, self).setUp()
        self.koji_service = patch('freshmaker.kojiservice.KojiService')
        self.koji_service.start()

    def tearDown(self):
        super(TestKrbContextPreparedForBuildContainer, self).tearDown()
        self.koji_service.stop()

    @patch('freshmaker.utils.conf')
    @patch('freshmaker.utils.krbContext')
    @patch("freshmaker.config.Config.krb_auth_principal",
           new_callable=PropertyMock, return_value="user@example.com")
    def test_prepare_with_keytab(self, auth_principal, krbContext, conf):
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

    @patch('freshmaker.utils.conf')
    @patch('freshmaker.utils.krbContext')
    @patch("freshmaker.config.Config.krb_auth_principal",
           new_callable=PropertyMock, return_value="user@example.com")
    def test_prepare_with_normal_user_credential(self, auth_principal, krbContext, conf):
        conf.krb_auth_use_keytab = False
        conf.krb_auth_principal = 'somebody@REALM'
        conf.krb_auth_ccache_file = '/tmp/freshmaker_cc'

        handler = MyHandler()
        handler.build_container('image-name', 'f26', '1234')

        krbContext.assert_called_once_with(
            principal='somebody@REALM',
            ccache_file='/tmp/freshmaker_cc',
        )


class TestContext(helpers.ModelsTestCase):
    """Test setting context of handler"""

    def test_context_event(self):
        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent)
        db.session.commit()
        handler = MyHandler()
        handler.set_context(db_event)

        self.assertEqual(handler.current_db_event_id, db_event.id)
        self.assertEqual(handler.current_db_artifact_build_id, None)

    def test_context_artifact_build(self):
        db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent)
        build = ArtifactBuild.create(db.session, db_event, "parent1-1-4",
                                     "image")
        db.session.commit()
        handler = MyHandler()
        handler.set_context(build)

        self.assertEqual(handler.current_db_event_id, db_event.id)
        self.assertEqual(handler.current_db_artifact_build_id, build.id)

    def test_context_unknown(self):
        handler = MyHandler()
        self.assertRaises(ProgrammingError, handler.set_context, "something")


class TestDryRun(helpers.FreshmakerTestCase):

    def test_force_dry_run(self):
        handler = MyHandler()
        self.assertFalse(handler.dry_run)

        handler.force_dry_run()
        self.assertTrue(handler.dry_run)


class TestGetRepoURLs(helpers.ModelsTestCase):

    def setUp(self):
        super(TestGetRepoURLs, self).setUp()

        self.compose_1 = Compose(odcs_compose_id=5)
        self.compose_2 = Compose(odcs_compose_id=6)
        self.compose_3 = Compose(odcs_compose_id=7)
        self.compose_4 = Compose(odcs_compose_id=8)
        db.session.add(self.compose_1)
        db.session.add(self.compose_2)
        db.session.add(self.compose_3)
        db.session.add(self.compose_4)

        self.event = Event.create(
            db.session, 'msg-1', 'search-key-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.BUILDING,
            released=False)

        self.build_1 = ArtifactBuild.create(
            db.session, self.event, 'build-1', ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED)
        self.build_2 = ArtifactBuild.create(
            db.session, self.event, 'build-2', ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED)

        db.session.commit()

        rels = (
            (self.build_1.id, self.compose_1.id),
            (self.build_1.id, self.compose_2.id),
            (self.build_1.id, self.compose_3.id),
            (self.build_1.id, self.compose_4.id),
        )

        for build_id, compose_id in rels:
            db.session.add(
                ArtifactBuildCompose(
                    build_id=build_id, compose_id=compose_id))

        db.session.commit()

        def mocked_odcs_get_compose(compose_id):
            return {
                "id": compose_id,
                "result_repofile": "http://localhost/%d.repo" % compose_id,
            }

        self.patch_odcs_get_compose = patch(
            "freshmaker.handlers.ContainerBuildHandler.odcs_get_compose",
            side_effect=mocked_odcs_get_compose)
        self.odcs_get_compose = self.patch_odcs_get_compose.start()

    def tearDown(self):
        super(TestGetRepoURLs, self).tearDown()
        self.patch_odcs_get_compose.stop()

    def test_get_repo_urls_no_composes(self):
        handler = MyHandler()
        repos = handler.get_repo_urls(self.build_2)
        self.assertEqual(repos, [])

    def test_get_repo_urls_both_pulp_and_main_compose(self):
        handler = MyHandler()
        repos = handler.get_repo_urls(self.build_1)
        self.assertEqual(
            [
                'http://localhost/5.repo',
                'http://localhost/6.repo',
                'http://localhost/7.repo',
                'http://localhost/8.repo',
            ],
            sorted(repos))

    @patch.object(freshmaker.conf, 'image_extra_repo', new={
        'build-3': "http://localhost/test.repo"
    })
    def test_get_repo_urls_extra_image_repo(self):
        build_3 = ArtifactBuild.create(
            db.session, self.event, 'build-3', ArtifactType.IMAGE,
            state=ArtifactBuildState.PLANNED, original_nvr="build-3-1")

        handler = MyHandler()
        repos = handler.get_repo_urls(build_3)
        self.assertEqual(repos, ["http://localhost/test.repo"])


class TestAllowBuildBasedOnWhitelist(helpers.FreshmakerTestCase):
    """Test BaseHandler.allow_build"""

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'name': 'test'
            }
        }
    })
    def test_allow_build_in_whitelist(self):
        """ Test if artifact is in the handlers whitelist """
        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(ArtifactType.IMAGE,
                                    name=container["name"],
                                    branch=container["branch"])
        assert allow

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'name': 'test1'
            }
        }
    })
    def test_allow_build_not_in_whitelist(self):
        """ Test if artifact is not in the handlers whitelist """
        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(ArtifactType.IMAGE,
                                    name=container["name"],
                                    branch=container["branch"])
        assert not allow

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'name': 'te(st'
            }
        }
    })
    def test_allow_build_regex_exception(self):
        """ If there is a regex error, method will raise UnprocessableEntity error """

        handler = MyHandler()
        container = {"name": "test", "branch": "branch"}

        with self.assertRaises(UnprocessableEntity):
            handler.allow_build(ArtifactType.IMAGE,
                                name=container["name"],
                                branch=container["branch"])

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_state': ['REL_PREP', 'SHIPPED_LIVE']
            }
        }
    })
    def test_rule_not_defined(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_state='SHIPPED_LIVE')
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_state='SHIPPED_LIVE', published=True)
        self.assertTrue(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_state': ['REL_PREP', 'SHIPPED_LIVE'],
                'published': False
            }
        }
    })
    def test_boolean_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_state='SHIPPED_LIVE', published=True)
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_state': ['REL_PREP', 'SHIPPED_LIVE']
            }
        }
    })
    def test_not_allow_if_none_passed_rule_is_configured(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, state='SHIPPED_LIVE')
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={})
    def test_not_allow_if_whitelist_is_not_configured(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE, state='SHIPPED_LIVE')
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_state': ['REL_PREP', 'SHIPPED_LIVE']
            }
        }
    })
    def test_define_rule_values_as_list(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_state='SHIPPED_LIVE')
        self.assertTrue(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_name': 'RHSA-\d+:\d+'
            }
        }
    })
    def test_define_rule_value_as_single_regex_string(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:31861')
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHBA-2017:31861')
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {
                'advisory_name': 'RHSA-\d+:\d+',
                'advisory_state': 'REL_PREP'
            }
        }
    })
    def test_AND_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      advisory_state='REL_PREP')
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      advisory_state='SHIPPED_LIVE')
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': any_(
                {'advisory_name': 'RHSA-\d+:\d+'},
                {'advisory_state': 'REL_PREP'},
            )
        }
    })
    def test_OR_rule(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      advisory_state='SHIPPED_LIVE')
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017',
                                      advisory_state='REL_PREP')
        self.assertTrue(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': all_(
                {'advisory_name': 'RHSA-\d+:\d+'},
                any_(
                    {'has_hightouch_bugs': True},
                    {'severity': ['critical', 'important']}
                ),
            )
        }
    })
    def test_OR_between_subrules(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      has_hightouch_bugs=True,
                                      severity="low")
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      has_hightouch_bugs=False,
                                      severity="critical")
        self.assertTrue(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHSA-2017:1000',
                                      has_hightouch_bugs=False,
                                      severity="low")
        self.assertFalse(allowed)

        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_name='RHBA-2017:1000',
                                      has_hightouch_bugs=False,
                                      severity="critical")
        self.assertFalse(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': {'advisory_name': 'RHSA-\d+:\d+'},
        }
    })
    @patch.object(freshmaker.conf, 'handler_build_blacklist', new={
        'MyHandler': {
            'image': {'advisory_name': 'RHSA-2016:\d+'},
        }
    })
    def test_blacklist(self):
        handler = MyHandler()
        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name='RHSA-2017:1000')
        self.assertTrue(allowed)

        allowed = handler.allow_build(
            ArtifactType.IMAGE, advisory_name='RHSA-2016:1000')
        self.assertFalse(allowed)
