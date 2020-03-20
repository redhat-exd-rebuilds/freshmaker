## Development scripts

This directory contains useful scripts for Freshmaker development.

It is hard to test Freshmaker end to end locally, because it depends
on lot of other services. To be able to test some parts locally,
we use few scripts stored in this directory.

The scripts with "template_" prefix are just templates creating instances
of particular Freshmaker classes so they can later be used for testing.

## Running the scripts


### dry_mode_build_errata_id

This script can be useful to try a build in dry_run mode after a complete deployment, to manually 
test if the deployment was successful. It automatically selects, from the latest successful event, 
the errata_id and it submits a build in dry_run mode.

``REQUESTS_CA_BUNDLE`` should be passed in `python3` to avoid SSL errors. Example usage:
       
    REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt python3 dev_scripts/dry_mode_build_errata_id.py

By default, the script is executed on prod. To execute the script on dev the parameter `--dev` 
should be added.
