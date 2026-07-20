"""Tests for how a waveform label survives the round trip to the monitor.

A poll reply names an object with ``NOM_ATTR_ID_LABEL``, a 32-bit nomenclature
code, and a priority list sends that same code back. In between, the codec
resolves the code to a readable description -- and that resolution is *lossy*:
34 of the 757 known codes share a description with another code, so a
description does not identify a code again.

Objects also carry ``NOM_ATTR_ID_LABEL_STRING``, the string the monitor itself
displays. That is localised (the reference capture's monitor is French) and is
not a key into the nomenclature table at all.

So neither readable form is a safe subscription key, and :class:`Signal` keeps
the raw code in ``label_code`` for that purpose. These tests pin down the two
ways the readable forms go wrong, and that the code path avoids both.
"""

import pytest

from intellipy.client import _wave_label
from intellipy.enumerate import Signal, harvest_inventory

#: The four waveforms in the reference capture: handle -> (code, description,
#: the string the French-localised monitor displays).
CAPTURED_WAVES = {
    686: ("0002014b", "ECG Lead MCL", "MCL"),
    696: ("00025000", "Imedance RESP wave", "Resp"),
    986: ("00024bb4", "PLETH wave label", "Pleth"),
    2332: ("00024a14", "Arterial Blood Pressure (ABP)", "PA"),
}


@pytest.fixture(scope="module")
def inventory(codec, enumeration_payloads):
    """The reference capture's inventory, harvested from the committed fixture."""
    return harvest_inventory(codec, enumeration_payloads)


@pytest.fixture(scope="module")
def waves(inventory):
    return {
        signal.handle: signal
        for signal in inventory.values()
        if signal.kind == "wave"
    }


# -- what the table cannot do ----------------------------------------------


def test_descriptions_do_not_identify_codes(codec):
    """Resolving a code to its description is not reversible for all codes.

    This is the reason `label_code` exists. If this ever comes out empty the
    description would be a safe key after all -- but it is not, and the failure
    is silent: the reverse lookup returns *a* valid code, just not the right
    one.
    """
    labels = codec.DataKeys["TextId"]
    codes = {key: value for key, value in labels.items() if isinstance(key, bytes)}

    ambiguous = [code for code, text in codes.items() if labels.get(text) != code]

    assert len(ambiguous) == 34
    # A concrete pair: two distinct codes, both described "Oxigen Saturation".
    assert codes[bytes.fromhex("0002f1c0")] == "Oxigen Saturation"
    assert codes[bytes.fromhex("0002f1d4")] == "Oxigen Saturation"
    assert labels["Oxigen Saturation"] == bytes.fromhex("0002f1d4")


def test_monitor_display_strings_are_not_table_keys(codec, waves):
    """The capture's monitor displays names the nomenclature table never has.

    ``PA`` (pression artérielle) is absent, so looking it up raises; the other
    three happen to coincide with English short labels. A subscription keyed on
    what the monitor displays is therefore a coin toss.
    """
    labels = codec.DataKeys["TextId"]

    assert "PA" not in labels
    assert waves[2332].label_string == "PA"

    with pytest.raises(KeyError):
        codec.writeData("MDSSetPriorityListWAVE", {"TextIdLabel": ["PA"]})


def test_a_display_string_can_resolve_to_an_unrelated_signal(codec, inventory):
    """Worse than missing: present, and meaning something else entirely.

    The monitor's non-invasive blood pressure displays as ``PB`` (pression
    brassard). ``PB`` *is* in the table -- as Barometric Pressure.
    """
    nibp = next(
        signal for signal in inventory.values() if signal.handle == 33386
    )
    assert nibp.label_string == "PB"
    assert nibp.label == "non-invasive blood pressure"

    labels = codec.DataKeys["TextId"]
    assert labels["PB"] == bytes.fromhex("0002f06b")
    assert labels[bytes.fromhex("0002f06b")] == "Barometric Pressure = Ambient Pressure"
    assert labels["PB"] != nibp.label_code


# -- what the code path does ------------------------------------------------


def test_enumeration_keeps_the_raw_label_code(waves):
    """Every waveform in the capture is enumerated with its 32-bit code."""
    assert set(waves) == set(CAPTURED_WAVES)

    for handle, (code, description, displayed) in CAPTURED_WAVES.items():
        signal = waves[handle]
        assert signal.label_code == bytes.fromhex(code)
        assert signal.label == description
        assert signal.label_string == displayed


def test_signals_subscribe_by_code(codec, waves):
    """Feeding `Signal` objects back sends exactly the codes that came in."""
    ordered = [waves[handle] for handle in sorted(CAPTURED_WAVES)]

    message = codec.writeData(
        "MDSSetPriorityListWAVE",
        {"TextIdLabel": [_wave_label(signal) for signal in ordered]},
    )

    expected = b"".join(
        bytes.fromhex(CAPTURED_WAVES[handle][0]) for handle in sorted(CAPTURED_WAVES)
    )
    assert message.endswith(expected)


def test_the_arterial_wave_is_now_subscribable(codec, waves):
    """The regression this whole change is about.

    Handle 2332 displays as ``PA``, which used to raise `KeyError` when fed
    back. By code it subscribes like any other.
    """
    message = codec.writeData(
        "MDSSetPriorityListWAVE", {"TextIdLabel": [_wave_label(waves[2332])]}
    )
    assert message.endswith(bytes.fromhex("00024a14"))


def test_codes_and_names_produce_identical_messages(codec):
    """A name that *is* a table key encodes the same as the code it resolves to."""
    by_name = codec.writeData("MDSSetPriorityListWAVE", {"TextIdLabel": ["Pleth"]})
    by_code = codec.writeData(
        "MDSSetPriorityListWAVE", {"TextIdLabel": [bytes.fromhex("00024bb4")]}
    )
    by_int = codec.writeData("MDSSetPriorityListWAVE", {"TextIdLabel": [0x00024BB4]})

    assert by_name == by_code == by_int


def test_unnamed_signal_cannot_be_subscribed():
    """An object the monitor never labelled is refused, not sent as garbage.

    The capture has one such numeric (handle 33477); a waveform could equally
    turn up unnamed.
    """
    unnamed = Signal(
        kind="wave",
        oid_class="NOM_MOC_VMO_METRIC_SA_RT",
        mds_context=0,
        handle=33477,
    )
    with pytest.raises(ValueError, match="no label code"):
        _wave_label(unnamed)


def test_plain_names_still_pass_through():
    """Strings are handed to the codec untouched, so named subscription works."""
    assert _wave_label("Pleth") == "Pleth"
    assert _wave_label(bytes.fromhex("00024bb4")) == bytes.fromhex("00024bb4")
