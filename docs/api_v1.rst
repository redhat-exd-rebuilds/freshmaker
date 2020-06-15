========================
API version 1
========================

.. _event_json_api_1:

Event JSON representation
====================================

The Freshmaker Event is always represented in the API request as JSON, for example:

.. sourcecode:: none

    {
        "builds": [],
        "depending_events": [],
        "depends_on_events": [],
        "dry_run": false,
        "event_type_id": 10,
        "id": 18730,
        "message_id": "message_123",
        "requested_rebuilds": [],
        "requester": null,
        "requester_metadata": {},
        "search_key": "44637",
        "state": 3,
        "state_name": "COMPLETE",
        "state_reason": "4 images rebuilt.",
        "time_created": "2019-08-01T07:00:46Z",
        "time_done": "2019-08-01T07:03:12Z",
        "url": "/api/1/events/18730"
    }

The fields used in the Freshmaker Event JSON have following meaning:

.. _event_builds:

*builds* - ``(list of Freshmaker Artifact build JSONs)``
    List of artifact builds which are part of this Freshmaker event.

.. _event_depending_events:

*depending_events* - ``(list of numbers)``
    List of IDs of other Freshmaker events which are depending on this Freshmaker event.

.. _event_depends_on_events:

*depends_on_events* - ``(list of numbers)``
    List of IDs of other Freshmaker events which this event depends on.

.. _event_dry_run:

*dry_run* - ``(boolean)``
    When set to ``true`` the event is handled in dry run mode. In this mode, no real builds are submitted to build system. Instead, all the builds are automatically moved to ``COMPLETE`` state.

.. _event_event_type_id:

*event_type_id* - ``(number)``
    The ID of the type of this Event. Full list of Event types can listed using the ``/api/1/event-types/`` REST API. The most important event types are:

    - 10 (``ErrataAdvisoryStateChangedEvent``) - Event triggered by message, rebuilding all artifacts (currently just container images) as result of advisory release.
    - 13 (``ManualRebuildWithAdvisoryEvent``) - Event triggered manually, rebuilding all artifacts (currently just container images) as result of advisory release.

.. _event_id:

*id* - ``(number)``
    The ID of Freshmaker event.

.. _event_message_id:

*message_id* - ``(string)``
    The ID of message (fedmsg or AMQP) which triggered the Event.

.. _event_requested_rebuilds:

*requested_rebuilds* - ``(list of strings)``
    List of artifacts which should be rebuilt in this Freshmaker Event. Filled in only for manual rebuilds which requested particular artifacts to be rebuilt. Currently, it is always list of container images NVRs.

.. _event_requester:

*requester* - ``(string or null)``
    The Kerberos username of requester of this Freshmaker Event. Set to string only for manual rebuilds, otherwise ``null``.

.. _event_requester_metadata:

*requester_metadata* - ``(JSON object)``
    Additional metadata set by requester when submitting the manual rebuild. It can be used to track the context of manual rebuild.

.. _event_search_key:
    
*search_key* - ``(string)``
    The key identifying source of the Event. For each Event type, there is a different way how the key is generated:

    - Event type 10 (``ErrataAdvisoryStateChangedEvent``) - The ID of advisory which triggered the Event.
    - Event type 13 (``ManualRebuildWithAdvisoryEvent``) - The ID of advisory which triggered the Event.

.. _event_state:

*state* - ``(number)``
    Number defining the state the Event is currently in:

    - 0 (``INITIALIZED``) - Event is initialized and Freshmaker is now searching for artifacts to build.
    - 1 (``BUILDING``) - Some artifacts to build have been found and Freshmaker is building them.
    - 2 (``COMPLETE``) - All artifacts have been build. Note that this does not mean all the builds were successfull - just one successfull artifact build is enough to mark the Event as ``COMPLETE``.
    - 3 (``FAILED``) - There was some major error while handling the Event or all the artifact builds failed to build.
    - 4 (``SKIPPED``) - No artifacts have been found to build or the Event is not allowed by the Freshmaker's configuration.
    - 5 (``CANCELED``) - Event has been manually cancelled using the REST API.

.. _event_state_name:

*state_name* - ``(string)``
    Name of the state the Event is currently in. See ``state`` for more info.

.. _event_state_reason:

*state_reason* - ``(string)``
    Sentence describing the current state.

.. _event_time_created:

*time_created* - ``(datetime)``
    The date and time on which the Event has been initialized (moved to ``INITIALIZED`` state).

.. _event_time_done:

*time_done* - ``(datetime)``
    The date and time on which the Event has been moved to ``FAILED``, ``COMPLETE``, or ``CANCELED`` state.


.. _build_json_api_1:

Artifact Build JSON representation
==================================

The Freshmaker Artifact Build is always represented in the API request as JSON, for example:

