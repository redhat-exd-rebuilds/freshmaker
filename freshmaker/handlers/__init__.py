# -*- coding: utf-8 -*-
# Copyright (c) 2016  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

import abc
import json
import re
from functools import wraps

from freshmaker import conf, log, db, models
from freshmaker.kojiservice import koji_service, parse_NVR
from freshmaker.mbs import MBS
from freshmaker.models import ArtifactBuildState
from freshmaker.types import ArtifactType
from freshmaker.models import ArtifactBuild, Event
from freshmaker.utils import krb_context, get_rebuilt_nvr
from freshmaker.errors import UnprocessableEntity, ProgrammingError

from freshmaker.odcsclient import ODCS
from freshmaker.odcsclient import AuthMech
from freshmaker.odcsclient import COMPOSE_STATES


def fail_event_on_handler_exception(func):
    """
    Decorator which marks the models.Event associated with handler by
    BaseHandler.set_context() as FAILED in case the `func` raises an
    exception.

    The exception is re-raised by this decorator once its finished.
    """
    @wraps(func)
    def decorator(handler, *args, **kwargs):
        try:
            return func(handler, *args, **kwargs)
        except Exception as e:
            err = 'Could not process message handler. See the traceback.'
            log.exception(err)

            # In case the exception interrupted the database transaction,
            # rollback it.
            db.session.rollback()

            # Mark the event as failed.
            db_event_id = handler.current_db_event_id
            db_event = db.session.query(Event).filter_by(
                id=db_event_id).first()
            if db_event:
                db_event.builds_transition(
                    ArtifactBuildState.FAILED.value, "Handling of "
                    "event failed with traceback: %s" % (str(e)))
                db.session.commit()
            raise
    return decorator


def fail_artifact_build_on_handler_exception(func):
    """
    Decorator which marks the models.ArtifactBuild associated with handler by
    BaseHandler.set_context() as FAILED in case the `func` raises an
    exception.

    The exception is re-raised by this decorator once its finished.
    """
    @wraps(func)
    def decorator(handler, *args, **kwargs):
        try:
            return func(handler, *args, **kwargs)
        except Exception as e:
            err = 'Could not process message handler. See the traceback.'
            log.exception(err)

            # In case the exception interrupted the database transaction,
            # rollback it.
            db.session.rollback()

            # Mark the event as failed.
            build_id = handler.current_db_artifact_build_id
            build = db.session.query(ArtifactBuild).filter_by(
                id=build_id).first()
            if build:
                build.transition(
                    ArtifactBuildState.FAILED.value, "Handling of "
                    "build failed with traceback: %s" % (str(e)))
                db.session.commit()
            raise
    return decorator


