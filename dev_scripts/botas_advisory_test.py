#!/usr/bin/env python
"""
Example usage:
    ./botas_advisory_test.py ADVISORY_ID
    ./botas_advisory_test.py 59808
"""
import os
import sys
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
from freshmaker.events import BotasErrataShippedEvent
from freshmaker.handlers.botas.botas_shipped_advisory import HandleBotasAdvisory
from freshmaker.errata import Errata, ErrataAdvisory


fedmsg_config = fedmsg.config.load_config()
dictConfig(fedmsg_config.get('logging', {'version': 1}))

if len(sys.argv) != 2:
    print("Usage: ./botas_advisory_test.py ADVISORY_ID")
    sys.exit(1)

app_context = app.app_context()
app_context.__enter__()

db.drop_all()
db.create_all()
db.session.commit()

advisory_id = sys.argv[1]
errata = Errata()
advisory = ErrataAdvisory.from_advisory_id(errata, advisory_id)

event = BotasErrataShippedEvent(msg_id='fake-msg', advisory=advisory,
                                dry_run=True)

handler = HandleBotasAdvisory()
with patch("freshmaker.consumer.get_global_consumer"):
    if handler.can_handle(event):
        handler.handle(event)
    else:
        print("Can't handle that event")
