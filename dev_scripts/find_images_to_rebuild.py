#!/usr/bin/env python
from __future__ import print_function
import os
import sys
from pprint import pprint
from unittest.mock import patch
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
from freshmaker.events import (
    ErrataAdvisoryStateChangedEvent, ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange

fedmsg_config = fedmsg.config.load_config()
dictConfig(fedmsg_config.get('logging', {'version': 1}))

if len(sys.argv) < 2:
    print("Queries Lightblue to find out all the images Freshmaker rebuilds.")
    print("Usage: ./lightblue.py ERRATA_ID [[CONTAINER_IMAGE], ...]")
    sys.exit(1)

container_images = sys.argv[2:]

app_context = app.app_context()
app_context.__enter__()

db.drop_all()
db.create_all()
db.session.commit()

errata = Errata()
kwargs = {}
if container_images:
    EventClass = ManualRebuildWithAdvisoryEvent
    kwargs['container_images'] = container_images
else:
    EventClass = ErrataAdvisoryStateChangedEvent
event = EventClass(
    "fake_message", ErrataAdvisory.from_advisory_id(errata, sys.argv[1]),
    dry_run=True, **kwargs)

handler = RebuildImagesOnRPMAdvisoryChange()
with patch("freshmaker.consumer.get_global_consumer"):
    handler.handle(event)
