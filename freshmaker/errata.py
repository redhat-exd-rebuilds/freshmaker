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

from freshmaker.events import BrewSignRPMEvent


class ErrataAdvisory(object):
    """
    Represents Errata advisory.
    """

    def __init__(self, errata_id, name, state, security_impact=None):
        """
        Initializes the ErrataAdvisory instance.
        """
        self.errata_id = errata_id
        self.name = name
        self.state = state
        self.security_impact = security_impact or ""


class Errata(object):
    """ Interface to Errata. """

    def __init__(self, server_url):
        """
        Initializes the Errata instance.

        :param str server_url: Base URL of Errata server.
        """
        self._rest_api_ver = 'api/v1'
        self.server_url = server_url.rstrip('/')

    def _errata_rest_get(self, endpoint):
        """Request REST-style API

        Document: /developer-guide/api-http-api.html
        """
        r = requests.get("%s/%s/%s" % (self.server_url,
                                       self._rest_api_ver,
                                       endpoint.lstrip('/')),
                         auth=HTTPKerberosAuth())
        r.raise_for_status()
        return r.json()

    def _errata_http_get(self, endpoint):
        """Request Errata legacy HTTP API

        See also Legacy section in /developer-guide/api-http-api.html
        """
        r = requests.get('{}/{}'.format(self.server_url, endpoint),
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
        if isinstance(event, BrewSignRPMEvent):
            build = self._errata_rest_get("/build/%s" % str(event.nvr))
            if "all_errata" not in build:
                return []

            advisories = []
            for errata in build["all_errata"]:
                extra_data = self._errata_http_get(
                    "advisory/%s.json" % str(errata["id"]))
                advisory = ErrataAdvisory(
                    errata["id"], errata["name"], errata["status"],
                    extra_data["security_impact"])
                advisories.append(advisory)

            return advisories
        else:
            raise ValueError("Unsupported event type")

    def builds_signed(self, errata_id):
        """
        Returns True if all builds in the advisory are signed.
        :param str or int errata_id: Errata advisory ID to check.
        :return: True if all builds in advisory are signed.
        :rtype: bool
        """
        builds_per_product = self._errata_http_get(
            "advisory/%s/builds.json" % str(errata_id))

        # Store NVRs of all builds in advisory to nvrs set.
        nvrs = set()
        for builds in builds_per_product.values():
            for build in builds:
                nvrs.update(set(build.keys()))

        # For each NVR, check that all the rpms are signed.
        for nvr in nvrs:
            build = self._errata_rest_get("build/%s" % str(nvr))
            if "rpms_signed" not in build or not build["rpms_signed"]:
                return False

        return True

    def get_pulp_repository_ids(self, errata_id):
        """Get Pulp repository IDs where packages included in errata will end up

        :param errata_id: Errata advisory ID, e.g. 25713.
        :type errata_id: str or int
        :return: a list of strings each of them represents a pulp repository ID
        :rtype: list
        """
        data = self._errata_http_get(
            '/errata/get_pulp_packages/{}.json'.format(errata_id))
        return data.keys()
