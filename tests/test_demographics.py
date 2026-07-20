"""Patient demographics: poll construction and reply parsing.

The fixture is frame 54 of ``reference/intellivue_enumeration.pcapng`` -- a real
``NOM_MOC_PT_DEMOG`` reply. The bed had been discharged, so every identifying
field is blank: this pins down the *structure* and the enumerated/unit fields,
but decoding of a populated record cannot be verified against this capture.
"""

from pathlib import Path

import pytest

from intellipy.client import _parse_demographics
from intellipy.enumerate import _iter_observations
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def codec():
    return IntellivueData()


@pytest.fixture(scope="module")
def reply(codec):
    raw = bytes.fromhex((DATA / "ptdemog_reply.hex").read_text().strip())
    return codec.readData(raw)


@pytest.fixture(scope="module")
def demographics(reply):
    observations = [obs for _, obs in _iter_observations(reply)]
    assert len(observations) == 1
    return _parse_demographics(observations[0])


def test_poll_targets_the_demographics_group(codec):
    """The poll must name the PT_DEMOG object and its attribute group.

    Compared against the capture's own request (frame 53); the two differ only
    in the caller-chosen invoke_id and poll_number.
    """
    poll = bytes(codec.writeData("MDSPatientDemographicsPoll"))
    captured = bytes.fromhex(
        "e10000020001001c03ea00070016002100000000000000000c16"
        "000800000001002a0807"
    )

    # NOM_MOC_PT_DEMOG (0x002a) under NOM_ATTR_GRP_PT_DEMOG (0x0807)
    assert poll.endswith(bytes.fromhex("0001002a0807"))

    # invoke_id (bytes 8:10) and poll_number (bytes 28:30) are the caller's to
    # choose; everything else must match the monitor's own request byte for byte.
    assert len(poll) == len(captured)
    blank = slice(8, 10), slice(28, 30)
    normalise = bytearray(poll), bytearray(captured)
    for buffer in normalise:
        for field in blank:
            buffer[field] = b"\x00\x00"
    assert normalise[0] == normalise[1]
    assert poll[28:30] != b"\x00\x00"  # a poll number is actually set


def test_reply_is_a_single_poll_result(codec, reply):
    raw = bytes.fromhex((DATA / "ptdemog_reply.hex").read_text().strip())
    assert codec.getMessageType(raw) == "MDSSinglePollActionResult"
    assert reply["PollMdibDataReply"]["Type"]["OIDType"] == "NOM_MOC_PT_DEMOG"


@pytest.mark.parametrize(
    "attribute",
    [
        "NOM_ATTR_PT_ID",
        "NOM_ATTR_PT_NAME_FAMILY",
        "NOM_ATTR_PT_NAME_GIVEN",
        "NOM_ATTR_PT_DOB",
        "NOM_ATTR_PT_SEX",
        "NOM_ATTR_PT_AGE",
        "NOM_ATTR_PT_HEIGHT",
        "NOM_ATTR_PT_WEIGHT",
        "NOM_ATTR_PT_BSA",
        "NOM_ATTR_PT_TYPE",
        "NOM_ATTR_PT_DEMOG_ST",
        "NOM_ATTR_PT_PACED_MODE",
        "NOM_ATTR_PT_ID_INT",
    ],
    ids=lambda name: name.removeprefix("NOM_ATTR_PT_"),
)
def test_attribute_is_recognised(demographics, attribute):
    """Every PT_* attribute the monitor sent is decoded, not skipped."""
    assert attribute in demographics["attributes"]["AVAType"]


def test_internal_patient_id_wins_the_oid_collision(demographics):
    """0xF001 is PT_ID_INT here, not POLL_PROFILE_EXT.

    The same code means different attributes in different object classes; only
    the polled class disambiguates them.
    """
    ava = demographics["attributes"]["AVAType"]
    assert "NOM_ATTR_POLL_PROFILE_EXT" not in ava
    assert ava["NOM_ATTR_PT_ID_INT"]["AttributeValue"]["raw"].hex() == (
        "0009fb70d80b1c217f4c"
    )


def test_discharged_bed_reports_no_identifiers(demographics):
    assert demographics["state"] == "DISCHARGED"
    assert demographics["handle"] == 80
    assert demographics["patient_id"] is None
    assert demographics["name_given"] is None
    assert demographics["name_family"] is None
    assert demographics["dob"] is None


def test_enumerated_fields_decode_to_names(demographics):
    assert demographics["sex"] == "SEX_UNKNOWN"
    assert demographics["patient_type"] == "ADULT"
    assert demographics["paced_mode"] == "PAT_NOT_PACED"
    assert demographics["bsa_formula"] == "BSA_FORMULA_DUBOIS"


@pytest.mark.parametrize(
    ("field", "unit"),
    [
        ("age", "years"),
        ("height", "cm"),
        ("weight", "kg"),
        ("bsa", "m2"),
    ],
)
def test_measures_are_unset_but_carry_their_unit(demographics, field, unit):
    """Unset measures send the IEEE-1073 NaN code yet still name their unit."""
    value, reported_unit = demographics[field]
    assert value is None
    assert reported_unit.startswith(unit)
