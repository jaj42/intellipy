"""Tests for the real-time example's signal-processing helpers.

``examples/realtime_algorithm.py`` is the one place in the project doing
numerical work rather than protocol work, so it is tested on synthetic
waveforms with known answers rather than on captured data.

The helpers are all lazy generators, carried over from the author's earlier
``plethomap`` project. Two properties matter and are easy to get wrong:

* **Each one changes the length of the stream.** ``mdiff`` yields one fewer
  than it consumes; a centred moving window drops ``n // 2`` from the front.
  Getting this wrong does not crash -- it shifts every detected time, which
  shows up as a plausible-but-wrong heart rate.
* **They must stay lazy**, since they run on an unbounded live stream.

The example is imported by path: ``examples/`` ships as sample code, not as
part of the installed package.
"""

import importlib.util
import math
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"


def load_example(name):
    """Import an example script by path."""
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def algo():
    return load_example("realtime_algorithm")


# -- moving-window helpers -------------------------------------------------


def test_mdiff_yields_successive_differences(algo):
    assert list(algo.mdiff([1, 2, 4, 8])) == [1, 2, 4]


def test_mdiff_yields_one_fewer_than_it_consumes(algo):
    """The length change the foot-time alignment has to compensate for."""
    assert len(list(algo.mdiff(range(10)))) == 9


@pytest.mark.parametrize("values", [[], [5]])
def test_mdiff_of_too_short_a_stream_is_empty(algo, values):
    assert list(algo.mdiff(values)) == []


def test_msum_is_a_trailing_window(algo):
    """The window fills as it goes, so early outputs cover fewer values."""
    assert list(algo.msum([1, 2, 3, 4], 2)) == [1, 3, 5, 7]


def test_msum_centred_drops_the_leading_half_window(algo):
    """Centring shifts the output back by ``n // 2`` inputs.

    That is what keeps a smoothed feature aligned with the sample it came
    from, and it is why the detector does not have to correct for the
    smoothing window separately.
    """
    assert list(algo.msum(range(6), 4, center=True)) == [2, 5, 9, 14]
    assert len(list(algo.msum(range(10), 4, center=True))) == 8


def test_mavg_divides_by_the_window_not_the_fill(algo):
    """Note the ramp: early outputs are averages over a partly-empty window.

    Real behaviour, not a bug -- but it means the first ``n`` outputs of a
    moving average understate the signal, which is why the detector waits for
    its threshold window to fill before trusting it.
    """
    assert list(algo.mavg([4, 4, 4, 4], 2)) == [2.0, 4.0, 4.0, 4.0]


def test_mmed_ignores_an_outlier_that_mavg_follows(algo):
    """Why ``mmed`` exists: it is the swap for ``mavg`` on noisy signals.

    One sample 100x the rest moves the moving average for the whole width of
    the window and leaves the median untouched.
    """
    values = [1, 1, 1, 100, 1, 1, 1]

    assert max(algo.mmed(values, 5)) == 1
    assert max(algo.mavg(values, 5)) > 20


def test_a_partly_filled_median_window_can_straddle_the_outlier(algo):
    """The ramp is not outlier-proof, though -- only the filled window is.

    While the window is still filling it is briefly even-length, and the median
    of ``[1, 100]`` is 50.5. So ``mmed`` protects the steady state, not the
    first ``n`` outputs. Pinned because it is the kind of edge that looks like
    a detection glitch at the start of a recording.
    """
    assert 50.5 in list(algo.mmed([1, 1, 1, 100, 1, 1, 1], 5, center=True))


@pytest.mark.parametrize("helper", ["mdiff", "msum", "mavg", "mmed"])
def test_helpers_are_lazy(algo, helper):
    """They run on an unbounded live stream, so none may materialise it.

    Passing an infinite iterator and taking a few values would hang if any of
    them called ``list()`` internally.
    """
    from itertools import count, islice

    function = getattr(algo, helper)
    stream = function(count()) if helper == "mdiff" else function(count(), 4)
    assert len(list(islice(stream, 5))) == 5


# -- pulse detection -------------------------------------------------------