.. sourcecode:: none

    {
        "build_args": {
            ...
        },
        "build_id": 22429387,
        "dep_on": "fedora-30-container",
        "dep_on_id": 21657,
        "event_id": 16730,
        "id": 21837,
        "name": "httpd-container",
        "odcs_composes": [],
        "original_nvr": "httpd-container-2.4-1",
        "rebuild_reason": "directly_affected",
        "rebuilt_nvr": "httpd-container-2.4-1.1561731291",
        "state": 1,
        "state_name": "DONE",
        "state_reason": "Built successfully.",
        "time_completed": "2019-06-29T03:28:56Z",
        "time_submitted": "2019-06-28T14:14:51Z",
        "type": 1,
        "type_name": "IMAGE",
        "url": "/api/1/builds/21837"
    }

.. _build_build_args:

*build_args* - ``(JSON object)``
    JSON object containing arguments passed to build system to build this artifact.
    
    .. WARNING::
        The content of this JSON object is not part of the Freshmaker REST API and can change at any time.

    Commonly used ``build_args`` are:

    - ``arches`` - white-space separated list of architecture the Artifact is built against.
    - ``branch`` - name of the branch from which the Artifact's source code is taken.
    - ``commit`` - commit hash in source repository from which the Artifact's source code is taken.
    - ``target`` - Koji target in which the Artifact is built.
    - ``retry_count`` - number describes how many times was Artifact build retried.

.. _build_build_id:

*build_id* - ``(number)``
    The ID of Artifact Build.

.. _build_dep_on:

*dep_on* - ``(string)``
    The :ref:`name<build_name>`. of the Artifact build this Artifact build depends on.

.. _build_dep_on_id:

*dep_on_id* - ``(number)``
    The ID of the Artifact build this Artifact build depends on.

.. _build_event_id:

*event_id* - ``(number)``
    The ID of the Event this Artifact Build is part of.

.. _build_name:

*name* - ``(string)``
    The name of this Artifact Build.

.. _build_odcs_composes:

*odcs_composes* - ``(list of numbers)``
    List of ODCS composes the Freshmaker directly generated and used while building this Artifact build in the build system.

.. _build_original_nvr:

*original_nvr* - ``(string)``
    The original (before the rebuild) NVR of Artifact build.

.. _build_rebuild_reason:

*rebuild_reason* - ``(string)``
    The reason why this artifact is included in the Event. Can be one of:

    - ``directly_affected`` - The Artifact build is directly affected by the Event (for example affected by the CVE) and is whitelisted by Freshmaker's configuration.
    - ``dependency`` - The Artifact build is included in the Event just because it is dependency of ``directly_affected`` Artifact build.

.. _build_rebuilt_nvr:

*rebuilt_nvr* - ``(string)``
    The NVR of Artifact build built by Freshmaker.

.. _build_state:

*state* - ``(number)``
    Number defining the state the Artifact build is currently in:

    - 0 (``BUILD``) - Artifact build is currently being built in build system.
    - 1 (``DONE``) - Artifact build has been built successfully.
    - 2 (``FAILED``) - Artifact build failed to be build.
    - 3 (``CANCELED``) - Artifact build has been cancelled manually.
    - 4 (``PLANNED``) - Artifact build is planned to be build.

.. _build_state_name:

*state_name* - ``(string)``
    Name of the state the Artifact build is currently in. See :ref:`state<build_state>` for more info.

.. _build_state_reason:

*state_reason* - ``(string)``
    Sentence describing the current state.

.. _build_time_completed:

*time_completed* - ``(datetime)``
    The date and time on which the Artifact Build has been completed.

.. _build_time_submitted:

*time_submitted* - ``(datetime)``
    The date and time on which the Artifact build has been moved to ``PLANNED`` state.

.. _build_type:

*type* - ``(number)``
    Type of the Artifact build:

    - 0 (``RPM``) - Artifact build is an RPM package.
    - 1 (``IMAGE``) - Artifact build is a container image.
    - 2 (``MODULE``) - Artifact build is a module.
    - 3 (``IMAGE_REPOSITORY``) - Artifact build is a container image repository.

.. _build_type_name:

*type__name* - ``(string)``
    Name of the type of Artifact build. See :ref:`type<build_type>` for more info.
    

.. _pagination_api_1:

REST API pagination
===================

When multiple objects are returned by the Freshmaker REST API, they are wrapped in the following JSON which allows pagination:

.. sourcecode:: none

    {
        "items": [
            {JSON_OBJECT},
            ...
        ],
        "meta": {
            "first": "http://freshmaker.localhost/api/1/events/?per_page=10&page=1",
            "last": "http://freshmaker.localhost/api/1/events/?per_page=10&page=14890",
            "next": "http://freshmaker.localhost/api/1/events/?per_page=10&page=2",
            "page": 1,
            "pages": 14890,
            "per_page": 10,
            "prev": null,
            "total": 148898
        }
    }

The ``items`` list contains the objects JSONs. The ``meta`` dict contains metadata about pagination. It is possible to use ``per_page`` argument to set the number of objects showed per single page and ``page`` to choose the page to show.


HTTP REST API
=============

.. automodule:: freshmaker

.. autoflask:: freshmaker:app
    :undoc-static:
    :endpoints: event_types_list, event_type, build_types_list, build_type, build_states_list, build_state, events_list, event, builds_list, build, manual_trigger, about, verify_image, verify_image_repository, async_build
    :modules: freshmaker.views
    :order: path
