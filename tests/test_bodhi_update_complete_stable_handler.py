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

import mock
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # noqa
from tests import helpers
from tests import get_fedmsg

from freshmaker import events, db, models
from freshmaker.types import ArtifactType
from freshmaker.handlers.bodhi import BodhiUpdateCompleteStableHandler
from freshmaker.parsers.bodhi import BodhiUpdateCompleteStableParser

mock_found_containers = [
    {
        'release': 'fedora-25-updates',
        'id': 5430,
        'name': 'testimage1',
        'branch': 'f25',
    },
    {
        'release': 'fedora-25-updates',
        'id': 5431,
        'name': 'testimage2',
        'branch': 'f25',
    },
]

mock_release_components = {
    5430: {
        'id': 5430,
        'release': {
            'active': True,
            'release_id': 'fedora-25-updates'
        },
        'bugzilla_component': None,
        'brew_package': None,
        'global_component': 'testimage1',
        'name': 'testimage1',
        'dist_git_branch': 'f25',
        'dist_git_web_url': 'http://pkgs.example.com/cgit/container/testimage1',
        'active': True,
        'type': 'container',
        'srpm': None,
    },
    5431: {
        'id': 5431,
        'release': {
            'active': True,
            'release_id': 'fedora-25-updates'
        },
        'bugzilla_component': None,
        'brew_package': None,
        'global_component': 'testimage2',
        'name': 'testimage2',
        'dist_git_branch': 'f25',
        'dist_git_web_url': 'http://pkgs.example.com/cgit/container/testimage2',
        'active': True,
        'type': 'container',
        'srpm': None,
    }
}


def mock_get_release_component_by_id(id):
    return mock_release_components[id]


class BodhiUpdateCompleteStableHandlerTest(helpers.FreshmakerTestCase):
    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        db.session.commit()

        events.BaseEvent.register_parser(BodhiUpdateCompleteStableParser)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.session.commit()

    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.PDC')
    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.utils')
    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.conf')
    def test_trigger_rebuild_container_when_receives_bodhi_update_complete_stable_message(self, conf, utils, PDC):

        conf.git_base_url = 'git://pkgs.fedoraproject.org'

        handler = BodhiUpdateCompleteStableHandler()
        handler.get_rpms_included_in_bodhi_update = mock.Mock()

        handler.get_containers_including_rpms = mock.Mock()

        containers = [
            {
                'release': 'fedora-25-updates',
                'id': 5430,
                'name': 'testimage1',
                'branch': 'f25',
            },
            {
                'release': 'fedora-25-updates',
                'id': 5431,
                'name': 'testimage2',
                'branch': 'f25',
            },
        ]
        handler.get_containers_including_rpms.return_value = containers

        utils.get_commit_hash.side_effect = ['c123', 'c456']

        handler.build_container = mock.Mock()
        handler.build_container.side_effect = [123, 456]

        msg = get_fedmsg('bodhi_update_stable')
        event = self.get_event_from_msg(msg)
        self.assertTrue(handler.can_handle(event))
        handler.handle(event)

        self.assertEqual(
            handler.build_container.call_args_list,
            [mock.call(
                'git://pkgs.fedoraproject.org/container/testimage1.git?#c123',
                'f25', 'f25-container-candidate'),
             mock.call(
                'git://pkgs.fedoraproject.org/container/testimage2.git?#c456',
                'f25', 'f25-container-candidate')])

        events = models.Event.query.all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message_id, msg['body']['msg_id'])
        builds = models.ArtifactBuild.query.all()
        self.assertEqual(len(builds), 2)
        self.assertEqual(builds[0].name, 'testimage1')
        self.assertEqual(builds[0].type, ArtifactType.IMAGE.value)
        self.assertEqual(builds[0].build_id, 123)
        self.assertEqual(builds[1].name, 'testimage2')
        self.assertEqual(builds[1].type, ArtifactType.IMAGE.value)
        self.assertEqual(builds[1].build_id, 456)

    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.PDC')
    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.utils')
    @mock.patch('freshmaker.handlers.bodhi.update_complete_stable.conf')
    def test_get_containers_including_rpms(self, conf, utils, PDC):
        expected_found_containers = [
            {
                'release': 'fedora-24-updates',
                'id': 5430,
                'name': 'testimage1',
                'branch': 'f25',
            },
            {
                'release': 'fedora-24-updates',
                'id': 5431,
                'name': 'testimage2',
                'branch': 'f25',
            },
        ]
        pdc = PDC(conf)
        pdc.find_containers_by_rpm_name.return_value = expected_found_containers

        handler = BodhiUpdateCompleteStableHandler()
        rpms = [
            {'id': 9515683,
             'name': 'community-mysql-devel',
             'nvr': 'community-mysql-devel-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
            {'id': 9515682,
             'name': 'community-mysql-libs',
             'nvr': 'community-mysql-libs-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
            {'id': 9515681,
             'name': 'community-mysql-server',
             'nvr': 'community-mysql-server-5.7.18-2.fc25',
             'release': '2.fc25',
             'version': '5.7.18'},
        ]

        containers = handler.get_containers_including_rpms(rpms)

        self.assertEqual(3, pdc.find_containers_by_rpm_name.call_count)
        found_containers = sorted(containers, key=lambda item: item['id'])
        self.assertEqual(expected_found_containers, found_containers)

    @mock.patch('freshmaker.kojiservice.KojiService.get_build_rpms')
    def test_get_rpms_included_in_bohdhi_update(self, get_build_rpms):
        rpms = {
            'community-mysql-5.7.18-2.fc25': [
                {
                    'id': 9515683,
                    'name': 'community-mysql-devel',
                    'nvr': 'community-mysql-devel-5.7.18-2.fc25',
                    'release': '2.fc25',
                    'version': '5.7.18',
                },
                {
                    'id': 9515682,
                    'name': 'community-mysql-libs',
                    'nvr': 'community-mysql-libs-5.7.18-2.fc25',
                    'release': '2.fc25',
                    'version': '5.7.18',
                },
                {
                    'id': 9515681,
                    'name': 'community-mysql-server',
                    'nvr': 'community-mysql-server-5.7.18-2.fc25',
                    'release': '2.fc25',
                    'version': '5.7.18',
                },
            ],
            'qt5-qtwebengine-5.8.0-11.fc25': [
                {
                    'id': 9571317,
                    'name': 'qt5-qtwebengine-devel',
                    'nvr': 'qt5-qtwebengine-devel-5.8.0-11.fc25',
                    'release': '11.fc25',
                    'version': '5.8.0',
                },
                {
                    'id': 9571316,
                    'name': 'qt5-qtwebengine-examples',
                    'nvr': 'qt5-qtwebengine-examples-5.8.0-11.fc25',
                    'release': '11.fc25',
                    'version': '5.8.0',
                }
            ],
        }

        get_build_rpms.side_effect = lambda x: rpms[x]

        builds = [
            {
                'build_id': 884455,
                'name': 'qt5-qtwebengine',
                'nvr': 'qt5-qtwebengine-5.8.0-11.fc25',
                'release': '11.fc25',
                'version': '5.8.0',
            },
            {
                'build_id': 881597,
                'name': 'community-mysql',
                'nvr': 'community-mysql-5.7.18-2.fc25',
                'release': '2.fc25',
                'version': '5.7.18',
            }
        ]
        handler = BodhiUpdateCompleteStableHandler()
        rpms = list(handler.get_rpms_included_in_bodhi_update(builds))

        self.assertEqual(5, len(rpms))

        rpm = list(filter(lambda item: item['id'] == 9515681, rpms))
        self.assertEqual(1, len(rpm))
