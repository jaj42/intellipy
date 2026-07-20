"""Tests for the IEEE 11073 32-bit FLOAT reader.

Not an IEEE 754 float. The wire form is four bytes: a signed 8-bit exponent
followed by a 24-bit two's-complement mantissa, giving ``mantissa * 10 **
exponent`` -- a *decimal* exponent, so values a monitor displays round-trip
exactly rather than landing on a binary approximation.

Four mantissa values are reserved as special codes, and the reader returns
those as strings rather than numbers. Callers must therefore be ready for a
str where they expect a float; that is pinned below because it is the property
most likely to surprise.
"""

import struct

import pytest


def read(codec, data):
    """Run ``readFLOAT`` over four bytes and return ``(value, bytes consumed)``."""
    parsed = {}
    index = codec.readFLOAT(0, parsed, bytearray(data))
    return parsed["FLOATType"], index


def encode(exponent, mantissa):
    """Build the wire form from an exponent and a (possibly negative) mantissa."""
    return struct.pack(">b", exponent) + struct.pack(">i", mantissa & 0xFFFFFF)[1:]


@pytest.mark.parametrize(
    "exponent, mantissa, value",
    [
        (0, 0, 0),
        (0, 1, 1),
        (0, 91, 91),  # the capture's ABP mean, in mmHg
        (0, 60, 60),
        (-1, 725, 72.5),
        (-2, 1234, 12.34),
        (-3, 5, 0.005),  # the ECG scaling factor's slope
        (1, 12, 120),
        (2, 3, 300),
    ],
)
def test_positive_values(codec, exponent, mantissa, value):
    assert read(codec, encode(exponent, mantissa)) == (pytest.approx(value), 4)


@pytest.mark.parametrize(
    "exponent, mantissa, value",
    [
        (0, -1, -1),
        (0, -40, -40),
        (-2, -4096, -40.96),  # the ECG scaling factor's intercept
        (0, -0x7FFFFD, -8388605),  # near the most negative usable mantissa
    ],
)
def test_negative_mantissas_are_twos_complement(codec, exponent, mantissa, value):
    """The 24-bit mantissa is signed, so the top bit is not part of the magnitude."""
    assert read(codec, encode(exponent, mantissa)) == (pytest.approx(value), 4)


def test_exponent_is_signed_too(codec):
    """A negative exponent scales down; read unsigned it would scale up hugely."""
    assert read(codec, encode(-2, 100)) == (pytest.approx(1.0), 4)


def test_exponent_is_a_power_of_ten_not_two(codec):
    assert read(codec, encode(1, 1)) == (10, 4)
    assert read(codec, encode(2, 1)) == (100, 4)


@pytest.mark.parametrize(
    "mantissa_bytes, meaning",
    [
        (b"\x7f\xff\xff", "Not a number"),
        (b"\x80\x00\x00", "Not at this resolution"),
        (b"\x7f\xff\xfe", "Positive Infinity"),
        (b"\x80\x00\x02", "Negative Infinity"),
    ],
)
def test_reserved_codes_decode_to_names_not_numbers(codec, mantissa_bytes, meaning):
    """The four special mantissas come back as strings.

    A monitor sends "not a number" for a measurement it has no current value
    for -- an unplugged sensor, say -- which is common, not exceptional. Any
    consumer doing arithmetic on a sample value has to handle it.
    """
    assert read(codec, b"\x00" + mantissa_bytes) == (meaning, 4)


@pytest.mark.parametrize("exponent", [0, 5, -5, 127, -128])
def test_reserved_codes_ignore_the_exponent(codec, exponent):
    """The special mantissas are recognised whatever exponent precedes them."""
    value, _ = read(codec, struct.pack(">b", exponent) + b"\x7f\xff\xff")
    assert value == "Not a number"


def test_neighbours_of_the_reserved_codes_are_ordinary_numbers(codec):
    """The reserved set is exactly four mantissas wide; 0x800001 is not in it."""
    assert read(codec, b"\x00" + b"\x7f\xff\xfd") == (8388605, 4)
    assert read(codec, b"\x00" + b"\x80\x00\x01") == (-8388607, 4)


def test_always_consumes_four_bytes(codec):
    """Including for the reserved codes -- the field is fixed width."""
    for data in (encode(0, 1), b"\x00\x7f\xff\xff", b"\x00\x80\x00\x00"):
        assert read(codec, data + b"\xaa" * 4)[1] == 4


def test_reads_at_the_caller_offset(codec):
    parsed = {}
    data = bytearray(b"\xde\xad" + encode(-1, 725))
    assert codec.readFLOAT(2, parsed, data) == 6
    assert parsed["FLOATType"] == pytest.approx(72.5)
