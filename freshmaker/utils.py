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

import functools
import requests
import subprocess
import sys
import tempfile
import time
import koji
import kobo.rpmlib

from freshmaker import conf, app, log
from freshmaker.types import ArtifactType
from flask import has_app_context, url_for


def _cmp(a, b):
    """
    Replacement for cmp() in Python 3.
    """
    return (a > b) - (a < b)


def sorted_by_nvr(lst, get_nvr=None, reverse=False):
    """
    Sorts the list `lst` containing NVR by the NVRs.

    :param list lst: List with NVRs to sort.
    :param fnc get_nvr: Function taking the item from a list and returning
        the NVR. If None, the item from `lst` is expected to be NVR string.
    :param bool reverse: When True, the result of sorting is reversed.
    :rtype: list
    :return: Sorted `lst`.
    """
    def _compare_items(item1, item2):
        if get_nvr:
            nvr1 = get_nvr(item1)
            nvr2 = get_nvr(item2)
        elif hasattr(item1, 'nvr') and hasattr(item2, 'nvr'):
            nvr1 = item1.nvr
            nvr2 = item2.nvr
        else:
            nvr1 = item1
            nvr2 = item2

        nvr1_dict = kobo.rpmlib.parse_nvr(nvr1)
        nvr2_dict = kobo.rpmlib.parse_nvr(nvr2)
        if nvr1_dict["name"] != nvr2_dict["name"]:
            return _cmp(nvr1_dict["name"], nvr2_dict["name"])
        return kobo.rpmlib.compare_nvr(nvr1_dict, nvr2_dict)

    return sorted(
        lst, key=functools.cmp_to_key(_compare_items), reverse=reverse)


def get_url_for(*args, **kwargs):
    """
    flask.url_for wrapper which creates the app_context on-the-fly.
    """
    if has_app_context():
        return url_for(*args, **kwargs)

    # Localhost is right URL only when the scheduler runs on the same
    # system as the web views.
    app.config['SERVER_NAME'] = 'localhost'
    with app.app_context():
        log.warning("get_url_for() has been called without the Flask "
                    "app_context. That can lead to SQLAlchemy errors caused by "
                    "multiple session being used in the same time.")
        return url_for(*args, **kwargs)


def get_rebuilt_nvr(artifact_type, nvr):
    """
    Returns the new NVR of artifact which should be used when rebuilding
    the artifact.

    :param ArtifactType artifact_type: Type of the rebuilt artifact.
    :param str nvr: Original NVR of artifact.

    :rtype: str
    :return: newly generated NVR
    """
    rebuilt_nvr = None
    if artifact_type == ArtifactType.IMAGE.value:
        # Set release from XX.YY to XX.$timestamp$release_suffix
        parsed_nvr = koji.parse_NVR(nvr)
        r_version = parsed_nvr["release"].split(".")[0]
        release = f"{r_version}.{int(time.time())}{conf.rebuilt_nvr_release_suffix}"
        rebuilt_nvr = "%s-%s-%s" % (parsed_nvr["name"], parsed_nvr["version"],
                                    release)

    return rebuilt_nvr


def load_class(location):
    """ Take a string of the form 'fedmsg.consumers.ircbot:IRCBotConsumer'
    and return the IRCBotConsumer class.
    """
    try:
        mod_name, cls_name = location.strip().split(':')
    except ValueError:
        raise ImportError('Invalid import path.')

    __import__(mod_name)

    try:
        return getattr(sys.modules[mod_name], cls_name)
    except AttributeError:
        raise ImportError("%r not found in %r" % (cls_name, mod_name))


def load_classes(import_paths):
    """Load classes from given paths"""
    return [load_class(import_path) for import_path in import_paths]


def retry(timeout=conf.net_timeout, interval=conf.net_retry_interval, wait_on=Exception, logger=None):
    """A decorator that allows to retry a section of code until success or timeout."""
    def wrapper(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            start = time.time()
            while True:
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    if time.time() - start >= timeout:
                        if logger is not None:
                            logger.exception(
                                "The timeout of %d seconds was exceeded after one or more retry "
                                "attempts",
                                timeout,
                            )
                        raise
                    if logger is not None:
                        logger.warning("Exception %r raised from %r.  Retry in %rs",
                                       e, function, interval)
                    time.sleep(interval)
        return inner
    return wrapper


def _run_command(command, logger=None, rundir=None, output=subprocess.PIPE, error=subprocess.PIPE, env=None,
                 log_output=True):
    """Run a command, return output. Error out if command exit with non-zero code."""

    if rundir is None:
        rundir = tempfile.gettempdir()

    if logger:
        logger.info("Running %s", subprocess.list2cmdline(command))

    p1 = subprocess.Popen(command, cwd=rundir, stdout=output, stderr=error, universal_newlines=True, env=env,
                          close_fds=True)
    (out, err) = p1.communicate()

    if out and logger and log_output:
        logger.debug(out)

    if p1.returncode != 0:
        if logger:
            logger.error("Got an error from %s", command[0])
            logger.error(err)
        raise OSError("Got an error (%d) from %s: %s" % (p1.returncode, command[0], err))

    return out


def is_pkg_modular(nvr):
    """ Returns True if the package is modular, False otherwise. """
    return "module+" in nvr


def get_ocp_release_date(ocp_version):
    """ Get the OpenShift version release date via the Product Pages API

    :param str ocp_version: the OpenShift version
    :return: None or date in format of "%Y-%m-%d", example: 2021-02-23.
    :rtype: str or None
    """
    if not conf.product_pages_api_url:
        raise RuntimeError("Product Pages API url is not set in config")

    ocp_release = f"openshift-{ocp_version}"

    url = f"{conf.product_pages_api_url.rstrip('/')}/releases/{ocp_release}/schedule-tasks"
    resp = requests.get(
        url,
        params={"name": "GA", "fields": "name,date_finish"},
        timeout=conf.net_timeout,
    )

    if resp.status_code == 404:
        log.warning(f"GA date of {ocp_release} is not found via {resp.url}: {resp.reason}")
        return None
    if not resp.ok:
        resp.raise_for_status()
    return resp.json()[0]['date_finish']


def is_in_unpublished_exceptions(image):
    """
    Check if image is published in one of the repositories that is in
    'unpublished_exceptions' configuration list.

    :param ContainerImage image: image that should be checked
    :return: True if image is published in 'exceptions' repository, False otherwise
    """
    repo_reg_pairs = {
        (image_repo["repository"], image_repo["registry"])
        for image_repo in image["repositories"]
    }
    return any(
        (exception["repository"], exception["registry"]) in repo_reg_pairs
        for exception in conf.unpublished_exceptions
    )
