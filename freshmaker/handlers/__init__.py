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

import abc
import re
import sys

from freshmaker import conf, log, db, models
from freshmaker.mbs import MBS
from freshmaker.kojiservice import koji_service


def load_class(location):
    """ Take a string of the form 'fedmsg.consumers.ircbot:IRCBotConsumer'
    and return the IRCBotConsumer class.
    """
    mod_name, cls_name = location.strip().split(':')

    __import__(mod_name)

    try:
        return getattr(sys.modules[mod_name], cls_name)
    except AttributeError:
        raise ImportError("%r not found in %r" % (cls_name, mod_name))


def load_handlers():
    """ Import and instantiate all handlers listed in the given config. """
    for import_path in conf.handlers:
        cls = load_class(import_path)
        handler = cls()
        yield handler


class BaseHandler(object):
    """
    Abstract base class for event handlers.
    """
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def can_handle(self, event):
        """
        Returns true if this class can handle this type of event.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def handle(self, event):
        """
        Handles the event. Can return another BaseEvent instances to
        generate another events to be used by other local handlers.

        :return: List of BaseEvent objects which will be handled by other
        handlers after this handler handles the event. This can be used to
        generate internal events for other handlers in Freshmaker.
        """
        raise NotImplementedError()

    def build_module(self, name, branch, rev):
        """
        Build a module in MBS.

        :param name: module name.
        :param branch: module branch.
        :param rev: git revision.
        """
        mbs = MBS(conf)
        return mbs.build_module(name, branch, rev)

    def build_container(self, name, branch, rev):
        """
        Build a container in koji.

        :param container: container name.
        :param branch: container branch.
        :param rev: revision.
        """
        with koji_service(profile=conf.koji_profile, logger=log) as service:
            log.debug('Logging into {0} with Kerberos authentication.'.format(service.server))
            proxyuser = conf.koji_build_owner if conf.koji_proxyuser else None
            service.krb_login(proxyuser=proxyuser)

            if not service.logged_in:
                log.error('Could not login server %s', service.server)
                return None

            build_source = "{}/container/{}.git?#{}".format(conf.git_base_url, name, rev)

            log.debug('Building container from source: %s', build_source)

            return service.build_container(build_source,
                                           branch,
                                           namespace='container',
                                           scratch=conf.koji_container_scratch_build)

    def record_build(self, event, name, type, build_id, dep_of=None):
        """
        Record build in db.

        :param event: instance of an event.
        :param name: name of the artifact.
        :param type: type of the artifact, can be 'rpm', 'image' or module.
        :param build_id: id of the build in build system.
        :param def_of: the artifact which this one depends on.
        """
        ev = models.Event.get_or_create(db.session, event.msg_id,
                                        event.search_key, event.__class__)
        models.ArtifactBuild.create(db.session, ev, name, type, build_id, dep_of)
        db.session.commit()

    def allow_build(self, event, artifact_type, name, branch):
        """
        Check whether the artifact is allowed to be built by checking
        HANDLER_BUILD_WHITELIST and HANDLER_BUILD_BLACKLIST in config.

        :param event: event instance.
        :param artifact_type: 'module' or 'image'.
        :param name: name of the artifact.
        :param branch: branch name of the artifact.
        :return: True or False.
        """
        # If there is a whitelist specified for the (handler, event, artifact_type),
        # the build target of (name, branch) need to be in that whitelist first.
        # After that (if the build target is in whitelist), check the build target
        # is not in the specified blacklist.

        # by default we assume the artifact is in whitelist and not in blacklist
        in_whitelist = True
        in_blacklist = False

        handler_name = self.name
        event_name = type(event).__name__
        whitelist_rules = conf.handler_build_whitelist.get(handler_name, {}).get(event_name, {})
        blacklist_rules = conf.handler_build_blacklist.get(handler_name, {}).get(event_name, {})

        def match_rule(name, branch, rule):
            name_rule = rule.get('name', None)
            branch_rule = rule.get('branch', None)
            if name_rule and not re.compile(name_rule).match(name):
                    return False
            if branch_rule and not re.compile(branch_rule).match(branch):
                    return False
            return True

        try:
            whitelist = whitelist_rules.get(artifact_type, [])
            if whitelist and not any([match_rule(name, branch, rule) for rule in whitelist]):
                log.debug('name=%r, branch=%r, type=%r is not whitelisted.',
                          name, branch, artifact_type)
                in_whitelist = False

            # only need to check blacklist when it is in whitelist first
            if in_whitelist:
                blacklist = blacklist_rules.get(artifact_type, [])
                if blacklist and any([match_rule(name, branch, rule) for rule in blacklist]):
                    log.debug('name=%r, branch=%r, type=%r is blacklisted.',
                              name, branch, artifact_type)
                    in_blacklist = True

        except re.error as exc:
            log.error("Error while compiling blacklist/whilelist rule for <handler(%s) event(%s) artifact(%s)>:\n"
                      "Incorrect regular expression: %s\nBlacklist and Whitelist will not take effect",
                      handler_name, event_name, artifact_type, str(exc))
            return True
        return in_whitelist and not in_blacklist
