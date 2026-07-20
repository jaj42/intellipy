"""Tests for ``readAttributeList``, the generic AVA container reader.

An AttributeList is ``count``, ``length``, then ``count`` attribute-value
assertions, each ``OID`` + ``length`` + value. It carries essentially every
piece of content in the protocol, so its failure modes matter more than its
happy path:

* An attribute whose value type the codec does not model must be **skipped by
  its declared length** so the rest of the message still parses. §4b made this
  the behaviour; these tests pin it.
* OID ``0xF001`` is **overloaded** and resolves differently depending on which
  object class the reply answers for.

One asymmetry is worth stating up front, because it shapes these tests: the
declared per-attribute length is only used for the attributes the codec
*cannot* decode. For the ones it can, it hands off to ``recurseRead``, which
consumes whatever the value type needs and ignores the declared length. So a
modelled attribute with a wrong length is not detected -- it desynchronises.
"""

import pytest

#: OID -> (name, a correctly sized value). Both are simple fixed-width types:
#: a Handle is 16 bits, a TextId label code is 32.
HANDLE = (b"\x09\x21", b"\x00\x50")
LABEL = (b"\x09\x24", b"\x00\x02\x01\x4b")


def ava(oid, value):
    """One attribute-value assertion: OID, byte length, value."""
    return oid + len(value).to_bytes(2, "big") + value


def attribute_list(*entries):
    """Wrap AVAs in the count/length header."""
    body = b"".join(entries)
    return len(entries).to_bytes(2, "big") + len(body).to_bytes(2, "big") + body


def read(codec, data, polled_class=None, offset=0):
    codec.polled_object_class = polled_class
    parsed = {}
    index = codec.readAttributeList(offset, parsed, bytes(b"\x00" * offset + data))
    return parsed["AttributeList"], index


# -- the header ------------------------------------------------------------


def test_empty_list_is_reported_as_null(codec):
    """A zero count short-circuits: AVAType is the string "Null", not a dict.

    Callers indexing into it get a TypeError rather than a KeyError, so it is
    worth knowing this is not an empty mapping.
    """
    parsed, index = read(codec, b"\x00\x00\x00\x00")
    assert parsed["count"] == 0
    assert parsed["AVAType"] == "Null"
    assert index == 4


def test_count_and_length_are_both_read(codec):
    entry = ava(*HANDLE)
    parsed, index = read(codec, attribute_list(entry))
    assert parsed["count"] == 1
    assert parsed["length"] == len(entry)
    assert index == 4 + len(entry)


def test_modelled_attributes_decode_to_their_values(codec):
    """The happy path: a handle and a label code, both resolved."""
    parsed, _ = read(codec, attribute_list(ava(*HANDLE), ava(*LABEL)))
    ava_types = parsed["AVAType"]

    handle = ava_types["NOM_ATTR_ID_HANDLE"]["AttributeValue"]
    assert handle["Handle"] == 0x0050

    label = ava_types["NOM_ATTR_ID_LABEL"]["AttributeValue"]
    assert label["TextId"] == "ECG Lead MCL"
    assert label["TextId_code"] == b"\x00\x02\x01\x4b"


# -- unmodelled attributes -------------------------------------------------


def test_unknown_oid_is_skipped_by_its_length(codec):
    """An OID absent from the table is kept as a placeholder, then stepped over.

    0xF2E1 is real: it appears in the capture's demographics reply and is in
    Philips' private range, which no published table covers (§4b).
    """
    unknown = ava(b"\xf2\xe1", b"\xde\xad\xbe\xef")
    known = ava(*HANDLE)

    parsed, index = read(codec, attribute_list(unknown, known))

    assert parsed["AVAType"][b"\xf2\xe1"]["AttributeValue"] == "OIDType Not Defined"
    assert index == 4 + len(unknown) + len(known)


