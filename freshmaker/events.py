# -*- coding: utf-8 -*-
# Copyright (c) 2016  Red Hat, Inc.
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

import itertools
from typing import Any  # noqa

from freshmaker import conf
from freshmaker.types import ArtifactType

from inspect import signature


class BaseEvent(object):

    _parsers = {}  # type: dict[Any, Any]

    def __init__(self, msg_id, manual=False, dry_run=False):
        """
        A base class to abstract events from different fedmsg messages.
        :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
        :param manual: True if the event was triggered manually by Freshmaker
            REST API.
        :param dry_run: True if the event should be handled in DRY_RUN mode.
        """
        self.msg_id = msg_id
        self.manual = manual
        self.dry_run = dry_run

        # Moksha calls `consumer.validate` on messages that it receives, and
        # even though we have validation turned off in the config there's still
        # a step that tries to access `msg['body']`, `msg['topic']` and
        # `msg.get('topic')`.
        # These are here just so that the `validate` method won't raise an
        # exception when we push our fake messages through.
        # Note that, our fake message pushing has worked for a while... but the
        # *latest* version of fedmsg has some code that exercises the bug.  I
        # didn't hit this until I went to test in jenkins.
        self.body = {}
        self.topic = None

    @classmethod
    def register_parser(cls, parser_class):
        """
        Registers a parser for BaseEvent which is used to parse
        fedmsg in `from_fedmsg(...)` method.
        """
        BaseEvent._parsers[parser_class.name] = parser_class()

    @classmethod
    def get_parsed_topics(cls):
        """
        Returns the list of topics this class is parsing using the
        registered parsers.
        """
        topic_suffixes = []
        for parser in BaseEvent._parsers.values():
            topic_suffixes.extend(parser.topic_suffixes)
        return ['{}.{}'.format(pref.rstrip('.'), cat)
                for pref, cat
                in itertools.product(
                    conf.messaging_topic_prefix,
                    topic_suffixes)]

    def __repr__(self):
        init_sig = signature(self.__init__)

        args_strs = (
            "{}={!r}".format(name, getattr(self, name))
            if param.default != param.empty
            else repr(getattr(self, name, {}))
            for name, param in init_sig.parameters.items())

        return "{}({})".format(type(self).__name__, ', '.join(args_strs))

    def __getitem__(self, key):
        """ Used to trick moksha into thinking we are a dict. """
        return getattr(self, key)

    def __setitem__(self, key, value):
        """ Used to trick moksha into thinking we are a dict. """
        return setattr(self, key, value)

    def get(self, key, value=None):
        """ Used to trick moksha into thinking we are a dict. """
        return getattr(self, key, value)

    def __json__(self):
        return dict(msg_id=self.msg_id, topic=self.topic, body=self.body)

    @staticmethod
    def from_fedmsg(topic, msg):
        """
        Takes a fedmsg topic and message and converts it to a BaseEvent
        object.
        :param topic: the topic of the fedmsg message
        :param msg: the message contents from the fedmsg message
        :return: an object of BaseEvent descent if the message is a type
        that the app looks for, otherwise None is returned
        """
        for parser in BaseEvent._parsers.values():
            if not parser.can_parse(topic, msg):
                continue

            return parser.parse(topic, msg)

        return None

    @property
    def search_key(self):
        """
        Returns the searchable key which is used to query for particular
        events using the JSON API.
        """
        return self.msg_id

    def is_allowed(self, handler, artifact_type, **kwargs):
        """
        Returns True if allowlist/blocklist allows handling this event.
        Calls `handler.allow_build()` to find the answer.

        :param BaseHandler handler: Handler currently handling the event.
        :param ArtifactType artifact_type: Type of artifact to build as part
            of event.
        :param args: Extra args to be passed to `handler.allow_build()`.
        :param kwargs: Extra kwargs to be passed to `handler.allow_build()`.
        """
        return handler.allow_build(
            artifact_type, dry_run=self.dry_run,
            manual=self.manual, **kwargs)


