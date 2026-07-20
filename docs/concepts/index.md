# Concepts

The Data Export protocol is an ISO/IEEE 11073 dialect, and its vocabulary is unlike
most network protocols: you do not read "channels" off a "device", you poll
*attribute groups* of *managed objects* in a *medical device system*'s *information
base*, addressed by *nomenclature codes*.

These pages explain that vocabulary in the order you meet it when writing a client.
If you only want to get data out, {doc}`../guides/quickstart` needs none of it.

```{toctree}
:maxdepth: 2

model
messages
association
enumeration
glossary
```

## The shape of a session, in one page

```{mermaid}
sequenceDiagram
    participant C as intellipy
    participant M as Monitor
    M-->>C: Connect Indication (broadcast, port 24005)
    C->>M: Association Request (poll profile options)
    M-->>C: Association Response (granted options, keep-alive period)
    M-->>C: MDS Create Event (device identity, time origin)
    C->>M: MDS Create Event Result
    Note over C,M: associated
    C->>M: Extended Poll, class = numerics, group = ALL
    M-->>C: Linked poll result… → final poll result
    Note over C,M: that reply *is* the signal inventory
    C->>M: Set Priority List (waveform labels)
    M-->>C: Set Priority List Result
    C->>M: Extended Poll, period = N seconds
    loop until the poll period expires
        M-->>C: poll results carrying values
    end
    C->>M: Release Request
    M-->>C: Release Response
```

Four ideas carry most of the weight:

{doc}`The information model <model>`
: The monitor presents itself as an **MDS** holding a tree of **objects** (one per
  measured thing), each with **attributes**, each addressed by a numeric **OID**.

{doc}`The message layers <messages>`
: Every packet is a session PDU wrapping a remote-operation APDU wrapping a command.
  "RORS", "ROLRS" and "ROER" are just *reply*, *reply-with-more-coming* and *error*.

{doc}`The association <association>`
: A session must be opened, kept alive and released. The options you request here
  decide what you are allowed to poll later.

{doc}`Enumeration <enumeration>`
: There is no "list signals" request. You discover the inventory by polling every
  attribute of every object of a class, once.
