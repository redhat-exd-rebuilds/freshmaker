# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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
#            Jan kaluza <jkaluza@redhat.com>

from unittest.mock import patch, Mock
from odcs.client.odcs import AuthMech

from freshmaker import conf, db
from freshmaker.lightblue import ContainerImage
from freshmaker.models import Event, ArtifactBuild, Compose
from freshmaker.odcsclient import create_odcs_client
from freshmaker.types import ArtifactBuildState, EventState, ArtifactType
from freshmaker.handlers import ContainerBuildHandler
from tests import helpers


class MyHandler(ContainerBuildHandler):
    """Handler for running tests to test things defined in parents"""

    name = "MyHandler"

    def can_handle(self, event):
        """Implement BaseHandler method"""

    def handle(self, event):
        """Implement BaseHandler method"""


class TestCreateODCSClient(helpers.FreshmakerTestCase):
    """Test odcsclient.create_odcs_client"""

    @patch.object(conf, 'odcs_auth_mech', new='kerberos')
    @patch('freshmaker.odcsclient.RetryingODCS')
    def test_create_with_kerberos_auth(self, ODCS):
        odcs = create_odcs_client()

        self.assertEqual(ODCS.return_value, odcs)
        ODCS.assert_called_once_with(
            conf.odcs_server_url,
            auth_mech=AuthMech.Kerberos,
            verify_ssl=conf.odcs_verify_ssl)

    @patch.object(conf, 'odcs_auth_mech', new='fas')
    def test_error_if_unsupported_auth_configured(self):
        self.assertRaisesRegex(
            ValueError, r'.*fas is not supported yet.',
            create_odcs_client)

    @patch.object(conf, 'odcs_auth_mech', new='openidc')
    @patch.object(conf, 'odcs_openidc_token', new='12345')
    @patch('freshmaker.odcsclient.RetryingODCS')
    def test_create_with_openidc_auth(self, ODCS):
        odcs = create_odcs_client()

        self.assertEqual(ODCS.return_value, odcs)
        ODCS.assert_called_once_with(
            conf.odcs_server_url,
            auth_mech=AuthMech.OpenIDC,
            openidc_token='12345',
            verify_ssl=conf.odcs_verify_ssl)

    @patch.object(conf, 'odcs_auth_mech', new='openidc')
    def test_error_if_missing_openidc_token(self):
        self.assertRaisesRegex(
            ValueError, r'Missing OpenIDC token.*',
            create_odcs_client)


class TestGetPackagesForCompose(helpers.FreshmakerTestCase):
    """Test MyHandler._get_packages_for_compose"""

    @helpers.mock_koji
    def test_get_packages(self, mocked_koji):
        build_nvr = 'chkconfig-1.7.2-1.el7_3.1'
        mocked_koji.add_build(build_nvr)
        mocked_koji.add_build_rpms(
            build_nvr,
            [build_nvr, "chkconfig-debuginfo-1.7.2-1.el7_3.1"])

        handler = MyHandler()
        packages = handler.odcs._get_packages_for_compose(build_nvr)

        self.assertEqual(set(['chkconfig', 'chkconfig-debuginfo']),
                         set(packages))


