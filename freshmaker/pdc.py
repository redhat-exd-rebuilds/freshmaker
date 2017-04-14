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

import inspect
import requests
from pdc_client import PDCClient

import freshmaker
import freshmaker.utils


def get_client_session(config):
    """
    :param config: instance of freshmaker.config.Config
    :return: pdc_client.PDCClient instance
    """
    if 'ssl_verify' in inspect.getargspec(PDCClient.__init__).args:
        # New API
        return PDCClient(
            server=config.pdc_url,
            develop=config.pdc_develop,
            ssl_verify=not config.pdc_insecure,
        )
    else:
        # Old API
        return PDCClient(
            server=config.pdc_url,
            develop=config.pdc_develop,
            insecure=config.pdc_insecure,
        )


@freshmaker.utils.retry(wait_on=(requests.ConnectTimeout, requests.ConnectionError), logger=freshmaker.log)
def get_modules(pdc_session, name=None, version=None, build_dep_name=None, build_dep_stream=None, active=True):
    """
    :param pdc_session: PDCClient instance
    :return: list of modules
    """
    query = {}
    if name is not None:
        query['variant_name'] = name
    if version is not None:
        query['variant_version'] = version
    if build_dep_name is not None:
        query['build_dep_name'] = build_dep_name
    if build_dep_stream is not None:
        query['build_dep_stream'] = build_dep_stream
    if active:
        query['active'] = 'true'

    modules = pdc_session['unreleasedvariants'](page_size=-1, **query)
    return modules
