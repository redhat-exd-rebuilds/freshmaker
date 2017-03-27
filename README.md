# Continuous Compose Service (CoCo)

## Design

CoCo waits for new fedmsg messages, this happens in `consumer.py`. Every fedmsg message handled by a CoCo is parsed by one of the parsers which can be found in the `parsers` directory. This parser converts the fedmsg to trigger object (inherits from `BaseTrigger`). All the triggers are defined in the `triggers.py`. This separation between message and trigger is done to possibly support different messaging backends in the future or easily change the message we react to. This trigger object is then handled by one or more handlers defined in the `handlers` directory.

The example flow for the modulemd yaml change in dist-git is following:

- Message from dist-git is received, ModuleMetadataUpdated trigger is generated out of this message and the trigger event is passed to handlers.
- MBS handler handles this message and triggers the rebuild of a module in MBS.
- MBS rebuilds the module and generates message, this message is received and parsed by CoCO. ModuleBuilt trigger is generated and passed to handlers.
- MBS handler handles this message if another modules depend on the built module and triggers the rebuild of these modules.
- OSBS handler handles this message if some containers depend on this module and instructs OSBS to rebuild them

Handlers can be turned on/off in config file.

## Testing

```
$ tox
```
