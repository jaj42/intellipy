# intellipy

A Python implementation of the **Philips IntelliVue Data Export protocol** — the
documented, vendor-supported interface for streaming live physiological data off
IntelliVue-family patient monitors (X2, MP-series, MX-series) over UDP or RS232.

`intellipy` associates with a monitor, asks it what it measures, subscribes to the
waveforms you want, and decodes the ISO/IEEE 11073-based message stream into plain
Python dicts:

```python
from intellipy.client import IntellivueClient

with IntellivueClient("udp") as client:
    client.associate()

    signals = client.enumerate()
    for signal in signals:
        print(signal)              # SpO₂ (handle 33749) [% ( percentage )]

    waves = [s for s in signals if s.kind == "wave"]
    client.set_wave_priority(waves[:1])

    for sample in client.stream(duration=60):
        print(sample["label"], sample["time"], sample.get("value"))
```

It is a **read-oriented** tool for clinical data export and research. It does not
configure the monitor, silence alarms, or influence anything the monitor does
clinically — the Data Export interface itself is one-way in that respect.

## Where to start

:::{list-table}
:header-rows: 1
:widths: 30 70

* - If you want to…
  - Read
* - install it and record your first minute of data
  - {doc}`guides/install` then {doc}`guides/quickstart`
* - understand what "MDS", "RORS" or "extended poll" mean
  - {doc}`concepts/index` — the protocol primer
* - find out which signals a monitor exposes
  - {doc}`guides/enumeration`
* - process a waveform as it arrives
  - {doc}`guides/realtime`
* - look up a class, method or argument
  - {doc}`reference/index`
* - decode a code you saw on the wire
  - {doc}`protocol/nomenclature`
:::

## What is implemented

- **Association** over UDP (verified against a real capture) and RS232 (structurally
  mirrored, untested here), including poll-profile option negotiation.
- **Signal enumeration** — numerics, waveforms, alarms and enumeration objects.
- **Subscription** to real-time waveforms via the priority list.
- **Streaming** of numerics, waveform blocks, alarms and enumeration states, with
  scaling, per-sample timestamps and automatic keep-alive.
- **Patient demographics** — request and decode the `NOM_MOC_PT_DEMOG` record.

## What is not

- No monitor configuration, no control, no writing to the MDIB.
- No trend or stored-data retrieval — only the real-time poll interface.
- 12-lead capture, `NOM_MOC_VMO_METRIC_SA_RT` bulk export and the serial
  multi-monitor topologies are out of scope.

:::{admonition} Clinical and regulatory scope
:class: warning

`intellipy` is research and interoperability software. It is not a medical device,
carries no regulatory clearance, and must not be relied on for clinical decisions,
diagnosis, monitoring or alarming. Alarms in particular are exported on a best-effort
basis over a lossy transport and are **not** a substitute for the monitor's own
alarm system.
:::

```{toctree}
:maxdepth: 2
:caption: Contents

guides/index
concepts/index
reference/index
protocol/index
```

## Attribution and licence

Originally created by Uday Agrawal, Adewole Oyalowo and the Asaad Lab (2015–2016, part
of the [pyMIND](https://bitbucket.org/asaadneurolab/pymind/) project) under the MIT
licence. Continued and repackaged by Jona Joachim. "Philips" and "IntelliVue" are
trademarks of Koninklijke Philips N.V.; this project is not affiliated with or
endorsed by Philips.
