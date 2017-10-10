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

from flask import request, url_for, jsonify

from freshmaker import db
from freshmaker.types import ArtifactType, ArtifactBuildState
from freshmaker.models import ArtifactBuild, Event


def pagination_metadata(p_query):
    """
    Returns a dictionary containing metadata about the paginated query. This must be run as part of a Flask request.
    :param p_query: flask_sqlalchemy.Pagination object
    :return: a dictionary containing metadata about the paginated query
    """

    pagination_data = {
        'page': p_query.page,
        'per_page': p_query.per_page,
        'total': p_query.total,
        'pages': p_query.pages,
        'first': url_for(request.endpoint, page=1, per_page=p_query.per_page, _external=True),
        'last': url_for(request.endpoint, page=p_query.pages, per_page=p_query.per_page, _external=True)
    }

    if p_query.has_prev:
        pagination_data['prev'] = url_for(request.endpoint, page=p_query.prev_num,
                                          per_page=p_query.per_page, _external=True)
    if p_query.has_next:
        pagination_data['next'] = url_for(request.endpoint, page=p_query.next_num,
                                          per_page=p_query.per_page, _external=True)

    return pagination_data


def filter_artifact_builds(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()

    artifact_type = flask_request.args.get('type', None)
    if artifact_type:
        if artifact_type.isdigit():
            if int(artifact_type) in [t.value for t in list(ArtifactType)]:
                search_query['type'] = artifact_type
            else:
                raise ValueError('An invalid artifact type was supplied')
        else:
            if str(artifact_type).upper() in [t.name for t in list(ArtifactType)]:
                search_query['type'] = ArtifactType[artifact_type.upper()].value
            else:
                raise ValueError('An invalid artifact type was supplied')

    state = flask_request.args.get('state', None)
    if state:
        if state.isdigit():
            if int(state) in [s.value for s in list(ArtifactBuildState)]:
                search_query['state'] = state
            else:
                raise ValueError('An invalid state was supplied')
        else:
            if str(state).upper() in [s.name for s in list(ArtifactBuildState)]:
                search_query['state'] = ArtifactBuildState[state.upper()].value
            else:
                raise ValueError('An invalid state was supplied')

    for key in ['name', 'event_id', 'dep_on_id', 'build_id', 'original_nvr',
                'rebuilt_nvr']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = ArtifactBuild.query

    if search_query:
        query = query.filter_by(**search_query)

    event_type_id = flask_request.args.get('event_type_id', None)
    if event_type_id:
        query = query.join(Event).filter(Event.event_type_id == event_type_id)

    event_search_key = flask_request.args.get('event_search_key', None)
    if event_search_key:
        # use alias to avoid 'ambiguous column name' error when we have both
        # event_type_id and event_search_key specified.
        ea = db.aliased(Event)
        query = query.join(ea).filter(ea.search_key == event_search_key)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)


def filter_events(flask_request):
    """
    Returns a flask_sqlalchemy.Pagination object based on the request parameters
    :param request: Flask request object
    :return: flask_sqlalchemy.Pagination
    """
    search_query = dict()

    for key in ['message_id', 'search_key', 'event_type_id']:
        if flask_request.args.get(key, None):
            search_query[key] = flask_request.args[key]

    query = Event.query

    if search_query:
        query = query.filter_by(**search_query)

    page = flask_request.args.get('page', 1, type=int)
    per_page = flask_request.args.get('per_page', 10, type=int)
    return query.paginate(page, per_page, False)


def json_error(status, error, message):
    response = jsonify({'status': status,
                        'error': error,
                        'message': message})
    response.status_code = status
    return response
