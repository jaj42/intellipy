# Subscribing and recording

{doc}`quickstart` runs the recorder; this page covers what it writes, how to change
that, and the things that bite on long recordings.

The full script is `examples/dump_to_file.py`.

## The flow

```python
from intellipy.client import IntellivueClient

with IntellivueClient("udp", timeout=5.0) as client:
    client.associate()
    signals = client.enumerate()

    waves = [s for s in signals if s.kind == "wave"]
    client.set_wave_priority([str(s.label) for s in waves[:2]])

    for sample in client.stream(duration=600):
        record(sample)
```

Subscription is a single call and takes effect immediately; the reply
(`MDSSetPriorityListResult`) is returned if the monitor confirms within the timeout,
`None` if it does not. `None` is not conclusive — the list may still have been set —
so check with {meth}`~intellipy.client.IntellivueClient.get_priority_list` if it
matters.

**How many waveforms?** Each is a continuous stream: ECG at 500 Hz, Pleth and ABP at
125 Hz, Resp at 62.5 Hz. Over UDP a handful is fine; over RS232 the link is the
constraint. Ask only for what you will use — the monitor is doing this work alongside
its clinical function.

## Output formats

The example writes one file per sample kind, chosen to match the shape of the data:

**`numerics.csv`** — one row per value, `time,label,handle,value,unit`. Numerics are
flat and regular, so CSV is the right fit and the file opens in anything.

**`waves.jsonl`** — one JSON object per *block*, not per sample:

```json
{"kind": "wave", "label": "NOM_ECG_ELEC_POTL_II", "object_label": "ECG Lead MCL",
 "handle": 686, "time": [12.372, 12.374], "wave": [-0.04, -0.035],
 "unit": "mV ( milli-volt )"}
```

Keeping blocks intact preserves the arrival structure, and JSON Lines can be appended
to and read back a line at a time. Flatten at analysis time:

```python
import json

with open("recording/waves.jsonl") as handle:
    for line in handle:
        block = json.loads(line)
        for t, v in zip(block["time"], block["wave"]):
            ...
```

**`alarms.jsonl`** — one object per active alarm *per poll cycle*. The monitor reports
the current alarm list, not transitions, so an alarm active for a minute appears many
times. De-duplicate on `(code, source, state)` if you want events.

**`enumerations.jsonl`** — ECG rhythm and ectopic status.

**`demographics.json`** — the patient record, written once, separately. See
{doc}`demographics`.

## Timestamps

`time` is seconds since the association's relative-time origin. To anchor a recording
to wall-clock time, capture the absolute time reported at association:

```python
client.associate()
origin = client.initial_time          # BCD: century, year, month, day, hour, ...
```

Waveform blocks carry per-sample times reconstructed from the sampling period, so
`time[i]` is the time of `wave[i]`. Both are already in seconds and the values are
already scaled to physical units.

:::{note}
Timestamps come from the monitor's clock, not the host's, and the two will drift over
a long recording. If you are merging with another data source, record the offset at
the start *and* at the end rather than assuming it holds.
:::

## Writing your own recorder

`stream()` yields plain dicts, so anything that consumes dicts works. To route by kind:

```python
for sample in client.stream(duration=None):
    match sample["kind"]:
        case "numeric":     numerics.writerow(sample)
        case "wave":        waves.write(json.dumps(sample) + "\n")
        case "alarm":       alarms.write(json.dumps(sample) + "\n")
        case "enumeration": enums.write(json.dumps(sample) + "\n")
```

Three things `Recorder` in the example does deliberately, and that are worth copying:

- **Open the files before streaming starts**, so a permissions or disk problem
  surfaces immediately rather than a minute into a recording you cannot repeat.
- **Flush after every write.** Recordings end with Ctrl-C far more often than they end
  cleanly, and an unflushed buffer loses the last few seconds.
- **Serialise with `default=str`.** Some decoded fields are bytes or enum names that
  `json.dumps` will not take.

## Recording open-endedly

`duration=None` streams until the monitor aborts or you stop consuming:

```python
for sample in client.stream():
    if should_stop():
        break
    record(sample)
```

Keep-alives are handled internally, paced off the last message *sent*, so a quiet
monitor does not drop the association. Over a long run, expect:

- **Gaps.** UDP loses packets; a lost block is gone, not retransmitted. Waveform
  timestamps are the only reliable way to detect this — check for jumps rather than
  assuming continuity.
- **Objects appearing and disappearing.** Plugging in a module adds objects mid-stream.
  New handles simply start showing up; re-enumerate if you need their metadata.
- **Aborts.** An `AssociationAbort` ends the generator normally, not with an
  exception. If the loop returns much earlier than `duration` asked for, that is why —
  reconnect by building a fresh client.

## Multiple consumers

To fan one stream out to several threads — a recorder and a live display, say — use
{meth}`~intellipy.client.IntellivueClient.stream_to_queues`:

```python
import queue, threading

numerics, waves = queue.Queue(), queue.Queue()
threading.Thread(
    target=client.stream_to_queues,
    kwargs={"numeric_queue": numerics, "wave_queue": waves, "duration": 600},
    daemon=True,
).start()

for sample in iter(waves.get, None):     # None sentinel ends the loop
    ...
```

Each queue receives a `None` sentinel when the stream ends, so `iter(q.get, None)`
terminates by itself. Samples whose queue is `None` are dropped, which is how you
subscribe a consumer to one kind only.