class BaseHandler(object):
    """
    Abstract base class for event handlers.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        self._db_event_id = None
        self._db_artifact_build_id = None

    @property
    def current_db_event_id(self):
        return self._db_event_id

    @property
    def current_db_artifact_build_id(self):
        return self._db_artifact_build_id

    def set_context(self, db_object):
        """
        Sets the current context of a handler. This method accepts models.Event
        or models.ArtifactBuild.

        Whenever the handler handles particular event or artifact build, it
        must set the context, so in case of a failure, the event or artifact
        build can be marked as FAILED by a consumer class.
        """
        if type(db_object) == Event:
            self._db_event_id = db_object.id
            self._db_artifact_build_id = None
        elif type(db_object) == ArtifactBuild:
            self._db_event_id = db_object.event.id
            self._db_artifact_build_id = db_object.id
        else:
            raise ProgrammingError(
                "Unsupported context type passed to BaseHandler.set_context()")

    @abc.abstractmethod
    def can_handle(self, event):
        """
        Returns true if this class can handle this type of event.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def handle(self, event):
        """
        Handles the event. Can return another BaseEvent instances to
        generate another events to be used by other local handlers.

        :return: List of BaseEvent objects which will be handled by other
        handlers after this handler handles the event. This can be used to
        generate internal events for other handlers in Freshmaker.
        """
        raise NotImplementedError()

    def build_module(self, name, branch, rev):
        """
        Build a module in MBS.

        :param name: module name.
        :param branch: module branch.
        :param rev: git revision.
        """
        mbs = MBS(conf)
        return mbs.build_module(name, branch, rev)

    def record_build(self, event, name, artifact_type,
                     build_id=None, dep_on=None, state=None,
                     original_nvr=None, rebuilt_nvr=None):
        """
        Record build in db.

        :param event: instance of an event.
        :param name: name of the artifact.
        :param artifact_type: an enum member of ArtifactType.
        :param build_id: id of the real build in a build system. If omitted,
            this build has not been built in external build system.
        :param dep_on: the artifact which this one depends on. If omitted, no
            other artifact is depended on.
        :param state: the initial state of build. If omitted, defaults to
            ``ArtifactBuildState.BUILD``.
        :param original_nvr: The original NVR of artifact.
        :param rebuilt_nvr: The NVR of newly rebuilt artifact.
        :return: recorded build.
        :rtype: ArtifactBuild.
        """

        ev = models.Event.get_or_create(db.session, event.msg_id,
                                        event.search_key, event.__class__)
        build = models.ArtifactBuild.create(db.session, ev, name,
                                            artifact_type.name.lower(),
                                            build_id, dep_on, state,
                                            original_nvr, rebuilt_nvr)

        db.session.commit()
        return build

    def allow_build(self, artifact_type, **kwargs):
        """
        Check whether the artifact is allowed to be built by checking
        HANDLER_BUILD_WHITELIST in config.

        :param artifact_type: an enum member of ArtifactType.
        :param kwargs: dictionary of arguments to check against
        :return: True or False.
        """
        # If there is a whitelist specified for the (handler, artifact_type),
        # the build target of (name, branch) need to be in that whitelist first.

        # by default we assume the artifact is in whitelist and not in blacklist
        in_whitelist = True

        # Global rules
        whitelist_rules = conf.handler_build_whitelist.get("global", {})

        # This handler rules
        handler_name = self.name
        whitelist_rules.update(conf.handler_build_whitelist.get(handler_name, {}))

        def match_rule(kwargs, rule):
            for key, value in kwargs.items():
                value_rule = rule.get(key, None)
                if not value_rule:
                    continue

                if not isinstance(value_rule, list):
                    value_rule = [value_rule]

                if not any((re.compile(r).match(value) for r in value_rule)):
                    return False
            return True

        try:
            whitelist = whitelist_rules.get(artifact_type.name.lower(), [])
            if whitelist and not any([match_rule(kwargs, rule) for rule in whitelist]):
                log.debug('%r, type=%r is not whitelisted.',
                          kwargs, artifact_type.name.lower())
                in_whitelist = False

        except re.error as exc:
            err_msg = ("Error while compiling whilelist rule "
                       "for <handler(%s) artifact(%s)>:\n"
                       "Incorrect regular expression: %s\n"
                       "Whitelist will not take effect" %
                       (handler_name, artifact_type.name.lower(), str(exc)))
            log.error(err_msg)
            raise UnprocessableEntity(err_msg)
        return in_whitelist


