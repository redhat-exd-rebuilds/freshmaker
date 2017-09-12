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
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
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

import six
import pytest
import unittest
import json

from mock import patch, MagicMock, PropertyMock, Mock

from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent

from freshmaker import db, events
from freshmaker.models import Event, ArtifactBuild
from freshmaker.types import ArtifactBuildState, ArtifactType


@pytest.mark.skipif(six.PY3, reason='koji does not work in Python 3')
class TestFindBuildSrpmName(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._find_build_srpm_name"""

    @patch('koji.ClientSession')
    def test_find_srpm_name(self, ClientSession):
        session = ClientSession.return_value
        session.getBuild.return_value = {
            'build_id': 439408,
            'id': 439408,
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }
        session.listRPMs.return_value = [{
            'arch': 'src',
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }]

        handler = ErrataAdvisoryRPMsSignedHandler()
        srpm_name = handler._find_build_srpm_name('bind-dyndb-ldap-2.3-8.el6')

        session.getBuild.assert_called_once_with('bind-dyndb-ldap-2.3-8.el6')
        session.listRPMs.assert_called_once_with(buildID=439408, arches='src')
        self.assertEqual('bind-dyndb-ldap', srpm_name)

    @patch('koji.ClientSession')
    def test_error_if_no_srpm_in_build(self, ClientSession):
        session = ClientSession.return_value
        session.getBuild.return_value = {
            'build_id': 439408,
            'id': 439408,
            'name': 'bind-dyndb-ldap',
            'nvr': 'bind-dyndb-ldap-2.3-8.el6',
        }
        session.listRPMs.return_value = []

        handler = ErrataAdvisoryRPMsSignedHandler()

        self.assertRaisesRegexp(
            ValueError,
            'Build bind-dyndb-ldap-2.3-8.el6 does not have a SRPM',
            handler._find_build_srpm_name,
            'bind-dyndb-ldap-2.3-8.el6',
        )

        session.getBuild.assert_called_once_with('bind-dyndb-ldap-2.3-8.el6')
        session.listRPMs.assert_called_once_with(buildID=439408, arches='src')


class TestAllowBuild(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler.allow_build"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_and_record_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "ErrataAdvisoryRPMsSignedHandler": {"image": [{"advisory_name": "RHSA-.*"}]}})
    def test_allow_build_false(self, handler_build_whitelist, record_images):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent("123", "RHBA-2017", 123, "")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_not_called()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_and_record_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "ErrataAdvisoryRPMsSignedHandler": {"image": [{"advisory_name": "RHSA-.*"}]}})
    def test_allow_build_true(self, handler_build_whitelist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent("123", "RHSA-2017", 123, "")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_called_once()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_and_record_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": [{
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }]
            }
        })
    def test_allow_security_impact_important_true(
            self, handler_build_whitelist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent("123", "RHSA-2017", 123,
                                              "Important")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_called_once()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_and_record_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": [{
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }]
            }
        })
    def test_allow_security_impact_important_false(
            self, handler_build_whitelist, record_images):
        """
        Tests that allow_build dost filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent("123", "RHSA-2017", 123, "None")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_not_called()


class TestBatches(unittest.TestCase):
    """Test handling of batches"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def _mock_build(self, build, parent=None):
        if parent:
            parent = {"brew": {"build": parent}}
        return {'brew': {'build': build}, 'repository': build + '_repo',
                'commit': build + '_123', 'parent': parent, "target": "t1"}

    def test_batches_records(self):
        """
        Tests that batches are properly recorded in DB.
        """
        # Creates following tree:
        # shared_parent
        #   |- child1_parent3
        #     |- child1_parent2
        #       |- child1_parent1
        #         |- child1
        #   |- child2_parent2
        #     |- child2_parent1
        #       |- child2
        batches = [[self._mock_build("shared_parent")],
                   [self._mock_build("child1_parent3", "shared_parent"),
                    self._mock_build("child2_parent2", "shared_parent")],
                   [self._mock_build("child1_parent2", "child1_parent3"),
                    self._mock_build("child2_parent1", "child2_parent2")],
                   [self._mock_build("child1_parent1", "child1_parent2"),
                    self._mock_build("child2", "child2_parent1")],
                   [self._mock_build("child1", "child1_parent1")]]

        # Flat list of images from batches with brew build id as a key.
        images = {}
        for batch in batches:
            for image in batch:
                images[image['brew']['build']] = image

        # Record the batches.
        event = events.BrewSignRPMEvent("123", "openssl-1.1.0-1")
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, event)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)
            self.assertEqual(build.type, ArtifactType.IMAGE.value)

            image = images[build.name]
            if image['parent']:
                self.assertEqual(build.dep_on.name, image['parent']['brew']['build'])
            else:
                self.assertEqual(build.dep_on, None)

            args = json.loads(build.build_args)
            self.assertEqual(args["repository"], build.name + "_repo")
            self.assertEqual(args["commit"], build.name + "_123")
            self.assertEqual(args["parent"],
                             build.dep_on.name if build.dep_on else None)


class TestGetPackagesForCompose(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose"""

    @patch('freshmaker.kojiservice.KojiService.get_build_rpms')
    def test_get_packages(self, get_build_rpms):
        get_build_rpms.return_value = [
            {
                'id': 4672404,
                'arch': 'src',
                'name': 'chkconfig',
                'release': '1.el7_3.1',
                'version': '1.7.2',
                'nvr': 'chkconfig-1.7.2-1.el7_3.1',
            },
            {
                'id': 4672405,
                'arch': 'ppc',
                'name': 'chkconfig',
                'release': '1.el7_3.1',
                'version': '1.7.2',
                'nvr': 'chkconfig-1.7.2-1.el7_3.1',
            },
            {
                'id': 4672420,
                'arch': 'i686',
                'name': 'chkconfig-debuginfo',
                'release': '1.el7_3.1',
                'version': '1.7.2',
                'nvr': 'chkconfig-debuginfo-1.7.2-1.el7_3.1',
            }
        ]

        build_nvr = 'chkconfig-1.7.2-1.el7_3.1'
        handler = ErrataAdvisoryRPMsSignedHandler()
        packages = handler._get_packages_for_compose(build_nvr)

        get_build_rpms.assert_called_once_with(build_nvr)

        self.assertEqual(set(['chkconfig', 'chkconfig-debuginfo']),
                         set(packages))


class TestGetComposeSource(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_compose_source"""

    @patch('freshmaker.kojiservice.KojiService.session', callable=PropertyMock)
    def test_get_tag(self, session):
        session.listTags.return_value = [
            {
                'id': 10974,
                'name': 'rhscl-3.0-rhel-6-candidate',
            },
            {
                'id': 11030,
                'name': 'rhscl-3.0-rhel-6-pending',
            },
            {
                'id': 11425,
                'name': 'rhscl-3.0-rhel-6-alpha-1.0-set',
            }
        ]
        session.listTagged.return_value = [
            {
                'build_id': 568228,
                'nvr': 'rh-postgresql96-3.0-9.el6',
            }
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('rhscl-3.0-rhel-6-candidate', tag)

    @patch('freshmaker.kojiservice.KojiService.session', callable=PropertyMock)
    def test_get_None_if_tag_has_new_build(self, session):
        session.listTags.return_value = [
            {
                'id': 10974,
                'name': 'rhscl-3.0-rhel-6-candidate',
            },
            {
                'id': 11030,
                'name': 'rhscl-3.0-rhel-6-pending',
            },
            {
                'id': 11425,
                'name': 'rhscl-3.0-rhel-6-alpha-1.0-set',
            }
        ]
        session.listTagged.return_value = [
            {
                'build_id': 568228,
                'nvr': 'rh-postgresql96-3.0-10.el6',
            }
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual(None, tag)


class TestPrepareYumRepo(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._prepare_yum_repo"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        Event.create(db.session, 'msg-id', 'nvr', 100)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.ODCS')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.Errata')
    def test_get_repo_url_when_succeed_to_generate_compose(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, ODCS):
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.return_value = 'rhel-7.2-candidate'
        ODCS.return_value.new_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "source": "f26",
            "source_type": 1,
            "state": 0,
            "state_name": "wait",
        }
        ODCS.return_value.get_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "source": "f26",
            "source_type": 1,
            "state": 2,
            "state_name": "done",
        }

        errata.return_value.get_builds.return_value = set(["httpd-2.4.15-1.f27"])

        event = Mock(msg_id='msg-id', search_key=12345)
        handler = ErrataAdvisoryRPMsSignedHandler()
        repo_url = handler._prepare_yum_repo(event)

        rebuild_event = db.session.query(Event).filter(
            Event.message_id == event.msg_id).first()
        self.assertEqual(3, rebuild_event.compose_id)

        _get_compose_source.assert_called_once_with("httpd-2.4.15-1.f27")
        _get_packages_for_compose.assert_called_once_with("httpd-2.4.15-1.f27")

        # Ensure new_compose is called to request a new compose
        ODCS.return_value.new_compose.assert_called_once_with(
            'rhel-7.2-candidate', 'tag', packages=['httpd', 'httpd-debuginfo'])

        # Ensure get_compose is called once in order to get lates state and see
        # if it still needs to wait for ODCS
        ODCS.return_value.get_compose.assert_called_once_with(3)

        # We should get the right repo URL eventually
        self.assertEqual(
            'http://localhost/composes/latest-odcs-3-1/compose/Temporary',
            repo_url)


class TestFindEventsToInclude(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._find_events_to_include"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        self.db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        ArtifactBuild.create(db.session, self.db_event, "foo", "image", 0)

        # Only this event should be reused, because it is unreleased and
        # contains the foo build.
        ev = Event.get_or_create(
            db.session, "msg2", "old_event_foo", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        ArtifactBuild.create(db.session, ev, "foo", "image", 0)

        ev = Event.get_or_create(
            db.session, "msg3", "old_event_foo_released",
            ErrataAdvisoryRPMsSignedEvent, released=True)
        ArtifactBuild.create(db.session, ev, "foo", "image", 0)

        ev = Event.get_or_create(
            db.session, "msg4", "old_event_bar", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        ArtifactBuild.create(db.session, ev, "bar", "image", 0)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    def test_find_events_to_include(self):
        builds = {"foo": MagicMock()}
        handler = ErrataAdvisoryRPMsSignedHandler()
        events = handler._find_events_to_include(self.db_event, builds)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].search_key, "old_event_foo")


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


class TestBuildFirstBatch(unittest.TestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._build_first_batch"""

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        build_args = '{"parent": "nvr", "repository": "repo", \
            "target": "target", "commit": "hash"}'

        self.db_event = Event.get_or_create(
            db.session, "msg1", "current_event", ErrataAdvisoryRPMsSignedEvent,
            released=False)
        self.db_event.compose_id = 3
        p1 = ArtifactBuild.create(db.session, self.db_event, "parent1-1-4",
                                  "image",
                                  state=ArtifactBuildState.PLANNED.value)
        p1.build_args = build_args
        b = ArtifactBuild.create(db.session, self.db_event, "parent1_child1", "image",
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

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.ODCS')
    @patch('koji.ClientSession')
    @patch('freshmaker.handlers.krbContext')
    def test_build_first_batch(self, krb, ClientSession, ODCS):
        """
        Tests that only PLANNED images without a parent are submitted to
        build system.
        """
        ODCS.return_value.get_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "result_repofile": "http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo",
            "source": "f26",
            "source_type": 1,
            "state": 2,
            "state_name": "done",
        }
        mock_session = ClientSession.return_value
        mock_session.buildContainer.return_value = 123

        handler = ErrataAdvisoryRPMsSignedHandler()
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
