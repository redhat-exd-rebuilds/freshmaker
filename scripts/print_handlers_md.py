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
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
#
# Prints all the available handlers and their dependencies on other services
# in Markdown format.
# It is intended to be called from the top-level Freshmaker git repository.
#

from __future__ import print_function
import os
import sys

# Set the PYTHON_PATH to top level Freshmaker directory and also set
# the FRESHMAKER_DEVELOPER_ENV to 1.
sys.path.append(os.getcwd())
os.environ["FRESHMAKER_DEVELOPER_ENV"] = "1"


def load_module(mod_name):
    """ Take a string of the form 'fedmsg.consumers.ircbot'
    and return the ircbot module.
    """
    __import__(mod_name)

    try:
        return sys.modules[mod_name]
    except AttributeError:
        raise ImportError("%r not found" % (mod_name))


# Key is the name of handler, value is list of dependencies.
handlers = {}

# Iterate over all directories in the ./freshmaker/handlers directory
# and in each of them, try to find out handlers.
handlers_path = "./freshmaker/handlers/"
for name in os.listdir(handlers_path):
    if not os.path.isdir(handlers_path + name) or name in ["__pycache__"]:
        continue
    mod = load_module("freshmaker.handlers." + name)
    for submod_name in dir(mod):
        try:
            submod = getattr(mod, submod_name)
        except AttributeError:
            continue
        key = None
        deps = []
        for cls in dir(submod):
            if cls.endswith("Handler"):
                key = "freshmaker.handlers." + name + ":" + cls
            elif cls in ["Pulp", "Errata", "LightBlue"]:
                deps.append(cls)
            elif cls == "koji_service":
                deps.append("Koji")

        if key:
            handlers[key] = deps

print("## List of Freshmaker handlers")
print("")
print("Following is the list of all available HANDLERS:")
print("")

for name, deps in handlers.items():
    print("* `%s`" % name)
    if deps:
        print("  * Depends on: %s" % (", ".join(deps)))
