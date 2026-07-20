#!/usr/bin/env python3
"""Derive a metric from a live waveform, beat by beat.

Where ``intellipy-dump`` stores everything and analyses nothing, this example
does the opposite: it consumes :meth:`~intellipy.client.IntellivueClient.stream`
as a generator, keeps a single waveform, and runs a small streaming algorithm
over it -- detecting the foot of each pulse and printing the instantaneous
heart rate as the beats arrive.

    uv run python examples/realtime_algorithm.py --wave Pleth
    uv run python examples/realtime_algorithm.py --simulate    # no monitor needed

Everything below is written as generators over generators, so no waveform
history is buffered beyond the few seconds each moving window needs and the
pipeline runs in constant memory for arbitrarily long recordings.

The algorithm is the pulse-foot detector from the author's `plethomap`
project, reduced to its essentials: differentiate twice, keep the upstrokes,
square, integrate over a short window, and call a beat wherever that energy
rises above a slow-moving multiple of itself. `plethomap` goes considerably
further with the same data -- locating the dicrotic notch to derive a
continuous non-invasive blood pressure (PlethoMAP), fanning one stream out to
several consumers with a queue-based ``tee``, and plotting it all live in Qt.
:meth:`~intellipy.client.IntellivueClient.stream_to_queues` exists to drive
exactly that shape of pipeline; see `queue_pipeline` at the bottom of this
file for how the two connect.
"""

import argparse
import math
import sys
from collections import deque
from itertools import islice, tee
from operator import itemgetter
from statistics import median

# -- moving-window helpers -------------------------------------------------
#
# Each takes an iterable and returns a generator, so they chain without
# materialising anything. Windowed ones emit one value per input value once
# their buffer has filled, and partial sums before that.


def mdiff(values):
    """Successive differences. Yields one value fewer than it consumes."""
    stream = iter(values)
    try:
        previous = next(stream)
    except StopIteration:
        return
    for current in stream:
        yield current - previous
        previous = current


