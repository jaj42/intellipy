# Real-time processing

Where {doc}`record` stores everything and analyses nothing, this does the opposite:
consume {meth}`~intellipy.client.IntellivueClient.stream` as a generator, keep one
waveform, and run an algorithm over it as the samples arrive.

The example is `examples/realtime_algorithm.py`, and it needs no monitor to try:

```console
$ uv run python examples/realtime_algorithm.py --simulate --duration 6
t=    0.85s  HR=  72.1 bpm
t=    1.68s  HR=  72.1 bpm
t=    2.51s  HR=  72.1 bpm
...
```

`--simulate` synthesises a plethysmogram in the client's own sample schema and runs
the identical pipeline, so the detector can be exercised — and tested — without
hardware. Against a real monitor:

```console
$ uv run python examples/realtime_algorithm.py --wave Pleth --duration 60
```

## The pipeline

The whole program is generators over generators, so nothing is buffered beyond the few
seconds each moving window needs, and it runs in constant memory for an arbitrarily
long recording:

```python
samples = client.stream(duration=args.duration)   # dicts, all kinds
points  = wave_points(samples, "Pleth")           # → (time, value) pairs
feet    = detect_feet(points, sampling_rate)      # → times of pulse onsets
rates   = heart_rate(feet)                        # → (time, bpm)

for time, rate in rates:
    print(f"t={time:8.2f}s  HR={rate:6.1f} bpm")
```

`wave_points` does the flattening the schema invites: `stream()` yields waveform
*blocks* with parallel `time` and `wave` lists, and everything downstream wants a flat
sequence of points.

## Filtering to one waveform

A block's `label` is the SCADA type for a compound wave and the object label
otherwise; `object_label` always carries the object's own name. Match on both:

```python
def wave_points(samples, label):
    for sample in samples:
        if sample["kind"] != "wave":
            continue
        if label not in (sample["label"], sample.get("object_label")):
            continue
        yield from zip(sample["time"], sample["wave"])
```

## The algorithm

A pulse-foot detector, reduced from the author's `plethomap` project to its
essentials: differentiate twice, keep the upstrokes, square, integrate over a short
window, and call a beat wherever that energy rises above a slow-moving multiple of
itself.

The moving-window helpers — `mdiff`, `msum`, `mavg`, `mmed` — each take an iterable
and return a generator, so they chain without materialising anything.

Two details that matter more than the detector itself:

**Windows are sized in seconds, not samples.** `detect_feet` takes `sampling_rate` and
converts (0.24 s integration, 3 s adaptive threshold). `plethomap` hard-coded 125 Hz
sample counts, which silently misbehaves on ECG at 500 Hz or Resp at 62.5 Hz. Pass
`--rate`, or read the real rate off the client — it caches the sampling period per
handle as it decodes.

**Implausible intervals are dropped, not smoothed.** `heart_rate` discards anything
outside 25–250 bpm. A missed foot doubles an interval; that is a detection failure, and
averaging it into the output turns a detectable error into a plausible-looking wrong
number.

```{admonition} Verified how
:class: note

`--simulate` recovers the synthetic rate at 45, 72, 100 and 160 bpm as 44.9, 72.1,
100.0 and 159.6 — the residual is quantisation of the beat interval at 125 Hz. The
live path needs a monitor and has not been exercised here.
```

## Keeping up with the monitor

The generator only advances when you consume it, and the socket buffer is finite.
Slow processing means dropped packets — and over UDP, silently dropped ones.

Keep the per-sample path cheap. If the work is not cheap, get it off the receive
thread:

```python
import queue, threading

waves = queue.Queue()
threading.Thread(
    target=client.stream_to_queues,
    kwargs={"wave_queue": waves},
    daemon=True,
).start()

for sample in iter(waves.get, None):
    expensive_analysis(sample)
```

Now the receiving thread does nothing but decode and enqueue. An unbounded queue
converts "dropped packets" into "growing memory", which is at least visible; bound it
if you would rather drop deliberately than grow.

`queue_pipeline()` at the bottom of the example is a runnable sketch of this shape.

## The richer example

`plethomap`, the author's earlier project, drives the same data considerably further:
it locates the dicrotic notch to derive a continuous non-invasive blood pressure
(PlethoMAP), fans one stream out to several consumers with a queue-based `tee`, and
plots the result live in Qt.
{meth}`~intellipy.client.IntellivueClient.stream_to_queues` exists to drive exactly
that shape of pipeline: because `stream()` yields the sample schema those pipelines
already consume, they compose onto this client unchanged.

The examples here stay dependency-light on purpose — standard library and numpy, no
pandas, no Qt — so they can be read as protocol documentation rather than as an
application.
