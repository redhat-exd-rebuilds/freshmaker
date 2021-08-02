#!/usr/bin/python3
from __future__ import print_function

import argparse
from datetime import date
import json
import logging
import re
import sys
import requests
from requests_kerberos import HTTPKerberosAuth
from tabulate import tabulate
from freshmaker import conf

from lightblue.service import LightBlueService
from lightblue.entity import LightBlueEntity
from lightblue.query import LightBlueQuery


LB_DATA_URL = 'https://datasvc.periwinkle.corp.redhat.com/rest/data'
LB_META_URL = 'https://datasvc.periwinkle.corp.redhat.com/rest/metadata'
ERRATA_URL = 'https://errata.devel.redhat.com/api/v1/'
FRESHMAKER_URL = 'https://freshmaker.engineering.redhat.com/api/1/'


def get_images_fixing_rhsa(service, start, finish):
    interface = LightBlueEntity(service, 'containerImage')
    advisory_type = 'RHSA'
    query = LightBlueQuery(
        interface,
        ('repositories.*.published', '=', True),
        ('createdBy', '=', 'metaxor'),
        ('creationDate', '$gte', '%sT00:00:00.000-0000' % start),
        ('creationDate', '$lte', '%sT00:00:00.000-0000' % finish),
    )
    query.add_raw_query({
        "field": "repositories.*.content_advisory_ids.*",
        "regex": "%s.*" % advisory_type
    })
    query._add_to_projection('repositories.*.content_advisory_ids.*')
    query._add_to_projection('brew.build')
    return query.find()['processed']


def get_important_critical_ids(service):
    interface = LightBlueEntity(service, 'redHatContainerAdvisory')
    query = {
        "field": "severity",
        "op": "$in",
        "values": ["Important", "Critical"]
    }

    projection = {"field": "_id", "include": True}

    response = interface.find_item(query, projection)

    if not interface.check_response(response):
        logging.warning(response)
        return []
    return set([adv['_id'] for adv in response['processed']])


def group_images_by_content_advisory(images):
    """
    Returns dict with content advisory name as a key and list of images
    containing some RPM from that content_advisory as value.
    """
    ret = {}
    for image in images:
        for advisory in image["repositories"][0]["content_advisory_ids"]:
            if not advisory.startswith("RHSA"):
                continue
            if advisory not in ret:
                ret[advisory] = []
            ret[advisory].append(image["brew"]["build"])
    return ret


def get_image_advisories_from_image_nvrs(grouped_images):
    nvr_to_image_erratum = {}
    krb_auth = HTTPKerberosAuth()

    nvrs_to_check = sum([len(nvrs) for nvrs in grouped_images.values()])
    nvrs_checks = 0
    print("Querying Errata for advisories belonging to %d images:" % nvrs_to_check)
    for nvrs in sorted(grouped_images.values(), key=len, reverse=True):
        for nvr in nvrs:
            nvrs_checks += 1
            if nvr in nvr_to_image_erratum:
                continue

            r = requests.get(ERRATA_URL + "build/" + nvr, auth=krb_auth, timeout=conf.requests_timeout)
            r.raise_for_status()
            data = r.json()
            if not data['all_errata']:
                # Super weird.  This means we have a container that wasn't shipped via an advisory.
                logging.warn("Failed to find errata for %s at %s" % (nvr, r.request.url))
                continue
            errata_id = data["all_errata"][0]["id"]
            errata_name = data["all_errata"][0]["name"]
            nvr_to_image_erratum[nvr] = errata_name

            msg = "[%i/%i]: %s" % (nvrs_checks, nvrs_to_check, errata_name)
            sys.stdout.write(msg + chr(8) * len(msg))
            sys.stdout.flush()
            r = requests.get(ERRATA_URL + "erratum/%s/builds" % (errata_name), auth=krb_auth, timeout=conf.requests_timeout)
            r.raise_for_status()
            data = r.json()
            for builds_dict in data.values():
                for builds_list in builds_dict["builds"]:
                    for next_nvr in builds_list.keys():
                        nvr_to_image_erratum[next_nvr] = [errata_id, errata_name, data.keys()]
    return nvr_to_image_erratum


def is_content_advisory_rebuilt_by_freshmaker(errata_name):
    krb_auth = HTTPKerberosAuth()
    r = requests.get(ERRATA_URL + "erratum/" + errata_name, auth=krb_auth, timeout=conf.requests_timeout)
    r.raise_for_status()
    data = r.json()
    errata_id = str(data["content"]["content"]["errata_id"])

    url = FRESHMAKER_URL + "events/?search_key=%s&per_page=1" % errata_id
    r = requests.get(url, timeout=conf.requests_timeout)
    r.raise_for_status()
    data = r.json()
    if data["meta"]["total"] == 0:
        return ""
    return FRESHMAKER_URL + "events/%d" % (data["items"][0]["id"])


