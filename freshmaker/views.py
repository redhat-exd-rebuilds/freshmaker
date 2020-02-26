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

import json
from flask import request, jsonify
from flask.views import MethodView
from flask import g

from freshmaker import app
from freshmaker import messaging
from freshmaker import models
from freshmaker import types
from freshmaker import db
from freshmaker import conf
from freshmaker import version
from freshmaker import log
from freshmaker import events
from freshmaker.api_utils import filter_artifact_builds
from freshmaker.api_utils import filter_events
from freshmaker.api_utils import json_error
from freshmaker.api_utils import pagination_metadata
from freshmaker.auth import login_required, requires_roles, require_scopes, user_has_role
from freshmaker.parsers.internal.manual_rebuild import FreshmakerManualRebuildParser
from freshmaker.parsers.koji.async_manual_build import FreshmakerAsyncManualbuildParser
from freshmaker.monitor import (
    monitor_api, freshmaker_build_api_latency, freshmaker_event_api_latency)
from freshmaker.image_verifier import ImageVerifier
from freshmaker.types import ArtifactBuildState, EventState

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
                'methods': ['GET', 'PATCH'],
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
    'async_builds': {
        'async_build': {
            'url': '/api/1/async-builds/',
            'options': {
                'methods': ['POST'],
            }
        },
    },
    'about': {
        'about': {
            'url': '/api/1/about/',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'verify_image': {
        'verify_image': {
            'url': '/api/1/verify-image/<image>',
            'options': {
                'methods': ['GET'],
            }
        },
    },
    'verify_image_repository': {
        'verify_image_repository': {
            'url': '/api/1/verify-image-repository/<project>/<repo>',
            'options': {
                'methods': ['GET'],
            }
        },
    }
}


class EventTypeAPI(MethodView):
    def get(self, id):
        event_types = []
        for cls, val in models.EVENT_TYPES.items():
            event_types.append({'name': cls.__name__, 'id': val})

        if id is None:
            return jsonify({'items': event_types}), 200

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
            return jsonify({'items': build_types}), 200

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
            return jsonify({'items': build_states}), 200

        else:
            build_state = [x for x in build_states if x['id'] == id]

            if build_state:
                return jsonify(build_state.pop()), 200
            else:
                return json_error(404, "Not Found", "No such build state found.")


class EventAPI(MethodView):

    _freshmaker_manage_prefix = 'event'

    @freshmaker_event_api_latency.time()
    def get(self, id):
        """ Returns Freshmaker Events.

        If ``id`` is set, only the Freshmaker Event defined by that ID is
        returned.

        :query string message_id: Return only events with this :ref:`message_id<event_message_id>`.
        :query string search_key: Return only events with this :ref:`search_key<event_search_key>`.
        :query number event_type_id: Return only events with this :ref:`event_type_id<event_event_type_id>`.
        :query number/string state: Return only events int this :ref:`state<event_state>`.
        :query bool show_full_json: When ``True``, the returned Freshmaker Event JSON objects
            contains all the fields described in the
            :ref:`Freshmaker Event representation for API version 1<event_json_api_1>`.

            When ``False``, the returned Freshmaker Event JSON objects are in the
            :ref:`Freshmaker Event representation for API version 2<event_json_api_2>` format.

            Default value for API version 1 is ``True``, for API version 2 is ``False``.

        :query string order_by: Order the events by the given field. If ``-`` prefix is used,
            the order will be descending. The default value is ``-id``. Available fields are:

            - :ref:`id<event_id>`
            - :ref:`message_id<event_message_id>`

        :statuscode 200: Requested events are returned.
        :statuscode 404: Freshmaker event not found.
        """
        # Boolean that is set to false if builds should not
        # be displayed in order to increase api speed
        # For API v1, this is true by default to not break the backward compatibility
        # For API v2, this is false by default
        value = request.args.getlist('show_full_json')
        show_full_json = request.base_url.find("/api/1/") != -1
        if len(value) == 1 and value[0] == 'False':
            show_full_json = False
        elif len(value) == 1 and value[0] == 'True':
            show_full_json = True

        if id is None:
            p_query = filter_events(request)

            json_data = {
                'meta': pagination_metadata(p_query, request.args)
            }

            if not show_full_json:
                json_data['items'] = [item.json_min() for item in p_query.items]
            else:
                json_data['items'] = [item.json() for item in p_query.items]

            return jsonify(json_data), 200

        else:
            event = models.Event.query.filter_by(id=id).first()
            if event:
                if not show_full_json:
                    return jsonify(event.json_min()), 200
                return jsonify(event.json()), 200
            else:
                return json_error(404, "Not Found", "No such event found.")

    @login_required
    @requires_roles(['admin', 'manual_rebuilder'])
    def patch(self, id):
        """
        Manage Freshmaker event defined by ID. The request must be
        :mimetype:`application/json`.

        Returns the cancelled Freshmaker event as JSON.

        **Sample request**:

        .. sourcecode:: http

            PATCH /api/1/events HTTP/1.1
            Accept: application/json
            Content-Type: application/json

            {
                "action": "cancel"
            }

        :jsonparam string action: Action to do with an Event. Currently only "cancel"
            is supported.
        :statuscode 200: Cancelled event is returned.
        :statuscode 400: Action is missing or is unsupported.
        """
        data = request.get_json(force=True)
        if 'action' not in data:
            return json_error(
                400, "Bad Request", "Missing action in request."
                " Don't know what to do with the event.")

        if data["action"] != "cancel":
            return json_error(400, "Bad Request", "Unsupported action requested.")

        event = models.Event.query.filter_by(id=id).first()
        if not event:
            return json_error(400, "Not Found", "No such event found.")

        if event.requester != g.user.username and not user_has_role("admin"):
            return json_error(
                403, "Forbidden", "You must be an admin to cancel someone else's event.")

        msg = "Event id %s requested for canceling by user %s" % (event.id, g.user.username)
        log.info(msg)

        event.transition(EventState.CANCELED, msg)
        event.builds_transition(
            ArtifactBuildState.CANCELED.value,
            "Build canceled before running on external build system.",
            filters={'state': ArtifactBuildState.PLANNED.value})
        builds_id = event.builds_transition(
            ArtifactBuildState.CANCELED.value, None,
            filters={'state': ArtifactBuildState.BUILD.value})
        db.session.commit()

        data["action"] = self._freshmaker_manage_prefix + data["action"]
        data["event_id"] = event.id
        data["builds_id"] = builds_id
        messaging.publish("manage.eventcancel", data)
        # Return back the JSON representation of Event to client.
        return jsonify(event.json()), 200


def _validate_rebuild_request(request):
    """
    Perform basic data validation against the rebuild request

    :param request: Flask request object.
    :return: If validation fails, returns JSON serialized flask.Response with
        error code and messages, otherwise returns None.
    """
    data = request.get_json(force=True)

    for key in ('errata_id', 'freshmaker_event_id'):
        if data.get(key) and not isinstance(data[key], int):
            return json_error(400, 'Bad Request', f'"{key}" must be an integer.')

    if data.get('freshmaker_event_id'):
        event = models.Event.get_by_event_id(db.session, data.get('freshmaker_event_id'))
        if not event:
            return json_error(
                400, 'Bad Request', 'The provided "freshmaker_event_id" is invalid.',
            )

    for key in ('dist_git_branch', 'brew_target'):
        if data.get(key) and not isinstance(data[key], str):
            return json_error(400, 'Bad Request', f'"{key}" must be a string.')

    container_images = data.get('container_images', [])
    if (
        not isinstance(container_images, list) or
        any(not isinstance(image, str) for image in container_images)
    ):
        return json_error(
            400, 'Bad Request', '"container_images" must be an array of strings.',
        )

    if not isinstance(data.get('dry_run', False), bool):
        return json_error(400, 'Bad Request', '"dry_run" must be a boolean.')

    return None


def _create_rebuild_event_from_request(db_session, parser, request):
    """
    Create a rebuild event by parsing the request data

    :param db_session: SQLAlchemy database session object.
    :param parser: Freshmaker parser object.
    :param request: Flask request object.
    :return: Event object.
    """
    data = request.get_json(force=True)
    event = parser.parse_post_data(data)

    # Store the event into database, so it gets the ID which we can return
    # to client sending this POST request. The client can then use the ID
    # to check for the event status.
    db_event = models.Event.get_or_create_from_event(db_session, event)
    db_event.requester = g.user.username
    db_event.requested_rebuilds = " ".join(event.container_images)
    if hasattr(event, 'requester_metadata_json') and event.requester_metadata_json:
        db_event.requester_metadata = json.dumps(event.requester_metadata_json)
    if data.get('freshmaker_event_id'):
        dependent_event = models.Event.get_by_event_id(
            db_session, data.get('freshmaker_event_id'),
        )
        if dependent_event:
            dependency = db_event.add_event_dependency(db_session, dependent_event)
            if not dependency:
                log.warn('Dependency between {} and {} could not be added!'.format(
                    event.freshmaker_event_id, dependent_event.id))
    db_session.commit()
    return db_event


class BuildAPI(MethodView):
    @freshmaker_build_api_latency.time()
    def get(self, id):
        if id is None:
            p_query = filter_artifact_builds(request)

            json_data = {
                'meta': pagination_metadata(p_query, request.args)
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
    @requires_roles(['admin', 'manual_rebuilder'])
    def post(self):
        """
        Trigger manual Freshmaker rebuild. The request must be
        :mimetype:`application/json`.

        Returns the newly created Freshmaker event as JSON.

        **Sample request**:

        .. sourcecode:: http

            POST /api/1/builds HTTP/1.1
            Accept: application/json
            Content-Type: application/json

            {
                "errata_id": 12345
            }


        :jsonparam string errata_id: The ID of Errata advisory to rebuild
            artifacts for. If this is not set, freshmaker_event_id must be set.
        :jsonparam list container_images: When set, defines list of NVRs
            of leaf container images which should be rebuild in the
            newly created Event.
        :jsonparam bool dry_run: When True, the Event will be handled in
            the DRY_RUN mode.
        :jsonparam bool freshmaker_event_id: When set, it defines the event
            which will be used as the dependant event. Successfull builds from
            this event will be reused in the newly created event instead of
            building all the artifacts from scratch. If errata_id is not
            provided, it will be inherited from this Freshmaker event.
        :statuscode 200: A new event was created.
        :statuscode 400: The provided input is invalid.
        """
        error = _validate_rebuild_request(request)
        if error is not None:
            return error

        data = request.get_json(force=True)
        if not data.get('errata_id') and not data.get('freshmaker_event_id'):
            return json_error(
                400,
                'Bad Request',
                'You must at least provide "errata_id" or "freshmaker_event_id" in the request.',
            )

        dependent_event = None
        if data.get('freshmaker_event_id'):
            dependent_event = models.Event.get_by_event_id(
                db.session, data.get('freshmaker_event_id'),
            )
            # requesting a CVE rebuild, the event can not be an async build event which
            # is for non-CVE only
            async_build_event_type = models.EVENT_TYPES[events.FreshmakerAsyncManualBuildEvent]
            if dependent_event.event_type_id == async_build_event_type:
                return json_error(
                    400, 'Bad Request', 'The event (id={}) is an async build event, '
                    'can not be used for this build.'.format(data.get('freshmaker_event_id')),
                )
            if not data.get('errata_id'):
                data['errata_id'] = int(dependent_event.search_key)
            elif int(dependent_event.search_key) != data['errata_id']:
                return json_error(
                    400,
                    'Bad Request',
                    'The provided "errata_id" doesn\'t match the Advisory ID associated with the '
                    'input "freshmaker_event_id".',
                )

        # Use the shared code to parse the POST data and generate right
        # event based on the data. Currently it generates just
        # ManualRebuildWithAdvisoryEvent.
        parser = FreshmakerManualRebuildParser()
        db_event = _create_rebuild_event_from_request(db.session, parser, request)

        # Forward the POST data (including the msg_id of the database event we
        # added to DB) to backend using UMB messaging. Backend will then
        # re-generate the event and start handling it.
        data["msg_id"] = db_event.message_id

        # add information about requester
        data["requester"] = db_event.requester

        messaging.publish("manual.rebuild", data)

        # Return back the JSON representation of Event to client.
        return jsonify(db_event.json()), 200


class AsyncBuildAPI(MethodView):
    @login_required
    @require_scopes('submit-build')
    @requires_roles(['admin', 'freshmaker_async_rebuilders'])
    def post(self):
        """
        Trigger Freshmaker async rebuild (a.k.a non-CVE rebuild). The request
        must be :mimetype:`application/json`.

        Returns the newly created Freshmaker event as JSON.

        **Sample request**:

        .. sourcecode:: http

            POST /api/1/async-builds HTTP/1.1
            Accept: application/json
            Content-Type: application/json

            {
                "dist_git_branch": "master",
                "container_images": ["foo-1-1"]
            }

        :jsonparam string dist_git_branch: The name of the branch in dist-git
            to build the container images from. This is a mandatory field.
        :jsonparam list container_images: A list of images to rebuild. They
            might be sharing a parent-child relationship which are then rebuilt
            by Freshmaker in the right order. For example, if images A is parent
            image of B, which is parent image of C, and container_images is
            [A, B, C], Freshmaker will make sure to rebuild all three images,
            in the correct order. It is however possible also to rebuild images
            completely unrelated to each other. This is a mandatory field.
        :jsonparam bool dry_run: When True, the Event will be handled in
            the DRY_RUN mode.
        :jsonparam bool freshmaker_event_id: When set, it defines the event
            which will be used as the dependant event. Successfull builds from
            this event will be reused in the newly created event instead of
            building all the artifacts from scratch. The event should refer
            to an async rebuild event.
        :jsonparam string brew_target: The name of the Brew target. While
            requesting an async rebuild, it should be the same for all the images
            in the list of container_images. This parameter is optional, with
            default value will be pulled from the previous buildContainer task.
        :statuscode 200: A new event was created.
        :statuscode 400: The provided input is invalid.
        """
        error = _validate_rebuild_request(request)
        if error is not None:
            return error

        data = request.get_json(force=True)
        if not all([data.get('dist_git_branch'), data.get('container_images')]):
            return json_error(
                400,
                'Bad Request',
                '"dist_git_branch" and "container_images" are required in the request '
                'for async builds',
            )

        dependent_event = None
        if data.get('freshmaker_event_id'):
            dependent_event = models.Event.get_by_event_id(
                db.session, data.get('freshmaker_event_id'),
            )
            async_build_event_type = models.EVENT_TYPES[events.FreshmakerAsyncManualBuildEvent]
            if dependent_event.event_type_id != async_build_event_type:
                return json_error(
                    400, 'Bad Request', 'The event (id={}) is not an async build '
                    'event.'.format(data.get('freshmaker_event_id')),
                )

        # The '-container' string is optional, the user might have omitted it. But we need it to be
        # there for our query. Let's check if it's there, and if it's not, let's add it.
        for i, image in enumerate(data.get('container_images', [])):
            if not image.endswith('-container'):
                data.get('container_images')[i] = f"{image}-container"

        # parse the POST data and generate FreshmakerAsyncManualBuildEvent
        parser = FreshmakerAsyncManualbuildParser()
        db_event = _create_rebuild_event_from_request(db.session, parser, request)

        # Forward the POST data (including the msg_id of the database event we
        # added to DB) to backend using UMB messaging. Backend will then
        # re-generate the event and start handling it.
        data["msg_id"] = db_event.message_id

        # add information about requester
        data["requester"] = db_event.requester

        messaging.publish("async.manual.build", data)

        # Return back the JSON representation of Event to client.
        return jsonify(db_event.json()), 200


class AboutAPI(MethodView):
    def get(self):
        json = {'version': version}
        config_items = ['auth_backend']
        for item in config_items:
            config_item = getattr(conf, item)
            # All config items have a default, so if doesn't exist it is an error
            if not config_item:
                raise ValueError(
                    'An invalid config item of "{0}" was specified'.format(item))
            json[item] = config_item
        return jsonify(json), 200


class VerifyImageAPI(MethodView):
    def get(self, image):
        """
        Verifies whether the container image defined by the NVR is handled
        by Freshmaker. If not, returns explanation why.

        **Sample request**:

        .. sourcecode:: http

            GET /api/1/verify-image/foo-1-1 HTTP/1.1
            Accept: application/json

        **Sample response**:

        .. sourcecode:: none

            {
                "images": {
                    "foo-1-1": [
                        "content-set-1",
                        "content-set-2"
                    ]
                },
                "msg": "Found 1 images which are handled by Freshmaker."
            }

        :statuscode 200: Image is handled by Freshmaker.
        :statuscode 400: Image is not handled by Freshmaker or not found.
        """
        if not image:
            raise ValueError("No image name provided")

        verifier = ImageVerifier()
        images = verifier.verify_image(image)
        ret = {
            "msg": "Found %d images which are handled by Freshmaker for "
                   "defined content_sets." % len(images),
            "images": images
        }
        return jsonify(ret), 200


class VerifyImageRepositoryAPI(MethodView):
    def get(self, project, repo):
        """
        Verifies whether the container image repository is handled
        by Freshmaker. If not, returns explanation why.

        **Sample request**:

        .. sourcecode:: http

            GET /api/1/verify-image-repository/foo/bar HTTP/1.1
            Accept: application/json

        **Sample response**:

        .. sourcecode:: none

            {
                "images": {
                    "foo-1-1": [
                        "content-set-1",
                        "content-set-2"
                    ]
                },
                "msg": "Found 1 images which are handled by Freshmaker."
            }

        :statuscode 200: Image repository is handled by Freshmaker.
        :statuscode 400: Image repository is not handled by Freshmaker or not
            found.
        """
        if not project and not repo:
            raise ValueError("No image repository name provided")

        verifier = ImageVerifier()
        images = verifier.verify_repository("%s/%s" % (project, repo))
        ret = {
            "msg": "Found %d images which are handled by Freshmaker for "
                   "defined content_sets." % len(images),
            "images": images,
        }
        return jsonify(ret), 200


API_V1_MAPPING = {
    'events': EventAPI,
    'builds': BuildAPI,
    'async_builds': AsyncBuildAPI,
    'event_types': EventTypeAPI,
    'build_types': BuildTypeAPI,
    'build_states': BuildStateAPI,
    'about': AboutAPI,
    'verify_image': VerifyImageAPI,
    'verify_image_repository': VerifyImageRepositoryAPI,
}


def register_api_v1():
    """ Registers version 1 of Freshmaker API. """
    for k, v in API_V1_MAPPING.items():
        view = v.as_view(k)
        for key, val in api_v1.get(k, {}).items():
            app.add_url_rule(val['url'],
                             endpoint=key,
                             view_func=view,
                             **val['options'])

    app.register_blueprint(monitor_api)


def register_api_v2():
    """ Registers version 2 of Freshmaker API. """

    # The API v2 has the same URL schema as v1, only semantic is different.
    for k, v in API_V1_MAPPING.items():
        view = v.as_view(k + "_v2")
        for key, val in api_v1.get(k, {}).items():
            app.add_url_rule(val['url'].replace("/api/1/", "/api/2/"),
                             endpoint=key + "_v2",
                             view_func=view,
                             **val['options'])

    app.register_blueprint(monitor_api)


register_api_v1()
register_api_v2()
