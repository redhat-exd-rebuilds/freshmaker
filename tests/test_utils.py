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

import shutil
import tempfile

from unittest.mock import patch

import pytest

from freshmaker import conf
from freshmaker.models import ArtifactType
from freshmaker.utils import get_rebuilt_nvr, sorted_by_nvr, get_distgit_files
from tests import helpers


@pytest.mark.parametrize("rebuilt_nvr_release_suffix", ("", ".dev"))
@patch("freshmaker.utils.time.time", return_value=1572631468.1807485)
def test_get_rebuilt_nvr(mock_time, rebuilt_nvr_release_suffix):
    nvr = "python-v3.6-201910221723"
    expected = f"{nvr}.1572631468{rebuilt_nvr_release_suffix}"
    with patch.object(conf, "rebuilt_nvr_release_suffix", new=rebuilt_nvr_release_suffix):
        rebuilt_nvr = get_rebuilt_nvr(ArtifactType.IMAGE.value, nvr)
    assert rebuilt_nvr == expected


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


class TestGetDistGitFiles(object):
    """Test get_distgit_files"""

    @classmethod
    def setup_class(cls):
        import os
        import subprocess
        cls.repo_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.repo_dir, 'a.txt'), 'w') as f:
            f.write('hello')
        with open(os.path.join(cls.repo_dir, 'b.txt'), 'w') as f:
            f.write('world')
        git_cmds = [
            ['git', 'init'],
            ['git', 'add', 'a.txt', 'b.txt'],
            ['git', 'config', 'user.name', 'tester'],
            ['git', 'config', 'user.email', 'tester@localhost'],
            ['git', 'commit', '-m', 'initial commit for test'],
        ]
        for cmd in git_cmds:
            subprocess.check_call(cmd, cwd=cls.repo_dir)

        cls.repo_url = 'file://' + cls.repo_dir

    @classmethod
    def teardown_class(cls):
        shutil.rmtree(cls.repo_dir)

    @pytest.mark.parametrize('files,expected', [
        [['a.txt'], {'a.txt': 'hello'}],
        [['a.txt', 'b.txt'], {'a.txt': 'hello', 'b.txt': 'world'}],
    ])
    def test_get_files(self, files, expected):
        result = get_distgit_files(self.repo_url, 'master', files)
        assert expected == result

    @patch('freshmaker.utils._run_command')
    def test_error_path_not_found(self, run_command):
        run_command.side_effect = OSError('path not found')
        result = get_distgit_files(self.repo_url, 'master', ['a.txt'])
        assert {'a.txt': None} == result

    @patch('freshmaker.utils._run_command')
    @patch('time.sleep')
    def test_unhandled_error_occurs(self, sleep, run_command):
        run_command.side_effect = ValueError
        with pytest.raises(ValueError):
            get_distgit_files(self.repo_url, 'master', ['a.txt'])
