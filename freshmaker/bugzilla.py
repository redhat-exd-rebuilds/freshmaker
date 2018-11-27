# -*- coding: utf-8 -*-
# Copyright (c) 2018  Red Hat, Inc.
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
#            Ralph Bean <rbean@redhat.com

import requests

from defusedxml import ElementTree
from freshmaker import log, conf


class BugzillaAPI(object):

    # Ordered Threat severities.
    THREAT_SEVERITIES = [
        "low",
        "moderate",
        "important",
        "critical",
    ]

    def __init__(self, server_url=None):
        """
        Creates new BugzillaAPI instance.

        :param str server_url: BugzillaAPI base URL.
        """
        if server_url is not None:
            self.server_url = server_url.rstrip('/')
        else:
            self.server_url = conf.bugzilla_server_url.rstrip('/')

    def _get_cve_whiteboard(self, cve):
        """
        Returns the whiteboard dict about `cve` obtained from
        show_bug.cgi?ctype=xml&id=$cve endpoint

        :param str cve: CVE, for example "CVE-2017-10268".
        :rtype: dict
        :return: the status whiteboard of the bugzilla CVE.
        """
        log.debug("Querying bugzilla for %s", cve)
        r = requests.get(
            "%s/show_bug.cgi" % self.server_url,
            params={"ctype": "xml", "id": cve})
        r.raise_for_status()

        # Parse
        root = ElementTree.fromstring(r.text.encode('utf-8'))

        # List the major xml elements
        elements = list(list(root)[0])

        # Extract the whiteboard string
        whiteboard = [e.text for e in elements if e.tag == 'status_whiteboard']

        # Handle missing and/or empty whiteboards
        if not whiteboard:
            return dict()
        whiteboard = whiteboard[0]
        if not whiteboard:
            return dict()

        # Convert the whiteboard to a dict, and return
        return dict(entry.split('=', 1) for entry in whiteboard.split(','))

    def get_highest_impact(self, cve_list):
        """
        Fetches metadata about each CVE in `cve_list` and returns the name of
        highest severity rate. See `BugzillaAPI.THREAT_SEVERITIES` for
        list of possible severity rates.

        :param list cve_list: List of strings with CVE names.
        :rtype: str
        :return: Name of highest severity rate occuring in CVEs from `cve_list`.
        """
        max_rating = -1
        for cve in cve_list:
            try:
                data = self._get_cve_whiteboard(cve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warning(
                        "CVE %s cannot be found in bugzilla, "
                        "threat_severity unknown.  %s", cve, e.response.request.url)
                    continue
                raise
            except IndexError:
                log.warning(
                    "CVE %s XML appears malformed.  No children?  "
                    "threat_severity unknown.", cve)
                continue

            try:
                severity = data["impact"].lower()
            except KeyError:
                log.warning(
                    "CVE %s has no 'impact' in bugzilla whiteboard, "
                    "threat_severity unknown.", cve)
                continue

            try:
                rating = BugzillaAPI.THREAT_SEVERITIES.index(severity)
            except ValueError:
                log.error("Unknown threat_severity '%s' for CVE %s",
                          severity, cve)
                continue

            max_rating = max(max_rating, rating)

        if max_rating == -1:
            return None
        return BugzillaAPI.THREAT_SEVERITIES[max_rating]
