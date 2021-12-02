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

import json
import koji
import requests
from odcs.common.types import PungiSourceType
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from freshmaker import conf, db, log
from freshmaker.errata import Errata
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.lightblue import LightBlue
from freshmaker.models import Event, Compose
from freshmaker.odcsclient import create_odcs_client
from freshmaker.pyxis import Pyxis
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState, RebuildReason


class RebuildFlatpakApplicationOnModuleReady(ContainerBuildHandler):
    # Module ready means Flatpak module advisory is in QE status
    # and all attached builds are signed.
    name = "RebuildFlatpakApplicationOnModuleReady"

    def can_handle(self, event):
        return isinstance(event, FlatpakModuleAdvisoryReadyEvent)

    @fail_event_on_handler_exception
    def handle(self, event):

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        self.errata = Errata()
        self.advisory_module_nvrs = self.errata.get_cve_affected_build_nvrs(
            event.advisory.errata_id, True
        )

        rebuild_images = []
        auto_build_image_modules_mapping = self._get_auto_rebuild_image_mapping()
        if auto_build_image_modules_mapping:
            images = list(auto_build_image_modules_mapping.keys())
            rebuild_images = self._filter_images_with_higher_rpm_nvr(images)
        if not auto_build_image_modules_mapping or not rebuild_images:
            msg = (
                "Images are not enabled for auto rebuild. "
                if not auto_build_image_modules_mapping
                else "No images are impacted by the advisory. "
            )
            msg = f"{msg} message_id: {event.msg_id}"
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        images_nvr = ",".join([rebuild_image.nvr for rebuild_image in rebuild_images])
        self.log_info("Following images %s will be rebuilt" % images_nvr)

        builds = self._record_builds(rebuild_images, auto_build_image_modules_mapping)
        if not builds:
            msg = "No container images to rebuild for advisory %r" % event.advisory.name
            self.log_info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

        # TODO: Return empty list so far as this method is still in progress.
        # Will think about whether to return the real BaseEvent objects in future.
        return []

    def _get_requests_session(cls, retry_options={}):
        """
        Create a requests session. Reference from:
        https://github.com/release-engineering/cachito/blob/master/cachito/workers/requests.py

        :param dict retry_options: overwrite options for initialization of Retry instance
        :return: the configured requests session
        :rtype: requests.Session
        """
        DEFAULT_RETRY_OPTIONS = {
            "total": 5,
            "read": 5,
            "connect": 5,
            "backoff_factor": 1.3,
            "status_forcelist": (500, 502, 503, 504),
        }
        session = requests.Session()
        retry_options = {**DEFAULT_RETRY_OPTIONS, **retry_options}
        adapter = HTTPAdapter(max_retries=Retry(**retry_options))
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_auto_rebuild_image_mapping(self):
        """
        Get rebuild image mapping which images can be auto rebuilt.

        :rtype: dict
        :return: A dict which key is the image which can be rebuilt
            and value are modules which are enabled in this image.
        """
        if not conf.pyxis_server_url:
            raise ValueError("'PYXIS_SERVER_URL' parameter should be set")
        self._pyxis = Pyxis(conf.pyxis_server_url)

        if not conf.flatpak_server_url:
            raise ValueError("'FLATPAK_SERVER_URL' parameter should be set")

        image_modules_mapping = {}
        req_session = self._get_requests_session()
        with koji_service(
            conf.koji_profile, log, login=False, dry_run=self.dry_run
        ) as session:
            for advisory_module_nvr in self.advisory_module_nvrs:
                mmd = session.get_modulemd(advisory_module_nvr)
                content_index_url = "{}/released/contents/modules/{}:{}.json".format(
                    conf.flatpak_server_url,
                    mmd.get_module_name(),
                    mmd.get_stream_name(),
                )
                response = req_session.get(content_index_url)
                if response.ok:
                    images_info = response.json().get("Images", [])
                    for image_info in images_info:
                        image_nvr = image_info["ImageNvr"]
                        is_tagged_auto_build = self._pyxis.image_is_tagged_auto_rebuild(
                            image_nvr
                        )
                        if is_tagged_auto_build:
                            image_modules_mapping.setdefault(image_nvr, [])
                            if (
                                advisory_module_nvr
                                not in image_modules_mapping[image_nvr]
                            ):
                                image_modules_mapping[image_nvr].append(
                                    advisory_module_nvr
                                )
                else:
                    self.log_error(
                        "Fetching module %s data failed.", advisory_module_nvr
                    )

        return image_modules_mapping

    def _filter_images_with_higher_rpm_nvr(self, images):
        """
        Filter out images which have higher NVR in rebuild_images than
        the advisory's.

        :param images list: A list of image NVRS.
        :return: a list of ContainerImage instances which can be auto rebuilt.
        :rtype: list
        """
        errata_rpm_nvrs = self.errata.get_cve_affected_rpm_nvrs(
            self.event.advisory.errata_id
        )
        lb = LightBlue(
            server_url=conf.lightblue_server_url,
            cert=conf.lightblue_certificate,
            private_key=conf.lightblue_private_key,
            event_id=self.current_db_event_id,
        )
        images = lb.get_images_by_nvrs(images, rpm_nvrs=errata_rpm_nvrs)
        return images

    def _outdated_composes(self, original_odcs_compose_ids, module_name_stream_set):
        """
        Generate outdated composes.

        :param original_odcs_compose_ids list: Original compose ids.
        :param module_name_stream_set set: Module name stream set from an advisory.
        :return: a set of outdated composes.
        :rtype: set
        """
        outdated_composes = set()
        for compose_id in original_odcs_compose_ids:
            compose = self.odcs.get_compose(compose_id)
            source_type = compose.get("source_type")
            if source_type != PungiSourceType.MODULE:
                outdated_composes.add(compose_id)
                continue

            name_stream_set = {f"{n}:{s}" for n, s, v, c in _compose_sources(compose)}

            if name_stream_set.isdisjoint(module_name_stream_set):
                outdated_composes.add(compose_id)

        return outdated_composes

    def _missing_composes(
        self,
        original_odcs_compose_ids,
        module_name_stream_set,
        module_name_stream_version_set,
    ):
        """
        Generate missing composes.

        :param original_odcs_compose_ids list: Original compose ids.
        :param module_name_stream_set set: Module name stream set from an advisory.
        :param module_name_stream_version_set set: Module name stream version set from an advisory.
        :return: a set of missing composes.
        :rtype: set
        """
        missing_composes = set()
        for compose_id in original_odcs_compose_ids:
            compose = self.odcs.get_compose(compose_id)
            source_type = compose.get("source_type")
            if source_type == PungiSourceType.MODULE:
                name_stream_set = {f"{n}:{s}" for n, s, v, c in _compose_sources(compose)}
                mapping = {f"{n}:{s}": f"{n}:{s}:{v}" for n, s, v, c in _compose_sources(compose)}

                if not name_stream_set.isdisjoint(module_name_stream_set):
                    missing_composes.update(
                        mapping[name_stream]
                        for name_stream in name_stream_set.difference(module_name_stream_set)
                    )
                missing_composes.update(module_name_stream_version_set)

        return missing_composes

    def _record_builds(self, images, auto_build_image_modules_mapping):
        """
        Records the images to database.

        :param images list: a list of ContainerImage instances.
        :param auto_build_image_modules_mapping dict: a dict which key is the
            original image's NVR and value is modules list enabled in the image.
        :return: a mapping between docker image build NVR and
            corresponding ArtifactBuild object representing a future rebuild of
            that docker image. It is extended by including those docker images
            stored into database.
        :rtype: dict
        """
        db_event = Event.get_or_create_from_event(db.session, self.event)

        # Cache for ODCS module composes. Key is white-spaced, sorted, list
        # of module's NAME:STREAM:VERSION. Value is Compose database object.
        odcs_cache = {}

        # Dict with {brew_build_nvr: ArtifactBuild, ...} mapping.
        builds = {}

        with koji_service(
            conf.koji_profile, log, login=False, dry_run=self.dry_run
        ) as session:
            for image in images:
                self.set_context(db_event)

                image.resolve_commit()
                image.resolve_original_odcs_compose_ids(False)
                nvr = image.nvr
                image_name = koji.parse_NVR(nvr)["name"]
                build = self.record_build(
                    self.event,
                    image_name,
                    ArtifactType.IMAGE,
                    state=ArtifactBuildState.PLANNED.value,
                    original_nvr=nvr,
                    rebuild_reason=RebuildReason.DIRECTLY_AFFECTED.value,
                )
                # Set context to particular build so logging shows this build
                # in case of error.
                self.set_context(build)

                module_name_stream_version_set = set()
                module_name_stream_set = set()
                module_nvrs = auto_build_image_modules_mapping[nvr]
                for module_nvr in module_nvrs:
                    mmd = session.get_modulemd(module_nvr)
                    name = mmd.get_module_name()
                    stream = mmd.get_stream_name()
                    version = mmd.get_version()
                    module_name_stream_set.add("%s:%s" % (name, stream))
                    module_name_stream_version_set.add(
                        ":".join([name, stream, str(version)])
                    )
                original_odcs_compose_ids = image["original_odcs_compose_ids"]
                outdated_composes = self._outdated_composes(
                    original_odcs_compose_ids, module_name_stream_set
                )

                build.build_args = json.dumps(
                    {
                        "repository": image["repository"],
                        "commit": image["commit"],
                        "target": image["target"],
                        "branch": image["git_branch"],
                        "arches": image["arches"],
                        "renewed_odcs_compose_ids": list(outdated_composes),
                        "flatpak": image.get("flatpak", False),
                        "isolated": image.get("isolated", True),
                    }
                )
                db.session.commit()

                missing_composes = self._missing_composes(
                    original_odcs_compose_ids,
                    module_name_stream_set,
                    module_name_stream_version_set,
                )
                for compose_source in missing_composes:
                    if compose_source in odcs_cache:
                        db_compose = odcs_cache[compose_source]
                    else:
                        compose = create_odcs_client().new_compose(
                            compose_source, "module"
                        )
                        db_compose = Compose(odcs_compose_id=compose["id"])
                        db.session.add(db_compose)
                        db.session.commit()
                        odcs_cache[compose_source] = db_compose

                    if db_compose:
                        build.add_composes(db.session, [db_compose])
                        db.session.commit()
                builds[nvr] = build

            # Reset context to db_event.
            self.set_context(db_event)

        return builds


def _compose_sources(compose):
    """
    Get compose sources .

    :param compose dict: Compose info from ODCS.
    :return: a list of lists in format [[N1, S1, V1, C1], [N2, S2, V2, C2]...].
    :rtype: list
    """
    source_value = compose.get("source", "")
    sources = []
    for source in source_value.split():
        sources.append(source.strip().split(":"))
    return sources
