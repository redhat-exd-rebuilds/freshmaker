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


### find_images_to_rebuild

This script can be used to find images to rebuild by an Errata ID Event. The argument 
`--container-image` can be used to provide the NVRs of images to rebuild. If not specified, all 
images will be rebuilt that are affected by the advisory. The `--cassette-path` argument can be set 
to the path of a vcrpy cassette downloaded from a deployed Freshmaker instance. This will use the 
recorded Lightblue queries instead of querying Lightblue directly.
 
 Example usage:
 
 ```bash
python3 find_images_to_rebuild.py 53137
  ```
 ```bash
python3 find_images_to_rebuild.py 53137 --cassette-path ~/vcr_test/fixtures/cassettes/1.yml
 ```
