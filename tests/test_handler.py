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
from unittest import TestCase

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


class MyHandler(ContainerBuildHandler):
    """Handler for running tests to test things defined in parents"""

    name = "MyHandler"

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestKrbContextPreparedForBuildContainer(TestCase):
    """Test krb_context for BaseHandler.build_container"""

    def setUp(self):
        self.koji_service = patch('freshmaker.kojiservice.KojiService')
        self.koji_service.start()

    def tearDown(self):
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


class TestContext(TestCase):
    """Test setting context of handler"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

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


class TestGetRepoURLs(TestCase):

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.compose_1 = Compose(odcs_compose_id=1)
        self.compose_2 = Compose(odcs_compose_id=2)
        self.compose_3 = Compose(odcs_compose_id=3)
        self.compose_4 = Compose(odcs_compose_id=4)
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

        self.patch_odcs_get_compose = patch(
            "freshmaker.handlers.ContainerBuildHandler.odcs_get_compose",
            side_effect=[
                {
                    "id": self.compose_1.id,
                    "result_repofile": "http://localhost/1.repo",
                },
                {
                    "id": self.compose_2.id,
                    "result_repofile": "http://localhost/2.repo",
                },
                {
                    "id": self.compose_3.id,
                    "result_repofile": "http://localhost/3.repo",
                },
                {
                    "id": self.compose_4.id,
                    "result_repofile": "http://localhost/4.repo",
                },
            ])
        self.odcs_get_compose = self.patch_odcs_get_compose.start()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()
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
                'http://localhost/1.repo',
                'http://localhost/2.repo',
                'http://localhost/3.repo',
                'http://localhost/4.repo',
            ],
            sorted(repos))


class TestAllowBuildBasedOnWhitelist(TestCase):
    """Test BaseHandler.allow_build"""

    @patch('freshmaker.handlers.conf')
    def test_allow_build_in_whitelist(self, conf):
        """ Test if artifact is in the handlers whitelist """
        whitelist_rules = {"image": [{'name': "test"}]}
        handler = MyHandler()
        conf.handler_build_whitelist.get.return_value = whitelist_rules
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(ArtifactType.IMAGE,
                                    name=container["name"],
                                    branch=container["branch"])
        assert allow

    @patch('freshmaker.handlers.conf')
    def test_allow_build_not_in_whitelist(self, conf):
        """ Test if artifact is not in the handlers whitelist """
        whitelist_rules = {"image": [{'name': "test1"}]}
        handler = MyHandler()
        conf.handler_build_whitelist.get.return_value = whitelist_rules
        container = {"name": "test", "branch": "branch"}

        allow = handler.allow_build(ArtifactType.IMAGE,
                                    name=container["name"],
                                    branch=container["branch"])
        assert not allow

    @patch('freshmaker.handlers.conf')
    def test_allow_build_regex_exception(self, conf):
        """ If there is a regex error, method will raise UnprocessableEntity error """

        whitelist_rules = {"image": [{'name': "te(st"}]}
        handler = MyHandler()
        conf.handler_build_whitelist.get.return_value = whitelist_rules
        container = {"name": "test", "branch": "branch"}

        with self.assertRaises(UnprocessableEntity):
            handler.allow_build(ArtifactType.IMAGE,
                                name=container["name"],
                                branch=container["branch"])

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': [
                {'advisory_state': ['REL_PREP', 'SHIPPED_LIVE']}
            ]
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
            'image': [
                {'advisory_state': ['REL_PREP', 'SHIPPED_LIVE']}
            ]
        }
    })
    def test_define_rule_values_as_list(self):
        handler = MyHandler()
        allowed = handler.allow_build(ArtifactType.IMAGE,
                                      advisory_state='SHIPPED_LIVE')
        self.assertTrue(allowed)

    @patch.object(freshmaker.conf, 'handler_build_whitelist', new={
        'MyHandler': {
            'image': [
                {'advisory_name': 'RHSA-\d+:\d+'}
            ]
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
            'image': [{
                'advisory_name': 'RHSA-\d+:\d+',
                'advisory_state': 'REL_PREP'
            }]
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
            'image': [
                {'advisory_name': 'RHSA-\d+:\d+'},
                {'advisory_state': 'REL_PREP'},
            ]
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
