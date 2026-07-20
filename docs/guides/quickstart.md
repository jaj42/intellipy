# Quickstart: record a minute of data

The shortest path from a monitor on the network to files on disk. Everything here
runs the `intellipy-dump` command (`intellipy.dump`), which is the reference for how
the pieces fit together — read it alongside this page.

```console
$ uv run intellipy-dump --duration 60 --all-waves --outdir recording
```

With a monitor broadcasting on the network, that associates, prints the signal
inventory, subscribes to every waveform it reports, records for sixty seconds and
writes:

```
recording/
  numerics.csv        time,label,handle,value,unit
  waves.jsonl         one JSON object per waveform block
  alarms.jsonl        one JSON object per active alarm, per poll cycle
  enumerations.jsonl  ECG rhythm / ectopic status changes
  demographics.json   the patient record (see the warning below)
```

## The same thing, written out

Nothing in the tool is hidden behind helpers; the whole flow is five calls.

```python
from intellipy.client import IntellivueClient

with IntellivueClient("udp", timeout=5.0) as client:
    client.associate()                      # 1. open the session

    signals = client.enumerate()            # 2. ask what it measures
    for signal in signals:
        print(signal)

    waves = [s for s in signals if s.kind == "wave"]
    client.set_wave_priority(waves[:1])               # 3. subscribe

    for sample in client.stream(duration=60):         # 4. consume
        print(sample["kind"], sample["label"], sample.get("value"))
# 5. released and closed by the context manager
```

Step by step:

**1. Associate.** Over UDP this blocks until the monitor's next broadcast, so it can
take a few seconds even when everything is right. See {doc}`../concepts/association`.

**2. Enumerate.** Handles are not stable across sessions, so do this every time rather
than hard-coding what you saw yesterday. See {doc}`enumeration`.

**3. Subscribe.** *Without this you get no waveforms* — the monitor's real-time
priority list starts empty. Numerics and alarms flow regardless.

:::{warning}
**Pass the `Signal` objects, not their names.** A label is a 32-bit code on the wire;
`set_wave_priority` sends the code the monitor itself reported
(`signal.label_code`). Naming a waveform instead means a table lookup that can fail
(`signal.label_string` is localised — `"PA"` on a French monitor raises `KeyError`)
or, worse, succeed as the wrong signal (that monitor's `"PB"` resolves to Barometric
Pressure). Names are for humans; codes are for the monitor.
:::

**4. Stream.** {meth}`~intellipy.client.IntellivueClient.stream` is a generator. It
sends the polls, handles keep-alives, and yields one dict per value. Stop consuming
and it stops; `duration` bounds it.

**5. Close.** The context manager sends the release request. Worth having: an
association left dangling occupies a session slot on the monitor until it times out.

## What a sample looks like

Illustrative, with the shapes and the code spellings a real monitor produces:

```python
{"kind": "numeric", "label": "Heart Rate", "handle": 33459,
 "time": 12.375, "value": 68.0,
 "unit": "bpm ( beats per minute used e.g. for HR/PULSE )"}

{"kind": "wave", "label": "NOM_ECG_ELEC_POTL_II", "object_label": "ECG Lead MCL",
 "handle": 686, "time": [12.372, 12.374, ...], "wave": [-0.04, -0.035, ...],
 "unit": "mV ( milli-volt )"}

{"kind": "alarm", "label": "patient_0", "handle": 33793, "time": 12.375,
 "code": "NOM_EVT_ECG_ASYSTOLE", "source": 33459, "alarm_type": ..., "state": ...,
 "text": ...}

{"kind": "enumeration", "label": "ECG Rhythm Status", "handle": ..., "time": 12.375,
 "state": "NOM_ECG_SINUS_RHY", "physio_id": ..., "value": None, "unit": None,
 "measurement_state": ...}
```

`time` is **seconds since the association was established**, not wall-clock. The
absolute time at that origin is in
{attr}`~intellipy.client.IntellivueClient.initial_time` if you need to anchor a
recording to the clock.

Waveform samples arrive in **blocks**, one per poll cycle, with `time` and `wave` as
parallel lists — per-sample timestamps reconstructed from the sampling period. Values
are already scaled to physical units.

## Useful options

```console
$ uv run intellipy-dump --help
```

| Option | Effect |
|---|---|
| `--duration N` | Seconds to record (default: until Ctrl-C) |
| `--wave LABEL` | Subscribe to this waveform; repeatable |
| `--all-waves` | Subscribe to every waveform the monitor reports |
| `--transport rs232 --host /dev/ttyUSB0` | Use the serial link |
| `--host 192.168.1.50` | Bind one interface instead of `0.0.0.0` |
| `--timeout N` | Seconds any single read may block (default 5) |
| `--no-demographics` | Do not request or write the patient record |

Ctrl-C stops a recording cleanly: the files are flushed after every write, so
everything received up to the interrupt is on disk.

:::{warning}
`demographics.json` contains **patient identifiers** — name, medical record number,
date of birth. It is written to its own file, separate from the signal streams, so it
can be handled or withheld independently. Pass `--no-demographics` if you do not need
it. See {doc}`demographics`.
:::

## When nothing arrives

| Symptom | Likely cause |
|---|---|
| `AssociationError: no ConnectIndicationEvent received` | Broadcasts are not reaching the host — wrong segment, firewall, or a router in between |
| Associates, but no waveform samples | The priority list was not set, or was set with a name the monitor's tables do not know |
| Numerics but the values are all `None` | Those objects are configured but not currently measuring |
| Everything stops after ~30 s | Keep-alive not being sent — only an issue in a hand-rolled loop, `stream()` handles it |
| Samples after the first cycle have `label: None` | Metadata is sent only in the first cycle and must be cached per handle; `stream()` does this, a custom decoder must too |

## Next

- {doc}`enumeration` — what the inventory means, and how to decode a capture offline
- {doc}`record` — the recorder in detail, and the file formats
- {doc}`realtime` — processing a waveform as it arrives instead of storing it
- {doc}`../concepts/index` — what any of these words mean
