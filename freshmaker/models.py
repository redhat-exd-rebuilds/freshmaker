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

# BUILD_STATES for the builds submitted by Freshmaker
BUILD_STATES = {
    # Artifact is building.
    "build": 0,
    # Artifact build is sucessfuly done.
    "done": 1,
    # Artifact build has failed.
    "failed": 2,
    # Artifact build is canceled.
    "canceled": 3,
}

INVERSE_BUILD_STATES = {v: k for k, v in BUILD_STATES.items()}

ARTIFACT_TYPES = {
    "rpm": 0,
    "image": 1,
    "module": 2,
    }

INVERSE_ARTIFACT_TYPES = {v: k for k, v in ARTIFACT_TYPES.items()}


class FreshmakerBase(db.Model):
    __abstract__ = True


class Event(FreshmakerBase):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String, nullable=False)

    # List of builds associated with this Event.
    builds = relationship("ArtifactBuild", back_populates="event")

    @classmethod
    def create(cls, session, message_id):
        event = cls(
            message_id=message_id,
        )
        session.add(event)
        return event

    @classmethod
    def get_or_create(cls, session, message_id):
        instance = session.query(cls).filter_by(message_id=message_id).first()
        if instance:
            return instance
        return cls.create(session, message_id)

    def __repr__(self):
        return "<Event %s>" % (self.message_id)


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
        if field in BUILD_STATES.values():
            return field
        if field in BUILD_STATES:
            return BUILD_STATES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, BUILD_STATES))

    @validates('type')
    def validate_type(self, key, field):
        if field in ARTIFACT_TYPES.values():
            return field
        if field in ARTIFACT_TYPES:
            return ARTIFACT_TYPES[field]
        raise ValueError("%s: %s, not in %r" % (key, field, ARTIFACT_TYPES))

    def __repr__(self):
        return "<ArtifactBuild %s, type %s, state %s, event %s>" % (
            self.name, INVERSE_ARTIFACT_TYPES[self.type],
            INVERSE_BUILD_STATES[self.state], self.event.message_id)