class MBSModuleStateChangeEvent(BaseEvent):
    """ A class that inherits from BaseEvent to provide an event
    object for a module event generated by module-build-service
    :param msg_id: the id of the msg (e.g. 2016-SomeGUID)
    :param module_build_id: the id of the module build
    :param module_build_state: the state of the module build
    """
    def __init__(self, msg_id, module, stream, build_id, build_state, **kwargs):
        super(MBSModuleStateChangeEvent, self).__init__(msg_id, **kwargs)
        self.module = module
        self.stream = stream
        self.build_id = build_id
        self.build_state = build_state

    @property
    def search_key(self):
        return str(self.build_id)


class GitModuleMetadataChangeEvent(BaseEvent):
    """
    Provides an event object for "Module metadata in dist-git updated".
    :param scm_url: SCM URL of a updated module.
    :param branch: Branch of updated module.
    """
    def __init__(self, msg_id, module, branch, rev, **kwargs):
        super(GitModuleMetadataChangeEvent, self).__init__(msg_id, **kwargs)
        self.module = module
        self.branch = branch
        self.rev = rev

    @property
    def search_key(self):
        return "%s/%s?#%s" % (self.module, self.branch, self.rev)


class GitRPMSpecChangeEvent(BaseEvent):
    """
    Provides an event object for "RPM spec file in dist-git updated".

    :param rpm: RPM name, also known as the name of component or source package.
    :param branch: Branch of updated RPM spec.
    :param rev: revision.
    """
    def __init__(self, msg_id, rpm, branch, rev, **kwargs):
        super(GitRPMSpecChangeEvent, self).__init__(msg_id, **kwargs)
        self.rpm = rpm
        self.branch = branch
        self.rev = rev

    @property
    def search_key(self):
        return "%s/%s?#%s" % (self.rpm, self.branch, self.rev)


class TestingEvent(BaseEvent):
    """
    Event used in unit-tests.
    """
    def __init__(self, msg_id, **kwargs):
        super(TestingEvent, self).__init__(msg_id, **kwargs)


class GitDockerfileChangeEvent(BaseEvent):
    """Represent the message omitted when Dockerfile is changed in a push"""

    def __init__(self, msg_id, container, branch, rev, **kwargs):
        super(GitDockerfileChangeEvent, self).__init__(msg_id, **kwargs)
        self.container = container
        self.branch = branch
        self.rev = rev

    @property
    def search_key(self):
        return "%s/%s?#%s" % (self.container, self.branch, self.rev)


class BodhiUpdateCompleteStableEvent(BaseEvent):
    """Event when RPMs are available in Fedora master mirrors

    Refer to an example in datagrepper:

    https://apps.fedoraproject.org/datagrepper/raw?delta=572800& \
        topic=org.fedoraproject.prod.bodhi.update.complete.stable
    """

    def __init__(self, msg_id, update_id, builds, release, **kwargs):
        """Initiate event with data from message got from fedmsg

        Not complete data is required, only part of attributes that are useful
        for rebuild are stored in this event.

        :param str update_id: the Bodhi update ID got from message.
        :param list builds: a list of maps, each of them contains build NVRs
            that are useful for getting RPMs for the rebuild.
        :param dist release: a map contains release information, e.g. name and
            branch. Refer to the example given above to see all available
            attributes in a message.
        """
        super(BodhiUpdateCompleteStableEvent, self).__init__(msg_id, **kwargs)
        self.update_id = update_id
        self.builds = builds
        self.release = release

    @property
    def search_key(self):
        return str(self.update_id)


class KojiTaskStateChangeEvent(BaseEvent):
    """
    Provides an event object for "the state of task changed in koji"
    """
    def __init__(self, msg_id, task_id, task_state, **kwargs):
        super(KojiTaskStateChangeEvent, self).__init__(msg_id, **kwargs)
        self.task_id = task_id
        self.task_state = task_state


