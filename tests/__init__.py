# -*- coding: utf-8 -*-
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

from os import path
import json
from freshmaker import app


def get_fedmsg(name):
    this_path = path.abspath(path.dirname(__file__))
    fedmsg_path = path.join(this_path, "fedmsgs", name)

    with open(fedmsg_path, 'r') as f:
        return {'body': json.load(f)}


# There is no Flask app-context in the tests and we need some,
# because models.Event.json() and models.ArtifactBuild.json() uses
# flask.url_for, which needs app_context to generate the URL.
# We also cannot generate Flask context on the fly each time in the
# mentioned json() calls, because each generation of Flask context
# changes db.session and unfortunatelly does not give it to original
# state which might be Flask bug, so the only safe way on backend is
app_context = app.app_context()
# We do not care about __exit__ in a tests, because the app_context is
# just use during the whole test-suite run.
app_context.__enter__()
