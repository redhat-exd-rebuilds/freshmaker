#!/usr/bin/env python
from __future__ import print_function
import os
import sys
from pprint import pprint
from mock import patch
from logging.config import dictConfig
import fedmsg.config

# Allow imports from parent directory.
sys.path.insert(1, os.path.join(sys.path[0], '..'))

# Set the FRESHMAKER_DEVELOPER_ENV variable.
os.environ["FRESHMAKER_DEVELOPER_ENV"] = "1"
os.environ["FRESHMAKER_CONFIG_FILE"] = os.path.join(sys.path[0], "config.py")
os.environ["REQUESTS_CA_BUNDLE"] = "/etc/ssl/certs/ca-bundle.crt"

from freshmaker import db, app
from freshmaker.errata import Errata, ErrataAdvisory
from freshmaker.events import ErrataAdvisoryStateChangedEvent
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange

fedmsg_config = fedmsg.config.load_config()
dictConfig(fedmsg_config.get('logging', {'version': 1}))

if len(sys.argv) != 2:
    print("Queries Lightblue to find out all the images Freshmaker rebuilds.")
    print("Usage: ./lightblue.py ERRATA_ID")
    sys.exit(1)

app_context = app.app_context()
app_context.__enter__()

for i in range(10):
    db.drop_all()
    db.create_all()
    db.session.commit()

    errata = Errata()
    event = ErrataAdvisoryStateChangedEvent(
        "fake_message", ErrataAdvisory.from_advisory_id(errata, sys.argv[1]),
        dry_run=True)

    handler = RebuildImagesOnRPMAdvisoryChange()
    with patch("freshmaker.consumer.get_global_consumer"):
        handler.handle(event)