class ErrataBaseEvent(BaseEvent):
    def __init__(self, msg_id, advisory, freshmaker_event_id=None, **kwargs):
        """
        Creates new ErrataBaseEvent.

        :param str msg_id: Message id.
        :param ErrataAdvisory advisory: Errata advisory associated with event.
        :param freshmaker_event_id: Freshmaker event id on which this event is based on.
        """
        super(ErrataBaseEvent, self).__init__(msg_id, **kwargs)
        self.advisory = advisory
        self.freshmaker_event_id = freshmaker_event_id

    @property
    def search_key(self):
        return str(self.advisory.errata_id)

    def is_allowed(self, handler, **kwargs):
        return super(ErrataBaseEvent, self).is_allowed(
            handler, ArtifactType.IMAGE,
            advisory_state=self.advisory.state,
            advisory_name=self.advisory.name,
            advisory_security_impact=self.advisory.security_impact,
            advisory_product_short_name=self.advisory.product_short_name,
            advisory_has_hightouch_bug=self.advisory.has_hightouch_bug,
            advisory_content_types=' '.join(self.advisory.content_types),
            **kwargs)


class ErrataAdvisoryStateChangedEvent(ErrataBaseEvent):
    """
    Represents change of Errata Advisory status.
    """


class FlatpakModuleAdvisoryReadyEvent(ErrataBaseEvent):
    """
    Represents change of module Errata Advisory ready for building flatpaks.
    """


class ErrataRPMAdvisoryShippedEvent(ErrataBaseEvent):
    """
    Event when all RPMs in Errata advisory are signed.
    """


class ManualRebuildWithAdvisoryEvent(ErrataRPMAdvisoryShippedEvent):
    """
    Event representing manual rebuild of particular container images with RPMs
    from advisory.
    """

    def __init__(self, msg_id, advisory, container_images,
                 requester_metadata_json=None,
                 requester=None, **kwargs):
        """
        Creates new ManualRebuildWithAdvisoryEvent.

        :param str msg_id: Message id.
        :param ErrataAdvisory advisory: Errata advisory associated with event.
        :param list container_images: List of NVRs of images to rebuild or
            empty list to rebuild all images affected by the advisory.
        :param requester_metadata_json: JSON of additional information about rebuild
        :param requester: name of requester of rebuild
        """
        super(ManualRebuildWithAdvisoryEvent, self).__init__(
            msg_id, advisory, **kwargs)
        self.manual = True
        self.container_images = container_images
        self.requester_metadata_json = requester_metadata_json
        self.requester = requester


class BrewSignRPMEvent(BaseEvent):
    """
    Represents the message sent by Brew when RPM is signed.
    """
    def __init__(self, msg_id, nvr, **kwargs):
        super(BrewSignRPMEvent, self).__init__(msg_id, **kwargs)
        self.nvr = nvr

    @property
    def search_key(self):
        return str(self.nvr)


class BrewContainerTaskStateChangeEvent(BaseEvent):
    """
    Represents the message sent by Brew when a container task state is changed.
    """
    def __init__(self, msg_id, container, branch, target, task_id, old_state,
                 new_state, **kwargs):
        super(BrewContainerTaskStateChangeEvent, self).__init__(msg_id, **kwargs)
        self.container = container
        self.branch = branch
        self.target = target
        self.task_id = task_id
        self.old_state = old_state
        self.new_state = new_state

    @property
    def search_key(self):
        return str(self.task_id)


class ODCSComposeStateChangeEvent(BaseEvent):
    """Represent a compose' state change event from ODCS"""

    def __init__(self, msg_id, compose, **kwargs):
        super(ODCSComposeStateChangeEvent, self).__init__(msg_id, **kwargs)
        self.compose = compose


class FreshmakerManualRebuildEvent(BaseEvent):
    """
    NOTE: This event is deprecated and not used anymore, but we have to keep
    it around, because we have instances of this event stored in database.
    """
    def __init__(self, msg_id, errata_id=None, dry_run=False):
        super(FreshmakerManualRebuildEvent, self).__init__(
            msg_id, dry_run=dry_run)
        self.errata_id = errata_id


