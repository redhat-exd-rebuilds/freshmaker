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

LOG_LEVEL = "DEBUG" if os.environ.get("DEBUG") else "INFO"


def setup_logger(component: str) -> None:
    """
    Set up and configure 'freshmaker' logger.
    """
    logger = logging.getLogger("freshmaker")
    logger.propagate = False
    logger.setLevel(LOG_LEVEL)
    custom_attr = {
        "environment": lambda: os.environ.get("FLASK_ENV"),
        "host": lambda: os.environ.get("KUBERNETES_POD_NAME"),
        "component": lambda: component,
        "sourcetype": lambda: f"freshmaker:{component}",
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
        filename="/var/log/freshmaker.splunk.log",
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=1,
        mode="a",
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s.%(msecs)d] [%(processName)s - %(threadName)s] "
            "[%(levelname)s] %(message)s",
            "%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(console_handler)


def str_to_log_level(level):
    """
    Returns internal representation of logging level defined
    by the string `level`.

    Available levels are: debug, info, warning, error
    """
    if level not in levels:
        return logging.NOTSET

    return levels[level]


def supported_log_backends():
    return ("console", "journal", "file")


def init_logging(conf):
    """
    Initializes logging according to configuration file.
    """
    log_format = '%(levelname)s - %(message)s'
    log_backend = conf.log_backend

    if not log_backend or len(log_backend) == 0 or log_backend == "console":
        logging.basicConfig(level=conf.log_level, format=log_format)
        log = logging.getLogger()
        log.setLevel(conf.log_level)
    elif log_backend == "journal":
        logging.basicConfig(level=conf.log_level, format=log_format)
        try:
            from systemd import journal
        except ImportError:
            raise ValueError("systemd.journal module is not installed")

        log = logging.getLogger()
        log.propagate = False
        log.addHandler(journal.JournalHandler())
    else:
        logging.basicConfig(filename=conf.log_file, level=conf.log_level,
                            format=log_format)
        log = logging.getLogger()
