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
from collections import defaultdict

import koji
import requests
from odcs.common.types import PungiSourceType
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from freshmaker import conf, db, log
from freshmaker.errata import Errata
from freshmaker.events import (
    FlatpakApplicationManualBuildEvent,
    FlatpakModuleAdvisoryReadyEvent,
)
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.kojiservice import koji_service
from freshmaker.image import PyxisAPI
from freshmaker.models import Event, Compose
from freshmaker.odcsclient import create_odcs_client
from freshmaker.pyxis import Pyxis
from freshmaker.types import ArtifactType, ArtifactBuildState, EventState, RebuildReason


def _only_auto_rebuild(image_modules_mapping):
    """
    Returns filtered out image list with images which can be auto rebuilt.
    """
    if not conf.pyxis_server_url:
        raise ValueError("'PYXIS_SERVER_URL' parameter should be set")

    pyxis = Pyxis(conf.pyxis_server_url)

    return {
        image: modules
        for image, modules in image_modules_mapping.items()
        if pyxis.image_is_tagged_auto_rebuild(image)
    }


class SkipEventException(Exception):
    def __init__(self, msg):
        super().__init__()
        self.msg = msg


class RebuildFlatpakApplicationOnModuleReady(ContainerBuildHandler):
    # Module ready means Flatpak module advisory is in QE status
    # and all attached builds are signed.
    name = "RebuildFlatpakApplicationOnModuleReady"

    def can_handle(self, event):
        return isinstance(event, FlatpakModuleAdvisoryReadyEvent) or isinstance(
            event, FlatpakApplicationManualBuildEvent
        )

    @fail_event_on_handler_exception
    def handle(self, event):

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        self.errata = Errata()
        self.advisory_module_nvrs = self.errata.get_attached_build_nvrs(
            event.advisory.errata_id
        )

        try:
            builds = self._handle_or_skip(event)
        except SkipEventException as e:
            msg = f"{e.msg} message_id: {event.msg_id}"
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        self.start_to_build_images(builds.values())
        msg = "Rebuilding %d container images." % (len(builds))
        db_event.transition(EventState.BUILDING, msg)
        return []

    def _handle_or_skip(self, event):
        """Raises SkipEventException if the event should be skipped."""
        image_modules_mapping = self._image_modules_mapping()
        if not image_modules_mapping:
            raise SkipEventException("No images are impacted by the advisory.")

        if event.manual and event.container_images:
            image_modules_mapping = {
                image: modules
                for image, modules in image_modules_mapping.items()
                if image in event.container_images
            }
            if not image_modules_mapping:
                specified_images = ", ".join(event.container_images)
                raise SkipEventException(
                    "None of the specified images are listed in flatpak index"
                    " service as latest published images impacted by"
                    f" the advisory: {specified_images}."
                )
        else:
            image_modules_mapping = _only_auto_rebuild(image_modules_mapping)
            if not image_modules_mapping:
                raise SkipEventException(
                    "No images impacted by the advisory are enabled for auto rebuild."
                )

        images = list(image_modules_mapping.keys())
        rebuild_images = self._filter_images_with_higher_rpm_nvr(images)
        if not rebuild_images:
            raise SkipEventException("Images are no longer impacted by the advisory.")

        images_nvr = ",".join([rebuild_image.nvr for rebuild_image in rebuild_images])
        self.log_info("Following images %s will be rebuilt" % images_nvr)

        return self._record_builds(rebuild_images, image_modules_mapping)

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

    def _image_modules_mapping(self):
        """
        Get image-to-modules mapping.

        :rtype: dict
        :return: A dict which key is the image which can be rebuilt
            and value is set of modules which are enabled in this image.
        """
        if not conf.flatpak_server_url:
            raise ValueError("'FLATPAK_SERVER_URL' parameter should be set")

        image_modules_mapping = defaultdict(set)
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
                        image_modules_mapping[image_nvr].add(advisory_module_nvr)
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
        errata_rpm_nvrs = self.errata.get_binary_rpm_nvrs(
            self.event.advisory.errata_id
        )
        pyxis = PyxisAPI(server_url=conf.pyxis_graphql_url)

        if errata_rpm_nvrs:
            return pyxis.get_images_by_nvrs(images, rpm_nvrs=errata_rpm_nvrs)

        return pyxis.get_images_by_nvrs(images)

    def _reused_composes(self, original_odcs_compose_ids, module_name_stream_set):
        """
        Generate reused composes.

        :param original_odcs_compose_ids list: Original compose ids.
        :param module_name_stream_set set: Module name stream set from an advisory.
        :return: a set of reused composes.
        :rtype: set
        """
        reused_composes = set()
        for compose_id in original_odcs_compose_ids:
            compose = self.odcs.get_compose(compose_id)
            source_type = compose.get("source_type")
            if source_type != PungiSourceType.MODULE:
                reused_composes.add(compose_id)
                continue

            name_stream_set = {f"{n}:{s}" for n, s, v, c in _compose_sources(compose)}

            if name_stream_set.isdisjoint(module_name_stream_set):
                reused_composes.add(compose_id)

        return reused_composes

    def _updated_compose_source(
        self,
        original_odcs_compose_ids,
        module_name_stream_set,
        module_nsvc_set,
    ):
        """
        Generate updated compose source.

        :param original_odcs_compose_ids list: Original compose ids.
        :param module_name_stream_set set: Module name stream set from an advisory.
        :param module_nsvc_set set: Module name stream version context set from an advisory.
        :return: a string of updated compose source.
        :rtype: set
        """
        updated_composes = set()
        for compose_id in original_odcs_compose_ids:
            compose = self.odcs.get_compose(compose_id)
            source_type = compose.get("source_type")
            if source_type == PungiSourceType.MODULE:
                name_stream_set = {
                    f"{n}:{s}" for n, s, v, c in _compose_sources(compose)
                }
                mapping = {
                    f"{n}:{s}": f"{n}:{s}:{v}:{c}"
                    for n, s, v, c in _compose_sources(compose)
                }

                if not name_stream_set.isdisjoint(module_name_stream_set):
                    updated_composes.update(
                        mapping[name_stream]
                        for name_stream in name_stream_set.difference(
                            module_name_stream_set
                        )
                    )
                updated_composes.update(module_nsvc_set)

        return " ".join(sorted(updated_composes))

    def _record_builds(self, images, image_modules_mapping):
        """
        Records the images to database.

        :param images list: a list of ContainerImage instances.
        :param image_modules_mapping dict: a dict which key is the
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

                module_nsvc_set = set()
                module_name_stream_set = set()
                module_nvrs = image_modules_mapping[nvr]
                for module_nvr in module_nvrs:
                    mmd = session.get_modulemd(module_nvr)
                    name = mmd.get_module_name()
                    stream = mmd.get_stream_name()
                    version = mmd.get_version()
                    context = mmd.get_context()
                    module_name_stream_set.add(f"{name}:{stream}")
                    module_nsvc_set.add(f"{name}:{stream}:{version}:{context}")
                original_odcs_compose_ids = image["odcs_compose_ids"]
                reused_composes = self._reused_composes(
                    original_odcs_compose_ids, module_name_stream_set
                )

                build.build_args = json.dumps(
                    {
                        "repository": image["repository"],
                        "commit": image["commit"],
                        "target": image["target"],
                        "branch": image["git_branch"],
                        "arches": image["arches"],
                        "renewed_odcs_compose_ids": list(reused_composes),
                        "flatpak": image.get("flatpak", False),
                        "isolated": image.get("isolated", True),
                        "original_parent": None,
                    }
                )
                db.session.commit()

                compose_source = self._updated_compose_source(
                    original_odcs_compose_ids,
                    module_name_stream_set,
                    module_nsvc_set,
                )
                arches = sorted(image["arches"].split())
                if compose_source:
                    if compose_source in odcs_cache:
                        db_compose = odcs_cache[compose_source]
                    else:
                        compose = create_odcs_client().new_compose(
                            compose_source, "module", arches=arches
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
