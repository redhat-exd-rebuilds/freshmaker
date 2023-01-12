=============
Configuration
=============

Freshmaker uses the configuration file located at
``/etc/freshmaker/config.py``. This is based on ``conf/config.py``, and many
default values are inherited from ``freshmaker/config.py``. If the
configuration you are interested in is not documented here, check both of those
files.


Permissions
===========

Freshmaker permissions are defined by using a dictionary, where the keys
are role names, and the values are dictionaries that have the keys ``groups``
and ``users``. If defined, these keys must have lists as values. If a role is
not defined, these values will default to empty lists.

The following is an example of this:

.. sourcecode:: python

    PERMISSIONS = {
        'admin': {
            'groups': ['fresmaker-admins'],
            'users': ['tom_hanks'],
        },
        'manual_rebuilder': {
            'groups': ['freshmaker-users'],
        },
    }

EUS images
==========
EUS (Extended Update Support) base images are handled a little bit differently than
standard container images. Mainly because its repository is unpublished and
Freshmaker usually rebuilds images from published repositories. Since those images
still need to be rebuilt there is
``UNPUBLISHED_EXCEPTIONS`` parameter in the configuration which allows you to add
**registry** and **repository** pairs that determine unpublished container repositories.
And if an image is published in one of these repositories it will be rebuilt
too.

With all the above said, if you want your EUS base images or any other image from
unpublished repositories to be rebuilt by Freshmaker alongside published repositories,
you should add **registry** and **repository** entries to the ``UNPUBLISHED_EXCEPTIONS``
configuration:

.. sourcecode:: python

    UNPUBLISHED_EXCEPTIONS = [
            {"registry": "your_registry", "repository": "your_registry"}
    ]

Other
=====

* ``rebuilt_nvr_release_suffix`` - a suffix to add to the ``rebuilt_nvr``
  release in addition to the timestamp. This defaults to an empty string.
