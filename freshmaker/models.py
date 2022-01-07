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
# Written by Jan Kaluza <jkaluza@redhat.com>

""" SQLAlchemy Database models for the Flask app
"""

import json

from collections import defaultdict
from datetime import datetime
from sqlalchemy.orm import (validates, relationship)
from sqlalchemy.schema import Index
from sqlalchemy.sql.expression import false

from flask_login import UserMixin

from freshmaker import db, log
from freshmaker import messaging
from freshmaker.utils import get_url_for
from freshmaker.types import (ArtifactType, ArtifactBuildState, EventState,
                              RebuildReason)
from freshmaker.events import (
    MBSModuleStateChangeEvent, GitModuleMetadataChangeEvent,
    GitRPMSpecChangeEvent, TestingEvent, GitDockerfileChangeEvent,
    BodhiUpdateCompleteStableEvent, KojiTaskStateChangeEvent, BrewSignRPMEvent,
    ErrataAdvisoryRPMsSignedEvent, BrewContainerTaskStateChangeEvent,
    ErrataAdvisoryStateChangedEvent, FreshmakerManualRebuildEvent,
    ODCSComposeStateChangeEvent, ManualRebuildWithAdvisoryEvent,
    FreshmakerAsyncManualBuildEvent, BotasErrataShippedEvent,
    ManualBundleRebuildEvent,
    FlatpakModuleAdvisoryReadyEvent,
    FlatpakApplicationManualBuildEvent,
)

EVENT_TYPES = {
    MBSModuleStateChangeEvent: 0,
    GitModuleMetadataChangeEvent: 1,
    GitRPMSpecChangeEvent: 2,
    TestingEvent: 3,
    GitDockerfileChangeEvent: 4,
    BodhiUpdateCompleteStableEvent: 5,
    KojiTaskStateChangeEvent: 6,
    BrewSignRPMEvent: 7,
    ErrataAdvisoryRPMsSignedEvent: 8,
    BrewContainerTaskStateChangeEvent: 9,
    ErrataAdvisoryStateChangedEvent: 10,
    FreshmakerManualRebuildEvent: 11,
    ODCSComposeStateChangeEvent: 12,
    ManualRebuildWithAdvisoryEvent: 13,
    FreshmakerAsyncManualBuildEvent: 14,
    BotasErrataShippedEvent: 15,
    ManualBundleRebuildEvent: 16,
    FlatpakModuleAdvisoryReadyEvent: 17,
    FlatpakApplicationManualBuildEvent: 18,
}

INVERSE_EVENT_TYPES = {v: k for k, v in EVENT_TYPES.items()}


def _utc_datetime_to_iso(datetime_object):
    """
    Takes a UTC datetime object and returns an ISO formatted string
    :param datetime_object: datetime.datetime
    :return: string with datetime in ISO format
    """
    if datetime_object:
        # Converts the datetime to ISO 8601
        return datetime_object.strftime("%Y-%m-%dT%H:%M:%SZ")

    return None


def commit_on_success(func):
    """
    Ensures db session is committed after a successful call to decorated
    function, otherwise rollback.
    """
    def _decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.commit()
    return _decorator


class FreshmakerBase(db.Model):
    __abstract__ = True


