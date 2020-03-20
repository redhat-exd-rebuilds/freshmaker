#!/usr/bin/python3
import subprocess
import shlex

import requests
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--dev', default=False, action='store_true', help="Run the script on the dev")
args = parser.parse_args()
if args.dev:
    url = "https://freshmaker.dev.engineering.redhat.com/api/1/"
else:
    url = "https://freshmaker.engineering.redhat.com/api/1/"

r = requests.get(url + "events/?state=2")
r.raise_for_status()
data = r.json()

# Get errata_id from last successful event
errata_id = data['items'][0]['search_key']

# Check that the deployment was successful:

url_build = url + "builds/"
command = (
        "curl --negotiate -u : -k -X POST -d '{\"errata_id\": %s, \"dry_run\": true}' %s  -l -v"
        % (errata_id, url_build))
subprocess_cmd = shlex.split(command)
stdout = subprocess.run(subprocess_cmd, stdout=subprocess.PIPE).stdout.decode('utf-8')

print(stdout)
