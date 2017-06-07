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

from datetime import datetime
from sqlalchemy.orm import (validates, relationship)

from freshmaker import db
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.events import (
    MBSModuleStateChangeEvent, GitModuleMetadataChangeEvent,
    GitRPMSpecChangeEvent, TestingEvent, GitDockerfileChangeEvent,
    BodhiUpdateCompleteStableEvent, KojiTaskStateChangeEvent)

EVENT_TYPES = {
    MBSModuleStateChangeEvent: 0,
    GitModuleMetadataChangeEvent: 1,
    GitRPMSpecChangeEvent: 2,
    TestingEvent: 3,
    GitDockerfileChangeEvent: 4,
    BodhiUpdateCompleteStableEvent: 5,
    KojiTaskStateChangeEvent: 6,
}

INVERSE_EVENT_TYPES = {v: k for k, v in EVENT_TYPES.items()}


class FreshmakerBase(db.Model):
    __abstract__ = True


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

    # List of builds associated with this Event.
    builds = relationship("ArtifactBuild", back_populates="event")

    @classmethod
    def create(cls, session, message_id, search_key, event_type):
        if event_type in EVENT_TYPES:
            event_type = EVENT_TYPES[event_type]
        event = cls(
            message_id=message_id,
            search_key=search_key,
            event_type_id=event_type
        )
        session.add(event)
        return event

    @classmethod
    def get_or_create(cls, session, message_id, search_key, event_type):
        instance = session.query(cls).filter_by(message_id=message_id).first()
        if instance:
            return instance
        return cls.create(session, message_id, search_key, event_type)

    @property
    def event_type(self):
        return INVERSE_EVENT_TYPES[self.event_type_id]

    def __repr__(self):
        return "<Event %s, %r, %s>" % (self.message_id, self.event_type, self.search_key)


class ArtifactBuild(FreshmakerBase):
    __tablename__ = "artifact_builds"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    type = db.Column(db.Integer)
    state = db.Column(db.Integer, nullable=False)
    time_submitted = db.Column(db.DateTime, nullable=False)
    time_completed = db.Column(db.DateTime)

    # Link to the Artifact on which this one depends and which triggered
    # the rebuild of this Artifact.
    dep_of_id = db.Column(db.Integer, db.ForeignKey('artifact_builds.id'))
    dep_of = relationship('ArtifactBuild', remote_side=[id])

    # Event associated with this Build
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    event = relationship("Event", back_populates="builds")

    # Id of a build in the build system
    build_id = db.Column(db.Integer)

    @classmethod
    def create(cls, session, event, name, type, build_id, dep_of=None):
        now = datetime.utcnow()
        build = cls(
            name=name,
            type=type,
            event=event,
            state="build",
            build_id=build_id,
            time_submitted=now,
            dep_of=dep_of
        )
        session.add(build)
        return build

    @validates('state')
    def validate_state(self, key, field):
        if field in [s.value for s in list(ArtifactBuildState)]:
            return field
        if field in [s.name.lower() for s in list(ArtifactBuildState)]:
            return ArtifactBuildState[field.upper()].value
        raise ValueError("%s: %s, not in %r" % (key, field, list(ArtifactBuildState)))

    @validates('type')
    def validate_type(self, key, field):
        if field in [t.value for t in list(ArtifactType)]:
            return field
        if field in [t.name.lower() for t in list(ArtifactType)]:
            return ArtifactType[field.upper()].value
        raise ValueError("%s: %s, not in %r" % (key, field, list(ArtifactType)))

    def __repr__(self):
        return "<ArtifactBuild %s, type %s, state %s, event %s>" % (
            self.name, ArtifactType(self.type).name,
            ArtifactBuildState(self.state).name, self.event.message_id)
