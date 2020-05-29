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


Other
=====

* ``rebuilt_nvr_release_suffix`` - a suffix to add to the ``rebuilt_nvr``
  release in addition to the timestamp. This defaults to an empty string.

* vcrpy - use this library for recording the Lightblue queries per
  Freshmaker event. The importing of vcrpy and the recording of Lightblue queries is performed if
  the vcrpy configuration variables (``vcrpy_path`` and ``vcrpy_mode``) are set in
  ``freshmaker/config.py``
