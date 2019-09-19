#!/usr/bin/python3
from __future__ import print_function
import os
import sys
from pprint import pprint

# Allow imports from parent directory.
sys.path.insert(1, os.path.join(sys.path[0], '..'))

# Set the FRESHMAKER_DEVELOPER_ENV variable.
os.environ["FRESHMAKER_DEVELOPER_ENV"] = "1"

from freshmaker.lightblue import LightBlue


if len(sys.argv) != 4:
    print("Template for testing freshmaker.Lightblue class")
    print("Usage: ./lightblue.py LB_SERVER_URL PATH_TO_LB_CLIENT_CERT "
          "PATH_TO_LB_CLIENT_KEY")
    sys.exit(1)


lb = LightBlue(sys.argv[1], sys.argv[2], sys.argv[3], False)


def example_image_request(lb):
    query = {
        "objectType": "containerImage",
        "query": {
            "$and": [
                {
                    "field": "repositories.*.tags.*.name",
                    "op": "=",
                    "rvalue": "latest"
                },
                {
                    "field": "brew.build",
                    "op": "=",
                    "rvalue": "s2i-core-container-1-66"
                },
                {
                    "field": "parsed_data.files.*.key",
                    "op": "=",
                    "rvalue": "buildfile"
                }
            ]
        },
        "projection": lb._get_default_projection(include_rpms=False)
    }
    images = lb.find_container_images(query)
    pprint(images)


def example_repository_request(lb):
    # Get all the latest container images containing "httpd"
    query = {
        "objectType": "containerRepository",
        "query": {
            "$and": [
                {
                    "field": "images.*.brew.build",
                    "op": "=",
                    "rvalue": "s2i-core-container-1-66"
                },

            ]
        },
        "projection": [
            {"field": "repository", "include": True},
        ]
    }
    repositories = lb.find_container_repositories(query)
    pprint(repositories)


example_image_request(lb)
example_repository_request(lb)
