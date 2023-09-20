# Copyright (c) 2016  Red Hat, Inc.
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

from unittest.mock import patch

import pytest

from freshmaker import conf
from freshmaker.models import ArtifactType
from freshmaker.utils import get_rebuilt_nvr, sorted_by_nvr, is_valid_ocp_versions_range
from tests import helpers


@pytest.mark.parametrize("rebuilt_nvr_release_suffix", ("", ".dev"))
@patch("freshmaker.utils.time.time", return_value=1572631468.1807485)
def test_get_rebuilt_nvr(mock_time, rebuilt_nvr_release_suffix):
    nvr = "python-v3.6-201910221723"
    expected = f"{nvr}.1572631468{rebuilt_nvr_release_suffix}"
    with patch.object(conf, "rebuilt_nvr_release_suffix", new=rebuilt_nvr_release_suffix):
        rebuilt_nvr = get_rebuilt_nvr(ArtifactType.IMAGE.value, nvr)
    assert rebuilt_nvr == expected


def test_is_valid_ocp_versions_range():
    assert is_valid_ocp_versions_range("v4.8")
    assert is_valid_ocp_versions_range("=v4.8")
    assert is_valid_ocp_versions_range("v4.7-v4.8")
    assert is_valid_ocp_versions_range("v4.5,v4.6")
    assert is_valid_ocp_versions_range("v4.6,v4.5")
    assert is_valid_ocp_versions_range("v4.5, v4.6")
    assert not is_valid_ocp_versions_range("v4.7,v4.8")


class TestSortedByNVR(helpers.FreshmakerTestCase):
    def test_simple_list(self):
        lst = ["foo-1-10", "foo-1-2", "foo-1-1"]
        expected = ["foo-1-1", "foo-1-2", "foo-1-10"]
        ret = sorted_by_nvr(lst)
        self.assertEqual(ret, expected)

    def test_simple_list_reverse(self):
        lst = ["foo-1-1", "foo-1-2", "foo-1-10"]
        expected = ["foo-1-10", "foo-1-2", "foo-1-1"]
        ret = sorted_by_nvr(lst, reverse=True)
        self.assertEqual(ret, expected)

    def test_get_nvr(self):
        lst = [{"nvr": "foo-1-10"}, {"nvr": "foo-1-2"}, {"nvr": "foo-1-1"}]
        expected = [{"nvr": "foo-1-1"}, {"nvr": "foo-1-2"}, {"nvr": "foo-1-10"}]
        ret = sorted_by_nvr(lst, lambda x: x["nvr"])
        self.assertEqual(ret, expected)

    def test_names_not_equal(self):
        lst = ["foo-1-10", "bar-1-2", "foo-1-1"]
        expected = ["bar-1-2", "foo-1-1", "foo-1-10"]
        ret = sorted_by_nvr(lst)
        self.assertEqual(ret, expected)

    def test_names_not_equal_reverse(self):
        lst = ["foo-1-10", "bar-1-2", "foo-1-1"]
        expected = ["bar-1-2", "foo-1-1", "foo-1-10"]
        ret = sorted_by_nvr(lst, reverse=True)
        self.assertEqual(ret, list(reversed(expected)))