def synthetic_wave(bpm, duration=20.0, rate=125.0):
    """The same pulse shape the example's ``--simulate`` mode generates."""
    period = 60.0 / bpm
    points = int(duration * rate)
    for index in range(points):
        time = index / rate
        phase = (time % period) / period
        yield time, math.sin(math.pi * phase**0.6) ** 3


@pytest.mark.parametrize("bpm", [45, 72, 100])
def test_detect_feet_finds_one_foot_per_beat(algo, bpm):
    """Foot count matches beat count across the normal range.

    The detector needs its threshold window to fill before it triggers, so a
    beat at either edge may be missed or added.
    """
    duration = 20.0
    feet = list(algo.detect_feet(synthetic_wave(bpm, duration), 125.0))
    expected = duration * bpm / 60.0

    assert expected - 1 <= len(feet) <= expected + 1


def test_detection_degrades_at_high_rates_but_the_rate_survives(algo):
    """At 160 bpm about a quarter of the feet are missed -- and it still reads 160.

    The 0.24 s integration window is a large fraction of a 0.375 s beat, so
    upstrokes start to blur together. What rescues the answer is the median in
    :func:`heart_rate`: a missed foot doubles one interval, and the median of
    the last five ignores it.

    Measured, not aspirational. It is the honest limit of this example's
    detector, and the reason it is an example rather than a clinical tool.
    """
    duration = 20.0
    feet = list(algo.detect_feet(synthetic_wave(160, duration), 125.0))
    expected = duration * 160 / 60.0

    assert 0.7 * expected <= len(feet) < 0.85 * expected

    rates = [rate for _, rate in algo.heart_rate(iter(feet))]
    assert rates[-1] == pytest.approx(160, abs=2.0)


def test_detected_feet_are_monotonic(algo):
    feet = list(algo.detect_feet(synthetic_wave(72), 125.0))
    assert feet == sorted(feet)
    assert len(set(feet)) == len(feet)


@pytest.mark.parametrize("bpm", [45, 72, 100, 160])
def test_heart_rate_recovers_the_synthetic_rate(algo, bpm):
    """End to end, wave in and bpm out.

    The tolerance is 2 bpm: the beat interval can only land on a 125 Hz sample
    boundary, which is worth about 1 bpm at these rates.
    """
    feet = algo.detect_feet(synthetic_wave(bpm, duration=30.0), 125.0)
    rates = [rate for _, rate in algo.heart_rate(feet)]

    assert rates
    assert rates[-1] == pytest.approx(bpm, abs=2.0)


def test_detect_feet_scales_its_windows_with_the_sampling_rate(algo):
    """The same waveform at half the rate gives the same beats.

    Windows are sized in seconds, not samples, so the detector works on ABP
    (125 Hz) and Resp (62.5 Hz) as well as Pleth -- unlike plethomap's
    125 Hz-hardcoded original.
    """
    fast = list(algo.detect_feet(synthetic_wave(72, 30.0, 125.0), 125.0))
    slow = list(algo.detect_feet(synthetic_wave(72, 30.0, 62.5), 62.5))

    assert len(fast) == pytest.approx(len(slow), abs=1)


def test_flat_signal_produces_no_beats(algo):
    """A disconnected sensor must not manufacture a heart rate."""
    flat = ((index / 125.0, 0.0) for index in range(2500))
    assert list(algo.detect_feet(flat, 125.0)) == []


# -- rate smoothing --------------------------------------------------------


def test_heart_rate_is_the_median_of_recent_intervals(algo):
    """Exactly one beat per second is 60 bpm."""
    feet = [float(second) for second in range(10)]
    rates = [rate for _, rate in algo.heart_rate(feet)]

    assert rates
    assert all(rate == pytest.approx(60.0) for rate in rates)


