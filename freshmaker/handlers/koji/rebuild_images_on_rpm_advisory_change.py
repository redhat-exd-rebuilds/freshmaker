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
# Written by Jan Kaluza <jkaluza@redhat.com>

import json
import koji

from freshmaker import conf, db
from freshmaker.events import (
    ErrataAdvisoryRPMsSignedEvent, ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.lightblue import LightBlue
from freshmaker.pulp import Pulp
from freshmaker.errata import Errata
from freshmaker.types import (
    ArtifactType, ArtifactBuildState, EventState, RebuildReason)
from freshmaker.models import Event, Compose


class RebuildImagesOnRPMAdvisoryChange(ContainerBuildHandler):
    """
    Rebuilds all Docker images which contain packages from the Errata
    advisory.
    """

    name = 'RebuildImagesOnRPMAdvisoryChange'

    def can_handle(self, event):
        if not isinstance(event, ErrataAdvisoryRPMsSignedEvent):
            return False

        if not {'rpm', 'module'} & set(event.advisory.content_types):
            self.log_info('Skip non-RPM and non-module advisory %s.', event.advisory.errata_id)
            return False

        return True

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        Rebuilds all container images which contain packages from the Errata
        advisory.
        """

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        # Generate the Database representation of `event`, it can be
        # triggered by user, we want to track what happened

        db_event = Event.get_or_create_from_event(db.session, event)

        db.session.commit()
        self.set_context(db_event)

        # Check if we are allowed to build this advisory.
        if not self.event.is_allowed(self):
            msg = ("Errata advisory {0} is not allowed by internal policy "
                   "to trigger rebuilds.".format(event.advisory.errata_id))
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        # Get and record all images to rebuild based on the current
        # ErrataAdvisoryRPMsSignedEvent event.
        batches = self._find_images_to_rebuild(db_event.search_key)
        builds = self._record_batches(batches, event)

        if not builds:
            msg = 'No container images to rebuild for advisory %r' % event.advisory.name
            self.log_info(msg)
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            return []

        if all([build.state == ArtifactBuildState.FAILED.value
                for build in builds.values()]):
            db_event.transition(
                EventState.COMPLETE,
                "No container images to rebuild, all are in failed state.")
            db.session.commit()
            return []

        if event.advisory.state != 'SHIPPED_LIVE':
            # If freshmaker is configured to rebuild images only when advisory
            # moves to SHIPPED_LIVE state, there is no need to generate new
            # composes for rebuild as all signed RPMs should already be
            # available from official YUM repositories.
            #
            # Generate the ODCS compose with RPMs from the current advisory.
            repo_urls = self.odcs.prepare_yum_repos_for_rebuilds(db_event)
            self.log_info(
                "Following repositories will be used for the rebuild:")
            for url in repo_urls:
                self.log_info("   - %s", url)

        # Log what we are going to rebuild
        self._check_images_to_rebuild(db_event, builds)
        self.start_to_build_images(
            db_event.get_image_builds_in_first_batch(db.session))

        msg = 'Advisory %s: Rebuilding %d container images.' % (
            db_event.search_key, len(db_event.builds.all()))
        db_event.transition(EventState.BUILDING, msg)

        return []

    def _check_images_to_rebuild(self, db_event, builds):
        """
        Checks the images to rebuild and logs them using self.log_info(...).
        :param Event db_event: Database Event associated with images.
        :param builds dict: list of docker images to build as returned by
            _find_images_to_rebuild(...).
        """
        self.log_info('Found container images to rebuild in following order:')
        batch = 0
        printed = []
        printed_cnt = 0
        builds_cnt = len(builds.values())
        db_event_builds_cnt = len(db_event.builds.all())

        while printed_cnt != builds_cnt or printed_cnt != db_event_builds_cnt:
            self.log_info('   Batch %d:', batch)

            old_printed_count = printed_cnt

            for build in builds.values():
                # Print build only if:
                # a) It depends on other build, but this dependency has not
                #    been printed yet or ...
                # b) ... it does not depend on other build and we are printing
                #   batch 0 - this handles the base images
                # In call cases, print only builds which have not been printed
                # so far.
                if (build.original_nvr not in printed and
                        ((build.dep_on and build.dep_on.original_nvr in printed) or
                         (not build.dep_on and batch == 0))):
                    args = json.loads(build.build_args)
                    if build.dep_on:
                        based_on = "based on %s" % build.dep_on.rebuilt_nvr
                    else:
                        based_on = "based on %s" % args["original_parent"] \
                            if args["original_parent"] else "base image"
                    self.log_info(
                        '      - %s#%s (%s)' %
                        (args["repository"], args["commit"], based_on))
                    printed.append(build.original_nvr)

            printed_cnt = len(printed)

            # Nothing has been printed, that means the dependencies between
            # images are not OK and we would loop forever. Instead of that,
            # print error and stop the rebuild.
            if old_printed_count == printed_cnt:
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value,
                    "No image to be built in batch %d." % (batch))
                self.log_error("Dumping the builds:")
                for build in builds.values():
                    self.log_error("   %r", build.original_nvr)
                self.log_error("Printed ones:")
                for p in printed:
                    self.log_error("   %r", p)
                break

            batch += 1

    def _record_batches(self, batches, event, builds=None):
        """
        Records the images from batches to database.

        :param batches list: Output of LightBlue._find_images_to_rebuild(...).
        :param event ErrataAdvisoryRPMsSignedEvent: The event this handler
            is currently handling.
        :param builds dict: mappings from docker image build NVR to
            corresponding ArtifactBuild object, e.g.
            ``{brew_build_nvr: ArtifactBuild, ...}``. Previous builds returned
            from this method can be passed to this call to be extended by
            adding a new mappings after docker image is stored into database.
            For the first time to call this method, builds could be None.
        :return: a mapping between docker image build NVR and
            corresponding ArtifactBuild object representing a future rebuild of
            that docker image. It is extended by including those docker images
            stored into database.
        :rtype: dict
        """
        db_event = Event.get_or_create_from_event(db.session, event)

        # Used as tmp dict with {brew_build_nvr: ArtifactBuild, ...} mapping.
        builds = builds or {}

        # Cache for ODCS pulp composes. Key is white-spaced, sorted, list
        # of content_sets. Value is Compose database object.
        odcs_cache = {}

        for batch in batches:
            for image in batch:
                # Reset context to db_event for each iteration before
                # the ArtifactBuild is created.
                self.set_context(db_event)

                nvr = image.nvr
                if nvr in builds:
                    self.log_debug("Skipping recording build %s, "
                                   "it is already in db", nvr)
                    continue

                parent_build = db_event.get_artifact_build_from_event_dependencies(nvr)
                if parent_build:
                    self.log_debug(
                        "Skipping recording build %s, "
                        "it is already built in dependant event %r", nvr, parent_build[0].event_id)
                    continue

                self.log_debug("Recording %s", nvr)
                parent_nvr = image["parent"].nvr \
                    if "parent" in image and image["parent"] else None
                dep_on = builds[parent_nvr] if parent_nvr in builds else None

                if parent_nvr:
                    build = db_event.get_artifact_build_from_event_dependencies(parent_nvr)
                    if build:
                        parent_nvr = build[0].rebuilt_nvr
                        dep_on = None

                if "error" in image and image["error"]:
                    state_reason = image["error"]
                    state = ArtifactBuildState.FAILED.value
                elif dep_on and dep_on.state == ArtifactBuildState.FAILED.value:
                    # If this artifact build depends on a build which cannot
                    # be built by Freshmaker, mark this one as failed too.
                    state_reason = "Cannot build artifact, because its " \
                        "dependency cannot be built."
                    state = ArtifactBuildState.FAILED.value
                else:
                    state_reason = ""
                    state = ArtifactBuildState.PLANNED.value

                image_name = koji.parse_NVR(image.nvr)["name"]

                # Only released images are considered as directly affected for
                # rebuild. If some image is not in the latest released version and
                # it is included in a rebuild, it must be just a dependency of
                # other image.
                if image.get('directly_affected'):
                    rebuild_reason = RebuildReason.DIRECTLY_AFFECTED.value
                else:
                    rebuild_reason = RebuildReason.DEPENDENCY.value

                build = self.record_build(
                    event, image_name, ArtifactType.IMAGE,
                    dep_on=dep_on,
                    state=ArtifactBuildState.PLANNED.value,
                    original_nvr=nvr,
                    rebuild_reason=rebuild_reason)

                # Set context to particular build so logging shows this build
                # in case of error.
                self.set_context(build)

                build.transition(state, state_reason)

                build.build_args = json.dumps({
                    "repository": image["repository"],
                    "commit": image["commit"],
                    "original_parent": parent_nvr,
                    "target": image["target"],
                    "branch": image["git_branch"],
                    "arches": image["arches"],
                    "renewed_odcs_compose_ids": image["original_odcs_compose_ids"],
                })

                db.session.commit()

                if state != ArtifactBuildState.FAILED.value:
                    # Store odcs pulp compose to build.
                    # Also generate pulp repos in case the image is unpublished,
                    # because in this case, we have to generate extra ODCS compose
                    # with all the RPMs in the image anyway later. And OSBS works
                    # in a way that we have to pass all the ODCS composes to it or
                    # no ODCS compose at all.
                    if image["generate_pulp_repos"] or not image["published"]:
                        original_pulp_compose_sources = set()
                        for compose_id in image["original_odcs_compose_ids"]:
                            compose = self.odcs.get_compose(compose_id)
                            source_type = compose.get("source_type")
                            # source_type of pulp composes is 4
                            if source_type != 4:
                                continue
                            source_value = compose.get("source", "")
                            for source in source_value.split():
                                original_pulp_compose_sources.add(source.strip())

                        # Add content set to new_pulp_sources if it's not found
                        # in original_pulp_compose_sources
                        new_pulp_sources = set()
                        for content_set in image["content_sets"]:
                            if content_set not in original_pulp_compose_sources:
                                new_pulp_sources.add(content_set)

                        if new_pulp_sources:
                            # Check if the compose for these new pulp sources is
                            # already cached and use it in this case.
                            cache_key = " ".join(sorted(new_pulp_sources))
                            if cache_key in odcs_cache:
                                db_compose = odcs_cache[cache_key]
                            else:
                                compose = self.odcs.prepare_pulp_repo(
                                    build, list(new_pulp_sources))

                                if build.state != ArtifactBuildState.FAILED.value:
                                    db_compose = Compose(odcs_compose_id=compose['id'])
                                    db.session.add(db_compose)
                                    db.session.commit()
                                    odcs_cache[cache_key] = db_compose
                                else:
                                    db_compose = None
                                    db.session.commit()
                            if db_compose:
                                build.add_composes(db.session, [db_compose])
                                db.session.commit()

                    # Unpublished images can contain unreleased RPMs, so generate
                    # the ODCS compose with all the RPMs in the image to allow
                    # installation of possibly unreleased RPMs.
                    if not image["published"]:
                        compose = self.odcs.prepare_odcs_compose_with_image_rpms(image)
                        if compose:
                            db_compose = Compose(odcs_compose_id=compose['id'])
                            db.session.add(db_compose)
                            db.session.commit()
                            build.add_composes(db.session, [db_compose])
                            db.session.commit()

                builds[nvr] = build

        # Reset context to db_event.
        self.set_context(db_event)

        return builds

    def _filter_out_not_allowed_builds(self, image):
        """
        Helper method for _find_images_to_rebuild(...) to filter
        out all images which are not allowed to build by configuration.

        :param ContainerImage image: Image to be checked.
        :rtype: bool
        :return: True when image should be filtered out.
        """

        parsed_nvr = koji.parse_NVR(image.nvr)

        if not self.event.is_allowed(
                self, image_name=parsed_nvr["name"],
                image_version=parsed_nvr["version"],
                image_release=parsed_nvr["release"]):
            self.log_info(
                "Skipping rebuild of image %s, not allowed by configuration",
                image.nvr)
            return True
        return False

    def _find_images_to_rebuild(self, errata_id):
        """
        Finds docker rebuild images from each build added to specific Errata
        advisory.

        Found images are yielded in proper rebuild order from base images to
        leaf images through the docker build dependency chain.

        :param int errata_id: Errata ID.
        """
        errata = Errata()
        errata_id = int(errata_id)

        # Use the errata_id to find out Pulp repository IDs from Errata Tool
        # and furthermore get content_sets from Pulp where signed RPM will end
        # up eventually when advisories are shipped.
        pulp_repo_ids = list(set(errata.get_pulp_repository_ids(errata_id)))

        pulp = Pulp(server_url=conf.pulp_server_url,
                    username=conf.pulp_username,
                    password=conf.pulp_password)
        content_sets = pulp.get_content_set_by_repo_ids(pulp_repo_ids)
        # Some container builds declare Pulp repos directly instead of content
        # sets, but they are stored in the same location as content sets so they
        # can be treated the same
        content_sets.extend(pulp_repo_ids)

        self.log_info('RPMs from advisory ends up in following content sets: '
                      '%s', content_sets)

        # Query images from LightBlue by signed RPM's srpm name and found
        # content sets
        lb = LightBlue(server_url=conf.lightblue_server_url,
                       cert=conf.lightblue_certificate,
                       private_key=conf.lightblue_private_key,
                       event_id=self.current_db_event_id)
        # Check if we are allowed to rebuild unpublished images and clear
        # published and release_categories if so.
        if self.event.is_allowed(self, published=True):
            published = True
            release_categories = conf.lightblue_release_categories
        else:
            published = None
            release_categories = None

        # Limit the Lightblue query to particular leaf images if set in Event.
        leaf_container_images = None
        if isinstance(self.event, ManualRebuildWithAdvisoryEvent):
            leaf_container_images = self.event.container_images

        # Get binary rpm nvrs which are affected by the CVEs in this advisory
        affected_nvrs = self.event.advisory.affected_rpm_nvrs

        # If there is no CVE affected binary rpms, this can be non-RHSA advisory,
        # just rebuild images that have the builds in this advisory installed
        if not affected_nvrs:
            affected_nvrs = errata.get_binary_rpm_nvrs(errata_id)

        self.log_info(
            "Going to find all the container images to rebuild as "
            "result of %r update.", affected_nvrs)
        batches = lb.find_images_to_rebuild(
            affected_nvrs, content_sets,
            filter_fnc=self._filter_out_not_allowed_builds,
            published=published, release_categories=release_categories,
            leaf_container_images=leaf_container_images)
        return batches
