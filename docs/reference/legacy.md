# Legacy interfaces

The original pyMIND drivers, kept for reference and backwards compatibility. They
work, but they couple connection, decoding, threading and storage together: each
driver owns a collection thread and requires a `SaveProtocol` to write through.

**New code should use {class}`~intellipy.client.IntellivueClient`**, which does the
same protocol work and yields samples instead of storing them. The equivalences:

| Legacy | Replacement |
|---|---|
| `ConnectToIntellivueUDP(...)` | `IntellivueClient("udp", ...)` |
| `ConnectToIntellivueRS232(...)` | `IntellivueClient("rs232", ...)` |
| `initiateAssociation()` | {meth}`~intellipy.client.IntellivueClient.associate` |
| `setPriorityLists()` | {meth}`~intellipy.client.IntellivueClient.set_wave_priority` |
| a `SaveProtocol` receiving parsed data | {meth}`~intellipy.client.IntellivueClient.stream` / {meth}`~intellipy.client.IntellivueClient.stream_to_queues` |

`ConnectToIntellivueUDP` additionally carries a `# FIXME ... most likely deprecated`
marker from the original authors.

## Save protocol

```{eval-rst}
.. automodule:: intellipy.SaveProto
   :members:
   :undoc-members:
   :show-inheritance:
```

## Connection base class

```{eval-rst}
.. automodule:: intellipy.ConnectionProtocol
   :members:
   :undoc-members:
   :show-inheritance:
```
