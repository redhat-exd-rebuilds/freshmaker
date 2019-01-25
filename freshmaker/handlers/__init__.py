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
import six
import copy
from functools import wraps

from freshmaker import conf, log, db, models
from freshmaker.kojiservice import koji_service, parse_NVR
from freshmaker.mbs import MBS
from freshmaker.models import ArtifactBuildState
from freshmaker.types import EventState
from freshmaker.models import ArtifactBuild, Event
from freshmaker.utils import krb_context, get_rebuilt_nvr
from freshmaker.errors import UnprocessableEntity, ProgrammingError
from freshmaker.odcsclient import create_odcs_client, FreshmakerODCSClient
from freshmaker.odcsclient import COMPOSE_STATES


class ODCSComposeNotReady(Exception):
    """
    Raised when ODCS compose is still generating and therefore not ready
    to be used to build an image.
    """
    pass


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
                msg = "Handling of event failed with traceback: %s" % (str(e))
                db_event.transition(EventState.FAILED, msg)
                db_event.builds_transition(ArtifactBuildState.FAILED.value, msg)
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

    # Defines the order of this handler when evaluating multiple handlers.
    # The handlers with lower order are called as first. If two handlers
    # have the same order value, they can be called in any random order.
    order = 50

    def __init__(self):
        self._db_event_id = None
        self._db_artifact_build_id = None
        self._log_prefix = ""
        self._force_dry_run = False
        self.odcs = FreshmakerODCSClient(self)

    def _log(self, log_fnc, msg, *args, **kwargs):
        """
        Logs the message `msg` using `log_fnc`, passing msg, *args and **kwargs
        to it.

        :param log_fnc: log.info, log.error, log.warning, ...
        :param str msg: Message to log (first argument passed to log_fnc).
        :param *args: Args passed to log_fnc.
        :param **kwargs: Kwargs passed to log_fnc.
        """
        return log_fnc("%s%s" % (self._log_prefix, msg), *args, **kwargs)

    def log_debug(self, msg, *args, **kwargs):
        """
        Wraps log.info, prefixes the message with a context of this handler.
        """
        return self._log(log.debug, msg, *args, **kwargs)

    def log_info(self, msg, *args, **kwargs):
        """
        Wraps log.info, prefixes the message with a context of this handler.
        """
        return self._log(log.info, msg, *args, **kwargs)

    def log_warn(self, msg, *args, **kwargs):
        """
        Wraps log.warning, prefixes the message with a context of this handler.
        """
        return self._log(log.warning, msg, *args, **kwargs)

    def log_error(self, msg, *args, **kwargs):
        """
        Wraps log.error, prefixes the message with a context of this handler.
        """
        return self._log(log.error, msg, *args, **kwargs)

    def force_dry_run(self):
        """
        Forces the handling of the current even in DRY_RUN mode.
        """
        self._force_dry_run = True

    @property
    def dry_run(self):
        """
        Returns True if the event should be hanled in DRY_RUN mode.
        """
        if self._force_dry_run:
            return True
        return conf.dry_run

    @property
    def current_db_event_id(self):
        return self._db_event_id

    @property
    def current_db_event(self):
        return db.session.query(Event).filter_by(id=self.current_db_event_id).first()

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
            self._log_prefix = "%s: " % str(db_object)
        elif type(db_object) == ArtifactBuild:
            self._db_event_id = db_object.event.id
            self._db_artifact_build_id = db_object.id
            # Prefix logs with "<models.Event> (<models.ArtifactBuild>):".
            self._log_prefix = "%s (%s): " % (str(db_object.event), str(db_object))
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

    def _match_allow_build_rule(self, criteria, rule):
        """
        Returns True if the build criteria matches the rule.

        :param dict criteria: key-val criteria defining all the attributes of
            an artifact which is considered for rebuild.
        :param dict or list of dicts rule: Rule from the Freshmaker
            configuration. It can be list or dict:

            If it is dict, all the key-vals in the rule dict must match the
            key-vals in the criteria dict. If the value is list for
            particular key in rule dict, the relationship between this list's
            items is OR.

            If it is list, it must have following format:

                ["operator_name", [{rules}, {to}, {evaluate}, ...]]

            Such list is constructed by freshmaker.config's any_() and all_()
            methods. The operator name is either "any" or "all".

            If "any" is used, this method returns True if *any* dict in list
            after the operator name matches the criteria.

            If "all" is used, this method returns True if *all* dicts in list
            after the operator name matches the criteria.
        :rtype: bool
        :return: True if the crtieria matches the rule.
        """
        # If rule is list, check each item (which should be a dict) separately
        # and return True if any item matches. Support also tuples for
        # convenience.
        if isinstance(rule, list):
            if not rule:
                return False

            if not isinstance(rule[0], six.string_types):
                raise TypeError(
                    "Rule does not have any operator, use any_() or all_() "
                    "methods to construct the rule: %r" % rule)

            if rule[0] == "any":
                operator = any
            elif rule[0] == "all":
                operator = all
            else:
                raise ValueError(
                    "Invalid operator %s in rule: %r." % (rule[0], rule))

            return operator([
                self._match_allow_build_rule(criteria, subrule)
                for subrule in rule[1]])

        if not isinstance(rule, dict):
            raise TypeError(
                "Rebuild rule must be dict or list, got %r." % rule)

        # If none of passed criteria matches configured rule, build is not allowed
        if not (set(rule.keys()) & set(criteria.keys())):
            return False

        # For each key-val of artifact to rebuild, check if it matches
        # the key-val of rule. If the key-val is not in the rule, it means
        # the configuration does not care about the value.
        for key, value in criteria.items():
            value_patterns = rule.get(key, None)
            if value_patterns is None:
                continue

            if not isinstance(value_patterns, (tuple, list)):
                value_patterns = [str(value_patterns)]

            if not any((re.match(regex, str(value)) for regex in value_patterns)):
                return False
        return True

    def allow_build(self, artifact_type, **criteria):
        """
        Check whether the artifact is allowed to be built by checking
        HANDLER_BUILD_WHITELIST in config.

        :param artifact_type: an enum member of ArtifactType.
        :param criteria: keyword arguments listing criteria that will be
            checked against whitelist to determine whether build is allowed.
            There is not specific order or logical relationship to these
            criteria. How they are checked depends on how whitelist is
            configured.
        :return: True if build is allowed, otherwise False is returned.
        :rtype: bool
        """
        # Global rules
        whitelist_rules = copy.deepcopy(
            conf.handler_build_whitelist.get("global", {}))
        blacklist_rules = copy.deepcopy(
            conf.handler_build_blacklist.get("global", {}))

        # This handler rules
        handler_name = self.name
        whitelist_rules.update(conf.handler_build_whitelist.get(handler_name, {}))
        blacklist_rules.update(conf.handler_build_blacklist.get(handler_name, {}))

        try:
            whitelist = whitelist_rules.get(artifact_type.name.lower(), [])
            if self._match_allow_build_rule(criteria, whitelist):
                blacklist = blacklist_rules.get(artifact_type.name.lower(), [])
                if self._match_allow_build_rule(criteria, blacklist):
                    self.log_debug('%r, type=%r is blacklisted.',
                                   criteria, artifact_type.name.lower())
                    return False
                self.log_debug('%r, type=%r is whitelisted.',
                               criteria, artifact_type.name.lower())
                self.log_debug('name=%r, whitelist=%r', handler_name, whitelist)
                return True
        except re.error as exc:
            err_msg = ("Error while compiling whilelist rule "
                       "for <handler(%s) artifact(%s)>:\n"
                       "Incorrect regular expression: %s\n"
                       "Whitelist will not take effect" %
                       (handler_name, artifact_type.name.lower(), str(exc)))
            self.log_error(err_msg)
            raise UnprocessableEntity(err_msg)

        self.log_debug('%r, type=%r is not whitelisted.',
                       criteria, artifact_type.name.lower())
        return False