def show_advisories(security_images, freshmaker_images):
    """
    Prints the table with advisories which:
      1) Contains container image not built by Freshmaker and ...
      2) ... contains the RPM from RHSA RPM advisory which trigerred
         Freshmaker's rebuild.
    """
    # At first, group the shipped images by the content_advisory in dict with
    # following format: {"RHSA-foo", ["image-1-2", "image2-1-2", ...], ...}.
    # We will later use this to easily compare "security_images" and
    # "freshmaker_images" by the advisory name.
    freshmaker_advisories = group_images_by_content_advisory(freshmaker_images)
    all_advisories = group_images_by_content_advisory(security_images)

    # For each image (NVR of the image), find out the advisory the image was
    # shipped in.
    nvr_to_image_erratum = get_image_advisories_from_image_nvrs(all_advisories)

    print("Advisories with images *not* built by Freshmaker:")
    advisories = {}
    for content_advisory, nvrs in all_advisories.items():
        non_freshmaker_nvrs = []
        if content_advisory in freshmaker_advisories:
            # In case Freshmaker rebuilt some images as a result of this
            # content advisory, filter them out to keep only those images
            # which have not been rebuilt by Freshmaker.
            non_freshmaker_nvrs = [
                nvr for nvr in nvrs
                if nvr not in freshmaker_advisories[content_advisory]]
        else:
            # In case Freshmaker did not rebuild this advisory at all, keep
            # all the NVRs in the list.
            non_freshmaker_nvrs = nvrs

        # For each image (nvr) not built by Freshmaker, get the info about
        # advisory it was included in and add it to `advisories`.
        for nvr in non_freshmaker_nvrs:
            if nvr not in nvr_to_image_erratum:
                continue
            errata_id, errata_name, products = nvr_to_image_erratum[nvr]
            if errata_name not in advisories:
                freshmaker_url = is_content_advisory_rebuilt_by_freshmaker(
                    content_advisory)
                advisories[errata_name] = {
                    "nvrs": [], "freshmaker_url": freshmaker_url,
                    "errata_id": errata_id, "products": products}
            advisories[errata_name]["nvrs"].append(nvr)

    # Print the table
    table = [["Name", "Errata URL", "Freshmaker URL", "Products"]]
    for advisory, data in advisories.items():
        table.append([
            advisory,
            "https://errata.devel.redhat.com/advisory/" + str(data["errata_id"]),
            str(data["freshmaker_url"]), data["products"]])
    print(tabulate(sorted(table, key=lambda x: x[0]), headers="firstrow"))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("FROM", help="Date to start report from (YYYYMMDD)")
    parser.add_argument("-T", "--to", help="Date to end report at (YYYYMMDD)",
                        default=date.today().strftime("%Y%m%d"))
    parser.add_argument("-c", "--lb-cert", help="Path to lightblue cert")
    parser.add_argument("-A", "--all", help="Include all RHSA in report "
                        "(not just important/critical", action='store_true',
                        default=False)
    parser.add_argument("-d", "--debug", help="Debugging info",
                        action='store_true', default=False)
    parser.add_argument("-s", "--show-advisories",
                        help="Show list of advisories together with stats",
                        action='store_true', default=False)

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if not args.lb_cert:
        print("Cannot run:\n    --lb-cert is required.", file=sys.stderr)
        sys.exit(1)

    start = args.FROM
    finish = args.to

    service = LightBlueService(LB_DATA_URL, LB_META_URL, args.lb_cert)

    # mx = Metaxor()
    # lb_advisory = mx.lb_container_advisory

    images = get_images_fixing_rhsa(service, start, finish)
    security_images = images
    if not args.all:
        # filter only important/critical
        important_ids = get_important_critical_ids(service)
        if not important_ids:
            logging.error("Failed getting important/critical RHSA IDs")
            sys.exit(1)
        security_images = []
        for image in images:
            if image in security_images:
                continue
            for repo in image['repositories']:
                ids = set(repo['content_advisory_ids'])
                if ids.intersection(important_ids):
                    security_images.append(image)
                    break

    freshmaker_images = []
    for image in security_images:
        if re.match(r'.*\d{10}$', image['brew']['build']):
            freshmaker_images.append(image)

    logging.debug("All shipped containers with security fixes: ")
    logging.debug(json.dumps(security_images, indent=4))
    logging.debug("Shipped Freshmaker builds: ")
    logging.debug(json.dumps(freshmaker_images, indent=4))

    if args.show_advisories:
        show_advisories(security_images, freshmaker_images)

    print("Total security builds: %d" % len(security_images), file=sys.stderr)
    print("Freshmaker rebuilds: %d" % len(freshmaker_images), file=sys.stderr)
    # for image in freshmaker_images:
    #     import pprint; pprint.pprint(image)
    percent = (len(freshmaker_images) / float(len(security_images))) * 100.0
    print(percent)
