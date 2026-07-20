# The association lifecycle

An **association** is a session: a negotiated, stateful, keep-alive-maintained
agreement between one client and one monitor. Nothing can be polled outside one, and a
monitor generally serves only a small number at a time.

The negotiation is **ACSE** (Association Control Service Element), the ISO layer that
sits above the session layer and below ROSE. Its job is to agree on the application
context and the options both sides support.

## The handshake, step by step

```{mermaid}
sequenceDiagram
    autonumber
    participant C as intellipy
    participant M as Monitor
    Note over C: socket bound to :24005
    M-->>C: ConnectIndicationEvent (broadcast)
    Note over C: retarget socket to the monitor's data port
    C->>M: AssociationRequest (requested poll profile options)
    M-->>C: AssociationResponse (granted options, min poll period)
    M-->>C: MDSCreateEvent (device identity, absolute + relative time)
    C->>M: MDSCreateEventResult
    Note over C,M: associated — polls now accepted
```

### 1. Connect indication (UDP only)

The monitor announces itself by broadcasting a `ConnectIndicationEvent` on port
**24005**. The message names the **data port** the rest of the session will use, which
is not 24005. `intellipy` binds the broadcast port, waits for the announcement, and
retargets its socket:

```python
_, portNumber, portAddress = self.codec.readData(message)
self.socket.portAddress = portAddress
self.socket.portNumber = portNumber
```

Consequences worth knowing: you cannot initiate a session on demand — you wait for the
monitor's next announcement, which is why
{meth}`~intellipy.client.IntellivueClient.associate` allows several timeout periods
here. And on a network with several monitors, the first announcement wins unless you
bind to a specific address.

Over RS232 there is no discovery: the client sends the association request straight
away.

### 2. Association request — negotiating what you may poll

The request carries the client's **poll profile options**, a bit field stating which
extensions it wants. This is the one point in the session where capability is
negotiated, and getting it wrong is not recoverable without re-associating:

| Option                          | Bit          | Grants                             |
| ------------------------------- | ------------ | ---------------------------------- |
| `POLL_EXT_PERIOD_NU_1SEC`       | `0x80000000` | 1-second numeric updates           |
| `POLL_EXT_PERIOD_NU_AVG_12SEC`  | `0x40000000` | 12-second averaged numerics        |
| `POLL_EXT_PERIOD_NU_AVG_60SEC`  | `0x20000000` | 60-second averaged numerics        |
| `POLL_EXT_PERIOD_NU_AVG_300SEC` | `0x10000000` | 300-second averaged numerics       |
| `POLL_EXT_PERIOD_RTSA`          | `0x08000000` | Real-time sampled waveforms        |
| `POLL_EXT_ENUM`                 | `0x04000000` | Enumeration objects                |
| `POLL_EXT_NU_PRIO_LIST`         | `0x02000000` | The numeric priority list          |
| `POLL_EXT_DYN_MODALITIES`       | `0x01000000` | Dynamically appearing measurements |

`intellipy` sends `0x8F000000` by default — 1-second numerics, waveforms,
enumerations, priority list and dynamic modalities — or `0x8B000000` when constructed
with `request_enumerations=False`.

:::{warning}
**Ask for `POLL_EXT_ENUM` at association time or not at all.** A monitor that was
never asked will answer an enumeration-object poll with a Remote Operation Error, and
there is no way to add the option to a live association.
:::

### 3. Association response — what you actually got

The monitor replies with the subset it will honour, as a bit field, *not* as the
combination that was requested. So the grant has to be decoded bit by bit;
{attr}`~intellipy.client.IntellivueClient.granted_poll_options` exposes the result as
a set of names:

```python
client.associate()
if "POLL_EXT_ENUM" not in client.granted_poll_options:
    print("this monitor will not serve enumeration objects")
```

The response also carries the **minimum poll period**, which `intellipy` stores as
{attr}`~intellipy.client.IntellivueClient.keep_alive_time` — the longest the client
may stay silent before the monitor drops the association.

A refusal arrives instead as `AssociationRefuse` (session byte `0x0C`), and
{class}`~intellipy.client.AssociationError` is raised.

### 4. MDS create event — identity and the time origin

Immediately after accepting, the monitor sends an `MDSCreateEvent` describing itself:
model, serial number, firmware revisions, bed label, and the two clocks
(see [Time](model.md#time)):

- `NOM_ATTR_TIME_ABS` — absolute wall-clock time, BCD.
- `NOM_ATTR_TIME_REL` — the relative tick counter's current value.

That relative value becomes the **origin all sample timestamps are measured from**,
stored as {attr}`~intellipy.client.IntellivueClient.relative_initial_time`.

:::{important}
The create event is a **confirmed** event report: it must be answered with an
`MDSCreateEventResult`. A client that skips the acknowledgement sees the monitor
re-announce itself in a loop and never accept a poll. This is the single most common
way an otherwise correct implementation fails to get data.
:::

## Keeping it alive

The monitor drops an association that goes quiet for longer than the negotiated
period. During streaming there is usually traffic anyway, but a monitor with no
waveforms on its priority list and no numerics changing can be silent for a long time.

{meth}`~intellipy.client.IntellivueClient.stream` therefore paces keep-alives off a
monotonic clock: if nothing has been *sent* for `keep_alive_time - 5 s`, it sends a
single poll (`MDSSinglePollAction`) and resets the timer. Pacing off send time rather
than off received traffic means the keep-alive does not depend on data arriving —
which is exactly the case where it is needed.

## Releasing

A clean shutdown sends a `ReleaseRequest` (session byte `0x09`) and waits for the
`ReleaseResponse`. {meth}`~intellipy.client.IntellivueClient.close` does this and then
closes the socket; the context manager calls it for you:

```python
with IntellivueClient("udp") as client:
    client.associate()
    ...
# released and closed, even if the body raised
```

Skipping the release is not fatal — the monitor times the association out — but it
leaves a session slot occupied for the keep-alive period, which matters if you are
reconnecting in a loop.

An `AssociationAbort` (`0x19`) from the monitor means the session is gone immediately;
`stream()` treats it as end of stream and returns.
