"""End-to-end tests for *signal* enumeration against real captured replies.

Not to be confused with test_enumerations.py, which covers enumeration
*objects* (a metric class reporting a state). This file drives
``collect_enumeration`` and ``harvest_inventory`` over
``tests/data/enumeration_replies.hex`` -- genuine monitor traffic -- and pins
what the reference monitor actually reports.

Two facts about that monitor drive most of the expectations, and both were
learned the hard way:

* **It is French-localised.** ``NOM_ATTR_ID_LABEL_STRING`` is display text, so
  SpO2 shows as ``SpO₂``, the arterial line as ``PA`` and the heart rate as
  ``FC``. Only the label *code* is stable across locales.
* **Objects span two MDS contexts**, so a handle alone is not unique; the
  inventory is keyed by ``(class, context, handle)``.
"""

import time

import pytest

from intellipy.enumerate import collect_enumeration, format_inventory, harvest_inventory

#: The three classes this capture's association actually polled. The default
#: (``CLASS_POLLS``) also includes ``NOM_MOC_VMO_METRIC_ENUM``, added in §4c,
#: which this monitor was never asked for -- see
#: :func:`test_a_class_that_never_answers_costs_the_whole_timeout`.
CAPTURED_CLASSES = (
    "NOM_MOC_VMO_METRIC_NU",
    "NOM_MOC_VMO_METRIC_SA_RT",
    "NOM_MOC_VMO_AL_MON",
)

#: The full inventory the reference capture yields: 20 numerics, 4 waveforms,
#: 1 alarm.
EXPECTED_COUNTS = {
    "NOM_MOC_VMO_METRIC_NU": 20,
    "NOM_MOC_VMO_METRIC_SA_RT": 4,
    "NOM_MOC_VMO_AL_MON": 1,
}

#: handle -> (description, display string). Real values, French display text.
EXPECTED_NUMERICS = {
    33459: ("Heart Rate", "FC"),
    33749: ("Arterial Oxigen Saturation", "SpO₂"),
    33756: ("Pulse Rate from Plethysmogram", "Pouls"),
    33466: ("Respiration Rate", "FR"),
    35098: ("Arterial Blood Pressure (ABP)", "PA"),
    33386: ("non-invasive blood pressure", "PB"),
}

EXPECTED_WAVES = {
    686: ("ECG Lead MCL", "MCL"),
    696: ("Imedance RESP wave", "Resp"),
    986: ("PLETH wave label", "Pleth"),
    2332: ("Arterial Blood Pressure (ABP)", "PA"),
}


@pytest.fixture(scope="module")
def inventory(codec, enumeration_payloads):
    return harvest_inventory(codec, enumeration_payloads)


def by_handle(inventory, kind):
    return {s.handle: s for s in inventory.values() if s.kind == kind}


# -- what the capture contains ---------------------------------------------


def test_inventory_has_twenty_five_signals(inventory):
    assert len(inventory) == 25


@pytest.mark.parametrize("oid_class, count", EXPECTED_COUNTS.items())
def test_signal_counts_per_object_class(inventory, oid_class, count):
    assert sum(1 for s in inventory.values() if s.oid_class == oid_class) == count


@pytest.mark.parametrize("handle, expected", EXPECTED_NUMERICS.items())
def test_numeric_labels(inventory, handle, expected):
    signal = by_handle(inventory, "numeric")[handle]
    assert (signal.label, signal.label_string) == expected


@pytest.mark.parametrize("handle, expected", EXPECTED_WAVES.items())
def test_wave_labels(inventory, handle, expected):
    signal = by_handle(inventory, "wave")[handle]
    assert (signal.label, signal.label_string) == expected


def test_the_alarm_object(inventory):
    alarms = [s for s in inventory.values() if s.kind == "alarm"]
    assert len(alarms) == 1
    assert alarms[0].handle == 33793


def test_units_come_through(inventory):
    """Units are printable text with the nomenclature name in parentheses."""
    waves = by_handle(inventory, "wave")
    assert waves[686].unit == "mV ( milli-volt )"
    assert waves[2332].unit == "mmHg ( mm mercury )"
    assert waves[696].unit == "Ohm ( Ohm )"


# -- the two properties that shaped the design -----------------------------


def test_objects_span_two_mds_contexts(inventory):
    """A handle is only unique within its MDS context.

    Both contexts are populated here, so keying the inventory by handle alone
    would silently merge distinct objects.
    """
    contexts = {s.mds_context for s in inventory.values()}
    assert contexts == {0, 1}

    numerics = by_handle(inventory, "numeric")
    assert numerics[33459].mds_context == 1
    assert numerics[35098].mds_context == 0


def test_display_strings_are_localised_but_codes_are_not(inventory):
    """The same code appears under different display text than English.

    ``NOM_ATTR_ID_LABEL`` for the arterial line resolves to the English
    description in the shipped table, while the monitor displays the French
    ``PA``. Subscribing on the display string is therefore locale-dependent;
    subscribing on the code is not (§6b).
    """
    wave = by_handle(inventory, "wave")[2332]
    assert wave.label_string == "PA"
    assert wave.label == "Arterial Blood Pressure (ABP)"
    assert wave.label_code == b"\x00\x02\x4a\x14"


