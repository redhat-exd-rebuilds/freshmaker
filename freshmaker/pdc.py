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
import concurrent.futures
from itertools import groupby
from pdc_client import PDCClient
import freshmaker.utils


class PDC(object):
    def __init__(self, config):
        # pdc_url, pdc_develop and pdc_insecure should be avaiable in config
        self.config = config
        self.session = self.get_client_session()

    def get_client_session(self):
        """
        Return pdc_client.PDCClient instance
        """
        if 'ssl_verify' in inspect.getargspec(PDCClient.__init__).args:
            # New API
            return PDCClient(
                server=self.config.pdc_url,
                develop=self.config.pdc_develop,
                ssl_verify=not self.config.pdc_insecure,
            )
        else:
            # Old API
            return PDCClient(
                server=self.config.pdc_url,
                develop=self.config.pdc_develop,
                insecure=self.config.pdc_insecure,
            )

    def is_latest_module(self, module):
        """Check if given module is the latest one in the name:stream in PDC"""
        data = self.get_modules(
            name=module['name'],
            stream=module['stream'],
            fields='version',
            ordering='-version',
            page_size=1)
        return data['results'][0]['version'] == module['version']

    def get_latest_modules(self, **criteria):
        criteria.update({
            'fields': ['uid', 'name', 'stream', 'version'],
            'ordering': 'name,stream,-version',
        })
        modules = self.get_modules(**criteria)

        def _return_module_if_latest(module):
            return module if self.is_latest_module(module) else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(_return_module_if_latest,
                                list(stream_modules)[0])
                for name_stream, stream_modules in groupby(
                    modules, key=lambda m: '%(name)s:%(stream)s' % m)
            ]
            concurrent.futures.wait(futures)

        return [m for m in (f.result() for f in futures) if m]

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def get_modules(self, **kwargs):
        """
        Query PDC with specified query parameters and return a list of modules.

        :param kwargs: query parameters in keyword arguments
        :return: a list of modules
        """
        page_size = kwargs.pop('page_size', -1)
        modules = self.session['modules'](page_size=page_size, **kwargs)
        return modules

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def find_containers_by_rpm_name(self, rpm_name):
        rels = self.session['release-component-relationships'](type='ContainerIncludesRPM',
                                                               to_component_name=rpm_name)
        return [rel['from_component'] for rel in rels['results']]

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def get_release_component_by_id(self, id):
        return self.session['release-components/{}/'.format(id)]()
