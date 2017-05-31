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
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
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

import requests
from requests_kerberos import HTTPKerberosAuth

from freshmaker.events import BrewRPMSignEvent


class ErrataAdvisory(object):
    """
    Represents Errata advisory.
    """

    def __init__(self, errata_id, name, state):
        """
        Initializes the ErrataAdvisory instance.
        """
        self.errata_id = errata_id
        self.name = name
        self.state = state


class Errata(object):
    """ Interface to Errata. """

    def __init__(self, server_url):
        """
        Initializes the Errata instance.

        :param str server_url: Base URL of Errata server.
        """
        self.server_url = server_url.rstrip('/')

    def _errata_get(self, endpoint):
        r = requests.get("%s/%s" % (self.server_url, endpoint),
                         auth=HTTPKerberosAuth())
        r.raise_for_status()
        return r.json()

    def advisories_from_event(self, event):
        """
        Returns list of ErrataAdvisory instances associated with
        the Freshmaker Event.

        :param BaseEvent event: Event from which the errata ID should be
            returned. Following events are supported:
                - BrewRPMSignEvent
        :raises ValueError: if unsupported BaseEvent subclass is passed
        :return: List of ErrataAdvisory instances
        :rtype: list
        """
        if isinstance(event, BrewRPMSignEvent):
            build = self._errata_get("api/v1/build/%s" % str(event.nvr))
            if "all_errata" not in build:
                return []
            return [
                ErrataAdvisory(errata["id"], errata["name"], errata["status"])
                for errata in build["all_errata"]]
        else:
            raise ValueError("Unsupported event type")

    def builds_signed(self, errata_id):
        """
        Returns True if all builds in the advisory are signed.
        :param str or int errata_id: Errata advisory ID to check.
        :return: True if all builds in advisory are signed.
        :rtype: bool
        """
        builds_per_product = self._errata_get(
            "advisory/%s/builds.json" % str(errata_id))

        # Store NVRs of all builds in advisory to nvrs set.
        nvrs = set()
        for builds in builds_per_product.values():
            for build in builds:
                nvrs.update(set(build.keys()))

        # For each NVR, check that all the rpms are signed.
        for nvr in nvrs:
            build = self._errata_get("api/v1/build/%s" % str(nvr))
            if "rpms_signed" not in build or not build["rpms_signed"]:
                return False

        return True