class TestGetComposeSource(helpers.FreshmakerTestCase):
    """Test MyHandler._get_compose_source"""

    @helpers.mock_koji
    def test_get_tag(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6")
        handler = MyHandler()
        tag = handler.odcs._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag-candidate', tag)

    @helpers.mock_koji
    def test_get_None_if_tag_has_new_build(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6")
        mocked_koji.add_build("rh-postgresql96-3.0-10.el6")
        handler = MyHandler()
        tag = handler.odcs._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual(None, tag)

    @helpers.mock_koji
    def test_get_tag_prefer_final_over_candidate(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6",
                              ["tag-candidate", "tag"])
        handler = MyHandler()
        tag = handler.odcs._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag', tag)

    @helpers.mock_koji
    def test_get_tag_fallback_to_second_tag(self, mocked_koji):
        mocked_koji.add_build("rh-postgresql96-3.0-10.el6",
                              ["tag"])
        mocked_koji.add_build("rh-postgresql96-3.0-9.el6",
                              ["tag", "tag-candidate"])
        handler = MyHandler()
        tag = handler.odcs._get_compose_source('rh-postgresql96-3.0-9.el6')
        self.assertEqual('tag-candidate', tag)


class TestPrepareYumRepo(helpers.ModelsTestCase):
    """Test MyHandler._prepare_yum_repo"""

    def setUp(self):
        super(TestPrepareYumRepo, self).setUp()

        self.ev = Event.create(db.session, 'handler', 'msg-id', '123', 100)
        ArtifactBuild.create(
            db.session, self.ev, "parent", "image",
            state=ArtifactBuildState.PLANNED)
        db.session.commit()

    @patch('freshmaker.odcsclient.create_odcs_client')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_packages_for_compose')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.odcsclient.Errata')
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

        errata.return_value.get_srpm_nvrs.return_value = set(["httpd-2.4.15-1.f27"])

        handler = MyHandler()
        compose = handler.odcs.prepare_yum_repo(self.ev)

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

    @patch('freshmaker.odcsclient.create_odcs_client')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_packages_for_compose')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.odcsclient.Errata')
    def test_get_repo_url_packages_in_multiple_tags(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, create_odcs_client):
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.side_effect = [
            'rhel-7.2-candidate', 'rhel-7.7-candidate']

        errata.return_value.get_srpm_nvrs.return_value = [
            set(["httpd-2.4.15-1.f27"]), set(["foo-2.4.15-1.f27"])]

        handler = MyHandler()
        repo_url = handler.odcs.prepare_yum_repo(self.ev)

        create_odcs_client.return_value.new_compose.assert_not_called()
        self.assertEqual(repo_url, None)

        db.session.refresh(self.ev)
        for build in self.ev.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            self.assertEqual(build.state_reason, "Packages for errata "
                             "advisory 123 found in multiple different tags.")

    @patch('freshmaker.odcsclient.create_odcs_client')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_packages_for_compose')
    @patch('freshmaker.odcsclient.FreshmakerODCSClient._get_compose_source')
    @patch('time.sleep')
    @patch('freshmaker.odcsclient.Errata')
    def test_get_repo_url_packages_not_found_in_tag(
            self, errata, sleep, _get_compose_source,
            _get_packages_for_compose, create_odcs_client):
        _get_packages_for_compose.return_value = ['httpd', 'httpd-debuginfo']
        _get_compose_source.return_value = None

        errata.return_value.get_srpm_nvrs.return_value = [
            set(["httpd-2.4.15-1.f27"]), set(["foo-2.4.15-1.f27"])]

        handler = MyHandler()
        repo_url = handler.odcs.prepare_yum_repo(self.ev)

        create_odcs_client.return_value.new_compose.assert_not_called()
        self.assertEqual(repo_url, None)

        db.session.refresh(self.ev)
        for build in self.ev.builds:
            self.assertEqual(build.state, ArtifactBuildState.FAILED.value)
            self.assertTrue(build.state_reason.endswith(
                "of advisory 123 is the latest build in its candidate tag."))

    def _get_fake_container_image(self, architecture='amd64', arches='x86_64'):
        rpm_manifest = [{u'rpms': [{
            u'architecture': architecture,
            u'gpg': u'199e2f91fd431d51',
            u'name': u'apache-commons-lang',
            u'nvra': u'apache-commons-lang-2.6-15.el7.noarch',
            u'release': u'15.el7',
            u'srpm_name': u'apache-commons-lang',
            u'srpm_nevra': u'apache-commons-lang-0:2.6-15.el7.src',
            u'summary': u'Provides a host of helper utilities for the java.lang API',
            u'version': u'2.6'
        }, {
            u'architecture': architecture,
            u'gpg': u'199e2f91fd431d51',
            u'name': u'avalon-logkit',
            u'nvra': u'avalon-logkit-2.1-14.el7.noarch',
            u'release': u'14.el7',
            u'srpm_name': u'avalon-logkit',
            u'srpm_nevra': u'avalon-logkit-0:2.1-14.el7.src',
            u'summary': u'Java logging toolkit',
            u'version': u'2.1'
        }]}]
        return ContainerImage.create({
            u'arches': arches,  # Populated based on Brew build
            u'architecture': architecture,  # Populated from Lightblue data
            u'rpm_manifest': rpm_manifest,
        })

    @patch('freshmaker.odcsclient.create_odcs_client')
    @patch('time.sleep')
    def test_prepare_odcs_compose_with_image_rpms(
            self, sleep, create_odcs_client):
        odcs = create_odcs_client.return_value
        odcs.new_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "result_repofile": "http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo",
            "source": "f26",
            "source_type": 1,
            "state": 0,
            "state_name": "wait",
        }

        image = self._get_fake_container_image()

        handler = MyHandler()
        compose = handler.odcs.prepare_odcs_compose_with_image_rpms(image)

        db.session.refresh(self.ev)
        self.assertEqual(3, compose['id'])

        # Ensure new_compose is called to request a new compose
        odcs.new_compose.assert_called_once_with(
            '', 'build', builds=['apache-commons-lang-2.6-15.el7', 'avalon-logkit-2.1-14.el7'],
            flags=['no_deps'], packages=[u'apache-commons-lang', u'avalon-logkit'], sigkeys=[],
            arches=['x86_64'])

    @patch('freshmaker.odcsclient.create_odcs_client')
    @patch('time.sleep')
    def test_prepare_odcs_compose_with_multi_arch_image_rpms(
            self, sleep, create_odcs_client):
        odcs = create_odcs_client.return_value
        odcs.new_compose.return_value = {
            "id": 3,
            "result_repo": "http://localhost/composes/latest-odcs-3-1/compose/Temporary",
            "result_repofile": "http://localhost/composes/latest-odcs-3-1/compose/Temporary/odcs-3.repo",
            "source": "f26",
            "source_type": 1,
            "state": 0,
            "state_name": "wait",
        }

        arches = 's390x x86_64'
        image_x86_64 = self._get_fake_container_image(architecture='amd64', arches=arches)
        image_s390x = self._get_fake_container_image(architecture='s390x', arches=arches)

        for image in (image_x86_64, image_s390x):
            handler = MyHandler()
            compose = handler.odcs.prepare_odcs_compose_with_image_rpms(image)

            db.session.refresh(self.ev)
            self.assertEqual(3, compose['id'])

            # Ensure new_compose is called to request a new multi-arch
            # compose regardless of which image is used.
            odcs.new_compose.assert_called_once_with(
                '', 'build', builds=['apache-commons-lang-2.6-15.el7', 'avalon-logkit-2.1-14.el7'],
                flags=['no_deps'], packages=[u'apache-commons-lang', u'avalon-logkit'], sigkeys=[],
                arches=['s390x', 'x86_64'])

            odcs.reset_mock()

    @patch("freshmaker.consumer.get_global_consumer")
    def test_prepare_odcs_compose_with_image_rpms_dry_run(self, global_consumer):
        consumer = self.create_consumer()
        global_consumer.return_value = consumer
        image = self._get_fake_container_image()

        # Run multiple times, so we can verify that id of fake compose is set
        # properly and is not repeating.
        for i in range(1, 3):
            handler = MyHandler()
            handler.force_dry_run()
            compose = handler.odcs.prepare_odcs_compose_with_image_rpms(image)
            db_compose = Compose(odcs_compose_id=compose['id'])
            db.session.add(db_compose)
            db.session.commit()

            self.assertEqual(-i, compose['id'])
            event = consumer.incoming.get()
            self.assertEqual(event.msg_id, "fake_compose_msg")

    def test_prepare_odcs_compose_with_image_rpms_no_rpm_manifest(self):
        handler = MyHandler()

        compose = handler.odcs.prepare_odcs_compose_with_image_rpms({})
        self.assertEqual(compose, None)

        compose = handler.odcs.prepare_odcs_compose_with_image_rpms(
            {"multi_arch_rpm_manifest": {}})
        self.assertEqual(compose, None)

        compose = handler.odcs.prepare_odcs_compose_with_image_rpms(
            {"multi_arch_rpm_manifest": {
                "amd64": [],
            }})
        self.assertEqual(compose, None)

        compose = handler.odcs.prepare_odcs_compose_with_image_rpms(
            {"multi_arch_rpm_manifest": {
                "amd64": [{"rpms": []}],
            }})
        self.assertEqual(compose, None)


