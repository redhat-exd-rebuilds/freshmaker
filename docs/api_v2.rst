========================
API version 2
========================

The Freshmaker API version 2 is mostly same as the API version 1. This document therefore describes only the differences between these two API versions.

.. _event_json_api_2:

Event JSON representation
====================================

The Freshmaker Event is always represented in the API request as JSON, for example:

.. sourcecode:: none

    {
        "builds_summary": {
            "total": 0
        },
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

The meaning of almost all the fields is the same as in :ref:`event_json_api_1` using the API version 1.

There are following differences between API version 1 and API version 2:

- The ``builds`` field is replaced with ``builds_summary``.

.. _event_builds_summary:

*builds_summary* - ``(JSON)``
    JSON object showing the summary of artifacts builds included in the Event grouped by their ``state_name``. For example:

    .. sourcecode:: none

        "builds_summary": {
            "total": 10,
            "DONE": 7,
            "FAILED": 3
        }


.. _build_json_api_2:

Artifact Build JSON representation
==================================

The JSON representation of Artifact Build is exactly the same as in :ref:`build_json_api_1` using the API version 1.


.. _pagination_api_2:

REST API pagination
===================

The pagination works exactly the same way as in :ref:`pagination_api_1` using the API version 1.


HTTP REST API
=============

.. automodule:: freshmaker

.. autoflask:: freshmaker:app
    :undoc-static:
    :endpoints: event_types_list_v2, event_type_v2, build_types_list_v2, build_type_v2, build_states_list_v2, build_state_v2, events_list_v2, event_v2, builds_list_v2, build_v2, manual_trigger_v2, about_v2, verify_image_v2, verify_image_repository_v2, async_build_v2
    :modules: freshmaker.views
    :order: path
