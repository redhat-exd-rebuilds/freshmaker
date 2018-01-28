![Freshmaker](https://pagure.io/freshmaker/raw/master/f/logo.png)

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
    * There are built-in classes to find these information in PDC or Lightblue.
* Plan the rebuild of artifacts and store them in Freshmaker database in tree-like structure.
    * Artifacts can depend on each other and Freshmaker ensures they are built in the right order.
* Prepare the prerequisites for a rebuild.
    * This can for example mean generating RPM repository with updated packages using ODCS.
* Start the rebuild.

Most of the common tasks for handlers are already implemented in Freshmaker including:

* Database and methods to store artifacts, their dependencies and all the information to build them there.
* Classes to get the information about artifacts from Koji, Lightblue, PDC, MBS, ...
* Classes to start the builds in Koji, ODCS, MBS, ...

The handler which rebuilds all the modules after the `.spec` file of RPM including in a module is updated can look like this:

    class GitRPMSpecChangeHandler(BaseHandler):
        name = "GitRPMSpecChangeHandler"

        def can_handle(self, event):
            return isinstance(event, GitRPMSpecChangeEvent)

        def handle(self, event):
            # Get the list of modules with this package from this branch using PDC.
            pdc = PDC(conf)
            modules = pdc.get_latest_modules(component_name=event.rpm,
                                            component_branch=event.branch,
                                            active='true')

            for module in modules:
                name = module['variant_name']
                version = module['variant_version']

                # Check if Freshmaker is configured to rebuild this module.
                if not self.allow_build(ArtifactType.MODULE, name=name, version=version):
                    continue

                # To rebuild a module, we need to bump its release in dist-git repo.
                commit_msg = "Bump to rebuild because of %s rpm spec update (%s)." % (event.rpm, event.rev)
                rev = utils.bump_distgit_repo('modules', name, branch=version, commit_msg=commit_msg, logger=log)

                # We start the rebuild of a module and store it in Freshmkaer DB.
                build_id = self.build_module(name, version, rev)
                if build_id is not None:
                    self.record_build(event, name, ArtifactType.MODULE, build_id)
