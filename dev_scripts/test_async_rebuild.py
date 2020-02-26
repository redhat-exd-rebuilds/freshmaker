#!/usr/bin/env python
"""
Example usage:
    ./test_async_rebuild.py BRANCH_NAME     CSV_IMAGES_LIST
    ./test_async_rebuild.py extras-rhel-7.8 etcd-container,rhel-server-container
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
from freshmaker.events import FreshmakerAsyncManualBuildEvent
from freshmaker.handlers.koji import RebuildImagesOnRPMAdvisoryChange, RebuildImagesOnAsyncManualBuild

fedmsg_config = fedmsg.config.load_config()
dictConfig(fedmsg_config.get('logging', {'version': 1}))

if len(sys.argv) < 3:
    print("Usage: ./test_async_rebuild.py BRANCH CSV_LIST_IMAGES")
    sys.exit(1)

app_context = app.app_context()
app_context.__enter__()

db.drop_all()
db.create_all()
db.session.commit()

branch = sys.argv[1]
images = sys.argv[2].split(',')
kwargs = {}

event = FreshmakerAsyncManualBuildEvent(msg_id='fake-msg', dist_git_branch=branch, container_images=images, dry_run=True)

handler = RebuildImagesOnAsyncManualBuild()
with patch("freshmaker.consumer.get_global_consumer"):
    with patch("freshmaker.handlers.koji.RebuildImagesOnAsyncManualBuild.start_to_build_images"):
        handler.handle(event)
