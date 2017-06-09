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

from flask import request, jsonify
from flask.views import MethodView

from freshmaker import app
from freshmaker.api_utils import pagination_metadata, filter_artifact_builds
from freshmaker.models import ArtifactBuild

api_v1 = {
    'events': {
        'events_list': {
            'url': '/freshmaker/1/events/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
    },
    'builds': {
        'builds_list': {
            'url': '/freshmaker/1/builds/',
            'options': {
                'defaults': {'id': None},
                'methods': ['GET'],
            }
        },
        'build': {
            'url': '/freshmaker/1/builds/<int:id>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
}


class EventAPI(MethodView):

    def get(self, id):
        return "Done", 200


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
            build = ArtifactBuild.query.filter_by(id=id).first()
            if build:
                return jsonify(build.json()), 200
            else:
                raise ValueError('No such build found.')


API_V1_MAPPING = {
    'events': EventAPI,
    'builds': BuildAPI,
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
