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

import unittest
import json

from mock import patch, PropertyMock, Mock, call

from freshmaker import conf, db, events
from freshmaker.errata import ErrataAdvisory
from freshmaker.events import ErrataAdvisoryRPMsSignedEvent
from freshmaker.events import ErrataAdvisoryStateChangedEvent
from freshmaker.handlers.errata import ErrataAdvisoryRPMsSignedHandler
from freshmaker.handlers.errata import ErrataAdvisoryStateChangedHandler
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, ArtifactBuild, EVENT_TYPES
from freshmaker.types import ArtifactBuildState, ArtifactType, EventState
from tests import helpers


class TestFindBuildSrpmName(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._find_build_srpm_name"""

    @helpers.mock_koji
    def test_find_srpm_name(self, mocked_koji):
        mocked_koji.add_build("bind-dyndb-ldap-2.3-8.el6")
        mocked_koji.add_build_rpms("bind-dyndb-ldap-2.3-8.el6")

        handler = ErrataAdvisoryRPMsSignedHandler()
        srpm_name = handler._find_build_srpm_name('bind-dyndb-ldap-2.3-8.el6')
        self.assertEqual('bind-dyndb-ldap', srpm_name)

    @helpers.mock_koji
    def test_error_if_no_srpm_in_build(self, mocked_koji):
        mocked_koji.add_build("bind-dyndb-ldap-2.3-8.el6")
        mocked_koji.add_build_rpms("bind-dyndb-ldap-2.3-8.el6", arches=["i686"])

        handler = ErrataAdvisoryRPMsSignedHandler()

        self.assertRaisesRegexp(
            ValueError,
            'Build bind-dyndb-ldap-2.3-8.el6 does not have a SRPM',
            handler._find_build_srpm_name,
            'bind-dyndb-ldap-2.3-8.el6',
        )


class TestAllowBuild(helpers.ModelsTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler.allow_build"""

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "ErrataAdvisoryRPMsSignedHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_false(self, handler_build_whitelist, record_images):
        """
        Tests that allow_build filters out advisories based on advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_not_called()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_images_to_rebuild", return_value=[])
    @patch("freshmaker.config.Config.handler_build_whitelist",
           new_callable=PropertyMock, return_value={
               "ErrataAdvisoryRPMsSignedHandler": {"image": {"advisory_name": "RHSA-.*"}}})
    def test_allow_build_true(self, handler_build_whitelist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_name.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"))
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_called_once()
        self.assertEqual(handler.current_db_event_id, 1)

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ],
                    "image_name": "foo",
                }
            }
        })
    def test_allow_security_impact_important_true(
            self, handler_build_whitelist, record_images):
        """
        Tests that allow_build does not filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="Important",
                           product_short_name="product"))
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_called_once()

    @patch("freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler."
           "_find_images_to_rebuild", return_value=[])
    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": {
                    "advisory_security_impact": [
                        "Normal", "Important"
                    ]
                }
            }
        })
    def test_allow_security_impact_important_false(
            self, handler_build_whitelist, record_images):
        """
        Tests that allow_build dost filter out advisories based on
        advisory_security_impact.
        """
        event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.handle(event)

        record_images.assert_not_called()

    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": {
                    "image_name": ["foo", "bar"]
                }
            }
        })
    def test_filter_out_not_allowed_builds(
            self, handler_build_whitelist):
        """
        Tests that allow_build does filter images based on image_name.
        """

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = {"brew": {"build": "foo-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "foo2-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "bar-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "unknown-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)

    @patch(
        "freshmaker.config.Config.handler_build_whitelist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": {
                    "image_name": ["foo", "bar"],
                    "advisory_name": "RHSA-.*",
                }
            }
        })
    def test_filter_out_image_name_and_advisory_name(
            self, handler_build_whitelist):
        """
        Tests that allow_build does filter images based on image_name.
        """

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = {"brew": {"build": "foo-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "unknown-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)


class TestBatches(helpers.ModelsTestCase):
    """Test handling of batches"""

    def setUp(self):
        super(TestBatches, self).setUp()
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.')
        self.should_generate_yum_repourls = self.patcher.patch(
            '_should_generate_yum_repourls', return_value=True)

    def tearDown(self):
        self.patcher.unpatch_all()

    def _mock_build(self, build, parent=None, error=None):
        if parent:
            parent = {"brew": {"build": parent + "-1-1.25"}}
        return ContainerImage({
            'brew': {'build': build + "-1-1.25"},
            'repository': build + '_repo',
            'parsed_data': {
                'layers': [
                    'sha512:1234',
                    'sha512:4567',
                    'sha512:7890',
                ],
            },
            'commit': build + '_123',
            'parent': parent,
            "target": "t1",
            'git_branch': 'mybranch',
            "error": error,
            "content_sets": ["first-content-set"]
        })

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.create_odcs_client')
    def test_batches_records(self, create_odcs_client):
        """
        Tests that batches are properly recorded in DB.
        """
        odcs = create_odcs_client.return_value
        # There are 8 mock builds below and each of them requires one pulp
        # compose.
        composes = [{
            'id': compose_id,
            'result_repofile': 'http://localhost/{}.repo'.format(compose_id),
            'state_name': 'done'
        } for compose_id in range(1, 9)]
        odcs.new_compose.side_effect = composes
        odcs.get_compose.side_effect = composes

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
                   [self._mock_build("child1_parent1", "child1_parent2", error="Fail"),
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
            # child1_parent1 and child1 are in FAILED states, because LB failed
            # to resolve child1_parent1 and therefore also child1 cannot be
            # build.
            if build.name in ["child1_parent1", "child1"]:
                self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            else:
                self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)
            self.assertEqual(build.type, ArtifactType.IMAGE.value)

            image = images[build.original_nvr]
            if image['parent']:
                self.assertEqual(build.dep_on.original_nvr, image['parent']['brew']['build'])
            else:
                self.assertEqual(build.dep_on, None)

            args = json.loads(build.build_args)
            self.assertEqual(args["repository"], build.name + "_repo")
            self.assertEqual(args["commit"], build.name + "_123")
            self.assertEqual(args["parent"],
                             build.dep_on.rebuilt_nvr if build.dep_on else None)


class TestCheckImagesToRebuild(helpers.ModelsTestCase):
    """Test handling of batches"""

    def setUp(self):
        super(TestCheckImagesToRebuild, self).setUp()

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

        self.ev = Event.create(db.session, 'msg-id', '123',
                               EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent])
        self.b1 = ArtifactBuild.create(
            db.session, self.ev, "parent", "image",
            state=ArtifactBuildState.PLANNED,
            original_nvr="parent-1-25")
        self.b1.build_args = build_args
        self.b2 = ArtifactBuild.create(
            db.session, self.ev, "child", "image",
            state=ArtifactBuildState.PLANNED,
            dep_on=self.b1,
            original_nvr="child-1-25")
        self.b2.build_args = build_args
        db.session.commit()

    def test_check_images_to_rebuild(self):
        builds = {
            "parent-1-25": self.b1,
            "child-1-25": self.b2
        }

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.PLANNED.value)

    def test_check_images_to_rebuild_missing_dep(self):
        # Do not include child nvr here to test that _check_images_to_rebuild
        # sets the state of event to failed.
        builds = {
            "parent-1-25": self.b1
        }

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)

    def test_check_images_to_rebuild_extra_build(self):
        builds = {
            "parent-1-25": self.b1,
            "child-1-25": self.b2,
            "something-1-25": self.b1,
        }

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.set_context(self.ev)
        handler._check_images_to_rebuild(self.ev, builds)

        # Check that the images have proper data in proper db columns.
        e = db.session.query(Event).filter(Event.id == 1).one()
        for build in e.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)


