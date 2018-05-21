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

import contextlib
import errno
import functools
import getpass
import os
import shutil
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
        log.warn("get_url_for() has been called without the Flask "
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
        # Set release from XX.YY to XX.$timestamp
        parsed_nvr = koji.parse_NVR(nvr)
        r_version = parsed_nvr["release"].split(".")[0]
        release = str(r_version) + "." + str(int(time.time()))
        rebuilt_nvr = "%s-%s-%s" % (parsed_nvr["name"], parsed_nvr["version"],
                                    release)

    return rebuilt_nvr


class krbContext(object):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


def krb_context():
    return krbContext()


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
                if (time.time() - start) >= timeout:
                    raise  # This re-raises the last exception.
                try:
                    return function(*args, **kwargs)
                except wait_on as e:
                    if logger is not None:
                        logger.warn("Exception %r raised from %r.  Retry in %rs",
                                    e, function, interval)
                    time.sleep(interval)
        return inner
    return wrapper


def makedirs(path, mode=0o775):
    try:
        os.makedirs(path, mode=mode)
    except OSError as ex:
        if ex.errno != errno.EEXIST:
            raise


@contextlib.contextmanager
def temp_dir(logger=None, *args, **kwargs):
    """Create a temporary directory and ensure it's deleted."""
    if kwargs.get('dir'):
        # If we are supposed to create the temp dir in a particular location,
        # ensure the location already exists.
        makedirs(kwargs['dir'])
    dir = tempfile.mkdtemp(*args, **kwargs)
    try:
        yield dir
    finally:
        try:
            shutil.rmtree(dir)
        except OSError as exc:
            # Okay, we failed to delete temporary dir.
            if logger:
                logger.warn('Error removing %s: %s', dir, exc.strerror)


def clone_repo(url, dest, branch='master', logger=None, commit=None):
    cmd = ['git', 'clone', '-b', branch, url, dest]
    _run_command(cmd, logger=logger)

    if commit:
        cmd = ['git', 'checkout', commit]
        _run_command(cmd, logger=logger, rundir=dest)

    return dest


def clone_distgit_repo(namespace, name, dest, branch='master', ssh=True,
                       user=None, logger=None, commit=None):
    """clone a git repo"""
    if ssh:
        if user is None:
            if hasattr(conf, 'git_user'):
                user = conf.git_user
            else:
                user = getpass.getuser()
        repo_url = conf.git_ssh_base_url % user
    else:
        repo_url = conf.git_base_url

    repo_url = os.path.join(repo_url, namespace, name)
    return clone_repo(repo_url, dest, branch=branch, logger=logger,
                      commit=commit)


def add_empty_commit(repo, msg="bump", author=None, logger=None):
    """Commit an empty commit to repo"""
    if author is None:
        author = conf.git_author
    cmd = ['git', 'commit', '--allow-empty', '-m', msg, '--author={}'.format(author)]
    _run_command(cmd, logger=logger, rundir=repo)
    return get_commit_hash(repo)


def push_repo(repo, logger=None):
    """Push repo"""
    cmd = ['git', 'push']
    _run_command(cmd, logger=logger, rundir=repo)


def get_commit_hash(repo, branch='master', revision='HEAD', logger=None):
    """Get commit hash from revision"""
    commit_hash = None
    cmd = ['git', 'rev-parse', revision]
    if '://' in repo:
        # this is a remote repo url
        with temp_dir(prefix='freshmaker-%s-' % repo.split('/').pop()) as repodir:
            clone_repo(repo, repodir, branch=branch, logger=logger)
            commit_hash = _run_command(cmd, rundir=repodir, return_output=True).strip()
    else:
        # repo is local dir
        commit_hash = _run_command(cmd, rundir=repo, return_output=True).strip()

    return commit_hash


def bump_distgit_repo(namespace, name, branch='master', user=None, commit_author=None, commit_msg=None, logger=None):
    rev = None
    with temp_dir(prefix='freshmaker-%s-%s-' % (namespace, name)) as repodir:
        try:
            msg = commit_msg or "Bump"
            clone_distgit_repo(namespace, name, repodir, branch=branch, ssh=True, user=user, logger=logger)
            rev = add_empty_commit(repodir, msg=msg, author=commit_author, logger=logger)
            push_repo(repodir, logger=logger)
        except Exception:
            if logger:
                logger.error("Failed to update repo of '%s/%s:%s'.", namespace, name, branch)
            return None
    return rev


def _run_command(command, logger=None, rundir=None, output=subprocess.PIPE, error=subprocess.PIPE, env=None, return_output=False):
    """Run a command, return output if return_output is True. Error out if command exit with non-zero code."""

    if rundir is None:
        rundir = tempfile.gettempdir()

    if logger:
        logger.info("Running %s", subprocess.list2cmdline(command))

    p1 = subprocess.Popen(command, cwd=rundir, stdout=output, stderr=error, universal_newlines=True, env=env,
                          close_fds=True)
    (out, err) = p1.communicate()

    if out and logger:
        logger.debug(out)

    if p1.returncode != 0:
        if logger:
            logger.error("Got an error from %s", command[0])
            logger.error(err)
        raise OSError("Got an error (%d) from %s: %s" % (p1.returncode, command[0], err))
    if return_output:
        return out
