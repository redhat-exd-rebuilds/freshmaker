# -*- coding: utf-8 -*-
# Copyright (c) 2021  Red Hat, Inc.
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
# Written by Valerij Maljulin <vmaljuli@redhat.com>
# Written by Chuang Zhang <chuazhan@redhat.com>

import requests
from http import HTTPStatus

from freshmaker import conf, db, log
from freshmaker.errata import Errata
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.models import Event
from freshmaker.pyxis import Pyxis
from freshmaker.types import EventState


class RebuildFlatpakApplicationOnModuleReady(ContainerBuildHandler):
    name = 'RebuildFlatpakApplicationOnModuleReady'

    def can_handle(self, event):
        return isinstance(event, FlatpakModuleAdvisoryReadyEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        TODO: Update in future.
        """

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        auto_build_images_list = self._get_auto_rebuild_image_list(event)
        if not auto_build_images_list:
            msg = ("There is no auto rebuild image can be rebuilt. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        rebuild_images = self._filter_images_with_higher_rpm_nvr(event, auto_build_images_list)
        if not rebuild_images:
            msg = ("There is no image with higher rpm nvr can be rebuilt. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

    def _get_auto_rebuild_image_list(self, event):
        """
        Get rebuild image list which can be auto rebuilt.

        :param event FlatpakModuleAdvisoryReadyEvent: The event this handler
            is currently handling.
        :rtype: list
        :return: List of images which can be auto rebuilt.
        """
        errata = Errata()
        module_nvrs = errata.get_cve_affected_build_nvrs(event.advisory.errata_id, True)
        rebuild_images_list = list()
        flatpak_server_url = "https://flatpaks.engineering.redhat.com"
        self._pyxis = Pyxis(conf.pyxis_server_url)

        with koji_service(conf.koji_profile, log, login=False, dry_run=self.dry_run) as session:
            for module_nvr in module_nvrs:
                mmd = session.get_modulemd(module_nvr)
                content_index_url = '{}/released/contents/modules/{}:{}.json'.format(flatpak_server_url,
                                                                                     mmd.get_module_name(),
                                                                                     mmd.get_stream_name())
                response = requests.get(content_index_url)
                status_code = response.status_code
                if status_code == HTTPStatus.OK:
                    images_info = response.json().get("Images", [])
                    for image_info in images_info:
                        image_nvr = image_info["ImageNvr"]
                        is_tagged_auto_build = self._pyxis.image_is_tagged_auto_rebuild(image_nvr)
                        if is_tagged_auto_build:
                            rebuild_images_list.append(image_nvr)

        return rebuild_images_list

    def _filter_images_with_higher_rpm_nvr(self, event, rebuild_images_list):
        """
        Filter out images which have higher nvr in rebuild_images_list than
        the advisory's.

        :param event FlatpakModuleAdvisoryReadyEvent: The event this handler
            is currently handling.
        :rtype: list
        :return: List of ContainerImage instances which can be auto rebuilt.
        """
        errata = Errata()
        errata_rpm_nvrs = errata.get_cve_affected_rpm_nvrs(event.advisory.errata_id)
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key,
                       event_id=self.current_db_event_id)
        images = lb.get_images_by_nvrs(rebuild_images_list, rpm_nvrs=errata_rpm_nvrs)
        return images