class TestPrepareYumReposForRebuilds(helpers.ModelsTestCase):
    """Test MyHandler._prepare_yum_repos_for_rebuilds"""

    def setUp(self):
        super(TestPrepareYumReposForRebuilds, self).setUp()

        self.patcher = helpers.Patcher()

        self.mock_prepare_yum_repo = self.patcher.patch(
            'freshmaker.odcsclient.FreshmakerODCSClient.prepare_yum_repo',
            side_effect=[
                {'id': 1, 'result_repofile': 'http://localhost/repo/1'},
                {'id': 2, 'result_repofile': 'http://localhost/repo/2'},
                {'id': 3, 'result_repofile': 'http://localhost/repo/3'},
                {'id': 4, 'result_repofile': 'http://localhost/repo/4'},
            ])

        self.mock_find_dependent_event = self.patcher.patch(
            'freshmaker.models.Event.find_dependent_events')

        self.db_event = Event.create(
            db.session, 'handler', 'msg-1', 'search-key-1', 1,
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

        handler = MyHandler()
        urls = handler.odcs.prepare_yum_repos_for_rebuilds(self.db_event)

        self.assertEqual(1, self.build_1.composes[0].compose.id)
        self.assertEqual(1, self.build_2.composes[0].compose.id)
        self.assertEqual(['http://localhost/repo/1'], urls)

    def test_prepare_with_dependent_events(self):
        self.mock_find_dependent_event.return_value = [
            Mock(), Mock(), Mock()
        ]

        handler = MyHandler()
        urls = handler.odcs.prepare_yum_repos_for_rebuilds(self.db_event)

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
