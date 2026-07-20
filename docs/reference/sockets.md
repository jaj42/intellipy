# `intellipy.Sockets`

Transport wrappers. {class}`~intellipy.client.IntellivueClient` constructs the right
one from its `transport` argument; you only need these directly to drive
{func}`~intellipy.enumerate.collect_enumeration` or the codec yourself.

All three share the same surface — `bind`, `send`, `receive`, `close` — so anything
implementing {class}`~intellipy.Sockets.Socket.Socket` can carry the protocol.

## Abstract base

```{eval-rst}
.. automodule:: intellipy.Sockets.Socket
   :members:
   :undoc-members:
   :show-inheritance:
```

## UDP

```{eval-rst}
.. automodule:: intellipy.Sockets.UDP
   :members:
   :undoc-members:
   :show-inheritance:
```

## RS232

```{eval-rst}
.. automodule:: intellipy.Sockets.RS232
   :members:
   :undoc-members:
   :show-inheritance:
```
