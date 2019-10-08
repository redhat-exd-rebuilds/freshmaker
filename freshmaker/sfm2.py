# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
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

import requests

from freshmaker import log, conf


class SFM2API(object):

    # Ordered Threat severities.
    THREAT_SEVERITIES = [
        "low",
        "moderate",
        "important",
        "critical",
    ]

    def __init__(self, server_url=None):
        """
        Creates new SFM2API instance.

        :param str server_url: SFM2API base URL.
        """
        if server_url is not None:
            self.server_url = server_url.rstrip('/')
        else:
            self.server_url = conf.sfm2_api_url.rstrip('/')

    def query_sfm2(self, cve):
        """
        Queries SFM2 to find out infos about the cve, specifically
        the CVE impact and list of affected packages
        It queries api/public/flaws?id=$cve&include_fields=affects,impact endpoint.

        :param str cve: CVE, for example "CVE-2017-10268".
        :rtype: list
        :return: dict with two keys, "impact", and "affects". The first references
        the impact of the CVE, and the second is a list of dicts representing packages
        affected by the CVE.
        """
        log.debug("Querying SFM2 for %s", cve)
        r = requests.get(
            "%s/api/public/flaws" % self.server_url,
            params={"include_fields": "affects,impact", "id": cve})
        r.raise_for_status()

        return r.json()[0]

    def fetch_cve_metadata(self, cve_list):
        """
        Fetches metadata about each CVE in `cve_list` and returns a tuple with
        the name of highest severity rate and the affected packages (a dictionary
        with product and pkg_name).
        See `SFM2API.THREAT_SEVERITIES` for list of possible severity rates.

        :param list cve_list: List of strings with CVE names.
        :rtype: str
        :return: Tuple, the first element is the name of highest severity rate occuring
        in CVEs from `cve_list`. The second element is a list of dicts, with "product"
        and "pkg_name" of the affected packages.
        """
        max_rating = -1
        elements = []
        affected_pkgs = []
        severity = None
        for cve in cve_list:
            try:
                elements = self.query_sfm2(cve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 400:
                    log.warning(
                        "The request for the CVE %s to the SFM2 API seems wrong, "
                        "impact and affected packages unknown. %s", cve, e.response.request.url)
                    continue
                if e.response.status_code == 500:
                    log.warning(
                        "Some error occurred looking forCVE %s with SFM2 API, "
                        "impact and affected packages unknown. %s", cve, e.response.request.url)
                    continue
                raise

            try:
                severity = elements['impact']
            except (IndexError, KeyError):
                log.warning("Some error occured looking for impact for CVE %s using SFM2 API", cve)

            try:
                affected_pkgs.extend([
                    {'product': item['ps_module'], 'pkg_name': item['ps_component']}
                    for item in elements['affects'] if (
                        item['affected'] != "notaffected" and
                        item['resolution'] not in ["wontfix", "ooss"])])
            except (KeyError, IndexError):
                log.exception("Some error occured looking for affected packages for CVE %s using SFM2 API", cve)

            try:
                rating = SFM2API.THREAT_SEVERITIES.index(severity)
            except ValueError:
                log.error("Unknown threat_severity '%s' for CVE %s",
                          severity, cve)
                continue

            max_rating = max(max_rating, rating)

        if max_rating == -1:
            return (None, affected_pkgs)
        return (SFM2API.THREAT_SEVERITIES[max_rating], affected_pkgs)
