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

import json
import six

from mock import patch, PropertyMock, Mock, call

from freshmaker import conf, db, events
from freshmaker.config import all_
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

        six.assertRaisesRegex(
            self,
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
    @patch(
        "freshmaker.config.Config.handler_build_blacklist",
        new_callable=PropertyMock,
        return_value={
            "ErrataAdvisoryRPMsSignedHandler": {
                "image": all_(
                    {
                        "image_name": "foo",
                        "image_version": "7.3",
                    }
                )
            }
        })
    def test_filter_out_not_allowed_builds_image_version(
            self, handler_build_blacklist, handler_build_whitelist):
        handler = ErrataAdvisoryRPMsSignedHandler()
        handler.event = ErrataAdvisoryRPMsSignedEvent(
            "123",
            ErrataAdvisory(123, "RHSA-2017", "REL_PREP", [],
                           security_impact="None",
                           product_short_name="product"))

        image = {"brew": {"build": "foo-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "foo-1-7.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, False)

        image = {"brew": {"build": "foo-7.3-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)

        image = {"brew": {"build": "unknown-1-2.3"}}
        ret = handler._filter_out_not_allowed_builds(image)
        self.assertEqual(ret, True)


class TestBatches(helpers.ModelsTestCase):
    """Test handling of batches"""

    def setUp(self):
        super(TestBatches, self).setUp()
        self.patcher = helpers.Patcher(
            'freshmaker.handlers.errata.ErrataAdvisoryRPMsSignedHandler.')

    def tearDown(self):
        super(TestBatches, self).tearDown()
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
            "content_sets": ["first-content-set"],
            "generate_pulp_repos": True,
            "arches": "x86_64",
            "odcs_compose_ids": [10, 11],
            "published": False,
        })

    @patch('freshmaker.odcsclient.create_odcs_client')
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
            self.assertEqual(args["renewed_odcs_compose_ids"],
                             [10, 11])


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
    @patch.object(conf, 'handler_build_whitelist', new={
        'ErrataAdvisoryStateChangedHandler': {
            'image': {
                'advisory_state': '.*',
            }
        }
    })
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
                'advisory_state': r'SHIPPED_LIVE',
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
            'freshmaker.odcsclient.FreshmakerODCSClient.prepare_pulp_repo',
            side_effect=[{'id': 1}, {'id': 2}])

        self.patcher.patch_dict(
            'freshmaker.models.EVENT_TYPES', {self.mock_event.__class__: 0})

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
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": None,
                "generate_pulp_repos": True,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": None,
                "generate_pulp_repos": False,
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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

    def test_pulp_compose_generated_just_once(self):
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
                "error": None,
                "arches": "x86_64",
                "generate_pulp_repos": True,
                "odcs_compose_ids": None,
                "published": False,
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
                "error": None,
                "arches": "x86_64",
                "generate_pulp_repos": True,
                "odcs_compose_ids": None,
                "published": False,
            })]
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        query = db.session.query(ArtifactBuild)
        parent_build = query.filter(
            ArtifactBuild.original_nvr == 'rhel-server-docker-7.3-82'
        ).first()
        self.assertEqual(1, len(parent_build.composes))
        compose_ids = sorted([rel.compose.odcs_compose_id
                              for rel in parent_build.composes])
        self.assertEqual([1], compose_ids)

        child_build = query.filter(
            ArtifactBuild.original_nvr == 'rh-dotnetcore10-docker-1.0-16'
        ).first()
        self.assertEqual(1, len(child_build.composes))

        self.mock_prepare_pulp_repo.assert_has_calls([
            call(parent_build, ["content-set-1"])
        ])

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
                "error": "Some error occurs while getting this image.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": "Some error occurs while getting this image.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": "Some error occured.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": "Some error occured too.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
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
                "error": "Some error occured.",
                "arches": "x86_64",
                "odcs_compose_ids": None,
                "published": False,
            })],
        ]

        handler = ErrataAdvisoryRPMsSignedHandler()
        handler._record_batches(batches, self.mock_event)

        build = db.session.query(ArtifactBuild).filter_by(
            original_nvr='rhel-server-docker-7.3-82').first()
        self.assertEqual(ArtifactBuildState.FAILED.value, build.state)

        # Pulp repo should not be prepared for FAILED build.
        self.mock_prepare_pulp_repo.assert_not_called()


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
