#!/usr/bin/env python
from __future__ import print_function
import os
import sys
import argparse
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

from freshmaker import db, app, conf
from freshmaker.errata import Errata, ErrataAdvisory
from freshmaker.events import (
    ErrataAdvisoryStateChangedEvent, ManualRebuildWithAdvisoryEvent)
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange

parser = argparse.ArgumentParser()
parser.add_argument('errata_event_id', type=int, help='Errata event ID')
parser.add_argument('--cassette-path', default=False, dest='cassette',
                    help='Set a path to a cassette')
parser.add_argument('--container-image', nargs='+', default=False, dest='container_img',
                    help='Container images id')
args = parser.parse_args()
fedmsg_config = fedmsg.config.load_config()
dictConfig(fedmsg_config.get('logging', {'version': 1}))

if len(sys.argv) < 2:
    print("Queries Lightblue to find out all the images Freshmaker rebuilds.")
    print("Usage: ./lightblue.py ERRATA_ID [[CONTAINER_IMAGE], ...]")
    sys.exit(1)

app_context = app.app_context()
app_context.__enter__()

db.drop_all()
db.create_all()
db.session.commit()

errata = Errata()
kwargs = {}

if args.container_img:
    EventClass = ManualRebuildWithAdvisoryEvent
    kwargs['container_images'] = args.container_img
else:
    EventClass = ErrataAdvisoryStateChangedEvent

event_id = None
if args.cassette:
    cassette_name = os.path.splitext(os.path.basename(args.cassette))[0]
    extension = os.path.splitext(os.path.basename(args.cassette))[1]
    try:
        event_id = int(cassette_name)
        if extension != ".yml":
            raise ValueError
    except ValueError:
        print("The input cassette must be named in the format of <event ID>.yml")
        sys.exit(1)

    conf.vcrpy_path = os.path.dirname(args.cassette)
    conf.vcrpy_mode = 'none'

event = EventClass(
    "fake_message", ErrataAdvisory.from_advisory_id(errata, sys.argv[1]),
    dry_run=True, freshmaker_event_id=event_id, **kwargs)

handler = RebuildImagesOnRPMAdvisoryChange()

with patch("freshmaker.consumer.get_global_consumer"):
    handler.handle(event)