def test_one_numeric_is_never_named_by_the_monitor(inventory):
    """Handle 33477 is reported with no label at all.

    Real behaviour, not a decode failure -- it is why ``set_wave_priority``
    has to raise rather than assume every object can be subscribed to.
    """
    assert by_handle(inventory, "numeric")[33477].label is None


# -- incremental merging ---------------------------------------------------


def test_labels_can_arrive_in_a_later_poll_cycle(codec, enumeration_payloads):
    """Two waves are first reported bare and only named by a later reply.

    An enumerator that stopped at the first reply for a class would report
    waves 686 and 696 as unlabelled. This is why ``harvest_inventory`` merges
    into an existing inventory instead of replacing it.
    """
    inventory = {}
    seen_unlabelled = False

    for payload in enumeration_payloads:
        harvest_inventory(codec, [payload], inventory=inventory)
        waves = by_handle(inventory, "wave")
        if 686 in waves and waves[686].label is None:
            seen_unlabelled = True

    assert seen_unlabelled, "expected wave 686 to appear before it is named"
    assert by_handle(inventory, "wave")[686].label == "ECG Lead MCL"


def test_merging_never_overwrites_a_label_with_nothing(codec, enumeration_payloads):
    """Once a signal is named, later bare replies must not blank it out.

    Later poll cycles carry values without metadata, so a naive merge would
    erase every label it had already collected.
    """
    inventory = harvest_inventory(codec, enumeration_payloads)
    named = {k: s.label for k, s in inventory.items() if s.label}

    harvest_inventory(codec, enumeration_payloads, inventory=inventory)

    assert {k: inventory[k].label for k in named} == named


# -- the collection loop ---------------------------------------------------


def test_collect_enumeration_replays_the_exchange(codec, enumeration_payloads):
    """The same routine the live client uses, driven off captured bytes.

    ``send`` is a sink and ``recv`` walks the fixture, which is the whole point
    of the callable-based design: pcap replay and a live socket run identical
    collection logic.
    """
    sent = []
    replies = iter(enumeration_payloads)

    inventory = collect_enumeration(
        sent.append,
        lambda: next(replies, b""),
        codec,
        classes=CAPTURED_CLASSES,
        timeout=5.0,
    )

    assert len(inventory) == 25
    assert len(sent) == 3  # one extended poll per object class


def test_collection_stops_on_the_final_reply_not_the_timeout(
    codec, enumeration_payloads
):
    """Every class closes, so the loop returns without spending its budget.

    If termination regressed to "wait for the timeout", this would take five
    seconds instead of none -- and against a live monitor it would stall every
    enumerate() call.
    """
    replies = iter(enumeration_payloads)

    def recv():
        try:
            return next(replies)
        except StopIteration:
            raise AssertionError("collection read past the final reply")

    inventory = collect_enumeration(
        lambda _: None, recv, codec, classes=CAPTURED_CLASSES, timeout=30.0
    )
    assert len(inventory) == 25


def test_polls_carry_distinct_poll_numbers(codec, enumeration_payloads):
    """Each class is polled under its own number so replies can be told apart."""
    sent = []
    replies = iter(enumeration_payloads)
    collect_enumeration(
        sent.append,
        lambda: next(replies, b""),
        codec,
        classes=CAPTURED_CLASSES,
        timeout=5.0,
    )

    assert len({bytes(p) for p in sent}) == len(sent)


def test_recv_failure_ends_collection_cleanly(codec):
    """A socket timeout is a normal end to the loop, not an error.

    Without this the client would propagate an OSError out of enumerate() on
    any monitor that simply stops replying.
    """

    def recv():
        raise TimeoutError

    assert collect_enumeration(lambda _: None, recv, codec, timeout=5.0) == {}


def test_a_class_that_never_answers_costs_the_whole_timeout(
    codec, enumeration_payloads
):
    """A silently-ignored poll can only be given up on by waiting.

    The default class list includes ``NOM_MOC_VMO_METRIC_ENUM``, and this
    capture's monitor was never asked for it, so no reply and no error ever
    arrives for that class. §4c handles an explicit ``RemoteOperationError``
    refusal, but silence is indistinguishable from a slow monitor, so the loop
    can only fall back on the timeout.

    Pinned because it is a real cost on any monitor predating software
    revision E.0: enumerate() returns a complete inventory but takes the full
    timeout to do it.
    """
    replies = iter(enumeration_payloads)
    started = time.monotonic()

    inventory = collect_enumeration(
        lambda _: None, lambda: next(replies, b""), codec, timeout=0.5
    )
    elapsed = time.monotonic() - started

    assert len(inventory) == 25
    assert elapsed >= 0.5


# -- presentation ----------------------------------------------------------


def test_format_inventory_lists_every_signal(inventory):
    """The CLI table returns a string rather than printing, so it is testable."""
    table = format_inventory(inventory)

    assert isinstance(table, str)
    for handle in list(EXPECTED_WAVES) + list(EXPECTED_NUMERICS):
        assert str(handle) in table
    assert "SpO₂" in table
