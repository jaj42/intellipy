# Messages and layers

Every Data Export packet is four things stacked: a **session PDU**, a
**remote-operation APDU**, a **command**, and the command's payload. Knowing where the
boundaries are makes both the wire format and this library's message names readable.

```
┌──────────────────────────────────────────────────────────┐
│ SPpdu           session layer      0xE1, session id      │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ ROapdus       ROSE APDU type + length                │ │
│ │ ┌──────────────────────────────────────────────────┐ │ │
│ │ │ ROIVapdu    invoke id + command type              │ │ │
│ │ │ ┌──────────────────────────────────────────────┐ │ │ │
│ │ │ │ ActionArgument / EventReportArgument …       │ │ │ │
│ │ │ │   → PollMdibDataReqExt, PollMdibDataReplyExt │ │ │ │
│ │ │ └──────────────────────────────────────────────┘ │ │ │
│ │ └──────────────────────────────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## Session layer

The first byte identifies the session PDU. Association-phase messages use ISO session
PDU codes; everything after association uses `0xE1`, the Data Export protocol's own
data PDU:

| Byte | Session PDU | Meaning |
|---|---|---|
| `0x0D` | `CN_SPDU_SI` | Connect — the association request |
| `0x0E` | `AC_SPDU_SI` | Accept — the association response |
| `0x0C` | `RF_SPDU_SI` | Refuse |
| `0x09` | `FN_SPDU_SI` | Finish — the release request |
| `0x0A` | `DN_SPDU_SI` | Disconnect — the release response |
| `0x19` | `AB_SPDU_SI` | Abort |
| `0xE1` | `SPpdu` | Data — everything else |

This is exactly how {meth}`~intellipy.IntellivueDataFiles.IntellivueData.IntellivueData.getMessageType`
classifies an incoming packet: first byte, then a handful of discriminating bytes
deeper in.

Lengths use two encodings, both handled by the codec: ASN.1-style long form
(`0x81` + 1 byte, `0x82` + 2 bytes) inside the APDU, and the session layer's own
`0xFF` + 2-byte form.

(rose)=
## ROSE: ROIV, RORS, ROER, ROLRS

The middle layer is **ROSE** — ISO's Remote Operation Service Element, a
request/response framework. Four APDU types appear, and the four-letter acronyms are
worth memorising because the whole protocol is described in them:

| APDU | Code | Meaning |
|---|---|---|
| **ROIV** | 1 | *Invoke* — a request. Everything the client sends is a ROIV. |
| **RORS** | 2 | *Result* — a reply, and the **last** one for this invocation. |
| **ROER** | 3 | *Error* — the request was refused. |
| **ROLRS** | 5 | *Linked result* — a reply **with more to come**. |

Every invocation carries an **invoke id**; replies echo it, which is how a reply is
matched to its request when several are outstanding.

:::{admonition} ROLRS is why replies arrive in pieces
:class: note

A poll reply enumerating twenty numerics does not fit in one datagram. The monitor
splits it into a run of **ROLRS** segments terminated by a single **RORS**. Each
segment carries a complete, parseable `PollInfoList` — just a partial one. So a client
must *merge* segments by `(class, context, handle)` rather than treat each as a fresh
snapshot, and must keep reading until the RORS arrives.

`intellipy` does this in
{func}`~intellipy.enumerate.collect_enumeration`: it sends one poll per class with a
distinct poll number, then reads until each class has produced its final RORS or the
timeout expires. A **ROER** means the monitor declined that poll outright — most often
an enumeration poll on an association that never negotiated `POLL_EXT_ENUM`.
:::

## Commands

Inside the ROIV sits a **command type**, the CMIP-style operation being invoked:

| Command | Used for |
|---|---|
| `CMD_CONFIRMED_ACTION` | Polls, priority-list changes — anything with a result |
| `CMD_CONFIRMED_EVENT_REPORT` | The MDS create event, which must be acknowledged |
| `CMD_GET` / `CMD_SET` | Reading and writing attributes directly |
| `CMD_EVENT_REPORT` | Unconfirmed notifications |

Data export is built almost entirely on **actions**, not on GET/SET. An action names
an **action type** — another nomenclature code — and carries a typed argument:

| Action | Meaning |
|---|---|
| `NOM_ACT_POLL_MDIB_DATA` | Single poll: send the current values once |
| `NOM_ACT_POLL_MDIB_DATA_EXT` | Extended poll: keep sending for a stated period |

(polls)=
## Single versus extended polls

This distinction drives everything the client does.

**Single poll** (`NOM_ACT_POLL_MDIB_DATA`)
: One request, one reply, one snapshot. Used here for patient demographics and as the
  keep-alive. Cheap and self-limiting.

**Extended poll** (`NOM_ACT_POLL_MDIB_DATA_EXT`)
: A *subscription with a deadline*. The argument carries a **poll period** —
  a `RelativeTime` in monitor ticks — and the monitor then reports that class
  repeatedly, unprompted, until the period expires. This is how streaming works:
  there is no separate "subscribe" message, only a poll with a long period.
  {meth}`~intellipy.client.IntellivueClient.stream` sets the period from its
  `duration` argument (defaulting to 72 hours when streaming open-endedly).

An extended poll argument also carries a **poll number**, chosen by the client and
echoed in the replies, which is how simultaneous polls of different classes are told
apart.

## Attribute groups

A poll does not name attributes individually. It names an **attribute group** — a
predefined bundle — and the monitor returns the whole bundle for every object of the
class. The group used for discovery is `ALL`, meaning literally every attribute,
which is why one poll with group `ALL` produces the complete inventory
({doc}`enumeration`). Value-only groups exist and are what later poll cycles
effectively deliver.

The addressing triple in a poll is therefore *(object polled, class wanted, group
wanted)* — always `NOM_MOC_VMS_MDS` first, since the poll is addressed to the MDS
even though it asks about its children:

```python
"OIDType": ["NOM_MOC_VMS_MDS", "NOM_MOC_VMO_METRIC_NU", "ALL"]
```

## Priority lists

The monitor will not stream every waveform it has — bandwidth, especially over
RS232, does not allow it. Instead it keeps a **real-time priority list** naming the
waveforms currently eligible for export, and it starts out **empty**.

So an extended poll of `NOM_MOC_VMO_METRIC_SA_RT` on a fresh association returns the
waveform objects (that is enumeration working correctly) but no samples. You must set
the list first, by label:

```python
client.set_wave_priority(["Pleth", "ECG MCL"])
```

There is a numeric priority list too (`MDSSetPriorityListNUMERIC`), but numerics are
exported without one.

## Transports and ports

**UDP** (`Sockets.UDP`)
: The monitor broadcasts a *connect indication* on port **24005**, naming the port its
  data will actually come from; the client retargets its socket there and associates.
  This is why the default host is `0.0.0.0` — you are listening for an announcement,
  not connecting to a known address. UDP is lossy and unordered; a dropped segment
  means a dropped waveform block, and nothing retransmits it.

**RS232** (`Sockets.RS232`)
: A framed serial link with no discovery step — the association request goes out
  immediately. Same message set, same client API.

:::{note}
Only the UDP path has been verified against a real capture. The RS232 path mirrors it
structurally and is untested in this repository.
:::

## The catalog

Every message template the codec can build or parse, with its layer chain, is listed
in {doc}`../protocol/messages`.
