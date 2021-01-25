===================
Development scripts
===================

The dev_scripts_ directory contains few useful scripts which can be used to debug Freshmaker locally.

.. _dev_scripts: https://github.com/redhat-exd-rebuilds/freshmaker/tree/master/dev_scripts


General configuration
=====================

The scripts are configured using the ``config.py`` configuration file. Before you execute any of the development scripts for the first time, you need to create your own ``config.py`` by renaming the ``config.py.template`` and editting the ``EDIT FOLLOWING OPTIONS BASED ON YOUR ENVIRONMENT`` section.


``find_images_to_rebuild.py``
=============================

This script executes the ``RebuildImagesOnRPMAdvisoryChange`` handler which is responsible for rebuilding container images as a result of RPM RHSA release. This is the main work done by Freshmaker running in the infrastructure.

Usage: ``./find_images_to_rebuild.py <errata_advisory_id>``

The script queries Errata Tool, Pulp and Lightblue database to find out the list of container images which would be rebuilt by Freshmaker as a result of this RPM RHSA. It prints the list of container images and also initial set of image builds as submitted to Koji.

It also creates ``freshmaker.db`` which contains the Event and Artifact builds as they would be created in real infrastructure.
