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

import json

from mock import patch, PropertyMock
from unittest import TestCase

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.models import ArtifactBuild
from freshmaker.models import ArtifactBuildState
from freshmaker.models import Event
from freshmaker.errors import UnprocessableEntity, ProgrammingError
from freshmaker.types import ArtifactType


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


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


class TestBuildFirstBatch(TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._build_first_batch"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        build_args = json.dumps({
            "parent": "nvr",
            "repository": "repo",
            "target": "target",
            "commit": "hash",
            "branch": "mybranch",
            "yum_repourl": "http://localhost/composes/latest-odcs-3-1/compose/"
                           "Temporary/odcs-3.repo",
            "odcs_pulp_compose_id": 15,
        })

        self.db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        self.db_event.compose_id = 3

        p1 = ArtifactBuild.create(db.session, self.db_event, "parent1-1-4",
                                  "image",
                                  state=ArtifactBuildState.PLANNED.value,
                                  original_nvr="parent1-1-4")
        p1.build_args = build_args
        self.p1 = p1

        b = ArtifactBuild.create(db.session, self.db_event,
                                 "parent1_child1", "image",
                                 state=ArtifactBuildState.PLANNED.value,
                                 dep_on=p1,
                                 original_nvr="parent1_child1-1-4")
        b.build_args = build_args

        # Not in PLANNED state.
        b = ArtifactBuild.create(db.session, self.db_event, "parent3", "image",
                                 state=ArtifactBuildState.BUILD.value,
                                 original_nvr="parent3-1-4")
        b.build_args = build_args

        # No build args
        b = ArtifactBuild.create(db.session, self.db_event, "parent4", "image",
                                 state=ArtifactBuildState.PLANNED.value,
                                 original_nvr="parent4-1-4")
        db.session.commit()

        # No parent - base image
        b = ArtifactBuild.create(db.session, self.db_event, "parent5", "image",
                                 state=ArtifactBuildState.PLANNED.value,
                                 original_nvr="parent5-1-4")
        b.build_args = build_args
        b.build_args = b.build_args.replace("nvr", "")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.handlers.ODCS')
    @patch('koji.ClientSession')
    @patch('freshmaker.utils.krbContext')
    def test_build_first_batch(self, krb, ClientSession, ODCS):
        """
        Tests that only PLANNED images without a parent are submitted to
        build system.
        """

        def _fake_get_compose(compose_id):
            return {
                "id": compose_id,
                "result_repo": "http://localhost/composes/latest-odcs-%d-1/compose/Temporary" % compose_id,
                "result_repofile": "http://localhost/composes/latest-odcs-%d-1/compose/Temporary/odcs-%s.repo" % (compose_id, compose_id),
                "source": "f26",
                "source_type": 1,
                "state": 2,
                "state_name": "done",
            }

        ODCS.return_value.get_compose = _fake_get_compose

        mock_session = ClientSession.return_value
        mock_session.buildContainer.return_value = 123

        handler = MyHandler()
        handler._build_first_batch(self.db_event)

        mock_session.buildContainer.assert_called_once_with(
            'git://pkgs.fedoraproject.org/repo#hash',
            'target',
            {'scratch': True, 'isolated': True, 'koji_parent_build': u'nvr',
             'git_branch': 'mybranch', 'release': AnyStringWith('4.'),
             'yum_repourls': [
                 'http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo',
                 'http://localhost/composes/latest-odcs-15-1/compose/Temporary/odcs-15.repo']})

        db.session.refresh(self.db_event)
        for build in self.db_event.builds:
            if build.name == "parent1-1-4":
                self.assertEqual(build.build_id, 123)
            elif build.name == "parent3":
                self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
                self.assertEqual(build.state_reason, "Container image build "
                                 "is not in PLANNED state.")
            elif build.name == "parent4":
                self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
                self.assertEqual(build.state_reason, "Container image does "
                                 "not have 'build_args' filled in.")
            elif build.name == "parent5":
                self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
                self.assertEqual(build.state_reason, "Rebuild of container "
                                 "base image is not supported yet.")
            else:
                self.assertEqual(build.build_id, None)
                self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)

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

    @patch('freshmaker.handlers.ODCS')
    @patch('koji.ClientSession')
    @patch('freshmaker.utils.krbContext')
    def test_build_first_batch_exception(self, krb, ClientSession, ODCS):
        """
        Tests that only PLANNED images without a parent are submitted to
        build system.
        """

        def _fake_get_compose(compose_id):
            return {
                "id": compose_id,
                "result_repo": "http://localhost/composes/latest-odcs-%d-1/compose/Temporary" % compose_id,
                "result_repofile": "http://localhost/composes/latest-odcs-%d-1/compose/Temporary/odcs-%s.repo" % (compose_id, compose_id),
                "source": "f26",
                "source_type": 1,
                "state": 2,
                "state_name": "done",
            }

        ODCS.return_value.get_compose = _fake_get_compose

        def mock_buildContainer(*args, **kwargs):
            raise ValueError("Expected exception")

        mock_session = ClientSession.return_value
        mock_session.buildContainer.side_effect = mock_buildContainer

        handler = MyHandler()
        self.assertRaises(ValueError, handler._build_first_batch, self.db_event)

        db.session.refresh(self.p1)
        self.assertEqual(self.p1.state, ArtifactBuildState.FAILED.value)
        self.assertTrue(self.p1.state_reason.startswith(
            "Handling of build failed with traceback"))
