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

from mock import patch
from unittest import TestCase

from freshmaker import db
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.handlers import ContainerBuildHandler
from freshmaker.models import ArtifactBuild
from freshmaker.models import ArtifactBuildState
from freshmaker.models import Event


class MyHandler(ContainerBuildHandler):
    """Handler for running tests to test things defined in parents"""

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestKrbContextPreparedForBuildContainer(TestCase):
    """Test krb_context for BaseHandler.build_container"""

    def setUp(self):
        self.koji_service = patch('freshmaker.handlers.koji_service')
        self.koji_service.start()

    def tearDown(self):
        self.koji_service.stop()

    @patch('freshmaker.handlers.conf')
    @patch('freshmaker.handlers.krbContext')
    def test_prepare_with_keytab(self, krbContext, conf):
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

    @patch('freshmaker.handlers.conf')
    @patch('freshmaker.handlers.krbContext')
    def test_prepare_with_normal_user_credential(self, krbContext, conf):
        conf.krb_auth_use_keytab = False
        conf.krb_auth_principal = 'somebody@REALM'
        conf.krb_auth_ccache_file = '/tmp/freshmaker_cc'

        handler = MyHandler()
        handler.build_container('image-name', 'f26', '1234')

        krbContext.assert_called_once_with(
            principal='somebody@REALM',
            ccache_file='/tmp/freshmaker_cc',
        )


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
            "yum_repourl": "http://localhost/composes/latest-odcs-3-1/compose/"
                           "Temporary/odcs-3.repo",
        })

        self.db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        self.db_event.compose_id = 3
        p1 = ArtifactBuild.create(db.session, self.db_event, "parent1-1-4",
                                  "image",
                                  state=ArtifactBuildState.PLANNED.value)
        p1.build_args = build_args
        b = ArtifactBuild.create(db.session, self.db_event,
                                 "parent1_child1", "image",
                                 state=ArtifactBuildState.PLANNED.value,
                                 dep_on=p1)
        b.build_args = build_args
        b = ArtifactBuild.create(db.session, self.db_event, "parent3", "image",
                                 state=ArtifactBuildState.BUILD.value)
        b.build_args = build_args
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('koji.ClientSession')
    @patch('freshmaker.handlers.krbContext')
    def test_build_first_batch(self, krb, ClientSession):
        """
        Tests that only PLANNED images without a parent are submitted to
        build system.
        """
        mock_session = ClientSession.return_value
        mock_session.buildContainer.return_value = 123

        handler = MyHandler()
        handler._build_first_batch(self.db_event)

        mock_session.buildContainer.assert_called_once_with(
            'git://pkgs.fedoraproject.org/repo#hash',
            'target',
            {'scratch': True, 'isolated': True, 'koji_parent_build': u'nvr',
             'git_branch': 'unknown', 'release': AnyStringWith('4.'),
             'yum_repourls': [
                 'http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo']})

        db.session.refresh(self.db_event)
        for build in self.db_event.builds:
            if build.name == "parent1-1-4":
                self.assertEqual(build.build_id, 123)
            else:
                self.assertEqual(build.build_id, None)
