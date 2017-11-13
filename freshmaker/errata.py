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
import dogpile.cache
from requests_kerberos import HTTPKerberosAuth

from freshmaker.events import (
    BrewSignRPMEvent, ErrataAdvisoryStateChangedEvent,
    FreshmakerManualRebuildEvent)
from freshmaker import conf, log


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

    # Cache for `advisories_from_event` related methods. The main reason
    # of this cache is lookup of BrewSignRPMEvents which came in waves.
    # Therefore the short 10 seconds timeout. We don't want to cache it for
    # too long to keep the data in sync with Errata tool.
    region = dogpile.cache.make_region().configure(
        conf.dogpile_cache_backend, expiration_time=10)

    # Change for _rhel_release_from_product_version.
    # Big expiration_time is OK here, because once we start rebuilding
    # something for particular product version, its rhel_release version
    # should not change.
    product_region = dogpile.cache.make_region().configure(
        conf.dogpile_cache_backend, expiration_time=24 * 3600)

    def __init__(self, server_url=None):
        """
        Initializes the Errata instance.

        :param str server_url: Base URL of Errata server.
        """
        self._rest_api_ver = 'api/v1'
        if server_url is not None:
            self.server_url = server_url.rstrip('/')
        else:
            self.server_url = conf.errata_tool_server_url.rstrip('/')

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

    def get_advisory(self, errata_id):
        return self._errata_http_get('advisory/{0}.json'.format(errata_id))

    @region.cache_on_arguments()
    def _advisories_from_nvr(self, nvr):
        """
        Returns the list of advisories which contain the artifact with
        `nvr` NVR.
        """
        build = self._errata_rest_get("/build/%s" % str(nvr))
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
            return self._advisories_from_nvr(event.nvr)
        elif (isinstance(event, ErrataAdvisoryStateChangedEvent) or
              isinstance(event, FreshmakerManualRebuildEvent)):
            data = self.get_advisory(event.errata_id)
            advisory = ErrataAdvisory(
                data["id"], data["advisory_name"], data["status"],
                data["security_impact"])
            return [advisory]
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
            log.info("Checking whether the build %s is signed", str(nvr))
            build = self._errata_rest_get("build/%s" % str(nvr))
            if "rpms_signed" not in build or not build["rpms_signed"]:
                return False

        return True

    def _rhel_release_from_product_version(self, errata_id, product_version):
        """
        Returns release name of RHEL release the product version is based on.

        :param number errata_id: Errata advisory ID.
        :param string product_version: Version of product to check the RHEL
            release for.
        :rtype: string
        :return: Name of the RHEL release.
        """

        # Get the product ID this advisory is about - for example "RHSCL".
        data = self._errata_http_get("advisory/%s.json" % str(errata_id))
        product_id = data["product"]["id"]

        # Get all the product versions associated with this product ID.
        data = self._errata_http_get("products/%s/product_versions.json"
                                     % str(product_id))

        # Find out the product version ID for the input `product_version`
        # name.
        pr_version_id = None
        for pr_version in data:
            if pr_version["product_version"]["name"] == product_version:
                pr_version_id = pr_version["product_version"]["id"]
                break

        if not pr_version_id:
            raise ValueError(
                "Cannot get RHEL release from Errata advisory %s, product "
                "version %s" % (str(errata_id), product_version))

        # Get the additional product version info to find out the RHEL release
        # name.
        data = self._errata_http_get("products/%s/product_versions/%s.json"
                                     % (str(product_id), str(pr_version_id)))

        return data["rhel_release"]["name"]

    def get_builds(self, errata_id, rhel_release_prefix=None):
        """
        Returns set of NVRs of builds added to the advisory. These are just
        brew build NVRs, not the particular RPM NVRs.

        :param number errata_id: ID of advisory.
        :param string rhel_release_prefix: When set to non-empty string,
            it will be used to limit the set of builds returned by this
            method to only builds based on the RHEL version starting with
            `rhel_release_prefix`. For example to return only RHEL-7 builds,
            this should be set to "RHEL-7".
            Defaults to conf.errata_rhel_release_prefix.
        :rtype: set of strings
        :return: Set of NVR builds.
        """
        if rhel_release_prefix is None:
            rhel_release_prefix = conf.errata_rhel_release_prefix

        builds_per_product = self._errata_http_get(
            "advisory/%s/builds.json" % str(errata_id))

        # Store NVRs of all builds in advisory to nvrs set.
        nvrs = set()
        for product_version, builds in builds_per_product.items():
            rhel_release = Errata.product_region.get(product_version)
            if not rhel_release:
                rhel_release = self._rhel_release_from_product_version(
                    errata_id, product_version)
                Errata.product_region.set(product_version, rhel_release)

            if (rhel_release_prefix and
                    not rhel_release.startswith(rhel_release_prefix)):
                log.info("Skipping builds for %s - not based on RHEL %s",
                         product_version, rhel_release_prefix)
                continue
            for build in builds:
                nvrs.update(set(build.keys()))
        return nvrs

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
