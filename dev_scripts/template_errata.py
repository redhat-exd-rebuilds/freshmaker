#!/usr/bin/python3
from __future__ import print_function
import os
import sys
from pprint import pprint

# Allow imports from parent directory.
sys.path.insert(1, os.path.join(sys.path[0], '..'))

# Set the FRESHMAKER_DEVELOPER_ENV variable.
os.environ["FRESHMAKER_DEVELOPER_ENV"] = "1"

from freshmaker.errata import Errata
from freshmaker import conf


if len(sys.argv) != 2:
    print("Template for testing freshmaker.Errata class")
    print("Usage: ./errata.py ERRATA_TOOL_SERVER_URL")
    sys.exit(1)


conf.errata_tool_server_url = sys.argv[1]
errata = Errata()

# Example usage:
data = errata.get_srpm_nvrs(42515)
pprint(data)
