# Enumeration explained

**There is no "list the signals" request.** The Data Export protocol has no
capability-description message, no device profile you can fetch, no manifest. A
monitor that is measuring SpO₂, ECG and two pressures will tell you so — but only as a
side effect of being asked for data.

This is the single most confusing thing about writing a client, and the trick is
short: **poll each object class once, asking for attribute group `ALL`, and read the
objects out of the reply.**

## Why that works

A poll addresses *(object, class, attribute group)*. Setting the group to `ALL` means
"every attribute of every object of this class", so the reply is forced to contain, for
each object, its identity attributes as well as its value:

```python
"OIDType": ["NOM_MOC_VMS_MDS", "NOM_MOC_VMO_METRIC_NU", "ALL"]
"action_type": "NOM_ACT_POLL_MDIB_DATA_EXT"
```

Every object in that reply carries at least:

| Attribute                  | OID      | What you learn                           |
| -------------------------- | -------- | ---------------------------------------- |
| `NOM_ATTR_ID_HANDLE`       | `0x0921` | The handle to match samples against      |
| `NOM_ATTR_ID_LABEL`        | `0x0924` | What it measures, as a 32-bit label code |
| `NOM_ATTR_ID_LABEL_STRING` | `0x0927` | The display string, e.g. `"SpO2"`        |
| `NOM_ATTR_UNIT_CODE`       | `0x0996` | Its unit (numerics and waveforms)        |

Collecting the objects from **the first full poll cycle is the enumeration**. Nothing
further is needed — and nothing further is possible.

One poll per class, since a poll names exactly one:

| Kind | Class | OID |
|---|---|---|
| numeric | `NOM_MOC_VMO_METRIC_NU` | 6 |
| wave | `NOM_MOC_VMO_METRIC_SA_RT` | 9 |
| alarm | `NOM_MOC_VMO_AL_MON` | 54 |
| enumeration | `NOM_MOC_VMO_METRIC_ENUM` | 5 |

## Reading the reply

The reply nests four levels deep, and this traversal is the heart of the library:

```
PollMdibDataReplyExt
└── PollInfoList                 all objects in this segment
    └── SingleContextPoll        one per MDS context
        └── poll_info
            └── ObservationPoll  one per object
                ├── Handle
                └── AttributeList
                    └── AVAType[...]   the attributes
```

{func}`~intellipy.enumerate.harvest_inventory` walks exactly this and folds each
`ObservationPoll` into a {class}`~intellipy.enumerate.Signal`, keyed by
`(class, context, handle)`.

The keying matters because the reply is **linked** ({ref}`see ROSE <rose>`): it arrives
as several ROLRS segments before the final RORS, each carrying a slice of the object
list. Objects must be *merged* across segments, not replaced — and collection must
continue until each class's RORS shows up.

## What it looks like

Against the reference capture (`reference/intellivue_enumeration.pcapng`, a Philips
M8000 in an operating theatre), three polls yield 25 objects:

```console
$ uv run intellipy-enumerate --pcap reference/intellivue_enumeration.pcapng
read 189 UDP payloads from intellivue_enumeration.pcapng

CLASS                      ctx  handle  disp       label / unit
--------------------------------------------------------------------------------------
NOM_MOC_VMO_AL_MON           0   33793             ?
NOM_MOC_VMO_METRIC_NU        0   35098  PA         Arterial Blood Pressure (ABP)
NOM_MOC_VMO_METRIC_NU        0   35105  Pouls      Pulse derived from ABP
NOM_MOC_VMO_METRIC_NU        1   33386  PB         non-invasive blood pressure
NOM_MOC_VMO_METRIC_NU        1   33459  FC         Heart Rate
NOM_MOC_VMO_METRIC_NU        1   33749  SpO₂       Arterial Oxigen Saturation
NOM_MOC_VMO_METRIC_NU        1   33763  Perf       Perfusion Indicator
                                       … 14 more numerics …
NOM_MOC_VMO_METRIC_SA_RT     0    2332  PA         Arterial Blood Pressure (ABP)  [mmHg ( mm mercury )]
NOM_MOC_VMO_METRIC_SA_RT     1     686  MCL        ECG Lead MCL  [mV ( milli-volt )]
NOM_MOC_VMO_METRIC_SA_RT     1     696  Resp       Imedance RESP wave  [Ohm ( Ohm )]
NOM_MOC_VMO_METRIC_SA_RT     1     986  Pleth      PLETH wave label  [- ( no dimension )]
--------------------------------------------------------------------------------------
counts: {'NOM_MOC_VMO_METRIC_NU': 20, 'NOM_MOC_VMO_METRIC_SA_RT': 4,
         'NOM_MOC_VMO_AL_MON': 1} | total objects: 25
```