class ContainerBuildHandler(BaseHandler):
    """Handler for building containers"""

    def build_container(self, scm_url, branch, target,
                        repo_urls=None, isolated=False,
                        release=None, koji_parent_build=None,
                        arch_override=None, compose_ids=None):
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
        with koji_service(
                profile=conf.koji_profile, logger=log,
                dry_run=self.dry_run) as service:
            log.info('Building container from source: %s, '
                     'release=%r, parent=%r, target=%r, arch=%r, compose_ids=%r',
                     scm_url, release, koji_parent_build, target, arch_override,
                     compose_ids)

            return service.build_container(scm_url,
                                           branch,
                                           target,
                                           repo_urls=repo_urls,
                                           isolated=isolated,
                                           release=release,
                                           koji_parent_build=koji_parent_build,
                                           arch_override=arch_override,
                                           scratch=conf.koji_container_scratch_build,
                                           compose_ids=compose_ids)

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
        scm_url = "%s/%s#%s" % (conf.git_base_url, args["repository"],
                                args["commit"])
        branch = args["branch"]
        target = args["target"]
        parent = args["parent"]

        # If set to None, then OSBS defaults to using the arches
        # of the build tag associated with the target.
        arches = args.get("arches")

        if not build.rebuilt_nvr and build.original_nvr:
            build.rebuilt_nvr = get_rebuilt_nvr(
                build.type, build.original_nvr)

        if not build.rebuilt_nvr:
            build.transition(
                ArtifactBuildState.FAILED.value,
                "Container image does not have rebuilt_nvr set.")
            return

        release = parse_NVR(build.rebuilt_nvr)["release"]

        # Get the list of ODCS compose IDs which should be used to build
        # the image.
        compose_ids = []
        for relation in build.composes:
            compose_ids.append(relation.compose.odcs_compose_id)
        if args["renewed_odcs_compose_ids"]:
            compose_ids += args["renewed_odcs_compose_ids"]

        # OSBS cannot handle both repo_urls and compose_ids in the same time.
        # We use repo_urls only in special cases to build base images. In this
        # cases, we want to convert compose_ids to repository URLs. Otherwise,
        # just pass compose_ids to OSBS via Koji.
        if repo_urls:
            for compose_id in compose_ids:
                odcs_compose = self.odcs_get_compose(compose_id)
                if odcs_compose["state"] in [COMPOSE_STATES['wait'],
                                             COMPOSE_STATES['generating']]:
                    # In case the ODCS compose is still generating, raise an
                    # exception.
                    msg = ("Compose %s is not in done state. Waiting with "
                           "rebuild." % (str(compose_id)))
                    self.log_info(msg)
                    raise ODCSComposeNotReady(msg)
                elif odcs_compose["state"] != COMPOSE_STATES["done"]:
                    # In case the compose is not in 'done' state, mark the
                    # build as failed. We should never get expired here,
                    # because the compose has been submitted just a minutes
                    # ago. If we get "expired" here, it is sign of an issue,
                    # because that means we are trying to build quite old
                    # image.
                    build.transition(
                        ArtifactBuildState.FAILED.value,
                        "Compose %s is not in 'done' state." % str(compose_id))
                    return
                repo_urls.append(odcs_compose["result_repofile"])
            compose_ids = []

        return self.build_container(
            scm_url, branch, target, repo_urls=repo_urls,
            isolated=True, release=release, koji_parent_build=parent,
            arch_override=arches, compose_ids=compose_ids)

    def odcs_get_compose(self, compose_id):
        """
        Returns the information from the ODCS server about compose with id
        `compose_id`. In DRY_RUN mode, returns fake compose information
        without contacting the ODCS server.
        """
        if self.dry_run:
            compose = {}
            compose['id'] = compose_id
            compose['result_repofile'] = "http://localhost/%d.repo" % (
                compose['id'])
            compose['state'] = COMPOSE_STATES['done']
            return compose

        with krb_context():
            return create_odcs_client().get_compose(compose_id)

    def get_repo_urls(self, build):
        """
        Returns list of URLs to ODCS repositories which should be used
        to rebuild the container image for this event.

        :param build: from this build to gather repo URLs.
        :type build: ArtifactBuild
        :return: list of repository URLs.
        :rtype: list
        """
        repo_urls = []

        # Include image_extra_repos if any for this name-version.
        if build.original_nvr:
            parsed_nvr = parse_NVR(build.original_nvr)
            name_version = "%s-%s" % (parsed_nvr["name"], parsed_nvr["version"])
            if name_version in conf.image_extra_repo:
                repo_urls.append(conf.image_extra_repo[name_version])
        return repo_urls

    def start_to_build_images(self, builds):
        """Start to build images

        :param builds: list of ArtifactBuild, each of them represents a
            container image to be rebuilt.
        :type builds: list or tuple
        """

        def build_image(build):
            self.set_context(build)
            repo_urls = self.get_repo_urls(build)
            try:
                build.build_id = self.build_image_artifact_build(build, repo_urls)
            except ODCSComposeNotReady:
                # We skip this image for now. It will be built once the ODCS
                # compose is finished.
                return
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

        list(six.moves.map(build_image, builds))
