# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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

import os
import tempfile

from freshmaker import db
from flask import Response
from flask.views import MethodView
from prometheus_client import (
    ProcessCollector, CollectorRegistry, Counter, multiprocess,
    Histogram, generate_latest)
from sqlalchemy import event


if not os.environ.get('prometheus_multiproc_dir'):
    os.environ.setdefault('prometheus_multiproc_dir', tempfile.mkdtemp())
registry = CollectorRegistry()
ProcessCollector(registry=registry)
multiprocess.MultiProcessCollector(registry)

# Generic metrics
messaging_received_counter = Counter(
    'messaging_received',
    'Total number of messages received',
    registry=registry)
messaging_received_ignored_counter = Counter(
    'messaging_received_ignored',
    'Number of received messages, which were ignored',
    registry=registry)
messaging_received_passed_counter = Counter(
    'messaging_received_passed',
    'Number of received messages, which were processed successfully',
    registry=registry)
messaging_received_failed_counter = Counter(
    'messaging_received_failed',
    'Number of received messages, which failed during processing',
    registry=registry)

db_dbapi_error_counter = Counter(
    'db_dbapi_error',
    'Number of DBAPI errors',
    registry=registry)
db_engine_connect_counter = Counter(
    'db_engine_connect',
    'Number of \'engine_connect\' events',
    registry=registry)
db_handle_error_counter = Counter(
    'db_handle_error',
    'Number of exceptions during connection',
    registry=registry)
db_transaction_begin_counter = Counter(
    'db_transaction_begin',
    'Number of started transactions',
    registry=registry)
db_transaction_commit_counter = Counter(
    'db_transaction_commit',
    'Number of transactions, which were committed',
    registry=registry)
db_transaction_rollback_counter = Counter(
    'db_transaction_rollback',
    'Number of transactions, which were rolled back',
    registry=registry)

# Freshmaker-specific metrics
freshmaker_artifact_build_done_counter = Counter(
    'freshmaker_artifact_build_done',
    'Number of successful artifact builds',
    registry=registry)
freshmaker_artifact_build_failed_counter = Counter(
    'freshmaker_artifact_build_failed',
    'Number of artifact builds, which failed due to error(s)',
    registry=registry)
freshmaker_artifact_build_canceled_counter = Counter(
    'freshmaker_artifact_build_canceled',
    'Number of artifact builds, which were canceled',
    registry=registry)

freshmaker_event_complete_counter = Counter(
    'freshmaker_event_complete',
    'Number of successfully handled events',
    registry=registry)
freshmaker_event_failed_counter = Counter(
    'freshmaker_event_failed',
    'Number of events, which failed due to error(s)',
    registry=registry)
freshmaker_event_skipped_counter = Counter(
    'freshmaker_event_skipped',
    'Number of events, for which no action was taken',
    registry=registry)

freshmaker_build_api_latency = Histogram(
    'build_api_latency',
    'BuildAPI latency', registry=registry)
freshmaker_event_api_latency = Histogram(
    'event_api_latency',
    'EventAPI latency', registry=registry)


@event.listens_for(db.engine, 'dbapi_error', named=True)
def receive_dbapi_error(**kw):
    db_dbapi_error_counter.inc()


@event.listens_for(db.engine, 'engine_connect')
def receive_engine_connect(conn, branch):
    db_engine_connect_counter.inc()


@event.listens_for(db.engine, 'handle_error')
def receive_handle_error(exception_context):
    db_handle_error_counter.inc()


@event.listens_for(db.engine, 'begin')
def receive_begin(conn):
    db_transaction_begin_counter.inc()


@event.listens_for(db.engine, 'commit')
def receive_commit(conn):
    db_transaction_commit_counter.inc()


@event.listens_for(db.engine, 'rollback')
def receive_rollback(conn):
    db_transaction_rollback_counter.inc()


class MonitorAPI(MethodView):
    rest_api_v1 = {
        'basic': {
            'url': '/api/1/monitor/metrics/',
            'options': {
                'methods': ['GET'],
            }
        }
    }

    def get(self):
        return Response(generate_latest(registry))