Twenty numerics, four waveforms, one alarm-monitor object. The alarm monitor is a
single object whose *attributes* are the active alarm lists, which is why there is one
of them regardless of how many alarms are active.

Three things in that table are worth pausing on:

- **Most of those numerics are not being measured.** The monitor reports the objects it
  is *configured* to have; twenty numerics on a bed running ECG, SpO₂ and one arterial
  line means most carry no value yet. Enumeration tells you what *can* appear.
- **Two MDS contexts.** Handles 686 and 2332 both exist, in contexts 1 and 0 — this
  monitor fronts a docked module rack as well as itself. Keying an inventory on the
  handle alone would have collided.
- **The `disp` column is localised, the label column is not.** This monitor is set to
  French: heart rate displays as `FC`, the arterial line as `PA`, the cuff as `PB`.
  The `label` column comes from the nomenclature table shipped with `intellipy` and is
  always English. Neither column is on the wire — both are renderings of a 32-bit
  code, and that distinction has teeth. See below.

:::{admonition} Subscribe with the `Signal`, not with a name
:class: warning

On the wire a label is a **32-bit code**, both when the monitor sends it and when you
send it back in a priority list. Names are a detour, and a lossy one:

- `label_string` is the monitor's display text. `"PA"` is not in the nomenclature
  table at all, so feeding it back raises `KeyError`. Worse, the NIBP's `"PB"` *is*
  in the table — as **Barometric Pressure**. That subscription succeeds, silently,
  to the wrong signal.
- `label` is the table's description, which is not unique: 34 of the 757 codes share
  a description with another code, so the description cannot always be turned back
  into the code it came from.

{class}`~intellipy.enumerate.Signal` therefore keeps the raw code as `label_code`, and
{meth}`~intellipy.client.IntellivueClient.set_wave_priority` accepts the `Signal`
itself. No lookup, nothing to misresolve:

```python
waves = [s for s in client.enumerate() if s.kind == "wave"]
client.set_wave_priority(waves)
```
:::

## Transport-agnostic by construction

{func}`~intellipy.enumerate.collect_enumeration` takes `send` and `recv` **callables**
rather than a socket. The consequence is that decoding a capture file and enumerating a
live monitor run the *same* collection logic — the offline path replays packets from a
pcap, the live path reads from a UDP or serial socket, and neither can drift from the
other:

```python
inventory = collect_enumeration(socket.send, socket.receive, codec, timeout=5.0)
```

This is what makes the enumeration path testable without hardware, and the reference
capture is what proves the decode is right.

## Enumeration objects versus signal enumeration

An unfortunate name collision, worth stating plainly:

**Signal enumeration** (this page)
: Discovering what the monitor exposes.

**Enumeration objects** (`NOM_MOC_VMO_METRIC_ENUM`)
: A *class of metric* that reports a state rather than a number — ECG rhythm status
  (`RytSta` → "Sinus Rhythm", "Vtach") and ectopic status (`EctSta` → "pair PVC's").
  Available from monitor software revision E.0, and only when `POLL_EXT_ENUM` was
  negotiated ({doc}`association`).

Enumeration objects appear in the inventory like any other class, and stream as
samples of `kind="enumeration"` carrying a `state` code.

:::{note}
The reference capture contains no enumeration replies — that association never
requested `POLL_EXT_ENUM` — so their value decoding is verified against synthetic
data built to the specification, not against a monitor. What *is* confirmed from the
capture: the monitor advertises the class (`max_inst = 60`) and grants `POLL_EXT_ENUM`
when asked.
:::

## Practical notes

- **Enumerate every session.** Handles are not stable across associations, and the
  inventory reflects what is *currently* being measured — plug in a CO₂ module and
  the next association has an extra object.
- **An empty class is not an error.** A monitor with no invasive lines simply has no
  pressure objects.
- **Waveform objects appear before you subscribe.** Enumeration shows the waveform
  exists; it does not put it on the priority list. Samples only start after
  {meth}`~intellipy.client.IntellivueClient.set_wave_priority`.
- **A refused class costs no time.** A Remote Operation Error is treated as one class
  that will never answer, so an enumeration poll declined by an older monitor does not
  burn the whole timeout. The error names no class, so refusals are counted rather
  than identified.
