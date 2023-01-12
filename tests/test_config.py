# Copyright (c) 2018  Red Hat, Inc.
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
# Written by Jan Kaluza <jkaluza@redhat.com>

import os
import threading

import pytest

from freshmaker import conf
from tests import helpers


class TestConfig(helpers.FreshmakerTestCase):

    def test_krb_auth_ccache_file(self):
        self.assertEqual(
            conf.krb_auth_ccache_file,
            "freshmaker_cc_%s_%s" % (os.getpid(),
                                     threading.current_thread().ident))


@pytest.mark.parametrize('value', (
    'not a dict',
    {'admin': 'not a dict'},
    {'admin': {'groups': 'not a list'}},
    {'admin': {'users': 'not a list'}},
    {'admin': {'invalid key': []}},
    {'admin': {'groups': [1]}},
))
def test_permissions(value):
    with pytest.raises(ValueError, match='The permissions configuration must be a dictionary'):
        conf.permissions = value
