## Development scripts

This directory contains useful scripts for Freshmaker development.

It is hard to test Freshmaker end to end locally, because it depends
on lot of other services. To be able to test some parts locally,
we use few scripts stored in this directory.

The scripts are just templates creating instances of particular Freshmaker
classes so they can later be used for testing.

The intended use-case is that when developing some feature, you can test
the feature using these scripts. You should *not* commit the changed script.