def test_a_missed_foot_is_dropped_not_smoothed(algo):
    """A doubled interval is a detection error, so it must not pull the rate.

    Here one foot is missing, doubling one interval to 2 s (30 bpm). That is
    inside the physiologic range, so it is not filtered by bounds -- the median
    is what keeps it from moving the answer.
    """
    feet = [0.0, 1.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    rates = [rate for _, rate in algo.heart_rate(feet)]

    assert rates[-1] == pytest.approx(60.0)


@pytest.mark.parametrize("interval", [0.2, 3.0])
def test_implausible_intervals_are_discarded(algo, interval):
    """Outside 25-250 bpm nothing is emitted at all."""
    feet = [index * interval for index in range(6)]
    assert list(algo.heart_rate(feet, low=25.0, high=250.0)) == []


def test_zero_and_negative_intervals_do_not_divide_by_zero(algo):
    """Duplicate timestamps must not raise."""
    assert list(algo.heart_rate([1.0, 1.0, 1.0])) == []


def test_heart_rate_of_no_feet_is_empty(algo):
    assert list(algo.heart_rate([])) == []


# -- the sample-stream adapter ---------------------------------------------


def test_track_waveform_flattens_blocks_to_pairs(algo):
    """Wave samples arrive as blocks; the detector wants a flat point stream."""
    samples = [
        {"kind": "wave", "label": "Pleth", "time": [0.0, 0.1], "wave": [1.0, 2.0],
         "sampling_rate": 10.0},
        {"kind": "wave", "label": "Pleth", "time": [0.2], "wave": [3.0],
         "sampling_rate": 10.0},
    ]
    rate, points = algo.track_waveform(samples, "Pleth")
    assert rate == 10.0
    assert list(points) == [
        (0.0, 1.0),
        (0.1, 2.0),
        (0.2, 3.0),
    ]


def test_track_waveform_ignores_other_signals(algo):
    """A stream carries every subscribed signal, so filtering is the caller's job."""
    samples = [
        {"kind": "wave", "label": "ABP", "time": [0.0], "wave": [9.0],
         "sampling_rate": 50.0},
        {"kind": "wave", "label": "Pleth", "time": [0.1], "wave": [1.0],
         "sampling_rate": 125.0},
        {"kind": "numeric", "label": "Pleth", "time": 0.2, "value": 5.0},
    ]
    rate, points = algo.track_waveform(samples, "Pleth")
    assert rate == 125.0
    assert list(points) == [(0.1, 1.0)]


def test_track_waveform_picks_the_first_waveform_when_label_is_none(algo):
    samples = [
        {"kind": "wave", "label": "ABP", "object_label": "ABP", "time": [0.0],
         "wave": [9.0], "sampling_rate": 50.0},
    ]
    rate, points = algo.track_waveform(samples, None)
    assert rate == 50.0
    assert list(points) == [(0.0, 9.0)]


def test_track_waveform_raises_without_a_sampling_rate(algo):
    """The first cycle carries the rate; a stream that skips it can't be sized."""
    samples = [
        {"kind": "wave", "label": "Pleth", "time": [0.0], "wave": [1.0],
         "sampling_rate": None},
    ]
    with pytest.raises(RuntimeError):
        algo.track_waveform(samples, "Pleth")


def test_track_waveform_raises_if_the_stream_ends_first(algo):
    with pytest.raises(RuntimeError):
        algo.track_waveform([], "Pleth")


def test_simulated_samples_match_the_client_schema(algo):
    """The simulator has to be substitutable for a real stream.

    If these keys drift from what ``IntellivueClient.stream()`` yields, the
    ``--simulate`` mode stops testing the same code path the live mode runs.
    """
    samples = list(algo.simulated_samples(duration=1.0, rate=125.0))

    assert samples
    for sample in samples:
        assert sample["kind"] == "wave"
        assert set(sample) >= {
            "kind", "label", "handle", "time", "wave", "unit", "sampling_rate"
        }
        assert sample["sampling_rate"] == 125.0
        assert len(sample["time"]) == len(sample["wave"])

    assert sum(len(s["wave"]) for s in samples) == 125


def test_simulated_samples_run_forever_when_duration_is_none(algo):
    """``--duration`` defaults to None, so the simulator must not precompute a length."""
    stream = algo.simulated_samples(duration=None, rate=125.0)
    first_hundred = [next(stream) for _ in range(100)]
    assert len(first_hundred) == 100
