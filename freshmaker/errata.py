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

import os
import re
import requests
import dogpile.cache
from requests_kerberos import HTTPKerberosAuth, OPTIONAL

from freshmaker.events import BrewSignRPMEvent, ErrataBaseEvent, FreshmakerManualRebuildEvent
from freshmaker import conf, log
from freshmaker.utils import retry


class ErrataAdvisory(object):
    """
    Represents Errata advisory.
    """

    def __init__(
        self,
        errata_id,
        name,
        state,
        content_types,
        security_impact=None,
        product_short_name=None,
        release_name=None,
        cve_list=None,
        is_major_incident=None,
        is_compliance_priority=None,
    ):
        """
        Initializes the ErrataAdvisory instance.
        """
        self.errata_id = errata_id
        self.name = name
        self.state = state
        self.content_types = content_types
        self.security_impact = security_impact or ""
        self.product_short_name = product_short_name or ""
        self.release_name = release_name or ""
        self.cve_list = cve_list or []
        self.is_major_incident = is_major_incident
        self.is_compliance_priority = is_compliance_priority

        self._affected_rpm_nvrs = None
        self._reporter = ""
        self._builds = None

    @property
    def affected_rpm_nvrs(self):
        if self._affected_rpm_nvrs is not None:
            return self._affected_rpm_nvrs

        errata = Errata()
        self._affected_rpm_nvrs = errata.get_cve_affected_rpm_nvrs(self.errata_id)
        return self._affected_rpm_nvrs

    @property
    def reporter(self):
        if self._reporter:
            return self._reporter

        errata = Errata()
        advisory_data = errata._get_advisory_legacy(self.errata_id)
        self._reporter = advisory_data["people"]["reporter"]
        return self._reporter

    @property
    def builds(self):
        if self._builds is None:
            errata = Errata()
            self._builds = errata._errata_rest_get(f"erratum/{self.errata_id}" "/builds")

        return self._builds

    @classmethod
    def from_advisory_id(cls, errata, errata_id):
        """
        Creates new ErrataAdvisory instance from the Erratum ID.
        """
        data = errata._get_advisory(errata_id)
        erratum_data = list(data["errata"].values())
        if not erratum_data:
            return None
        erratum_data = erratum_data[0]

        release_data = errata._get_release(errata_id)
        product_data = errata._get_product(erratum_data["product_id"])
        cve = data["content"]["content"]["cve"].strip()
        if cve:
            cve_list = cve.split(" ")
        else:
            cve_list = []

        # security_impact in errata is capitalized string, making it lowercase
        # for backwards compatibility with SFM2's security impact (we used to
        # get the severity from SFM2). It's used in our config to allow or block
        # rebuilds for artifacts.
        security_impact = erratum_data["security_impact"].lower()

        has_hightouch_bug = False
        has_compliance_priority_bug = False
        bugs = errata._get_bugs(erratum_data["id"]) or []

        has_hightouch_bug = any(["hightouch+" in bug.get("flags", "") for bug in bugs])
        has_compliance_priority_bug = any(
            ["compliance_priority+" in bug.get("flags", "") for bug in bugs]
        )

        has_jira_major_incident = errata.has_jira_major_incidents(errata_id)
        is_major_incident = has_hightouch_bug or has_jira_major_incident

        has_jira_compliance_priority = errata.has_compliance_priority_jira_label(errata_id)
        is_compliance_priority = has_compliance_priority_bug or has_jira_compliance_priority

        return ErrataAdvisory(
            erratum_data["id"],
            erratum_data["fulladvisory"],
            erratum_data["status"],
            erratum_data["content_types"],
            security_impact,
            product_data["product"]["short_name"],
            release_data["data"]["attributes"]["name"],
            cve_list,
            is_major_incident,
            is_compliance_priority,
        )

    def is_flatpak_module_advisory_ready(self):
        """Returns True only if a Flatpaks can be rebuilt from module advisory.

        Flatpaks can be rebuilt only if all of the following are true:
        - Advisory must contain modules.
        - Advisory is in QE state.
        - All attached builds are only shipped to hidden pulp repositories.
        - All attached builds are signed.
        """
        errata = Errata()
        return (
            self.state == "QE"
            and "module" in self.content_types
            and all(
                "-hidden-" in repo_id for repo_id in errata.get_pulp_repository_ids(self.errata_id)
            )
            and errata.builds_signed(self.errata_id)
            and errata.is_zstream(self.errata_id)
        )


