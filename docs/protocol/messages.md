# Message catalog

Every message {meth}`~intellipy.IntellivueDataFiles.IntellivueData.IntellivueData.writeData`
can build and
{meth}`~intellipy.IntellivueDataFiles.IntellivueData.IntellivueData.readData` can
parse.

## How a template works

A template is a **layer chain** plus a dict of default parameters. `writeData` encodes
the layers in order, taking each field from your overrides if present and from the
template otherwise:

```python
codec.writeData("MDSExtendedPollActionNUMERIC", {"poll_number": 3})
```

That produces a complete extended poll — session PDU, ROSE APDU, action argument and
all — with only the poll number changed. The parameters worth overriding in practice:

| Parameter               | Meaning                                                      |
| ----------------------- | ------------------------------------------------------------ |
| `poll_number`           | Client-chosen id echoed in the replies; distinguishes concurrent polls |
| `invoke_id`             | ROSE invocation id; replies echo it                          |
| `RelativeTime`          | For an extended poll, the **poll period** in 1/8000 s ticks  |
| `OIDType`               | The addressing triple *(object, class polled, attribute group)* |
| `TextIdLabel`           | Waveform labels, for the priority-list messages              |
| `PollProfileExtOptions` | Which extensions to request at association time              |

## Classification on receipt

`getMessageType` identifies an incoming message from its first byte and a few
discriminating bytes deeper in — it does not parse the whole thing, so it is cheap
enough to call on every packet before deciding whether to decode it:

| First byte               | Yields                                                       |
| ------------------------ | ------------------------------------------------------------ |
| `0x0D` / `0x0E` / `0x0C` | `AssociationRequest` / `AssociationResponse` / `AssociationRefuse` |
| `0x09` / `0x0A` / `0x19` | `ReleaseRequest` / `ReleaseResponse` / `AssociationAbort`    |
| `0xE1`                   | A data message — the ROSE APDU type and action code then pick the exact one |
| leading `00 00 01 00`    | `ConnectIndicationEvent`                                     |

Two returns have no template because nothing is ever built from them:
`RemoteOperationError` (the monitor declined a request — see
{ref}`ROSE <rose>`) and `Unknown`.

The linked variants (`LinkedMDS…Result`) are ROLRS segments: same payload structure,
more to come. Treat them identically to the final result but keep reading.

```{include} _generated/message_templates.md
```
