"""Tests for the two variable-width length encodings.

The protocol stacks two framings with different rules, and ``readLengths``
picks between them on the *name* of the field being read:

``ASNLength``
    ASN.1 BER-style. A byte < 128 is the length itself; ``0x81`` means "one
    length byte follows"; ``0x82`` means "two follow".

``LILength``
    The session layer's own length indicator. A byte < 255 is the length
    itself; ``0xff`` means "two length bytes follow". Note the different escape
    and the different threshold -- 129 and 130 are ordinary lengths here, but
    escapes in ASN.1.

Confusing the two is a realistic bug and a quiet one, since the two agree for
every length below 129. The tests below therefore concentrate on the range
where they disagree.
"""

import pytest


def read(codec, data, data_type):
    """Run ``readLengths`` over ``data`` and return ``(value, bytes consumed)``."""
    parsed = {}
    index = codec.readLengths(0, parsed, bytearray(data), [data_type])
    return parsed[data_type], index


# -- ASN.1 lengths ---------------------------------------------------------


@pytest.mark.parametrize(
    "data, value, consumed",
    [
        (b"\x00", 0, 1),
        (b"\x7f", 127, 1),  # largest short form
        (b"\x81\x80", 128, 2),  # smallest long form
        (b"\x81\xff", 255, 2),
        (b"\x82\x01\x00", 256, 3),
        (b"\x82\xff\xff", 65535, 3),
    ],
)
def test_asn_length_forms(codec, data, value, consumed):
    assert read(codec, data + b"\xaa" * 4, "ASNLength") == (value, consumed)


# -- session-layer lengths -------------------------------------------------


@pytest.mark.parametrize(
    "data, value, consumed",
    [
        (b"\x00", 0, 1),
        (b"\xfe", 254, 1),  # largest short form
        (b"\xff\x00\xff", 255, 3),  # smallest long form
        (b"\xff\xff\xff", 65535, 3),
    ],
)
def test_li_length_forms(codec, data, value, consumed):
    assert read(codec, data + b"\xaa" * 4, "LILength") == (value, consumed)


@pytest.mark.parametrize("byte, value", [(0x81, 129), (0x82, 130)])
def test_asn_escapes_are_ordinary_li_lengths(codec, byte, value):
    """The two encodings disagree exactly where the ASN.1 escapes live.

    An LI length of 129 is one byte meaning 129; read as an ASN.1 length the
    same byte means "a length follows". Anything that mixes the two silently
    mis-frames every message longer than 128 bytes.
    """
    assert read(codec, bytes([byte]) + b"\xaa" * 4, "LILength") == (value, 1)
    assert read(codec, bytes([byte]) + b"\xaa" * 4, "ASNLength") != (value, 1)


@pytest.mark.parametrize("length", [0, 1, 127])
def test_the_two_encodings_agree_below_128(codec, length):
    """Which is why a mix-up survives casual testing."""
    data = bytes([length]) + b"\xaa" * 4
    assert read(codec, data, "ASNLength") == read(codec, data, "LILength")


@pytest.mark.parametrize("byte", [0x80, 0x83, 0x84, 0xFF])
def test_asn_reader_only_knows_the_one_and_two_byte_escapes(codec, byte):
    """Long forms other than ``0x81``/``0x82`` are read as short lengths.

    Strict BER says a leading byte with the top bit set always means "the low 7
    bits count the length bytes that follow", so ``0x83`` introduces a 3-byte
    length and ``0x80`` is the indefinite form. This reader special-cases only
    ``0x81`` and ``0x82`` and treats everything else as a literal, so ``0x83``
    parses as the length 131.

    That is fine for this protocol -- IntelliVue APDUs never exceed 65535 bytes,
    so the longer forms cannot legitimately occur -- but it means the reader
    mis-frames rather than rejects a malformed message. Pinned so the
    simplification stays a known one.
    """
    assert read(codec, bytes([byte]) + b"\xaa" * 4, "ASNLength") == (byte, 1)


# -- the plain 16-bit length ------------------------------------------------


def test_plain_length_is_a_fixed_width_uint16(codec):
    """``length`` (no prefix) has no variable form at all."""
    assert read(codec, b"\x01\x00" + b"\xaa" * 4, "length") == (256, 2)
    assert read(codec, b"\x00\x81" + b"\xaa" * 4, "length") == (129, 2)


def test_unrecognised_field_name_consumes_nothing(codec):
    """An unknown data type leaves the index where it was.

    ``readLengths`` is called for every field and only acts on the three names
    it knows, so this is the path taken by the vast majority of calls.
    """
    parsed = {}
    assert codec.readLengths(7, parsed, bytearray(b"\xaa" * 8), ["Handle"]) == 7
    assert parsed == {}


def test_index_is_relative_not_absolute(codec):
    """Lengths are read at the caller's offset, not from the start of the buffer."""
    parsed = {}
    data = bytearray(b"\xff\xff\xff\x82\x01\x00")
    index = codec.readLengths(3, parsed, data, ["ASNLength"])
    assert (parsed["ASNLength"], index) == (256, 6)