class FreshmakerManageEvent(BaseEvent):
    """
    Event triggered by an internal message for managing Freshmaker itself.
    """
    _max_tries = 3

    def __init__(self, msg_body, **kwargs):
        super(FreshmakerManageEvent, self).__init__(None, manual=True, **kwargs)
        self.body = msg_body

    def __new__(cls, msg_body, *args, **kwargs):
        # The intention here is to balance control over retries. We want
        # to allow handlers to implement their own logic depending on
        # `last_try`, when they *SHALL* return an empty list. But, we also
        # want to avoid endless loops and guarantee some higher control. If
        # handler(s) don't stop their tries (by returning new events),
        # then the unhandleable `None` is returned here as last resort,
        # instead of `FreshmakerManageEvent`.
        instance = super(FreshmakerManageEvent, cls).__new__(cls)
        instance.action = msg_body['action']
        instance.try_count = msg_body['try']
        instance.try_count += 1
        instance.last_try = instance.try_count == FreshmakerManageEvent._max_tries

        if instance.try_count > FreshmakerManageEvent._max_tries:
            return None
        return instance


class FreshmakerAsyncManualBuildEvent(BaseEvent):
    """Event triggered via API endpoint /async-builds"""

    def __init__(self, msg_id, dist_git_branch, container_images,
                 freshmaker_event_id=None, brew_target=None, dry_run=False,
                 requester=None, requester_metadata_json=None):
        """Initialize this event

        :param str msg_id: the message id.
        :param str dist_git_branch: name of the branch in container dist-git
            repository from which to rebuild images.
        :param container_images: list of image names, for example,
            ``['image1', 'image2']``. Please note that each of the element is
            the N part of image's N-V-R.
        :type container_images: list[str]
        :param freshmaker_event_id: a Freshmaker event ID. If set, it will be
            used as a dependent event. Successful builds from this Event will
            be reused in the newly created Event instead of building all the
            artifacts from scratch.
        :type freshmaker_event_id: int or None
        :param brew_target: the Brew target for the build. If not set, the
            previous ``buildContainer`` task build target will be used.
        :type brew_target: str or None
        :param dry_run: True if the event should be handled in DRY_RUN mode.
        :param requester: name of requester of rebuild
        :param requester_metadata_json: JSON of additional information about rebuild
        """
        super(FreshmakerAsyncManualBuildEvent, self).__init__(
            msg_id, manual=True, dry_run=dry_run)
        self.dist_git_branch = dist_git_branch
        self.container_images = container_images
        self.freshmaker_event_id = freshmaker_event_id
        self.brew_target = brew_target
        self.requester = requester
        self.requester_metadata_json = requester_metadata_json


class BotasErrataShippedEvent(ErrataBaseEvent):
    """ Event triggered, when BOTAS pushes advisory to SHIPPED_LIVE state """

    def __init__(self, msg_id, advisory, dry_run=False):
        super().__init__(msg_id, advisory, dry_run=dry_run)


class ManualBundleRebuildEvent(ErrataBaseEvent):
    """
    Event triggered when Release Driver requests manual rebuild
    OR when manual rebuild of bundles requested by person
    """
    def __init__(self, msg_id, advisory, container_images,
                 requester_metadata_json=None, freshmaker_event_id=None,
                 requester=None, dry_run=False, **kwargs):
        super().__init__(
            msg_id, advisory,
            freshmaker_event_id=freshmaker_event_id, dry_run=dry_run, **kwargs
        )
        self.manual = True
        self.container_images = container_images
        self.requester_metadata_json = requester_metadata_json
        self.requester = requester

    @property
    def search_key(self):
        return str(self.advisory.errata_id)


class FlatpakApplicationManualBuildEvent(ManualRebuildWithAdvisoryEvent):
    """
    Event triggered when manual rebuild of a flatpak is requested.
    """