class User(FreshmakerBase, UserMixin):
    """User information table"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), nullable=False, unique=True)

    @classmethod
    def find_user_by_name(cls, username):
        """Find a user by username

        :param str username: a string of username to find user
        :return: user object if found, otherwise None is returned.
        :rtype: User
        """
        try:
            return db.session.query(cls).filter(cls.username == username)[0]
        except IndexError:
            return None

    @classmethod
    def create_user(cls, username):
        user = cls(username=username)
        db.session.add(user)
        return user


class Event(FreshmakerBase):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    # ID of message generating the rebuild event.
    message_id = db.Column(db.String, nullable=False)
    # Searchable key for the event - used when searching for events from the JSON
    # API.
    search_key = db.Column(db.String, nullable=False)
    # Event type id defined in EVENT_TYPES - ID of class inherited from
    # BaseEvent class - used when searching for events of particular type.
    event_type_id = db.Column(db.Integer, nullable=False)
    # True when the Event is already released and we do not have to include
    # it in the future rebuilds of artifacts.
    # This is currently only used for internal Docker images rebuilds, but in
    # the future might be used even for modules or Fedora Docker images.
    released = db.Column(db.Boolean, default=True)
    state = db.Column(db.Integer, nullable=False)
    state_reason = db.Column(db.String, nullable=True)
    time_created = db.Column(db.DateTime, nullable=True)
    time_done = db.Column(db.DateTime, nullable=True)
    # AppenderQuery for getting builds associated with this Event.
    builds = relationship("ArtifactBuild", back_populates="event",
                          lazy="dynamic", cascade="all, delete-orphan",
                          passive_deletes=True)
    # True if the even should be handled in dry run mode.
    dry_run = db.Column(db.Boolean, default=False)
    # For manual rebuilds, set to user requesting the rebuild. Otherwise null.
    requester = db.Column(db.String, nullable=True)
    # For manual rebuilds, contains the white-space separate list of artifacts
    # (for example NVR of container images) to rebuild if passed using the
    # REST API.
    requested_rebuilds = db.Column(db.String, nullable=True)
    # For manual rebuilds, contains the serialized JSON optionally submitted
    # by the requester to track the context of this event.
    requester_metadata = db.Column(db.String, nullable=True)

    manual_triggered = db.Column(
        db.Boolean,
        default=False,
        doc='Whether this event is triggered manually')

    @classmethod
    def create(cls, session, message_id, search_key, event_type, released=True,
               state=None, manual=False, dry_run=False, requester=None,
               requested_rebuilds=None, requester_metadata=None):
        if event_type in EVENT_TYPES:
            event_type = EVENT_TYPES[event_type]
        now = datetime.utcnow()
        event = cls(
            message_id=message_id,
            search_key=search_key,
            event_type_id=event_type,
            released=released,
            state=state or EventState.INITIALIZED.value,
            time_created=now,
            manual_triggered=manual,
            dry_run=dry_run,
            requester=requester,
            requested_rebuilds=requested_rebuilds,
            requester_metadata=requester_metadata,
        )
        session.add(event)
        return event

    @validates('state')
    def validate_state(self, key, field):
        if field in [s.value for s in list(EventState)]:
            return field
        if field in [s.name.lower() for s in list(EventState)]:
            return EventState[field.upper()].value
        if isinstance(field, EventState):
            return field.value
        raise ValueError("%s: %s, not in %r" % (key, field, list(EventState)))

    @classmethod
    def get(cls, session, message_id):
        return session.query(cls).filter_by(message_id=message_id).first()

    @classmethod
    def get_or_create(cls, session, message_id, search_key, event_type,
                      released=True, manual=False, dry_run=False,
                      requester=None, requested_rebuilds=None,
                      requester_metadata=None):
        instance = cls.get(session, message_id)
        if instance:
            return instance
        instance = cls.create(
            session, message_id, search_key, event_type,
            released=released, manual=manual, dry_run=dry_run,
            requester=requester, requested_rebuilds=requested_rebuilds,
            requester_metadata=requester_metadata)
        session.commit()
        return instance

    @classmethod
    def get_or_create_from_event(cls, session, event, released=True):
        # we must extract all needed arguments,
        # because event might not have some of them so we will use defaults
        requester = getattr(event, "requester", None)
        requested_rebuilds_list = getattr(event, "container_images", None)
        requested_rebuilds = None
        # make sure 'container_images' field is a list and convert it to str
        if requested_rebuilds_list is not None and \
                isinstance(requested_rebuilds_list, list):
            requested_rebuilds = " ".join(requested_rebuilds_list)
        requester_metadata = getattr(event, "requester_metadata_json", None)
        if requester_metadata is not None:
            # try to convert JSON into str, if it's invalid use None
            try:
                requester_metadata = json.dumps(requester_metadata)
            except TypeError:
                log.warning("requester_metadata_json field is ill-formatted: %s",
                            requester_metadata)
                requester_metadata = None

        return cls.get_or_create(session, event.msg_id,
                                 event.search_key, event.__class__,
                                 released=released, manual=event.manual,
                                 dry_run=event.dry_run, requester=requester,
                                 requested_rebuilds=requested_rebuilds,
                                 requester_metadata=requester_metadata)

    @classmethod
    def get_unreleased(cls, session, states=None):
        """
        Returns list of all unreleased events in given states. If no states
        are provided, returns only events in INITIALIZED, BUILDING or COMPLETE
        state.
        :param session: db.session
        :param list states: List of states to filter events for. If None,
            INITIALIZED, BUILDING and COMPLETE is used.
        :rtype: list of models.Event.
        :return: List of unreleased events of `states` state.
        """
        if not states:
            states = [EventState.INITIALIZED.value,
                      EventState.BUILDING.value,
                      EventState.COMPLETE.value]
        else:
            states = [
                state.value if isinstance(state, EventState) else state for
                state in states
            ]
        return session.query(cls).filter(cls.released == false(),
                                         cls.state.in_(states)).all()

    @classmethod
    def get_by_event_id(cls, session, event_id):
        return session.query(cls).filter_by(id=event_id).first()

    def get_image_builds_in_first_batch(self, session):
        return session.query(ArtifactBuild).filter_by(
            dep_on=None,
            type=ArtifactType.IMAGE.value,
            event_id=self.id,
        ).all()

    @property
    def event_type(self):
        return INVERSE_EVENT_TYPES[self.event_type_id]

    def add_event_dependency(self, session, event):
        """Add a dependent event

        :param session: the `db.session`.
        :param event: the dependent event to be added.
        :type event: :py:class:`Event`
        :return: instance of :py:class:`EventDependency`. Caller is responsible
            for committing changes to database. If `event` has been added
            already, nothing changed and `None` will be returned.
        """
        dep = session.query(EventDependency.id).filter_by(
            event_id=self.id, event_dependency_id=event.id).first()
        if dep is None:
            dep = EventDependency(event_id=self.id,
                                  event_dependency_id=event.id)
            session.add(dep)
            return dep
        else:
            return None

    @property
    def event_dependencies(self):
        """
        Returns the list of Events this Event depends on.
        """
        events = []
        deps = EventDependency.query.filter_by(event_id=self.id).all()
        for dep in deps:
            events.append(Event.query.filter_by(
                id=dep.event_dependency_id).first())
        return events

    @property
    def depending_events(self):
        """
        Returns the list of Events depending on this Event.
        """
        depending_events = []
        parents = EventDependency.query.filter_by(event_dependency_id=self.id).all()
        for p in parents:
            depending_events.append(Event.query.filter_by(
                id=p.event_id).first())
        return depending_events

    def has_all_builds_in_state(self, state):
        """
        Returns True when all builds are in the given `state`.
        """
        return db.session.query(ArtifactBuild).filter_by(
            event_id=self.id).filter(state != state).count() == 0

    def builds_transition(self, state, reason, filters=None):
        """
        Calls transition(state, reason) for all builds associated with this
        event.

        :param dict filters: Filter only specific builds to transition.
        :return: list of build ids which were transitioned
        """

        if not self.builds:
            return []

        builds_to_transition = self.builds.filter_by(
            **filters).all() if isinstance(filters, dict) else self.builds

        return [build.id
                for build in builds_to_transition if build.transition(state, reason)]

    def transition(self, state, state_reason=None):
        """
        Sets the time_done, state, and state_reason of this Event.

        :param state: EventState value
        :param state_reason: Reason why this state has been set.
        :return: True/False, whether state was changed
        """
        # Convert state from its possible representation to number.
        state = self.validate_state("state", state)

        # Update the state reason.
        if state_reason is not None:
            self.state_reason = state_reason

        # Log the state and state_reason
        if state == EventState.FAILED.value:
            log_fnc = log.error
        else:
            log_fnc = log.info
        log_fnc("Event %r moved to state %s, %r" % (
            self, EventState(state).name, state_reason))

        # In case Event is already in the state, return False.
        if self.state == state:
            return False

        self.state = state

        # Log the time done
        if state in [EventState.FAILED.value, EventState.COMPLETE.value,
                     EventState.SKIPPED.value, EventState.CANCELED.value]:
            self.time_done = datetime.utcnow()

        if EventState(state).counter:
            EventState(state).counter.inc()

        db.session.commit()
        messaging.publish('event.state.changed', self.json())
        messaging.publish('event.state.changed.min', self.json_min())

        return True

    def __repr__(self):
        return "<Event %s, %r, %s>" % (self.message_id, self.event_type, self.search_key)

    def __str__(self):
        if self.event_type_id in INVERSE_EVENT_TYPES:
            type_name = INVERSE_EVENT_TYPES[self.event_type_id].__name__
        else:
            type_name = "UnknownEventType %d" % self.event_type_id
        return "<%s, search_key=%s>" % (type_name, self.search_key)

    @property
    def requester_metadata_json(self):
        if not self.requester_metadata:
            return {}
        return json.loads(self.requester_metadata)

    def json(self):
        data = self._common_json()
        data['builds'] = [b.json() for b in self.builds]
        return data

    def json_min(self):
        builds_summary = defaultdict(int)
        builds_summary['total'] = len(self.builds.all())
        for build in self.builds:
            state_name = ArtifactBuildState(build.state).name
            builds_summary[state_name] += 1

        data = self._common_json()
        data['builds_summary'] = dict(builds_summary)
        return data

    def _common_json(self):
        event_url = get_url_for('event', id=self.id)
        db.session.add(self)
        return {
            "id": self.id,
            "message_id": self.message_id,
            "search_key": self.search_key,
            "event_type_id": self.event_type_id,
            "state": self.state,
            "state_name": EventState(self.state).name,
            "state_reason": self.state_reason,
            "time_created": _utc_datetime_to_iso(self.time_created),
            "time_done": _utc_datetime_to_iso(self.time_done),
            "url": event_url,
            "dry_run": self.dry_run,
            "requester": self.requester,
            "requested_rebuilds": (self.requested_rebuilds.split(" ")
                                   if self.requested_rebuilds else []),
            "requester_metadata": self.requester_metadata_json,
            "depends_on_events": [event.id for event in self.event_dependencies],
            "depending_events": [event.id for event in self.depending_events],
        }

    def find_dependent_events(self):
        """
        Find other unreleased Events which built the same builds (or just some
        of them) as this Event and adds them as a dependency for this event.

        Dependent events of may also rebuild some same images that current event
        will build. So, for building images found from current event, we also
        need those YUM repositories used to build images in dependent events.
        """
        builds_nvrs = [build.name for build in self.builds]

        states = [EventState.INITIALIZED.value,
                  EventState.BUILDING.value,
                  EventState.COMPLETE.value]

        query = db.session.query(ArtifactBuild.event_id)
        dep_event_ids = query.join(ArtifactBuild.event).filter(
            ArtifactBuild.name.in_(builds_nvrs),
            ArtifactBuild.event_id != self.id,
            ArtifactBuild.type == ArtifactType.IMAGE.value,
            Event.manual_triggered == false(),
            Event.released == false(),
            Event.state.in_(states),
        ).distinct()

        dep_events = []
        query = db.session.query(Event)
        for row in dep_event_ids:
            dep_event = query.filter_by(id=row[0]).first()
            self.add_event_dependency(db.session, dep_event)
            dep_events.append(dep_event)
        db.session.commit()
        return dep_events

    def get_artifact_build_from_event_dependencies(self, nvr):
        """
        It returns the artifact build, with `DONE` state, from the event dependencies (the build
        of the parent event). `nvr` is used as `original_nvr` when finding the `ArtifactBuild`.
        It returns all the parent artifact builds from the first found event dependency.
        If the build is not found, it returns None.
        """
        for parent_event in self.event_dependencies:
            parent_build = db.session.query(
                ArtifactBuild).filter_by(event_id=parent_event.id,
                                         original_nvr=nvr,
                                         state=ArtifactBuildState.DONE.value).all()
            if parent_build:
                return parent_build


Index('idx_event_message_id', Event.message_id, unique=True)


class EventDependency(FreshmakerBase):
    __tablename__ = "event_dependencies"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    event_dependency_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)


Index(
    'idx_event_dependency_rel',
    EventDependency.event_id,
    EventDependency.event_dependency_id,
    unique=True)


class ArtifactBuild(FreshmakerBase):
    __tablename__ = "artifact_builds"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    original_nvr = db.Column(db.String, nullable=True)
    rebuilt_nvr = db.Column(db.String, nullable=True)
    type = db.Column(db.Integer)
    state = db.Column(db.Integer, nullable=False)
    state_reason = db.Column(db.String, nullable=True)
    time_submitted = db.Column(db.DateTime, nullable=False)
    time_completed = db.Column(db.DateTime)

    # Link to the Artifact on which this one depends and which triggered
    # the rebuild of this Artifact.
    dep_on_id = db.Column(db.Integer, db.ForeignKey('artifact_builds.id'))
    dep_on = relationship('ArtifactBuild', remote_side=[id])

    # Event associated with this Build
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    event = relationship("Event", back_populates="builds")

    # Id of corresponding real build in external build system.
    # For container images (the only supported artifact at this moment),
    # this is the Koji (or Brew) buildContainer task ID. It could be NULL,
    # which means Freshmaker did not submit a buildContainer task (due to
    # some other failure), or Koji failed to return a task ID for some
    # reason.
    build_id = db.Column(db.Integer)

    # Build args in json format.
    build_args = db.Column(db.String, nullable=True)

    # The reason why this artifact is rebuilt. Set according to
    # `freshmaker.types.RebuildReason`.
    rebuild_reason = db.Column(db.Integer, nullable=True)

    # pullspec overrides
    _bundle_pullspec_overrides = db.Column(
        "bundle_pullspec_overrides", db.Text, nullable=True
    )

    composes = db.relationship('ArtifactBuildCompose', back_populates='build')

    @classmethod
    def create(cls, session, event, name, type,
               build_id=None, dep_on=None, state=None,
               original_nvr=None, rebuilt_nvr=None,
               rebuild_reason=0):

        now = datetime.utcnow()
        build = cls(
            name=name,
            original_nvr=original_nvr,
            rebuilt_nvr=rebuilt_nvr,
            type=type,
            event=event,
            state=state or ArtifactBuildState.BUILD.value,
            build_id=build_id,
            time_submitted=now,
            dep_on=dep_on,
            rebuild_reason=rebuild_reason
        )
        session.add(build)
        return build

    @validates('state')
    def validate_state(self, key, field):
        if field in [s.value for s in list(ArtifactBuildState)]:
            return field
        if field in [s.name.lower() for s in list(ArtifactBuildState)]:
            return ArtifactBuildState[field.upper()].value
        if isinstance(field, ArtifactBuildState):
            return field.value
        raise ValueError("%s: %s, not in %r" % (key, field, list(ArtifactBuildState)))

    @validates('type')
    def validate_type(self, key, field):
        if field in [t.value for t in list(ArtifactType)]:
            return field
        if field in [t.name.lower() for t in list(ArtifactType)]:
            return ArtifactType[field.upper()].value
        if isinstance(field, ArtifactType):
            return field.value
        raise ValueError("%s: %s, not in %r" % (key, field, list(ArtifactType)))

    @classmethod
    def get_lowest_build_id(cls, session):
        """
        Returns the lowest build_id. If there is no build so far,
        returns 0.
        """
        build = (session.query(ArtifactBuild)
                 .filter(cls.build_id != None)  # noqa
                 .order_by(ArtifactBuild.build_id.asc())
                 .first())
        if not build:
            return 0
        return build.build_id

    @classmethod
    def get_most_original_nvr(cls, nvr):
        """
        Get original NVR recursively until reach the one which was not built by freshmaker

        Return the NVR of most original image
        """
        original_nvr = None
        build = db.session.query(ArtifactBuild).filter(cls.rebuilt_nvr == nvr).first()
        while build:
            original_nvr = build.original_nvr
            build = db.session.query(ArtifactBuild).filter(cls.rebuilt_nvr == original_nvr).first()
        return original_nvr

    @property
    def bundle_pullspec_overrides(self):
        """Return the Python representation of the JSON bundle_pullspec_overrides."""
        return (
            json.loads(self._bundle_pullspec_overrides)
            if self._bundle_pullspec_overrides
            else None
        )

    @bundle_pullspec_overrides.setter
    def bundle_pullspec_overrides(self, bundle_pullspec_overrides):
        """
        Set the bundle_pullspec_overrides column to the input bundle_pullspec_overrides as a JSON string.
        If ``None`` is provided, it will be simply set to ``None`` and not be converted to JSON.
        :param dict bundle_pullspec_overrides: the dictionary of the bundle_pullspec_overrides or ``None``
        """
        self._bundle_pullspec_overrides = (
            json.dumps(bundle_pullspec_overrides, sort_keys=True)
            if bundle_pullspec_overrides is not None
            else None
        )

    def depending_artifact_builds(self):
        """
        Returns list of artifact builds depending on this one.
        """
        return ArtifactBuild.query.filter_by(dep_on_id=self.id).all()

    def transition(self, state, state_reason):
        """
        Sets the state and state_reason of this ArtifactBuild.

        :param state: ArtifactBuildState value
        :param state_reason: Reason why this state has been set.
        :return: True/False, whether state was changed
        """
        # Convert state from its possible representation to number.
        state = self.validate_state("state", state)

        # Log the state and state_reason
        if state == ArtifactBuildState.FAILED.value:
            log_fnc = log.error
        else:
            log_fnc = log.info
        log_fnc("Artifact build %r moved to state %s, %r" % (
            self, ArtifactBuildState(state).name, state_reason))

        if self.state == state:
            return False

        self.state = state
        if ArtifactBuildState(state).counter:
            ArtifactBuildState(state).counter.inc()

        self.state_reason = state_reason
        if self.state in [ArtifactBuildState.DONE.value,
                          ArtifactBuildState.FAILED.value,
                          ArtifactBuildState.CANCELED.value]:
            self.time_completed = datetime.utcnow()

        # For FAILED/CANCELED states, move also all the artifacts depending
        # on this one to FAILED/CANCELED state, because there is no way we
        # can rebuild them.
        if self.state in [ArtifactBuildState.FAILED.value,
                          ArtifactBuildState.CANCELED.value]:
            for build in self.depending_artifact_builds():
                build.transition(
                    self.state, "Cannot build artifact, because its "
                    "dependency cannot be built.")

        messaging.publish('build.state.changed', self.json())

        return True

    def __repr__(self):
        return "<ArtifactBuild %s, type %s, state %s, event %s>" % (
            self.name, ArtifactType(self.type).name,
            ArtifactBuildState(self.state).name, self.event.message_id)

    def json(self):
        build_args = {}
        if self.build_args:
            build_args = json.loads(self.build_args)

        build_url = get_url_for('build', id=self.id)
        db.session.add(self)
        return {
            "id": self.id,
            "name": self.name,
            "original_nvr": self.original_nvr,
            "rebuilt_nvr": self.rebuilt_nvr,
            "type": self.type,
            "type_name": ArtifactType(self.type).name,
            "state": self.state,
            "state_name": ArtifactBuildState(self.state).name,
            "state_reason": self.state_reason,
            "dep_on": self.dep_on.name if self.dep_on else None,
            "dep_on_id": self.dep_on.id if self.dep_on else None,
            "time_submitted": _utc_datetime_to_iso(self.time_submitted),
            "time_completed": _utc_datetime_to_iso(self.time_completed),
            "event_id": self.event_id,
            "build_id": self.build_id,
            "url": build_url,
            "build_args": build_args,
            "odcs_composes": [rel.compose.odcs_compose_id for rel in self.composes],
            "rebuild_reason": RebuildReason(self.rebuild_reason or 0).name.lower()
        }

    def get_root_dep_on(self):
        dep_on = self.dep_on
        while dep_on:
            dep = dep_on.dep_on
            if dep:
                dep_on = dep
            else:
                break
        return dep_on

    def add_composes(self, session, composes):
        """Add an ODCS compose to this build"""
        for compose in composes:
            session.add(ArtifactBuildCompose(
                build_id=self.id, compose_id=compose.id))

    @property
    def composes_ready(self):
        """Check if composes this build has have been done in ODCS"""
        return all((rel.compose.finished for rel in self.composes))

    @classmethod
    def get_rebuilt_original_nvrs_by_search_key(cls, session, search_key, directly_affected=True):
        """Get NVRs of original images which have been rebuilt successfully in events"""
        builds = (
            session.query(cls)
            .filter(cls.event.has(search_key=search_key))
            .filter(cls.state == ArtifactBuildState.DONE.value)
        )
        if directly_affected:
            builds = builds.filter(cls.rebuild_reason == RebuildReason.DIRECTLY_AFFECTED.value)

        return list({b.original_nvr for b in builds.all()})


class Compose(FreshmakerBase):
    __tablename__ = 'composes'

    id = db.Column(db.Integer, primary_key=True)
    odcs_compose_id = db.Column(db.Integer, nullable=False)

    builds = db.relationship('ArtifactBuildCompose', back_populates='compose')

    @property
    def finished(self):
        from freshmaker.odcsclient import create_odcs_client
        return 'done' == create_odcs_client().get_compose(
            self.odcs_compose_id)['state_name']

    @classmethod
    def get_lowest_compose_id(cls, session):
        """
        Returns the lowest odcs_compose_id. If there is no compose,
        returns 0.
        """
        compose = session.query(Compose).order_by(
            Compose.odcs_compose_id.asc()).first()
        if not compose:
            return 0
        return compose.odcs_compose_id


Index('idx_odcs_compose_id', Compose.odcs_compose_id, unique=True)


class ArtifactBuildCompose(FreshmakerBase):
    __tablename__ = 'artifact_build_composes'

    build_id = db.Column(
        db.Integer,
        db.ForeignKey('artifact_builds.id'),
        primary_key=True)

    compose_id = db.Column(
        db.Integer,
        db.ForeignKey('composes.id'),
        primary_key=True)

    build = db.relationship('ArtifactBuild', back_populates='composes')
    compose = db.relationship('Compose', back_populates='builds')