def msum(values, n, center=False):
    """Moving sum over `n` values.

    Parameters
    ----------
    values: iterable of float
    n: int
        Window length in samples.
    center: bool
        Skip the first ``n // 2`` inputs so each output is centred on its
        input rather than trailing it.

    """
    stream = islice(iter(values), n // 2, None) if center else iter(values)
    window = deque(maxlen=n)
    for current in stream:
        window.append(current)
        yield sum(window)


def mavg(values, n, center=False):
    """Moving average over `n` values."""
    return (total / n for total in msum(values, n, center))


def mmed(values, n, center=False):
    """Moving median over `n` values -- outlier-tolerant where `mavg` is not."""
    stream = islice(iter(values), n // 2, None) if center else iter(values)
    window = deque(maxlen=n)
    for current in stream:
        window.append(current)
        yield median(window)


# -- pulse detection --------------------------------------------------------

#: Moving-window lengths, in seconds. The integration window is roughly one
#: upstroke; the threshold window spans several beats so the threshold tracks
#: signal amplitude without following an individual beat.
INTEGRATION_WINDOW = 0.24
THRESHOLD_WINDOW = 3.0

#: How far above the recent mean energy a beat has to rise. Below ~1.2 noise
#: starts triggering; well above ~2 weak pulses are missed.
THRESHOLD_MULTIPLIER = 1.5


def detect_feet(points, sampling_rate,
                integration_window=INTEGRATION_WINDOW,
                threshold_window=THRESHOLD_WINDOW,
                multiplier=THRESHOLD_MULTIPLIER):
    """Yield the time of each pulse foot in a waveform.

    The foot -- the start of the upstroke -- is used rather than the peak
    because it is the sharpest feature of a plethysmogram and the least
    affected by damping.

    The signal is differentiated twice and negative first derivatives are
    zeroed, so only accelerating upstrokes survive; squaring and integrating
    turns each upstroke into an energy bump. A bump counts as a beat when it
    exceeds `multiplier` times the average energy of the last
    `threshold_window` seconds, and the foot is placed at the bump's maximum.
    Because the threshold is derived from the signal itself, no calibration or
    absolute amplitude is needed.

    Parameters
    ----------
    points: iterable of (float, float)
        ``(time, value)`` pairs, in order.

    sampling_rate: float
        Samples per second, used to size the moving windows.

    integration_window, threshold_window: float
        Window lengths in seconds.

    multiplier: float
        Threshold as a multiple of recent mean energy.

    Yields
    ------
    float
        Time of a pulse foot, in the same units as the input times.

    """
    integration_n = max(int(integration_window * sampling_rate), 1)
    threshold_n = max(int(threshold_window * sampling_rate), 1)

    timed, valued = tee(iter(points))
    # Two differentiations consume two samples, so drop two times to keep the
    # remaining streams aligned with the samples they describe. `msum`'s
    # centring already compensates for the integration window itself.
    times = islice(map(itemgetter(0), timed), 2, None)
    values = map(itemgetter(1), valued)

    first = mdiff(values)
    first_a, first_b = tee(first)
    second = mdiff(first_a)
    # Keep acceleration only where the signal is also rising: this is what
    # separates the upstroke from the (equally sharp) downstroke.
    upstroke = (
        acceleration * (slope > 0)
        for slope, acceleration in zip(first_b, second)
    )
    upstroke_a, upstroke_b = tee(upstroke)

    energy = msum((value * value for value in upstroke_a), integration_n, center=True)
    energy_a, energy_b = tee(energy)
    threshold = (mean * multiplier for mean in mavg(energy_a, threshold_n))

    inside_beat = False
    candidates = []
    for time, value, limit, acceleration in zip(
        times, energy_b, threshold, upstroke_b
    ):
        above = value > limit
        # The beat is emitted on the falling edge, once the whole bump has
        # been seen and its maximum is known.
        if inside_beat and not above:
            if candidates:
                yield max(candidates, key=itemgetter(1))[0]
                candidates.clear()
        elif above:
            candidates.append((time, acceleration))
        inside_beat = above


def heart_rate(feet, beats=5, low=25.0, high=250.0):
    """Yield ``(time, bpm)`` from a stream of pulse-foot times.

    A single beat-to-beat interval is noisy and one missed foot doubles it, so
    the rate is the median of the last `beats` intervals. Intervals outside
    the physiologic range are dropped rather than smoothed, since they are
    detection errors rather than measurements.

    Parameters
    ----------
    feet: iterable of float
        Pulse-foot times in seconds.

    beats: int
        How many intervals the median spans.

    low, high: float
        Plausible heart-rate bounds, in beats per minute.

    Yields
    ------
    (float, float)
        Time of the beat and the smoothed rate at that beat.

    """
    window = deque(maxlen=beats)
    previous = None
    for foot in feet:
        if previous is not None:
            interval = foot - previous
            if interval > 0:
                rate = 60.0 / interval
                if low <= rate <= high:
                    window.append(rate)
                    yield foot, median(window)
        previous = foot


# -- plumbing ---------------------------------------------------------------


def _matches(sample, wanted):
    return sample["kind"] == "wave" and wanted in (
        sample["label"], sample.get("object_label")
    )


def track_waveform(samples, label):
    """Split a sample stream into one waveform's rate and its points.

    `detect_feet` needs `sampling_rate` up front to size its windows, but the
    client only knows the real rate once the monitor has named it -- in the
    metadata carried by the *first* reply cycle (see
    :meth:`~intellipy.client.IntellivueClient.stream`). So the first matching
    sample is peeked here to read it, rather than taking it as a flag: a
    `--rate` argument could silently disagree with what the monitor is
    actually sending.

    Parameters
    ----------
    samples: iterable of dict
        Samples from :meth:`~intellipy.client.IntellivueClient.stream`.

    label: str or None
        Waveform to keep; None keeps the first waveform seen and sticks to it.

    Returns
    -------
    (float, iterator of (float, float))
        The waveform's sampling rate in Hz, and its flattened
        ``(time, value)`` points -- a wave sample carries a block of points,
        so the block structure is undone here.

    """
    wanted = label
    stream = iter(samples)
    for sample in stream:
        if sample["kind"] != "wave":
            continue
        if wanted is None:
            wanted = sample["label"]
            print(f"tracking waveform {wanted!r}", file=sys.stderr)
        if not _matches(sample, wanted):
            continue
        sampling_rate = sample["sampling_rate"]
        if not sampling_rate:
            raise RuntimeError(
                f"{wanted!r}: monitor has not reported a sampling rate yet"
            )
        first_points = list(zip(sample["time"], sample["wave"]))
        break
    else:
        raise RuntimeError(f"stream ended before any {wanted!r} sample arrived")

    def points():
        yield from first_points
        for sample in stream:
            if _matches(sample, wanted):
                yield from zip(sample["time"], sample["wave"])

    return sampling_rate, points()


def simulated_samples(duration, rate=125.0, bpm=72.0, block=64):
    """Fake a plethysmogram, so the pipeline can be run without a monitor.

    Produces the same sample dicts the client yields, `sampling_rate`
    included, so `track_waveform` needs no simulate-specific handling. The
    pulse shape is a skewed sine -- a fast upstroke and a slow decay -- which
    is crude, but carries the one feature the detector looks for.

    Parameters
    ----------
    duration: float or None
        Seconds to simulate; None runs forever, matching a live
        ``stream(duration=None)``.

    """
    period = 60.0 / bpm
    limit = None if duration is None else int(duration * rate)

    def values():
        index = 0
        while limit is None or index < limit:
            time = index / rate
            phase = (time % period) / period
            yield math.sin(math.pi * phase**0.6) ** 3
            index += 1

    stream = values()
    start = 0
    while True:
        chunk = list(islice(stream, block))
        if not chunk:
            return
        yield {
            "kind": "wave",
            "label": "Pleth",
            "object_label": "Pleth",
            "handle": 0,
            "time": [(start + offset) / rate for offset in range(len(chunk))],
            "wave": chunk,
            "unit": None,
            "sampling_rate": rate,
        }
        start += len(chunk)


def queue_pipeline(client, duration=None):
    """The queue-based alternative, for multi-consumer pipelines.

    Kept as a runnable sketch rather than wired into ``main``: this is the
    shape `plethomap` uses, where one waveform queue is teed to a plotting
    consumer and an analysis consumer that must not block each other.
    """
    from queue import Queue
    from threading import Thread

    wave_queue = Queue()
    Thread(
        target=client.stream_to_queues,
        kwargs={"wave_queue": wave_queue, "duration": duration},
        daemon=True,
    ).start()

    # `stream_to_queues` ends every queue with a None sentinel, so the
    # generator below terminates on its own when the stream stops.
    return iter(wave_queue.get, None)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Print a live heart rate derived from a monitor waveform.",
    )
    parser.add_argument(
        "--wave", default="Pleth", metavar="LABEL",
        help="waveform to analyse (default: Pleth)",
    )
    parser.add_argument(
        "--transport", choices=("udp", "rs232"), default="udp",
        help="how to reach the monitor (default: udp)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="monitor address for udp, serial device for rs232 "
             "(default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=24005,
        help="UDP port to bind (default: 24005)",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0,
        help="seconds any single read may block (default: 5)",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="seconds to run for (default: until interrupted with Ctrl-C)",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="run the algorithm on a synthetic waveform instead of a monitor",
    )
    return parser.parse_args(argv)


def run(points, sampling_rate):
    """Print a heart rate per beat, from a stream of ``(time, value)``."""
    for time, rate in heart_rate(detect_feet(points, sampling_rate)):
        print(f"t={time:8.2f}s  HR={rate:6.1f} bpm", flush=True)


def main(argv=None):
    args = parse_args(argv)

    if args.simulate:
        samples = simulated_samples(args.duration)
        try:
            sampling_rate, points = track_waveform(samples, "Pleth")
            run(points, sampling_rate)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
        return 0

    from intellipy.client import IntellivueClient

    options = {"timeout": args.timeout, "portAddress": args.host}
    if args.transport == "udp":
        options["portNumber"] = args.port

    with IntellivueClient(transport=args.transport, **options) as client:
        print("associating...", file=sys.stderr)
        client.associate()
        client.enumerate()
        client.set_wave_priority([args.wave])

        try:
            sampling_rate, points = track_waveform(
                client.stream(duration=args.duration), args.wave
            )
            run(points, sampling_rate)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
