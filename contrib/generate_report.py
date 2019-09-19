#!/usr/bin/python3
from __future__ import print_function

import argparse
import requests
from requests_kerberos import HTTPKerberosAuth

TEMPLATE = """
On {freshmaker_date}, Freshmaker rebuilt {original_nvr} container image [1] as a result of Important/Critical RHSA advisory [2].

It seems the maintainer of this image did not use the Freshmaker's build, but instead built and shipped the new image [3] himself on {container_advisory_date}.

Was there any reason why you haven't used the Freshmaker's build? We think that by using the Freshmaker's build, you could save the time needed for rebuild and also provide the fixed image faster.

This ticket is created mainly for us to find out if there was any issue you hit with Freshmaker which prevented you to use the mentioned build and also reminder for you that Freshmaker is building the images with fixed security issues automatically for you.

[1] {freshmaker_brew_build}
[2] {rhsa_advisory}
[3] {container_advisory}

"""


ERRATA_URL = 'https://errata.devel.redhat.com/api/v1/'
FRESHMAKER_URL = 'https://freshmaker.engineering.redhat.com/api/1/'


def get_advisory(errata_id):
    krb_auth = HTTPKerberosAuth()
    r = requests.get(ERRATA_URL + "erratum/%s" % str(errata_id), auth=krb_auth)
    r.raise_for_status()
    data = r.json()
    return data["errata"].values()[0]


def get_freshmaker_build(search_key, original_nvr):
    url = FRESHMAKER_URL + "events/?search_key=%s" % search_key
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
    for build in data["items"][0]["builds"]:
        if build["original_nvr"].startswith(original_nvr):
            return data["items"][0], build
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("SEARCH_KEY", help="Freshmaker's search_key")
    parser.add_argument("ORIGINAL_NVR", help="Freshmaker's original_nvr")
    parser.add_argument("CONTAINER_ADVISORY", help="Advisory with shipped non-freshmaker build")
    args = parser.parse_args()

    search_key = args.SEARCH_KEY
    original_nvr = args.ORIGINAL_NVR
    container_advisory = args.CONTAINER_ADVISORY
    event, build = get_freshmaker_build(search_key, original_nvr)
    errata = get_advisory(container_advisory)

    template_data = {
        "freshmaker_date": build["time_completed"].split("T")[0],
        "original_nvr": build["original_nvr"],
        "freshmaker_brew_build": "https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=%d" % build["build_id"],
        "rhsa_advisory": "https://errata.devel.redhat.com/advisory/%s" % event["search_key"],
        "container_advisory": "https://errata.devel.redhat.com/advisory/%s" % container_advisory,
        "container_advisory_date": errata["issue_date"].split("T")[0],
    }
    print(TEMPLATE.format(**template_data))
