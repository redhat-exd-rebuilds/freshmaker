# Freshmaker

## Design

Freshmaker waits for new fedmsg messages, this happens in `consumer.py`. Every
fedmsg message handled by a Freshmaker is parsed by one of the parsers which can
be found in the `parsers` directory. This parser converts the fedmsg to trigger
object (inherits from `BaseTrigger`). All the triggers are defined in the
`triggers.py`. This separation between message and trigger is done to possibly
support different messaging backends in the future or easily change the message
we react to. This trigger object is then handled by one or more handlers defined
in the `handlers` directory.

The example flow for the modulemd yaml change in dist-git is following:

- Message from dist-git is received, `ModuleMetadataUpdated` trigger is
  generated out of this message and the trigger event is passed to handlers.
- MBS handler handles this message and triggers the rebuild of a module in MBS.
- MBS rebuilds the module and generates message, this message is received and
  parsed by Freshmaker. `ModuleBuilt` trigger is generated and passed to
  handlers.
- MBS handler handles this message if another modules depend on the built module
  and triggers the rebuild of these modules.
- OSBS handler handles this message if some containers depend on this module and
  instructs OSBS to rebuild them

Handlers can be turned on/off in config file.

## List of Freshmaker handlers

Following is the list of all available HANDLERS:

* `freshmaker.handlers.koji:KojiTaskStateChangeHandler`
* `freshmaker.handlers.mbs:MBSModuleStateChangeHandler`
    * Depends on: MBS, PDC
* `freshmaker.handlers.git:GitRPMSpecChangeHandler`
    * Depends on: PDC
* `freshmaker.handlers.brew:BrewSignRPMHandler`
    * Depends on: Errata, LightBlue, Pulp, Koji
* `freshmaker.handlers.git:GitDockerfileChangeHandler`
* `freshmaker.handlers.git:GitModuleMetadataChangeHandler`
* `freshmaker.handlers.bodhi:BodhiUpdateCompleteStableHandler`
    * Depends on: PDC, Koji

## Messaging

Freshmaker sends messages to either fedmsg or UMB, which depends on how it is
configured, when certain event happens.

| Event | Topic |
|-------|-------|
| Containers are found and will be built soon | `images.found` |

## Testing

```
$ tox -e py27,py35
```