class ContainerBuildHandler(BaseHandler):
    """Handler for building containers"""

    def build_container(self, scm_url, branch, target,
                        repo_urls=None, isolated=False,
                        release=None, koji_parent_build=None):
        """
        Build a container in Koji.

        :param str name: container name.
        :param str branch: container branch.
        :param str rev: revision.
        :param str namespace: namespace of container in dist-git. By default,
            it is container.
        :return: task id returned from Koji buildContainer API.
        :rtype: int
        """
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            log.info('Building container from source: %s, '
                     'release=%r, parent=%r, target=%r',
                     scm_url, release, koji_parent_build, target)

            return service.build_container(scm_url,
                                           branch,
                                           target,
                                           repo_urls=repo_urls,
                                           isolated=isolated,
                                           release=release,
                                           koji_parent_build=koji_parent_build,
                                           scratch=conf.koji_container_scratch_build)

    @fail_artifact_build_on_handler_exception
    def build_image_artifact_build(self, build, repo_urls=[]):
        """
        Submits ArtifactBuild of 'image' type to Koji.

        :param build: ArtifactBuild of 'image' type.
        :rtype: number
        :return: Koji build id.
        """
        if build.state != ArtifactBuildState.PLANNED.value:
            build.transition(
                ArtifactBuildState.FAILED.value,
                "Container image build is not in PLANNED state.")
            return

        if not build.build_args:
            build.transition(
                ArtifactBuildState.FAILED.value,
                "Container image does not have 'build_args' filled in.")
            return

        args = json.loads(build.build_args)
        if not args["parent"]:
            # TODO: Rebuild base image.
            build.transition(
                ArtifactBuildState.FAILED.value,
                "Rebuild of container base image is not supported yet.")
            return

        scm_url = "%s/%s#%s" % (conf.git_base_url, args["repository"],
                                args["commit"])
        branch = args["branch"]
        target = args["target"]
        parent = args["parent"]

        if not build.rebuilt_nvr and build.original_nvr:
            build.rebuilt_nvr = get_rebuilt_nvr(
                build.type, build.original_nvr)

        if not build.rebuilt_nvr:
            build.transition(
                ArtifactBuildState.FAILED.value,
                "Container image does not have rebuilt_nvr set.")
            return

        release = parse_NVR(build.rebuilt_nvr)["release"]

        return self.build_container(
            scm_url, branch, target, repo_urls=repo_urls,
            isolated=True, release=release, koji_parent_build=parent)

    def odcs_get_compose(self, compose_id):
        """
        Returns the information from the ODCS server about compose with id
        `compose_id`. In DRY_RUN mode, returns fake compose information
        without contacting the ODCS server.
        """
        if conf.dry_run:
            compose = {}
            compose['id'] = compose_id
            compose['result_repofile'] = "http://localhost/%d.repo" % (
                compose['id'])
            compose['state'] = COMPOSE_STATES['done']
            return compose

        odcs = ODCS(conf.odcs_server_url, auth_mech=AuthMech.Kerberos,
                    verify_ssl=conf.odcs_verify_ssl)
        with krb_context():
            return odcs.get_compose(compose_id)

    def get_repo_urls(self, db_event, build):
        """
        Returns list of URLs to ODCS repositories which should be used
        to rebuild the container image for this event.
        """
        rebuild_event = Event.get(db.session, db_event.message_id)

        # Get compose ids of ODCS composes of all event dependencies.
        compose_ids = [rebuild_event.compose_id]
        for event in rebuild_event.event_dependencies:
            compose_ids.append(event.compose_id)

        # Use compose ids to get the repofile URLs.
        repo_urls = []
        for compose_id in compose_ids:
            compose = self.odcs_get_compose(compose_id)
            repo_urls.append(compose["result_repofile"])

        # Add PULP compose repo url.
        if build.build_args and "odcs_pulp_compose_id" in build.build_args:
            args = json.loads(build.build_args)
            compose = self.odcs_get_compose(args["odcs_pulp_compose_id"])
            repo_urls.append(compose["result_repofile"])

        return repo_urls

    def _build_first_batch(self, db_event):
        """
        Rebuilds all the parents images - images in the first batch which don't
        depend on other images.
        """

        builds = db.session.query(ArtifactBuild).filter_by(
            type=ArtifactType.IMAGE.value, event_id=db_event.id,
            dep_on=None).all()

        for build in builds:
            self.set_context(build)
            repo_urls = self.get_repo_urls(db_event, build)
            build.build_id = self.build_image_artifact_build(build, repo_urls)
            if build.build_id:
                build.transition(
                    ArtifactBuildState.BUILD.value,
                    "Building container image in Koji.")
            else:
                build.transition(
                    ArtifactBuildState.FAILED.value,
                    "Error while building container image in Koji.")
            db.session.add(build)
            db.session.commit()

        self.set_context(db_event)
