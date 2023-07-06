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
# Written by Petr Šabata <contyk@redhat.com>
#            Matt Prahl <mprahl@redhat.com>
#            Jan Kaluza <jkaluza@redhat.com>

import pkg_resources

from logging import getLogger
from typing import Any  # noqa

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

from freshmaker.logger import init_logging, setup_logger
from freshmaker.config import init_config
from freshmaker.proxy import ReverseProxy

try:
    version = pkg_resources.get_distribution('freshmaker').version
except pkg_resources.DistributionNotFound:
    version = 'unknown'

app = Flask(__name__)  # type: Any
app.wsgi_app = ReverseProxy(app.wsgi_app)

conf = init_config(app)

db = SQLAlchemy(app)  # type: Any

init_logging(conf)
setup_logger(conf)
log = getLogger(__name__)

login_manager = LoginManager()
login_manager.init_app(app)

from freshmaker.auth import init_auth  # noqa
init_auth(login_manager, conf.auth_backend)

from freshmaker import views  # noqa

from freshmaker.monitor import db_hook_event_listeners  # noqa
db_hook_event_listeners(target=db.engine)
