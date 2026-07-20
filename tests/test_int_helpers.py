"""Tests for the fixed-width integer helpers.

These are one-line ``struct`` wrappers, but every multi-byte field in the
protocol goes through them, so the properties worth pinning are the ones a
rewrite could plausibly break: the byte order is big-endian (network order, not
the host's), and ``geti16`` is the *only* signed reader -- the rest wrap around.
"""

import pytest


@pytest.mark.parametrize(
    "value, encoded",
    [
        (0, b"\x00\x00\x00\x00"),
        (1, b"\x00\x00\x00\x01"),
        (0x0002014B, b"\x00\x02\x01\x4b"),  # the ECG wave's label code
        (0xFFFFFFFF, b"\xff\xff\xff\xff"),
    ],
)
def test_set32_get32_round_trip(codec, value, encoded):
    assert bytes(codec.set32(value)) == encoded
    assert codec.get32(encoded) == value


@pytest.mark.parametrize(
    "value, encoded",
    [
        (0, b"\x00\x00"),
        (33749, b"\x83\xd5"),  # the SpO2 numeric's handle
        (65535, b"\xff\xff"),
    ],
)
def test_set16_get16_round_trip(codec, value, encoded):
    assert bytes(codec.set16(value)) == encoded
    assert codec.get16(encoded) == value


@pytest.mark.parametrize("value, encoded", [(0, b"\x00"), (200, b"\xc8"), (255, b"\xff")])
def test_set8_get8_round_trip(codec, value, encoded):
    assert bytes(codec.set8(value)) == encoded
    assert codec.get8(encoded) == value


def test_multibyte_helpers_are_big_endian(codec):
    """Byte order is network order, whatever the host is.

    Little-endian would read 0x0102 back as 0x0201, so a single asymmetric
    value catches it.
    """
    assert codec.get16(b"\x01\x02") == 0x0102
    assert codec.get32(b"\x01\x02\x03\x04") == 0x01020304
    assert bytes(codec.set16(0x0102)) == b"\x01\x02"
    assert bytes(codec.set32(0x01020304)) == b"\x01\x02\x03\x04"


@pytest.mark.parametrize(
    "encoded, signed, unsigned",
    [
        (b"\xff\xff", -1, 65535),
        (b"\x80\x00", -32768, 32768),
        (b"\x7f\xff", 32767, 32767),
        (b"\xff\x9c", -100, 65436),
    ],
)
def test_geti16_is_signed_where_get16_is_not(codec, encoded, signed, unsigned):
    """``geti16`` is the signed reader; ``get16`` on the same bytes differs.

    Waveform samples and some numerics are signed, so reading them with
    ``get16`` turns small negatives into values near 65535 rather than raising.
    """
    assert codec.geti16(encoded) == signed
    assert codec.get16(encoded) == unsigned


@pytest.mark.parametrize(
    "setter, value",
    [("set8", 256), ("set8", -1), ("set16", 65536), ("set16", -1), ("set32", -1)],
)
def test_setters_reject_out_of_range_values(codec, setter, value):
    """Out-of-range values raise rather than silently truncating."""
    with pytest.raises(Exception):
        getattr(codec, setter)(value)


def test_getters_require_exactly_their_width(codec):
    """A short or long slice raises instead of returning a plausible number."""
    with pytest.raises(Exception):
        codec.get16(b"\x01")
    with pytest.raises(Exception):
        codec.get32(b"\x01\x02\x03")