class TestGetPackagesForCompose(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose"""

    @helpers.mock_koji
    def test_get_packages(self, mocked_koji):
        build_nvr = 'chkconfig-1.7.2-1.el7_3.1'
        mocked_koji.add_build(build_nvr)
        mocked_koji.add_build_rpms(
            build_nvr,
            [build_nvr, "chkconfig-debuginfo-1.7.2-1.el7_3.1"])

        handler = ErrataAdvisoryRPMsSignedHandler()
        packages = handler._get_packages_for_compose(build_nvr)

        self.assertEqual(set(['chkconfig', 'chkconfig-debuginfo']),
                         set(packages))


class TestGetComposeSource(helpers.FreshmakerTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._get_compose_source"""

    @helpers.mock_koji
    def test_get_tag(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6")
        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag-candidate', tag)

    @helpers.mock_koji
    def test_get_None_if_tag_has_new_build(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6")
        mocked_koji.add_build("rh-postgresql96-3.0-10.el6")
        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual(None, tag)

    @helpers.mock_koji
    def test_get_tag_prefer_final_over_candidate(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6",
                              ["tag-candidate", "tag"])
        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag', tag)

    @helpers.mock_koji
    def test_get_tag_fallback_to_second_tag(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-10.el6",
                              ["tag"])
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6",
                              ["tag", "tag-candidate"])
        handler = ErrataAdvisoryRPMsSignedHandler()
        tag = handler._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag-candidate', tag)


class TestPrepareYumRepo(helpers.ModelsTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._prepare_yum_repo"""

    def setUp(self):
        super(TestPrepareYumRepo, self).setUp()

        self.ev = Event.create(db.session, 'msg-id', '123', 100)
        ArtifactBuild.create(
            db.session, self.ev, "parent", "image",
            state=ArtifactBuildState.PLANNED)
        db.session.commit()

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'create_odcs_client')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.Errata')
    def test_get_repo_url_when_succeed_to_generate_compose(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, create_odcs_client):
        odcs = create_odcs_client.return_value
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.return_value = 'rhel-7.2-candidate'
        odcs.new_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "result_repofile": "http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo",
            "source": "f26",
            "source_type": 1,
            "state": 0,
            "state_name": "wait",
        }

        errata.return_value.get_builds.return_value = set(["httpd-2.4.15-1.f27"])

        handler = ErrataAdvisoryRPMsSignedHandler()
        compose = handler._prepare_yum_repo(self.ev)

        db.session.refresh(self.ev)
        self.assertEqual(3, compose['id'])

        _get_compose_source.assert_called_once_with("httpd-2.4.15-1.f27")
        _get_packages_for_compose.assert_called_once_with("httpd-2.4.15-1.f27")

        # Ensure new_compose is called to request a new compose
        odcs.new_compose.assert_called_once_with(
            'rhel-7.2-candidate', 'tag', packages=['httpd', 'httpd-debuginfo'],
            sigkeys=[], flags=["no_deps"])

        # We should get the right repo URL eventually
        self.assertEqual(
            "http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo",
            compose['result_repofile'])

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'create_odcs_client')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.Errata')
    def test_get_repo_url_packages_in_multiple_tags(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, create_odcs_client):
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.side_effect = [
            'rhel-7.2-candidate', 'rhel-7.7-candidate']

        errata.return_value.get_builds.return_value = [
            set(["httpd-2.4.15-1.f27"]), set(["foo-2.4.15-1.f27"])]

        handler = ErrataAdvisoryRPMsSignedHandler()
        repo_url = handler._prepare_yum_repo(self.ev)

        create_odcs_client.return_value.new_compose.assert_not_called()
        self.assertEqual(repo_url, None)

        db.session.refresh(self.ev)
        for build in self.ev.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            self.assertEqual(build.state_reason, "Packages for errata "
                             "advisory 123 found in multiple different tags.")

    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'create_odcs_client')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_packages_for_compose')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.'
           'ErrataAdvisoryRPMsSignedHandler._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.handlers.errata.errata_advisory_rpms_signed.Errata')
    def test_get_repo_url_packages_not_found_in_tag(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, create_odcs_client):
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.return_value = None

        errata.return_value.get_builds.return_value = [
            set(["httpd-2.4.15-1.f27"]), set(["foo-2.4.15-1.f27"])]

        handler = ErrataAdvisoryRPMsSignedHandler()
        repo_url = handler._prepare_yum_repo(self.ev)

        create_odcs_client.return_value.new_compose.assert_not_called()
        self.assertEqual(repo_url, None)

        db.session.refresh(self.ev)
        for build in self.ev.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            self.assertTrue(build.state_reason.endswith(
                "of advisory 123 is the latest build in its candidate tag."))


class TestErrataAdvisoryStateChangedHandler(helpers.ModelsTestCase):

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists(self, advisories_from_event):
        handler = ErrataAdvisoryStateChangedHandler()

        for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
            advisories_from_event.return_value = [
                ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, "RHSA-2017", state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 1)
            self.assertEqual(ret[0].advisory.errata_id, 123)
            self.assertEqual(ret[0].advisory.security_impact, "Critical")
            self.assertEqual(ret[0].advisory.name, "RHSA-2017")

    @patch('freshmaker.errata.Errata.advisories_from_event')
    @patch.object(conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryStateChangedHandler': {
            'image': {
                'advisory_state': r'REL_PREP|SHIPPED_LIVE',
            }
        }
    })
    def test_rebuild_if_not_exists_unknown_states(
            self, advisories_from_event):
        handler = ErrataAdvisoryStateChangedHandler()

        for state in ["NEW_FILES", "QE", "UNKNOWN"]:
            advisories_from_event.return_value = [
                ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 0)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists_already_exists(
            self, advisories_from_event):
        handler = ErrataAdvisoryStateChangedHandler()

        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent)
        db.session.commit()

        for manual in [True, False]:
            for db_event_state in [
                    EventState.INITIALIZED, EventState.BUILDING,
                    EventState.COMPLETE, EventState.FAILED,
                    EventState.SKIPPED]:
                db_event.state = db_event_state
                db.session.commit()
                for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
                    advisories_from_event.return_value = [
                        ErrataAdvisory(123, "RHSA-2017", state, ["rpm"], "Critical")]
                    ev = ErrataAdvisoryStateChangedEvent(
                        "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
                    ev.manual = manual
                    ev.dry_run = manual  # use also manual just for the sake of test.
                    ret = handler.handle(ev)

                    if db_event_state == EventState.FAILED or ev.manual:
                        self.assertEqual(len(ret), 1)
                        self.assertEqual(ret[0].manual, manual)
                        self.assertEqual(ret[0].dry_run, manual)
                    else:
                        self.assertEqual(len(ret), 0)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_rebuild_if_not_exists_unknown_errata_id(
            self, advisories_from_event):
        advisories_from_event.return_value = []
        handler = ErrataAdvisoryStateChangedHandler()

        for state in ["REL_PREP", "PUSH_READY", "IN_PUSH", "SHIPPED_LIVE"]:
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, 'RHSA-2017', state, ['rpm']))
            ret = handler.handle(ev)

            self.assertEqual(len(ret), 0)

    def test_passing_dry_run(self):
        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]),
            dry_run=True)
        self.assertEqual(ev.dry_run, True)

        ev = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHBA-2017", "REL_PREP", [],
                           security_impact="",
                           product_short_name="product"),
            dry_run=True)
        self.assertEqual(ev.dry_run, True)

    def test_mark_as_released(self):
        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        self.assertEqual(db_event.released, False)

        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]))

        handler = ErrataAdvisoryStateChangedHandler()
        handler.handle(ev)

        db.session.refresh(db_event)
        self.assertEqual(db_event.released, True)

    def test_mark_as_released_wrong_advisory_status(self):
        db_event = Event.create(
            db.session, "msg124", "123", ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        for state in ["NEW_FILES", "QE", "REL_PREP", "PUSH_READY", "IN_PUSH"]:
            ev = ErrataAdvisoryStateChangedEvent(
                "msg123", ErrataAdvisory(123, "name", state, ['rpm']))

            handler = ErrataAdvisoryStateChangedHandler()
            handler.handle(ev)

            db.session.refresh(db_event)
            self.assertEqual(db_event.released, False)

    @patch('freshmaker.errata.Errata.advisories_from_event')
    def test_mark_as_released_unknown_event(self, advisories_from_event):
        ev = ErrataAdvisoryStateChangedEvent(
            "msg123", ErrataAdvisory(123, "name", "SHIPPED_LIVE", ["rpm"]))

        handler = ErrataAdvisoryStateChangedHandler()
        handler.handle(ev)

    @patch('freshmaker.handlers.errata.ErrataAdvisoryStateChangedHandler'
           '.rebuild_if_not_exists')
    @patch.object(conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryStateChangedHandler': {
            'image': {
                'advisory_state': r'REL_PREP',
            }
        }
    })
    def test_not_rebuild_if_errata_state_is_not_allowed(
            self, rebuild_if_not_exists):
        rebuild_if_not_exists.return_value = [Mock(), Mock()]

        Event.create(db.session, "msg-id-123", "123456",
                     ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-123',
            ErrataAdvisory(123456, 'name', 'SHIPPED_LIVE', ['rpm']))
        handler = ErrataAdvisoryStateChangedHandler()
        msgs = handler.handle(event)

        self.assertEqual([], msgs)

    @patch('freshmaker.handlers.errata.ErrataAdvisoryStateChangedHandler'
           '.rebuild_if_not_exists')
    @patch.object(conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryStateChangedHandler': {
            'image': {
                'advisory_state': r'REL_PREP',
            }
        }
    })
    def test_rebuild_if_errata_state_is_not_allowed_but_manual_is_true(
            self, rebuild_if_not_exists):
        rebuild_if_not_exists.return_value = [Mock()]

        Event.create(db.session, "msg-id-123", "123456",
                     ErrataAdvisoryRPMsSignedEvent, False)
        db.session.commit()

        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-123',
            ErrataAdvisory(123456, "name", 'SHIPPED_LIVE', ['rpm']))
        event.manual = True
        handler = ErrataAdvisoryStateChangedHandler()
        msgs = handler.handle(event)

        self.assertEqual(len(msgs), 1)


class TestRecordBatchesImages(helpers.ModelsTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._record_batches"""

    def setUp(self):
        super(TestRecordBatchesImages, self).setUp()

        self.mock_event = Mock(msg_id='msg-id', search_key=12345)

        self.patcher = helpers.Patcher(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.')

        self.mock_prepare_pulp_repo = self.patcher.patch(
            '_prepare_pulp_repo', side_effect=[{'id': 1}, {'id': 2}])

        self.mock_request_boot_iso_compose = self.patcher.patch(
            '_request_boot_iso_compose',
            side_effect=[{'id': 100}, {'id': 200}])

        self.should_generate_yum_repourls = self.patcher.patch(
            '_should_generate_yum_repourls', return_value=True)

        self.patcher.patch_dict(
            'freshmaker.models.EVENT_TYPES', {self.mock_event.__class__: -1})

    def tearDown(self):
        super(TestRecordBatchesImages, self).tearDown()
        self.patcher.unpatch_all()

    def test_record_batches(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:2345af2e293',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertNotEqual(None, parent_image)
        self.assertEqual(ArtifactBuildState.PLANNED.value, parent_image.state)

        # Check child image
        child_image = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertNotEqual(None, child_image)
        self.assertEqual(parent_image, child_image.dep_on)
        self.assertEqual(ArtifactBuildState.PLANNED.value, child_image.state)

    def test_record_batches_should_not_generate_pulp_repos(self):
        self.should_generate_yum_repourls.return_value = False
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        # Check parent image
        query = db.session.query(ArtifactBuild)
        parent_image = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertNotEqual(None, parent_image)
        self.assertEqual(ArtifactBuildState.PLANNED.value, parent_image.state)
        self.mock_prepare_pulp_repo.assert_not_called()

    @unittest.skip('Enable again when enable to request boot.iso compose')
    def test_pulp_compose_is_stored_for_each_build(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:2345af2e293',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": None
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        parent_build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertEqual(2, len(parent_build.composes))
        compose_ids = sorted([rel.compose.odcs_compose_id
                              for rel in parent_build.composes])
        # Ensure both pulp compose id and boot.iso compose id are stored
        self.assertEqual([1, 100], compose_ids)

        child_build = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertEqual(1, len(child_build.composes))
        self.assertEqual(2, child_build.composes[0].compose.odcs_compose_id)

        self.mock_prepare_pulp_repo.assert_has_calls([
            call(child_build.event, ["content-set-1"]),
            call(child_build.event, ["content-set-1"])
        ])

        self.mock_request_boot_iso_compose.assert_called_once_with(
            batches[0][0])

    def test_no_parent(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occurs while getting this image."
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()

        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_failed_state_if_image_has_error(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occurs while getting this image."
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()

        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_state_failed_if_depended_image_is_failed(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured."
            })],
            [ContainerImage({
                "brew": {
                    "build": "rh-dotnetcore10-docker-1.0-16",
                    "package": "rh-dotnetcore10-docker",
                    "completion_date": "20170511T10:06:09.000-0400"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:378a8ef2730',
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": ContainerImage({
                    "brew": {
                        "completion_date": "20170420T17:05:37.000-0400",
                        "build": "rhel-server-docker-7.3-82",
                        "package": "rhel-server-docker"
                    },
                    'parsed_data': {
                        'layers': [
                            'sha512:12345678980',
                            'sha512:10987654321'
                        ]
                    },
                    "parent": None,
                    "content_sets": ["content-set-1"],
                    "repository": "repo-1",
                    "commit": "123456789",
                    "target": "target-candidate",
                    "git_branch": "rhel-7",
                    "error": None
                }),
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "987654321",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured too."
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

        build = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

    def test_mark_base_image_failed_if_fail_to_request_boot_iso_compose(self):
        batches = [
            [ContainerImage({
                "brew": {
                    "completion_date": "20170420T17:05:37.000-0400",
                    "build": "rhel-server-docker-7.3-82",
                    "package": "rhel-server-docker"
                },
                'parsed_data': {
                    'layers': [
                        'sha512:12345678980',
                        'sha512:10987654321'
                    ]
                },
                "parent": None,
                "content_sets": ["content-set-1"],
                "repository": "repo-1",
                "commit": "123456789",
                "target": "target-candidate",
                "git_branch": "rhel-7",
                "error": "Some error occured."
            })],
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        build = db.session.query(ArtifactBuild).filter_by(
            original_nvr='rhel-server-docker-7.3-82').first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

        # Pulp repo should not be prepared for FAILED build.
        self.mock_prepare_pulp_repo.assert_not_called()


class TestPrepareYumReposForRebuilds(helpers.ModelsTestCase):
    """Test ErrataAdvisoryRPMsSignedHandler._prepare_yum_repos_for_rebuilds"""

    def setUp(self):
        super(TestPrepareYumReposForRebuilds, self).setUp()

        self.patcher = helpers.Patcher(
            'freshmaker.handlers.errata.errata_advisory_rpms_signed.'
            'ErrataAdvisoryRPMsSignedHandler.')

        self.mock_prepare_yum_repo = self.patcher.patch(
            '_prepare_yum_repo',
            side_effect=[
                {'id': 1, 'result_repofile': 'http://localhost/repo/1'},
                {'id': 2, 'result_repofile': 'http://localhost/repo/2'},
                {'id': 3, 'result_repofile': 'http://localhost/repo/3'},
                {'id': 4, 'result_repofile': 'http://localhost/repo/4'},
            ])

        self.mock_find_dependent_event = self.patcher.patch(
            'freshmaker.models.Event.find_dependent_events')

        self.db_event = Event.create(
            db.session, 'msg-1', 'search-key-1',
            EVENT_TYPES[ErrataAdvisoryRPMsSignedEvent],
            state=EventState.INITIALIZED,
            released=False)
        self.build_1 = ArtifactBuild.create(
            db.session, self.db_event, 'build-1', ArtifactType.IMAGE)
        self.build_2 = ArtifactBuild.create(
            db.session, self.db_event, 'build-2', ArtifactType.IMAGE)

        db.session.commit()

    def tearDown(self):
        super(TestPrepareYumReposForRebuilds, self).tearDown()
        self.patcher.unpatch_all()

    def test_prepare_without_dependent_events(self):
        self.mock_find_dependent_event.return_value = []

        handler = ErrataAdvisoryRPMsSignedHandler()
        urls = handler._prepare_yum_repos_for_rebuilds(self.db_event)

        self.assertEqual(1, self.build_1.composes[0].compose.id)
        self.assertEqual(1, self.build_2.composes[0].compose.id)
        self.assertEqual(['http://localhost/repo/1'], urls)

    def test_prepare_with_dependent_events(self):
        self.mock_find_dependent_event.return_value = [
            Mock(), Mock(), Mock()
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        urls = handler._prepare_yum_repos_for_rebuilds(self.db_event)

        odcs_compose_ids = [rel.compose.id for rel in self.build_1.composes]
        self.assertEqual([1, 2, 3, 4], sorted(odcs_compose_ids))

        odcs_compose_ids = [rel.compose.id for rel in self.build_2.composes]
        self.assertEqual([1, 2, 3, 4], sorted(odcs_compose_ids))

        self.assertEqual([
            'http://localhost/repo/1',
            'http://localhost/repo/2',
            'http://localhost/repo/3',
            'http://localhost/repo/4',
        ], sorted(urls))


class TestSkipNonRPMAdvisory(helpers.FreshmakerTestCase):

    def test_ensure_to_handle_rpm_adivsory(self):
        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-1',
            ErrataAdvisory(123, 'name', 'REL_PREP', ['rpm', 'jar', 'pom']))
        handler = ErrataAdvisoryStateChangedHandler()
        self.assertTrue(handler.can_handle(event))

    def test_not_handle_non_rpm_advisory(self):
        event = ErrataAdvisoryStateChangedEvent(
            'msg-id-1', ErrataAdvisory(123, 'name', 'REL_PREP', ['docker']))
        handler = ErrataAdvisoryStateChangedHandler()
        self.assertFalse(handler.can_handle(event))
