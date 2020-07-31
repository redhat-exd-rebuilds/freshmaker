# -*- coding: utf-8 -*-
# Copyright (c) 2020  Red Hat, Inc.
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

import koji
import json

from freshmaker import conf, db, log
from freshmaker.lightblue import LightBlue
from freshmaker.handlers import ContainerBuildHandler, fail_event_on_handler_exception
from freshmaker.events import FreshmakerAsyncManualBuildEvent
from freshmaker.types import EventState
from freshmaker.models import Event
from freshmaker.kojiservice import koji_service
from freshmaker.types import ArtifactBuildState, ArtifactType
from freshmaker.utils import sorted_by_nvr


class RebuildImagesOnAsyncManualBuild(ContainerBuildHandler):
    """Rebuild images on async.manual.build"""

    name = 'RebuildImagesOnAsyncManualBuild'

    def can_handle(self, event):
        return isinstance(event, FreshmakerAsyncManualBuildEvent)

    @fail_event_on_handler_exception
    def handle(self, event):
        """
        Rebuilds all container images requested by the user and the tree in between the
        requested images, if relationships between them are found.
        """

        if event.dry_run:
            self.force_dry_run()

        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        self.set_context(db_event)

        # Check if we are allowed to build this image.
        if not self.event.is_allowed(self, ArtifactType.IMAGE):
            msg = ("This image rebuild is not allowed by internal policy. "
                   f"message_id: {event.msg_id}")
            db_event.transition(EventState.SKIPPED, msg)
            db.session.commit()
            self.log_info(msg)
            return []

        lb = self.init_lightblue_instance()
        # images contains at this point a list of images with all NVR for the same package
        images = self._find_images_to_rebuild(lb)

        # Since the input is an image name, and not an NVR, freshmaker won't be able to know
        # exactly which one needs to be rebuilt. For this reason Freshmaker asked Lightblue
        # all the NVRs that match that image name. Now we need to check which one has the
        # dist_git_branch. If more than one is found Freshmaker will choose the one with the
        # highest NVR.
        images = self.filter_images_based_on_dist_git_branch(images, db_event)
        if not images:
            return []

        # If the user requested to rebuild only one image, there's no need to find out all the tree
        # it is just more efficient to return that single image
        if len(images) == 1:
            batches = [images]
        else:
            images_trees = self.find_images_trees_to_rebuild(images, lb)
            to_rebuild = self.filter_out_unrelated_images(images_trees)
            batches = self.generate_batches(to_rebuild, images, lb)

        builds = self._record_batches(batches, db_event, lb)

        if not builds:
            msg = f"No container images to rebuild for event with message_id {event.msg_id}"
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

        self.start_to_build_images(
            db_event.get_image_builds_in_first_batch(db.session))

        msg = 'Rebuilding %d container images.' % (len(db_event.builds.all()))
        db_event.transition(EventState.BUILDING, msg)

        return []

    def init_lightblue_instance(self):
        return LightBlue(server_url=conf.lightblue_server_url,
                         cert=conf.lightblue_certificate,
                         private_key=conf.lightblue_private_key,
                         event_id=self.event.msg_id)

    def filter_out_unrelated_images(self, batches):
        """
        Filters out images that are unrelated to the requested images.
        Example:
        batches =
            [
                [image_b, image_a, image_0],
                [image_d, image_a, image_0]
            ]
        Returns:
        [
            [image_b],
            [image_d]
        ]

        :param batches: list of lists, the first item is the image requested and the
            following items are its tree, up to the base image.
        :return: container images that will actually be rebuilt, because the user requested them
            or because they are part of the tree that needs to be rebuilt.
        """
        new_batches = []
        for batch in batches:
            # We expect the first item in the list to always be in the requested images
            # if not, there must be something wrong... maybe we should return an error.
            if batch[0]['brew']['package'] not in self.event.container_images:
                self.log_info('Unexpected error identifying images to rebuild.')
                return []
            filtered_batch = []
            maybe_batch = []
            for image in batch:
                maybe_batch.append(image)
                if image['brew']['package'] in self.event.container_images:
                    filtered_batch.extend(maybe_batch)
                    maybe_batch = []
            new_batches.append(filtered_batch)
        return new_batches

    def generate_batches(self, to_rebuild, images, lb):
        # Get all the directly affected images so that any parents that are not marked as
        # directly affected can be set in _images_to_rebuild_to_batches
        directly_affected_nvrs = {
            image.nvr for image in images if image.get("directly_affected")
        }
        # Now generate batches from deduplicated list and return it.
        return lb._images_to_rebuild_to_batches(to_rebuild, directly_affected_nvrs)

    def _find_images_to_rebuild(self, lb):
        """
        Since the input is an image name, and not an NVR, freshmaker won't be able to know
        exactly which one needs to be rebuilt. For this reason Freshmaker will ask Lightblue
        all the NVRs that match that image name. It will then check which one has the
        dist_git_branch. If more than one is found Freshmaker will choose the one with the highest
        NVRArtifactType.IMAGE.

        :param lb LightBlue: LightBlue instance
        :return: list of container images matching a certain name.
        :rtype: list
        """

        return lb.get_images_by_brew_package(self.event.container_images)

    def get_image_tree(self, lb, image, tree):
        """
        This method recursively finds the tree for given image, up to the base image.
        At every recursive call it will add one element of the tree.
        When the base image is reached, the tree will be completed.

        :param lb LightBlue: LightBlue instance
        :param image ContainerImage: image of which we want the tree.
        :param tree list: the list of images that we found until now.
        :return: list of images, in this order: [parent, grandparent, ..., baseimage]
        :rtype: list
        """
        parent_nvr = lb.find_parent_brew_build_nvr_from_child(image)
        if parent_nvr:
            parent = lb.get_images_by_nvrs([parent_nvr], published=None)
            if parent:
                parent = parent[0]
                parent.resolve(lb)
                image['parent'] = parent
                tree.append(parent)
                return self.get_image_tree(lb, parent, tree)
        return tree

    def filter_images_based_on_dist_git_branch(self, images, db_event):
        """
        Filter images based on the dist-git branch requested by the user. If the images were never
        be built for that branch, let's skip the build.
        The input images are all the images matching a specific name. In this method we also select
        the images with higher NVR for the same name (package).

        :param images list: images to rebuild.
        :param db_event Event: event object in the db.
        :return: list of images to rebuild. If the event gets skipped, return empty list.
        :rtype: list
        """
        with koji_service(
                conf.koji_profile, log, dry_run=conf.dry_run,
                login=False) as session:

            # Sort images by nvr
            images = sorted_by_nvr(images, reverse=True)

            # Use a dict to map a package (name) to the highest NVR image. For example:
            # {"ubi8-container": ContainerImage<nvr=ubi8-container-8.1-100>,
            # "nodejs-12-container": ContainerImage<nvr=nodejs12-container-1.0-101>)}
            images_to_rebuild = {}

            # In case the user requested to build ['s2i-core-container', 'cnv-libvirt-container']
            # lightblue will return a bunch of NVRs for each name, example:
            #   * s2i-core-container-1-127
            #   * s2i-core-container-1-126
            #   * ...
            #   * cnv-libvirt-container-1.3-1
            #   * cnv-libvirt-container-1.2-4
            #   * ...
            # Since `images` is a list of sorted NVRs, we just need to select the first NVR for
            # each package (name).
            for image in images:
                build = None
                git_branch = None

                package = image['brew']['package']
                # if package is already in images_to_rebuild we don't need to keep searching
                # since the images were sorted by NVR in the beginning
                if package not in images_to_rebuild:
                    # Let's get the branch for this image
                    build = session.get_build(image.nvr)
                    task_id = build.get("extra", {}).get("container_koji_task_id")
                    if task_id:
                        task = session.get_task_request(task_id)
                        # The task_info should always be in the 3rd element
                        task_info = task[2]
                        git_branch = task_info.get("git_branch") if len(task_info) else None

                    if (build and task_id and git_branch and
                            self.event.dist_git_branch == git_branch):
                        images_to_rebuild[package] = image

            if not images_to_rebuild or len(images_to_rebuild) < len(self.event.container_images):
                # If we didn't find images to rebuild, or we found less than what the user asked
                # it means that some of those images were never been built before for the requested
                # branch. In this case we need to throw an error because we won't build something
                # that was never built before.
                # We cannot return to the API with an error, because the request already completed
                # at this point. Let's mark this build as FAILED then.
                msg = ("One or more of the requested image was never built before for the "
                       f"requested branch: {self.event.dist_git_branch}. "
                       "Cannot build it, please change your request.")
                missing_images = set(self.event.container_images) - set(images_to_rebuild.keys())
                if missing_images:
                    msg += f" Problematic images are {missing_images}"
                db_event.transition(EventState.FAILED, msg)
                db.session.commit()
                self.log_info(msg)
                return []

            # The result needs to be a list
            return list(images_to_rebuild.values())

    def find_images_trees_to_rebuild(self, images_to_rebuild, lb):
        """
        At this point images_to_rebuilds contains the images to rebuild requested by the
        user. We now need to find out if there's some dependency between these images.
        Example: image A is parent image of B, B is parent image of C (A > B > C). The user
        requests to build A and C. In this case we'll also have to build B, and we need to
        build all of them in the right order (first A, then B, and C in the end).
        Let's find out if those images are related to each other. To do that, we find check
        all the hierarchy of these images until we don't reach the base image. Then we check
        if these images are related (if A appears in the parent tree of C).

        This method, for the given input images, return their trees, after deduplication.

        :param images_to_rebuild list: list of images to rebuild.
        :param lb LightBlue: LightBlue instance
        :return: list of trees of images.
        :rtype: list of lists
        """
        # images_trees will be a list of lists, where the first elements in the list will be
        # the requested images and the following elements are the elements in the tree up to the
        # base image.
        images_trees = []
        for image in images_to_rebuild:
            images_trees.append([image] + self.get_image_tree(lb, image, []))

        # Let's remove duplicated images which share the same name and version, but different
        # release.
        to_rebuild = lb._deduplicate_images_to_rebuild(images_trees)
        return to_rebuild

    def _record_batches(self, batches, db_event, lb):
        """
            Records the images from batches to the database.

        :param batches list: Output of LightBlue._find_images_to_rebuild(...).
        :param db_event: event to handle.
        :param lb LightBlue: LightBlue instance
        :return: a mapping between image build NVR and corresponding ArtifactBuild
            object representing a future rebuild of that. It is extended by including
            those images stored into database.
        :rtype: dict
        """
        # builds tracks all the builds we register in db
        builds = {}

        for batch in batches:
            for image in batch:
                # Reset context to db_event for each iteration before
                # the ArtifactBuild is created.
                self.set_context(db_event)

                nvr = image["brew"]["build"]

                self.log_debug("Recording %s", nvr)
                parent_nvr = image["parent"].nvr \
                    if "parent" in image and image["parent"] else None

                if "error" in image and image["error"]:
                    state_reason = image["error"]
                    state = ArtifactBuildState.FAILED.value
                else:
                    state_reason = ""
                    state = ArtifactBuildState.PLANNED.value

                image_name = koji.parse_NVR(image["brew"]["build"])["name"]
                parent_nvr = image["parent"].nvr \
                    if "parent" in image and image["parent"] else None
                dep_on = builds[parent_nvr] if parent_nvr in builds else None

                # We don't need to rebuild the nvr this time. The release value
                # will be automatically generated by OSBS.
                build = self.record_build(
                    self.event, image_name, ArtifactType.IMAGE,
                    dep_on=dep_on,
                    state=ArtifactBuildState.PLANNED.value,
                    original_nvr=nvr)

                # Set context to particular build so logging shows this build
                # in case of error.
                self.set_context(build)

                image.resolve(lb)
                build.transition(state, state_reason)
                build_args = {}
                build_args["repository"] = image['repository']
                build_args["commit"] = image["commit"]
                build_args["target"] = (
                    self.event.brew_target if self.event.brew_target else image["target"])
                build_args["branch"] = image["git_branch"]
                build_args["original_parent"] = parent_nvr
                build_args["arches"] = image["arches"]
                build.build_args = json.dumps(build_args)

                db.session.commit()

                builds[nvr] = build

        # Reset context to db_event.
        self.set_context(db_event)

        return builds