class Errata(object):
    """Interface to Errata."""

    # Cache for `advisories_from_event` related methods. The main reason
    # of this cache is lookup of BrewSignRPMEvents which came in waves.
    # Therefore the short 10 seconds timeout. We don't want to cache it for
    # too long to keep the data in sync with Errata tool.
    region = dogpile.cache.make_region().configure(conf.dogpile_cache_backend, expiration_time=10)

    # Change for _rhel_release_from_product_version.
    # Big expiration_time is OK here, because once we start rebuilding
    # something for particular product version, its rhel_release version
    # should not change.
    product_region = dogpile.cache.make_region().configure(
        conf.dogpile_cache_backend, expiration_time=24 * 3600
    )

    def __init__(self, server_url=None):
        """
        Initializes the Errata instance.

        :param str server_url: Base URL of Errata server.
        """
        self._rest_api_ver = "api/v1"
        if server_url is not None:
            self.server_url = server_url.rstrip("/")
        else:
            self.server_url = conf.errata_tool_server_url.rstrip("/")

    @retry(wait_on=(requests.exceptions.RequestException,), logger=log)
    def _errata_authorized_get(self, *args, **kwargs):
        try:
            r = requests.get(
                *args,
                auth=HTTPKerberosAuth(
                    mutual_authentication=OPTIONAL, principal=conf.krb_auth_principal
                ),
                **kwargs,
                timeout=conf.requests_timeout,
            )
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 401:
                log.info("CCache file probably expired, removing it.")
                os.unlink(conf.krb_auth_ccache_file)
            raise
        return r.json()

    def _errata_rest_get(self, endpoint):
        """Request REST-style API

        Document: /developer-guide/api-http-api.html
        """
        return self._errata_authorized_get(
            "%s/%s/%s" % (self.server_url, self._rest_api_ver, endpoint.lstrip("/"))
        )

    def _errata_http_get(self, endpoint):
        """Request Errata legacy HTTP API

        See also Legacy section in /developer-guide/api-http-api.html
        """
        return self._errata_authorized_get("{}/{}".format(self.server_url, endpoint))

    def _get_advisory(self, errata_id):
        return self._errata_rest_get("erratum/{0}".format(errata_id))

    def _get_advisory_legacy(self, errata_id):
        return self._errata_http_get("advisory/{0}.json".format(errata_id))

    def _get_product(self, product_id):
        return self._errata_http_get("products/%s.json" % str(product_id))

    def _get_bugs(self, errata_id):
        return self._errata_http_get("advisory/%s/bugs.json" % str(errata_id))

    def _get_blocking_advisories(self, errata_id):
        return self._errata_http_get(f"errata/blocking_errata_for/{errata_id}.json")

    def _get_attached_builds(self, errata_id):
        return self._errata_http_get(f"advisory/{errata_id}/builds.json")

    def _get_builds_by_product(self, errata_id):
        return self._errata_rest_get(f"/erratum/{errata_id}/builds_list?with_sig_key=1")

    def _get_jira_issues(self, errata_id):
        return self._errata_http_get(f"advisory/{errata_id}/jira_issues.json")

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
            advisory = ErrataAdvisory.from_advisory_id(self, errata["id"])
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
        elif isinstance(event, ErrataBaseEvent):
            return [event.advisory]
        elif isinstance(event, FreshmakerManualRebuildEvent):
            return [ErrataAdvisory.from_advisory_id(self, event.errata_id)]
        else:
            raise ValueError("Unsupported event type")

    def builds_signed(self, errata_id):
        """
        Returns True if all builds in the advisory are signed.
        :param str or int errata_id: Errata advisory ID to check.
        :return: True if all builds in advisory are signed.
        :rtype: bool
        """
        data_by_product = self._get_builds_by_product(errata_id)
        return all(
            build_info.get("is_signed") is True
            for product_data in data_by_product.values()
            for build in product_data.get("builds", [])
            for build_info in build.values()
        )

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
        data = self._errata_http_get("products/%s/product_versions.json" % str(product_id))

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
                "version %s" % (str(errata_id), product_version)
            )

        # Get the additional product version info to find out the RHEL release
        # name.
        data = self._errata_http_get(
            "products/%s/product_versions/%s.json" % (str(product_id), str(pr_version_id))
        )

        return data["rhel_release"]["name"]

    def _get_rpms(self, errata_id, rhel_release_prefix=None):
        """
        Returns dictionary of NVRs of builds added to the advisory.
        "source_rpms" key with SRPMs as a value
        "binary_rpms" key with binary rpms as a value

        If module build is attached to advisory, also all the NVRs of builds
        included in this module build are returned, together with the NVR of
        the module build.

        :param number errata_id: ID of advisory.
        :param string rhel_release_prefix: When set to non-empty string,
            it will be used to limit the set of builds returned by this
            method to only builds based on the RHEL version starting with
            `rhel_release_prefix`. For example to return only RHEL-7 builds,
            this should be set to "RHEL-7".
            Defaults to conf.errata_rhel_release_prefix.
        :rtype: dict
        :return: Dictionary with source and binary rpms.
        """
        if rhel_release_prefix is None:
            rhel_release_prefix = conf.errata_rhel_release_prefix

        builds_per_product = self._get_attached_builds(errata_id)

        # Store NVRs of all builds in advisory to nvrs set.
        source_rpms = set()
        binary_rpms = set()
        for product_version, builds in builds_per_product.items():
            if rhel_release_prefix:
                rhel_release = Errata.product_region.get(product_version)
                if not rhel_release:
                    rhel_release = self._rhel_release_from_product_version(
                        errata_id, product_version
                    )
                    Errata.product_region.set(product_version, rhel_release)

                if not rhel_release.startswith(rhel_release_prefix):
                    log.info(
                        "Skipping builds for %s - not based on RHEL %s",
                        product_version,
                        rhel_release_prefix,
                    )
                    continue

            for build in builds:
                for variant_arch in build.values():
                    for arch_rpms in variant_arch.values():
                        for arch, rpms in arch_rpms.items():
                            if arch == "SRPMS":
                                source_rpms.update(rpms)
                            else:
                                binary_rpms.update(rpms)
        return {"source_rpms": source_rpms, "binary_rpms": binary_rpms}

    def get_srpm_nvrs(self, errata_id, rhel_release_prefix=None):
        """ "
        Returns list with nvrs of SRPMs attached to the advisory

        :param number errata_id: ID of advisory.
        :param string rhel_release_prefix: When set to non-empty string,
            it will be used to limit the set of builds returned by this
            method to only builds based on the RHEL version starting with
            `rhel_release_prefix`. For example to return only RHEL-7 builds,
            this should be set to "RHEL-7".
            Defaults to conf.errata_rhel_release_prefix.
        :rtype: list
        :return: List with SRPMs nvrs.
        """
        rpms = self._get_rpms(errata_id, rhel_release_prefix)
        source_rpms = rpms.get("source_rpms", [])
        srpm_nvrs = {nvr.rsplit(".", 2)[0] for nvr in source_rpms}
        return list(srpm_nvrs)

    def get_binary_rpm_nvrs(self, errata_id, rhel_release_prefix=None):
        """ "
        Returns list with nvrs of all binary RPMs attached to the advisory

        :param number errata_id: ID of advisory.
        :param string rhel_release_prefix: When set to non-empty string,
            it will be used to limit the set of builds returned by this
            method to only builds based on the RHEL version starting with
            `rhel_release_prefix`. For example to return only RHEL-7 builds,
            this should be set to "RHEL-7".
            Defaults to conf.errata_rhel_release_prefix.
        :rtype: list
        :return: List with nvrs of binary RPMs.
        """
        rpms = self._get_rpms(errata_id, rhel_release_prefix)
        binary_rpms = rpms.get("binary_rpms", [])
        nvrs = {nvr.rsplit(".", 2)[0] for nvr in binary_rpms}
        return list(nvrs)

    def get_pulp_repository_ids(self, errata_id):
        """Get Pulp repository IDs where packages included in errata will end up

        :param errata_id: Errata advisory ID, e.g. 25713.
        :type errata_id: str or int
        :return: a list of strings each of them represents a pulp repository ID
        :rtype: list
        """
        data = self._errata_http_get("/errata/get_pulp_packages/{}.json".format(errata_id))
        return data.keys()

    def get_cve_affected_rpm_nvrs(self, errata_id):
        """Get RPM nvrs which are affected by the CVEs in errata

        :param errata_id: Errata advisory ID, e.g. 25713.
        :type errata_id: str or int
        :return: a list of strings each of them is a binary rpm nvr
        :rtype: list
        """
        data = self._errata_rest_get(f"/erratum/{errata_id}/builds_by_cve")
        nvrs = set()
        for data_by_product in data.values():
            for product_data in data_by_product.values():
                for build in product_data.get("builds", []):
                    for build_info in build.values():
                        # for rpm advisories, build_nvr equal to srpm nvr, but this is
                        # not true for module advisories, so we need to get the srpms
                        # from variants data
                        for variant, variant_data in build_info.get("variant_arch", {}).items():
                            for arch, rpms in variant_data.items():
                                # Remove '.arch.....' part from rpm's name
                                # and make a list from them
                                if arch != "SRPMS":
                                    just_nvrs = [rpm["filename"].rsplit(".", 2)[0] for rpm in rpms]
                                    nvrs.update(just_nvrs)

        return list(nvrs)

    def get_blocking_advisories_builds(self, errata_id):
        """Get all advisories that block given advisory id, and fetch all builds from it

        :param number errata_id: ID of advisory
        :return: NVRs of builds attached to all dependent advisories
        :rtype: set
        """
        nvrs = set()
        for advisory_id in self._get_blocking_advisories(errata_id):
            # recursively check for other blocking advisories and get builds from it
            nvrs.update(self.get_blocking_advisories_builds(advisory_id))

            product_builds = self._get_attached_builds(advisory_id)
            for builds in product_builds.values():
                for build in builds:
                    nvrs.update(set(build.keys()))
        return nvrs

    def get_attached_build_nvrs(self, errata_id):
        """Get all attached builds' NVRs

        :param number errata_id: ID of advisory
        :return: NVRs of attached builds
        :rtype: set
        """
        product_builds = self._get_attached_builds(errata_id)
        return {
            nvr for builds in product_builds.values() for build in builds for nvr in build.keys()
        }

    def _get_release(self, errata_id):
        """
        Returns release for the specified advisory.

        :param number errata_id: ID of advisory

        :return: a dict for release data
        :rtype: dict
        """

        # Get the release ID of this advisory
        data = self._get_advisory_legacy(errata_id)
        release_id = data["release"]["id"]

        # Get release with the release ID.
        release = self._errata_rest_get("releases/%s" % str(release_id))

        return release

    def is_zstream(self, errata_id):
        release = self._get_release(errata_id)
        return release["data"]["attributes"]["type"] == "Zstream"

    def has_jira_major_incidents(self, errata_id: str) -> bool:
        """
        Checks if this errata has a 'major incident' issue in JIRA

        :param errata_id: The ID of the errata advisory
        :type errata_id: str

        :return: Wether the errata has or not a major incident issue in JIRA
        :rtype: bool
        """
        resp = self._get_jira_issues(errata_id=errata_id)

        if isinstance(resp, dict) and resp.get("error", False):
            log.info(
                f"Error when querying for Jira issues for advisory {errata_id}: {resp['error']}"
            )
            return False

        mi_pattern = re.compile(r"major\s*incident", re.IGNORECASE)

        for issue in resp:
            if mi_pattern.search(issue["summary"]):
                log.info(f"Found 'major incident' issue for advisory {errata_id}: {issue['key']}")
                return True

        return False

    def has_compliance_priority_jira_label(self, errata_id) -> bool:
        """
        Checks if this erratas has an issue in JIRA with 'compliance_priority' label.

        :param errata_id: The ID of the errata advisory
        :type errata_id: str

        :return: Wether the errata has or not a compliance priority issue in JIRA
        :rtype: bool
        """
        resp = self._get_jira_issues(errata_id=errata_id)

        if isinstance(resp, dict) and resp.get("error", False):
            log.info(
                f"Error when querying for Jira issues for advisory {errata_id}: {resp['error']}"
            )
            return False

        for issue in resp:
            if "compliance-priority" in issue["labels"]:
                log.info(
                    f"Found 'compliance-priority' label in issue {issue['key']} for advisory {errata_id}"
                )
                return True

        return False
