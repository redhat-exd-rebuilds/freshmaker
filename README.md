[![Freshmaker-status](https://quay.io/repository/factory2/freshmaker/status)](https://quay.io/repository/factory2/freshmaker)
![Freshmaker](https://github.com/redhat-exd-rebuilds/freshmaker/raw/master/logo.png)

## What is Freshmaker?

Freshmaker is a service which:

* Rebuilds various artifacts after its dependencies changed. For example:
  * Rebuilds module when .spec file of RPM in a module is updated or  the RPM is pushed to stable using Bodhi.
  * Rebuilds container image when RPM in a container is updated or pushed to stable using Bodhi.
  * ...
* Provides a REST API to retrieve information about artifact rebuilds and the reasons for these rebuilds and sends messages to the message bus about these event.
* Is based on Event-Handler architecture:
  * Events are fedmsg messages received from other services like dist-git, Koji, Bodhi, ...
  * Handlers are small classes using the high-level API provided to them by Freshmaker core to rebuild artifacts.
* Provides high-level API to track dependencies between artifacts and make rebuilding of them easy.

See the [docs](https://redhat-exd-rebuilds.github.io/freshmaker/) for additional information.

## How does it work?

Freshmaker waits for new fedmsg messages about artifact being updated,
this happens in `consumer.py`. Every fedmsg message handled by a Freshmaker
is parsed by one of the parsers which can be found in the `parsers` directory.
This parser converts the fedmsg to `Event` object (inherits from `BaseEvent`).
All the events are defined in the `events.py`.

This Event object is then handled by one or more handlers defined
in the `handlers` directory.

The handlers typically do following:

* Find out the list of artifacts like RPMs, Container images, ... which must be rebuilt as result of Event.
  * There are built-in classes to find these information in Lightblue.
* Plan the rebuild of artifacts and store them in Freshmaker database in tree-like structure.
  * Artifacts can depend on each other and Freshmaker ensures they are built in the right order.
* Prepare the prerequisites for a rebuild.
  * This can for example mean generating RPM repository with updated packages using ODCS.
* Start the rebuild.

Most of the common tasks for handlers are already implemented in Freshmaker including:

* Database and methods to store artifacts, their dependencies and all the information to build them there.
* Classes to get the information about artifacts from Koji, Lightblue, ...
* Classes to start the builds in Koji, ODCS, ...

The handler which rebuilds all the images that contain packages affected by CVEs in advisory when the advisory is shipped can look like this (only sample code for demonstration):

```python
class RebuildImagesOnRPMAdvisoryChange(ContainerBuildHandler):

    name = 'RebuildImagesOnRPMAdvisoryChange'

    def can_handle(self, event):
        if not isinstance(event, ErrataAdvisoryRPMsSignedEvent):
            return False
        return True

    def handle(self, event):
        self.event = event

        db_event = Event.get_or_create_from_event(db.session, event)
        db.session.commit()

        # Check if we are allowed to build this advisory.
        if not self.event.is_allowed(self):
            db_event.transition(
                EventState.SKIPPED, f"Advisory {event.advisory.errata_id} is not allowed")
            db.session.commit()
            return []

        # Get and record all images to rebuild
        batches = self._find_images_to_rebuild(db_event.search_key)
        builds = self._record_batches(batches, event)

        self.start_to_build_images(db_event.get_image_builds_in_first_batch(db.session))
        db_event.transition(EventState.BUILDING, msg)

        return []
```

# Initial development setup

Create and activate a [Python virtual environment](https://virtualenv.pypa.io/en/stable/).

Install the dependencies with:

```bash
python3 setup.py develop
```

Install required rpm packages:

```bash
dnf install $(sed 's/#.*//' yum-packages-devel.txt)
```

Install the requirements:

```bash
pip3 install -r requirements.txt
```

Install the requirements useful to run the tests:

```bash
pip3 install -r test-requirements.txt
```

Run the tests:

```bash
pytest tests/
```

In order to generate the requirements you need pip-tools:

```bash
python -m pip install pip-tools
```

more info available at: https://github.com/jazzband/pip-tools/
