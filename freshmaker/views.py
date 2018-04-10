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

import six
from flask import request, jsonify
from flask.views import MethodView

from freshmaker import app
from freshmaker import messaging
from freshmaker import models
from freshmaker import types
from freshmaker.api_utils import filter_artifact_builds
from freshmaker.api_utils import filter_events
from freshmaker.api_utils import json_error
from freshmaker.api_utils import pagination_metadata
from freshmaker.auth import login_required, requires_role, require_scopes
from freshmaker.errata import Errata, ErrataAdvisory

api_v1 = {
    'event_types': {
        'event_types_list': {
            'url': '/api/1/event-types/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'event_type': {
            'url': '/api/1/event-types/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'build_types': {
        'build_types_list': {
            'url': '/api/1/build-types/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'build_type': {
            'url': '/api/1/build-types/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'build_states': {
        'build_states_list': {
            'url': '/api/1/build-states/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'build_state': {
            'url': '/api/1/build-states/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'events': {
        'events_list': {
            'url': '/api/1/events/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'event': {
            'url': '/api/1/events/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'builds': {
        'builds_list': {
            'url': '/api/1/builds/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'build': {
            'url': '/api/1/builds/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
        'manual_trigger': {
            'url': '/api/1/builds/',
            'options': {
                'methods': ['POST'],
            }
        },
    },
}


class EventTypeAPI(MethodView):
    def get(self, id):
        event_types = []
        for cls, val in six.iteritems(models.EVENT_TYPES):
            event_types.append({'name': cls.__name__, 'id': val})

        if id is None:
            json_data = {}
            json_data['items'] = event_types

            return jsonify(json_data), 200

        else:
            event_type = [x for x in event_types if x['id'] == id]

            if event_type:
                return jsonify(event_type.pop()), 200
            else:
                return json_error(404, "Not Found", "No such event type found.")


class BuildTypeAPI(MethodView):
    def get(self, id):
        build_types = []
        for x in list(types.ArtifactType):
            build_types.append({'name': x.name, 'id': x.value})

        if id is None:
            json_data = {}
            json_data['items'] = build_types

            return jsonify(json_data), 200

        else:
            build_type = [x for x in build_types if x['id'] == id]

            if build_type:
                return jsonify(build_type.pop()), 200
            else:
                return json_error(404, "Not Found", "No such build type found.")


class BuildStateAPI(MethodView):
    def get(self, id):
        build_states = []
        for x in list(types.ArtifactBuildState):
            build_states.append({'name': x.name, 'id': x.value})

        if id is None:
            json_data = {}
            json_data['items'] = build_states

            return jsonify(json_data), 200

        else:
            build_state = [x for x in build_states if x['id'] == id]

            if build_state:
                return jsonify(build_state.pop()), 200
            else:
                return json_error(404, "Not Found", "No such build state found.")


class EventAPI(MethodView):
    def get(self, id):
        if id is None:
            p_query = filter_events(request)

            json_data = {
                'meta': pagination_metadata(p_query)
            }
            json_data['items'] = [item.json() for item in p_query.items]

            return jsonify(json_data), 200

        else:
            event = models.Event.query.filter_by(id=id).first()
            if event:
                return jsonify(event.json()), 200
            else:
                return json_error(404, "Not Found", "No such event found.")


class BuildAPI(MethodView):
    def get(self, id):
        if id is None:
            p_query = filter_artifact_builds(request)

            json_data = {
                'meta': pagination_metadata(p_query)
            }
            json_data['items'] = [item.json() for item in p_query.items]

            return jsonify(json_data), 200

        else:
            build = models.ArtifactBuild.query.filter_by(id=id).first()
            if build:
                return jsonify(build.json()), 200
            else:
                return json_error(404, "Not Found", "No such build found.")

    @login_required
    @require_scopes('submit-build')
    @requires_role('admins')
    def post(self):
        """Trigger image rebuild"""
        data = request.get_json(force=True)
        if 'errata_id' not in data:
            return json_error(
                400, 'Bad Request', 'Missing errata_id in request')

        errata = Errata()
        advisory = ErrataAdvisory.from_advisory_id(errata, data['errata_id'])
        if 'rpm' not in advisory.content_types:
            return json_error(
                400,
                'Bad Request',
                'Erratum {} is not a RPM advisory'.format(data['errata_id']))

        messaging.publish("manual.rebuild", data)
        return jsonify(data), 200


API_V1_MAPPING = {
    'events': EventAPI,
    'builds': BuildAPI,
    'event_types': EventTypeAPI,
    'build_types': BuildTypeAPI,
    'build_states': BuildStateAPI,
}


def register_api_v1():
    """ Registers version 1 of MBS API. """
    for k, v in API_V1_MAPPING.items():
        view = v.as_view(k)
        for key, val in api_v1.get(k, {}).items():
            app.add_url_rule(val['url'],
                             endpoint=key,
                             view_func=view,
                             **val['options'])


register_api_v1()
