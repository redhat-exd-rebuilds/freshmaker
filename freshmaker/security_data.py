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

import requests

from freshmaker import log, conf


class SecurityDataAPI(object):

    # Ordered Threat severities.
    THREAT_SEVERITIES = [
        "low",
        "moderate",
        "important",
        "critical",
    ]

    def __init__(self, server_url=None):
        """
        Creates new SecurityDataAPI instance.

        :param str server_url: SecurityDataAPI base URL.
        """
        if server_url is not None:
            self.server_url = server_url.rstrip('/')
        else:
            self.server_url = conf.security_data_server_url.rstrip('/')

    def _get_cve(self, cve):
        """
        Returns the JSON with metadata about `cve` obtained from
        /cve/$cve.json endpoint.

        :param str cve: CVE, for example "CVE-2017-10268".
        :rtype: dict
        :return: Dict with metadata about CVE.
        """
        log.debug("Querying SecurityDataAPI for %s", cve)
        r = requests.get("%s/cve/%s.json" % (self.server_url, cve))
        r.raise_for_status()
        return r.json()

    def get_highest_threat_severity(self, cve_list):
        """
        Fetches metadata about each CVE in `cve_list` and returns the name of
        highest severity rate. See `SecurityDataAPI.THREAT_SEVERITIES` for
        list of possible severity rates.

        :param list cve_list: List of strings with CVE names.
        :rtype: str
        :return: Name of highest severity rate occuring in CVEs from `cve_list`.
        """
        max_rating = -1
        for cve in cve_list:
            try:
                data = self._get_cve(cve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    log.warn(
                        "CVE %s cannot be found in SecurityDataAPI, "
                        "threat_severity unknown.", cve)
                    continue
                raise
            severity = data["threat_severity"].lower()
            try:
                rating = SecurityDataAPI.THREAT_SEVERITIES.index(severity)
            except ValueError:
                log.error("Unknown threat_severity '%s' for CVE %s",
                          severity, cve)
                continue
            max_rating = max(max_rating, rating)

        if max_rating == -1:
            return None
        return SecurityDataAPI.THREAT_SEVERITIES[max_rating]
