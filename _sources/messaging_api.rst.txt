========================
Messaging API
========================

Freshmaker also sends AMQP or Fedmsg messages when events or builds change its state.

``event.state.changed``
=======================

This message is sent on every :ref:`Freshmaker Event<event_json_api_1>`'s :ref:`state<event_state>` change. The message contains :ref:`Event JSON representation as defined in API version 1<event_json_api_1>`.

``event.state.changed.min``
===========================

This message is sent on every :ref:`Freshmaker Event<event_json_api_2>`'s :ref:`state<event_state>` change. The message contains :ref:`Event JSON representation as defined in API version 2<event_json_api_2>`.

``build.state.changed``
=======================

This message is sent on every :ref:`Artifact Build<build_json_api_1>`'s :ref:`state<build_state>` change. The message contains :ref:`Artifact Build<build_json_api_1>`.