def test_named_attribute_with_unmodelled_type_keeps_its_raw_bytes(codec):
    """A *named* attribute the codec cannot decode is preserved, not dropped.

    ``NOM_ATTR_PT_ID_INT`` is the case §4b hit: the name resolves, the value
    type does not, and before the fix this raised KeyError and lost the whole
    message.
    """
    payload = b"\x00\x09\xfb\x70\xd8\x0b"
    parsed, index = read(
        codec,
        attribute_list(ava(b"\xf0\x01", payload)),
        polled_class="NOM_MOC_PT_DEMOG",
    )

    value = parsed["AVAType"]["NOM_ATTR_PT_ID_INT"]["AttributeValue"]
    assert value["raw"] == payload
    assert index == 4 + 4 + len(payload)


@pytest.mark.parametrize("entry", [HANDLE, LABEL])
def test_an_unmodelled_attribute_does_not_derail_the_rest(codec, entry):
    """The attribute *after* an unparseable one still decodes correctly.

    This is the point of skipping by length: one unknown private attribute
    costs one value, not the remainder of the message.
    """
    unmodelled = ava(b"\xf0\x01", b"\x00\x09\xfb\x70\xd8\x0b")
    body = attribute_list(unmodelled, ava(*entry))

    parsed, index = read(codec, body, polled_class="NOM_MOC_PT_DEMOG")

    assert "NOM_ATTR_PT_ID_INT" in parsed["AVAType"]
    assert codec.DataKeys["OIDType"][entry[0]] in parsed["AVAType"]
    assert index == len(body)


# -- the overloaded OID ----------------------------------------------------


@pytest.mark.parametrize(
    "polled_class, expected",
    [
        ("NOM_MOC_PT_DEMOG", "NOM_ATTR_PT_ID_INT"),
        ("NOM_MOC_VMS_MDS", "NOM_ATTR_POLL_PROFILE_EXT"),
        (None, "NOM_ATTR_POLL_PROFILE_EXT"),
    ],
)
def test_f001_resolves_on_the_polled_object_class(codec, polled_class, expected):
    """0xF001 means two different attributes, told apart only by context.

    It is ``NOM_ATTR_POLL_PROFILE_EXT`` in association and MDS replies but
    ``NOM_ATTR_PT_ID_INT`` in the demographics group. Nothing in the attribute
    itself distinguishes them -- only the class the reply answers for, which is
    why ``readData`` has to record it.
    """
    # Sized for whichever way it resolves: PollProfileExt is a 32-bit option
    # word plus a nested (here empty) AttributeList, and the demographics
    # branch keeps the same bytes verbatim as raw.
    value = b"\x8f\x00\x00\x00" + b"\x00\x00\x00\x00"

    parsed, _ = read(
        codec,
        attribute_list(ava(b"\xf0\x01", value)),
        polled_class=polled_class,
    )
    assert expected in parsed["AVAType"]


def test_mdib_obj_support_oid_bypasses_the_table(codec):
    """0x0102 is hard-coded, not looked up.

    In the OID table 0x0102 is an ordinary attribute; inside an AttributeList
    it always means ``NOM_MDIB_OBJ_SUPPORT``.
    """
    parsed, _ = read(codec, attribute_list(ava(b"\x01\x02", b"\x00\x00")))
    assert "NOM_MDIB_OBJ_SUPPORT" in parsed["AVAType"]


def test_all_zero_oid_is_its_own_placeholder(codec):
    """OID 0x0000 becomes the int 0, not a name and not bytes."""
    parsed, _ = read(codec, attribute_list(ava(b"\x00\x00", b"\xff\xff")))
    assert parsed["AVAType"][0]["AttributeValue"] == "OIDType Not Defined"


# -- offsets ---------------------------------------------------------------


def test_reads_at_the_caller_offset(codec):
    """Attribute lists are nested inside larger messages, never at index 0."""
    body = attribute_list(ava(*HANDLE))
    parsed, index = read(codec, body, offset=3)
    assert index == 3 + len(body)
    assert parsed["count"] == 1
    assert parsed["AVAType"]["NOM_ATTR_ID_HANDLE"]["AttributeValue"]["Handle"] == 0x0050
