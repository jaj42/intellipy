"""Tests for the three variable-length value readers.

``readString``
    UTF-16 text. The wire order is big-endian, which the reader gets to by
    swapping each byte pair and decoding the result as (BOM-less, therefore
    little-endian) UTF-16.

``readVariableLabel``
    A length followed by that many raw bytes, kept as a list of ints. Used for
    identifiers that are not text at all -- ``NOM_ATTR_SYS_ID`` is a 6-byte
    system id, not a string.

``readVariableData``
    A *byte* length followed by that many bytes read as 16-bit words -- so the
    element count is half the length. This is the waveform sample carrier.
"""

import pytest


def encode_string(text):
    """Build the wire form of a String attribute: uint16 byte length, UTF-16-BE."""
    encoded = text.encode("utf-16-be")
    return len(encoded).to_bytes(2, "big") + encoded


def read_string(codec, data):
    parsed = {}
    index = codec.readString(0, parsed, bytearray(data))
    return parsed["String"]["value"], index


# -- strings ---------------------------------------------------------------


@pytest.mark.parametrize("text", ["Pleth", "PA", "MCL", "Resp", "LeTemple_1"])
def test_round_trips_single_word_strings(codec, text):
    assert read_string(codec, encode_string(text)) == (text, 2 + 2 * len(text))


def test_decodes_non_ascii(codec):
    """Display strings are not ASCII: the capture's monitor sends SpO₂ and Δ."""
    assert read_string(codec, encode_string("SpO₂"))[0] == "SpO₂"
    assert read_string(codec, encode_string("ΔTemp"))[0] == "ΔTemp"


def test_length_is_in_bytes_not_characters(codec):
    """Two bytes per character, so a 5-character string declares length 10."""
    wire = encode_string("Pleth")
    assert wire[:2] == b"\x00\x0a"
    assert read_string(codec, wire)[1] == 12


def test_reads_at_the_caller_offset(codec):
    parsed = {}
    data = bytearray(b"\xde\xad" + encode_string("Pleth"))
    assert codec.readString(2, parsed, data) == 14
    assert parsed["String"]["value"] == "Pleth"


def test_empty_string(codec):
    assert read_string(codec, b"\x00\x00") == ("", 2)


def test_the_nul_terminator_and_its_padding_are_dropped(codec):
    """Fixed-width fields arrive NUL-terminated and space-padded.

    Both are encoding, not content, so neither reaches the caller. Real
    values: the capture's bed label is ``LeTemple_1`` followed by seven NULs,
    and its display labels are space-padded before the terminator
    (``'PA    \\x00'``).
    """
    assert read_string(codec, encode_string("LeTemple_1" + "\x00" * 7))[0] == (
        "LeTemple_1"
    )
    assert read_string(codec, encode_string("PA    \x00"))[0] == "PA"


def test_text_after_a_terminator_is_not_content(codec):
    """The string ends at the first NUL, whatever follows it in the field."""
    assert read_string(codec, encode_string("Resp\x00junk"))[0] == "Resp"


@pytest.mark.parametrize(
    "text",
    [
        "Jean Pierre",
        "van der Berg",
        "ABP Mean",
        "Non Invasive Blood Pressure",
        " leading",
    ],
)
def test_multi_word_strings_are_not_truncated(codec, text):
    """Regression test: everything from the first space used to be discarded.

    ``readString`` ended with ``.split(" ")[0]``, so a multi-word value lost
    its tail *inside the decoder*, where no caller could recover it. Patient
    names go through this reader, so a patient admitted as "Jean Pierre"
    decoded as "Jean" -- and alarm text and display labels lost everything
    after their first word too.

    The reference capture cannot catch this: it holds exactly one string,
    single-word and NUL-padded.
    """
    assert read_string(codec, encode_string(text))[0] == text


def test_interior_spaces_survive_the_padding_strip(codec):
    """The point of the fix: padding goes, interior spaces stay.

    This is the case the old ``.split(" ")[0]`` conflated -- it could not
    remove trailing padding without also cutting the value at its first
    interior space.
    """
    padded = "Jean Pierre" + "  " + "\x00" * 5
    assert read_string(codec, encode_string(padded))[0] == "Jean Pierre"


# -- variable labels -------------------------------------------------------


def test_variable_label_reads_bytes_at_the_offset(codec):
    """The value is read from the current position, not the start of the buffer.

    Regression test. This previously read ``data[i]`` rather than
    ``data[index + i]``, so every VariableLabel in every message decoded to the
    message's own leading bytes -- ``NOM_ATTR_SYS_ID`` came back as the session
    header ``e1 00 00 02 00 01`` instead of the monitor's system id.
    """
    parsed = {}
    data = bytearray(b"\xde\xad\xbe\xef" + b"\x00\x03" + b"\x41\x42\x43")
    index = codec.readVariableLabel(4, parsed, data)
    assert parsed["VariableLabel"]["value"] == [0x41, 0x42, 0x43]
    assert index == 9


def test_variable_label_length_is_a_byte_count(codec):
    parsed = {}
    codec.readVariableLabel(0, parsed, bytearray(b"\x00\x06\x00\x09\xfb\x70\xd8\x0b"))
    assert parsed["VariableLabel"]["length"] == 6
    assert bytes(parsed["VariableLabel"]["value"]) == b"\x00\x09\xfb\x70\xd8\x0b"


def test_variable_label_empty(codec):
    parsed = {}
    assert codec.readVariableLabel(0, parsed, bytearray(b"\x00\x00")) == 2
    assert parsed["VariableLabel"]["value"] == []


# -- variable data ---------------------------------------------------------


def test_variable_data_reads_16_bit_words(codec):
    """The length counts bytes; the values come back as half as many uint16s."""
    parsed = {}
    data = bytearray(b"\x00\x08" + b"\x00\x01\x00\x02\xff\xfe\x12\x34")
    index = codec.readVariableData(0, parsed, data)
    assert parsed["VariableData"]["length"] == 8
    assert parsed["VariableData"]["value"] == [1, 2, 0xFFFE, 0x1234]
    assert index == 10


def test_variable_data_words_are_unsigned(codec):
    """Samples are read unsigned here; sign handling belongs to the scaling step."""
    parsed = {}
    codec.readVariableData(0, parsed, bytearray(b"\x00\x02\xff\xff"))
    assert parsed["VariableData"]["value"] == [65535]


def test_variable_data_reads_at_the_caller_offset(codec):
    parsed = {}
    data = bytearray(b"\xde\xad" + b"\x00\x04\x00\x01\x00\x02")
    assert codec.readVariableData(2, parsed, data) == 8
    assert parsed["VariableData"]["value"] == [1, 2]


def test_variable_data_empty(codec):
    parsed = {}
    assert codec.readVariableData(0, parsed, bytearray(b"\x00\x00")) == 2
    assert parsed["VariableData"]["value"] == []
