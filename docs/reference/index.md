# API reference

Generated from the source. For the narrative versions see {doc}`../guides/index`.

The supported surface is small:

{mod}`intellipy.client`
: {class}`~intellipy.client.IntellivueClient` — associate, enumerate, subscribe,
  stream, read demographics, release. Start here.

{mod}`intellipy.enumerate`
: {class}`~intellipy.enumerate.Signal` and the transport-agnostic collection routine
  behind {meth}`~intellipy.client.IntellivueClient.enumerate`, plus the
  `intellipy-enumerate` command line entry point.

{mod}`intellipy.dump`
: The `intellipy-dump` recorder — wave selection and the per-kind file writers. The
  worked example of the client, and importable if you want to build on it.

{mod}`intellipy.IntellivueDataFiles.IntellivueData`
: The codec. `writeData` builds a message from a template, `readData` parses one,
  `getMessageType` classifies bytes. Only needed if you are going below the client.

{mod}`intellipy.Sockets`
: Transport wrappers — UDP, RS232, and the abstract base both implement.

{mod}`intellipy.SaveProto`
: The original project's queue-based save protocol. Legacy; retained because the older
  drivers require one.

```{toctree}
:maxdepth: 2

client
enumerate
dump
codec
sockets
legacy
```
