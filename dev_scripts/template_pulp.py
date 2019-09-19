#!/usr/bin/python3
from __future__ import print_function
import os
import sys
from pprint import pprint

# Allow imports from parent directory.
sys.path.insert(1, os.path.join(sys.path[0], '..'))

# Set the FRESHMAKER_DEVELOPER_ENV variable.
os.environ["FRESHMAKER_DEVELOPER_ENV"] = "1"

from freshmaker.pulp import Pulp


if len(sys.argv) != 4:
    print("Template for testing freshmaker.Pulp class")
    print("Usage: ./pulp.py PULP_SERVER_URL PULP_USERNAME PULP_PASSWORD")
    sys.exit(1)


pulp = Pulp(sys.argv[1], sys.argv[2], sys.argv[3])


repo_ids = [
    "rhel-7-server-release-e2e-test-1-rpms__x86_64"
]
pprint(pulp.get_content_set_by_repo_ids(repo_ids))
