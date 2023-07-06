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
# Written by Jan Kaluza <jkaluza@redhat.com>

"""
Logging functions.

At the beginning of the Freshmaker flow, init_logging(conf) must be called.

After that, logging from any module is possible using Python's "logging"
module as showed at
<https://docs.python.org/3/howto/logging.html#logging-basic-tutorial>.

Examples:

import logging

logging.debug("Phasers are set to stun.")
logging.info("%s tried to build something", username)
logging.warning("%s failed to build", task_id)

"""

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from jsonformatter import JsonFormatter

levels = {
    "debug": logging.DEBUG,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
}

DEV_ENV = os.environ.get("FRESHMAKER_TESTING_ENV") == "1"
LOG_DIR = "." if DEV_ENV else "/var/log/freshmaker"


def setup_logger(conf):
    """
    Set up and configure 'freshmaker' logger.
    """
    logger = logging.getLogger("freshmaker")
    logger.propagate = False
    logger.setLevel(conf.log_level)
    source = "freshmaker"
    custom_attr = {
        "environment": lambda: os.environ.get("FRESHMAKER_ENV"),
        "host": lambda: os.environ.get("HOSTNAME"),
        "sourcetype": lambda: f"{source}",
    }
    file_format = """{
        "environment":     "environment",
        "host":            "host",
        "sourcetype":      "sourcetype",
        "name":            "name",
        "levelno":         "levelno",
        "levelname":       "levelname",
        "pathname":        "pathname",
        "filename":        "filename",
        "module":          "module",
        "lineno":          "lineno",
        "funcname":        "funcName",
        "created":         "created",
        "asctime":         "asctime",
        "msecs":           "msecs",
        "relativeCreated": "relativeCreated",
        "thread":          "thread",
        "threadName":      "threadName",
        "process":         "process",
        "message":         "message"
    }"""
    file_formatter = JsonFormatter(
        file_format, ensure_ascii=False, record_custom_attrs=custom_attr, mix_extra=True
    )
    file_handler = RotatingFileHandler(
        filename=os.path.join(LOG_DIR, "freshmaker.splunk.log"),
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=1,
        mode="a",
    )
    file_handler.setLevel(conf.log_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)


def str_to_log_level(level):
    """
    Returns internal representation of logging level defined
    by the string `level`.

    Available levels are: debug, info, warning, error
    """
    if level not in levels:
        return logging.NOTSET

    return levels[level]


def init_logging(conf):
    """
    Initializes logging according to configuration file.
    """
    log = logging.getLogger()

    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)d] [%(processName)s - %(threadName)s] [%(levelname)s] %(message)s",
        "%Y-%m-%dT%H:%M:%S",
    )
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(conf.log_level)
    console_handler.setFormatter(formatter)
    # explicitly add a handler to root logger to avoid duplicated log lines:
    # if the root logger does not have a handler, a call to logging.basicConfig() or
    # logging.debug/warning/error/... will create and attach one, and if we set another handler
    # to the console, we will have duplicated log lines
    log.addHandler(console_handler)
