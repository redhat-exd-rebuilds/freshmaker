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

    def get_latest_modules(self, **kwargs):
        """
        Query PDC with query parameters in kwargs and return a list of modules
        which contains latest modules of each (module_name, module_version).

        :param kwargs: query parameters in keyword arguments, should only provide
                    valid query parameters supported by PDC's module query API.
        :return: a list of modules
        """
        modules = self.get_modules(**kwargs)
        active = kwargs.get('active', 'true')
        latest_modules = []
        for (name, version) in set([(m.get('variant_name'), m.get('variant_version')) for m in modules]):
            mods = self.get_modules(variant_name=name, variant_version=version, active=active)
            latest_modules.append(sorted(mods, key=lambda x: x['variant_release']).pop())
        return list(filter(lambda x: x in latest_modules, modules))

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def get_modules(self, **kwargs):
        """
        Query PDC with specified query parameters and return a list of modules.

        :param kwargs: query parameters in keyword arguments
        :return: a list of modules
        """
        modules = self.session['unreleasedvariants'](page_size=-1, **kwargs)
        return modules

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def find_containers_by_rpm_name(self, rpm_name):
        rels = self.session['release-component-relationships'](type='ContainerIncludesRPM',
                                                               to_component_name=rpm_name)
        return [rel['from_component'] for rel in rels['results']]

    @freshmaker.utils.retry(wait_on=(requests.Timeout, requests.ConnectionError), logger=freshmaker.log)
    def get_release_component_by_id(self, id):
        return self.session['release-components/{}/'.format(id)]()
