"""Tests for enumeration objects (``NOM_MOC_VMO_METRIC_ENUM``).

Enumeration objects report a *state* -- "Sinus Rhythm", "pair PVC's" -- rather
than a number. The reference capture was recorded on an association that did
not negotiate ``POLL_EXT_ENUM``, so it contains no enumeration replies to test
against. The wire data here is therefore **synthetic**, built to the structure
the Data Export spec defines::

    typedef struct {
        OIDType          physio_id;
        MeasurementState state;
        EnumVal          value;
    } EnumObsVal;

Two things anchor it to the real monitor: the reply header is spliced from a
genuine (empty) extended-poll reply in the capture, and every nomenclature code
used below is one the vendor guide tabulates. The capture's MDS does advertise
the object class -- see :func:`test_capture_mds_advertises_enumeration_class`.
"""

import struct


# Nomenclature codes, from the Data Export guide's "Enumerations" section.
NOM_ATTR_ID_HANDLE = 0x0921
NOM_ATTR_ID_LABEL = 0x0924
NOM_ATTR_VAL_ENUM_OBS = 0x099E

NOM_ECG_STAT_ECT = 0xD006  # EctSta, ECG Ectopic Status
NOM_ECG_STAT_RHY = 0xD007  # RytSta, ECG Rhythm Status
NOM_ECG_SINUS_RHY = 0x4012  # "Sinus Rhythm"
NOM_ECG_V_P_C_PAIR = 0x4280  # "pair PVC's"
NOM_DIM_BEAT_PER_MIN = 0x0AA0

ENUM_OBJ_ID_CHOSEN = 1
ENUM_OBJ_ID_VAL_CHOSEN = 4

#: Frame 53 of ``reference/intellivue_enumeration.pcapng``: a real
#: ``MDSExtendedPollActionResult`` whose ``PollInfoList`` happens to be empty,
#: which makes it a clean header to splice a synthetic body onto.
EMPTY_REPLY = bytes.fromhex(
    "e10000020002002a03eb00070024002100000000f13b001a"
    "000000000d617300ffffffffffffffff00010006000000000000"
)

#: Offsets into `EMPTY_REPLY` of the three enclosing length fields (each a
#: plain 2-byte count of the bytes that follow it), the polled object class,
#: and the start of the PollInfoList.
LENGTH_OFFSETS = (6, 12, 22)
OBJECT_CLASS_OFFSET = 42
POLL_INFO_LIST_OFFSET = 46


def ava(oid, value):
    """One attribute-value assertion: OID, length, value."""
    return struct.pack(">HH", oid, len(value)) + value


def attribute_list(*avas):
    body = b"".join(avas)
    return struct.pack(">HH", len(avas), len(body)) + body


def enum_obs_val(physio_id, choice, branch, measurement_state=0):
    """An ``EnumObsVal`` attribute value: physio id, state, tagged union."""
    return (
        struct.pack(">HH", physio_id, measurement_state)
        + struct.pack(">HH", choice, len(branch))
        + branch
    )


def poll_info_list(observations, mds_context=0):
    """Wrap ``(handle, attribute_list)`` pairs in one SingleContextPoll."""
    body = b"".join(
        struct.pack(">H", handle) + attributes for handle, attributes in observations
    )
    poll_info = struct.pack(">HH", len(observations), len(body)) + body
    context = struct.pack(">H", mds_context) + poll_info
    return struct.pack(">HH", 1, len(context)) + context


def enumeration_reply(observations):
    """Splice a synthetic enumeration PollInfoList onto the real header.

    Retargets the reply at ``NOM_MOC_VMO_METRIC_ENUM`` (object class 5) and
    grows the three enclosing length fields by however much the body added.
    """
    body = poll_info_list(observations)
    packet = bytearray(EMPTY_REPLY[:POLL_INFO_LIST_OFFSET]) + body

    struct.pack_into(">H", packet, OBJECT_CLASS_OFFSET, 5)

    grew = len(body) - 4  # the header already accounted for an empty list
    for offset in LENGTH_OFFSETS:
        current = struct.unpack_from(">H", packet, offset)[0]
        struct.pack_into(">H", packet, offset, current + grew)

    return bytes(packet)


# -- nomenclature ---------------------------------------------------------


def test_object_class_and_attribute_resolve(codec):
    """The enumeration object class and its observed-value attribute are known."""
    assert codec.DataKeys["OIDType"][b"\x00\x05"] == "NOM_MOC_VMO_METRIC_ENUM"
    assert codec.DataKeys["OIDType"][b"\x09\x9e"] == "NOM_ATTR_VAL_ENUM_OBS"


def test_enumeration_states_resolve(codec):
    """Enumeration values name states from the SCADA partition."""
    assert codec.DataKeys["SCADAType"][b"\xd0\x07"] == "NOM_ECG_STAT_RHY"
    assert codec.DataKeys["SCADAType"][b"\x40\x12"] == "NOM_ECG_SINUS_RHY"
    assert codec.DataKeys["SCADAType"][b"\x42\x80"] == "NOM_ECG_V_P_C_PAIR"


def test_enumeration_labels_resolve(codec):
    """The two enumeration objects have display labels."""
    assert codec.DataKeys["TextId"][b"\x00\x02\xd0\x06"] == "ECG Ectopic Status"
    assert codec.DataKeys["TextId"][b"\x00\x02\xd0\x07"] == "ECG Rhythm Status"


def test_poll_profile_requests_enum_bit(codec):
    """The ENUM-enabled option combination sets POLL_EXT_ENUM (0x04000000)."""
    combination = codec.DataKeys["PollProfileExtOptions"][
        "POLL1SECANDWAVEANDENUMANDLISTANDDYN"
    ]
    assert int.from_bytes(combination, "big") & 0x04000000


def test_enumeration_poll_targets_the_enum_class(codec):
    """The enumeration poll differs from the numeric one only in object class."""
    numeric = codec.writeData("MDSExtendedPollActionNUMERIC")
    enumeration = codec.writeData("MDSExtendedPollActionENUM")

    differing = [i for i in range(len(numeric)) if numeric[i] != enumeration[i]]
    assert len(numeric) == len(enumeration)
    assert differing == [33]
    assert numeric[33] == 6 and enumeration[33] == 5


# -- decoding -------------------------------------------------------------


def test_decodes_object_id_branch(codec):
    """ENUM_OBJ_ID_CHOSEN: the value is just the state's code."""
    value = enum_obs_val(
        NOM_ECG_STAT_RHY, ENUM_OBJ_ID_CHOSEN, struct.pack(">H", NOM_ECG_SINUS_RHY)
    )
    packet = enumeration_reply([(258, attribute_list(ava(NOM_ATTR_VAL_ENUM_OBS, value)))])

    message = codec.readData(packet)
    reply = message["PollMdibDataReplyExt"]
    assert reply["Type"]["OIDType"] == "NOM_MOC_VMO_METRIC_ENUM"

    observation = reply["PollInfoList"]["SingleContextPoll_0"]["SingleContextPoll"][
        "poll_info"
    ]["ObservationPoll_0"]["ObservationPoll"]
    decoded = observation["AttributeList"]["AVAType"]["NOM_ATTR_VAL_ENUM_OBS"][
        "AttributeValue"
    ]["EnumObsVal"]

    assert decoded["physio_id"] == "NOM_ECG_STAT_RHY"
    assert decoded["EnumVal"]["choice"] == "ENUM_OBJ_ID_CHOSEN"
    assert decoded["EnumVal"]["enum_obj_id"] == "NOM_ECG_SINUS_RHY"


def test_decodes_object_id_value_branch(codec):
    """ENUM_OBJ_ID_VAL_CHOSEN: state code plus a measured value and its unit."""
    branch = (
        struct.pack(">H", NOM_ECG_V_P_C_PAIR)
        + b"\x00\x00\x00\x03"  # FLOATType: exponent 0, mantissa 3
        + struct.pack(">H", NOM_DIM_BEAT_PER_MIN)
    )
    value = enum_obs_val(NOM_ECG_STAT_ECT, ENUM_OBJ_ID_VAL_CHOSEN, branch)
    packet = enumeration_reply([(259, attribute_list(ava(NOM_ATTR_VAL_ENUM_OBS, value)))])

    message = codec.readData(packet)
    decoded = message["PollMdibDataReplyExt"]["PollInfoList"]["SingleContextPoll_0"][
        "SingleContextPoll"
    ]["poll_info"]["ObservationPoll_0"]["ObservationPoll"]["AttributeList"]["AVAType"][
        "NOM_ATTR_VAL_ENUM_OBS"
    ]["AttributeValue"]["EnumObsVal"]

    assert decoded["physio_id"] == "NOM_ECG_STAT_ECT"
    assert decoded["EnumVal"]["choice"] == "ENUM_OBJ_ID_VAL_CHOSEN"

    measured = decoded["EnumVal"]["EnumObjIdVal"]
    assert measured["enum_obj_id"] == "NOM_ECG_V_P_C_PAIR"
    assert measured["FLOATType"] == 3
    assert measured["UNITType"].startswith("bpm")


def test_unknown_union_branch_is_skipped_not_fatal(codec):
    """An unmodelled EnumVal branch keeps its bytes without derailing the parse."""
    value = enum_obs_val(NOM_ECG_STAT_RHY, 7, b"\xde\xad\xbe\xef")
    packet = enumeration_reply(
        [
            (
                260,
                attribute_list(
                    ava(NOM_ATTR_VAL_ENUM_OBS, value),
                    ava(NOM_ATTR_ID_HANDLE, struct.pack(">H", 260)),
                ),
            )
        ]
    )

    message = codec.readData(packet)
    attributes = message["PollMdibDataReplyExt"]["PollInfoList"]["SingleContextPoll_0"][
        "SingleContextPoll"
    ]["poll_info"]["ObservationPoll_0"]["ObservationPoll"]["AttributeList"]["AVAType"]

    assert attributes["NOM_ATTR_VAL_ENUM_OBS"]["AttributeValue"]["EnumObsVal"][
        "EnumVal"
    ]["raw"] == b"\xde\xad\xbe\xef"
    # The attribute after the unknown branch still lands in the right place.
    assert attributes["NOM_ATTR_ID_HANDLE"]["AttributeValue"]["Handle"] == 260


# -- client-facing samples -------------------------------------------------


def test_client_yields_enumeration_samples(codec):
    """A whole reply turns into the client's ``enumeration`` sample dicts."""
    from intellipy.client import IntellivueClient

    client = IntellivueClient.__new__(IntellivueClient)  # no socket needed
    client.codec = codec
    client.relative_initial_time = 0
    client._enum_labels = {}

    value = enum_obs_val(
        NOM_ECG_STAT_RHY, ENUM_OBJ_ID_CHOSEN, struct.pack(">H", NOM_ECG_SINUS_RHY)
    )
    packet = enumeration_reply(
        [
            (
                261,
                attribute_list(
                    ava(NOM_ATTR_ID_LABEL, b"\x00\x02\xd0\x07"),
                    ava(NOM_ATTR_VAL_ENUM_OBS, value),
                ),
            )
        ]
    )

    samples = list(client._decode_poll_reply(codec.readData(packet)))
    assert len(samples) == 1

    sample = samples[0]
    assert sample["kind"] == "enumeration"
    assert sample["label"] == "ECG Rhythm Status"
    assert sample["handle"] == 261
    assert sample["state"] == "NOM_ECG_SINUS_RHY"
    assert sample["physio_id"] == "NOM_ECG_STAT_RHY"
    assert sample["value"] is None


def test_client_caches_labels_across_poll_cycles(codec):
    """Later cycles carry bare values; the label must survive from the first."""
    from intellipy.client import IntellivueClient

    client = IntellivueClient.__new__(IntellivueClient)
    client.codec = codec
    client.relative_initial_time = 0
    client._enum_labels = {}

    value = enum_obs_val(
        NOM_ECG_STAT_RHY, ENUM_OBJ_ID_CHOSEN, struct.pack(">H", NOM_ECG_SINUS_RHY)
    )
    labelled = enumeration_reply(
        [
            (
                262,
                attribute_list(
                    ava(NOM_ATTR_ID_LABEL, b"\x00\x02\xd0\x07"),
                    ava(NOM_ATTR_VAL_ENUM_OBS, value),
                ),
            )
        ]
    )
    bare = enumeration_reply([(262, attribute_list(ava(NOM_ATTR_VAL_ENUM_OBS, value)))])

    list(client._decode_poll_reply(codec.readData(labelled)))
    (sample,) = list(client._decode_poll_reply(codec.readData(bare)))

    assert sample["label"] == "ECG Rhythm Status"


# -- what the reference capture does say -----------------------------------


def test_capture_mds_advertises_enumeration_class(codec, enumeration_payloads):
    """The captured monitor lists the enumeration class in its MDS object support.

    This is real data: the M8000 in the capture reports it supports up to 60
    ``NOM_MOC_VMO_METRIC_ENUM`` instances, even though that association never
    asked for them.
    """
    payloads = enumeration_payloads
    supported = None
    for payload in payloads:
        if codec.getMessageType(payload) != "MDSCreateEvent":
            continue
        message, _ = codec.readData(payload)
        entries = message["MDSCreateInfo"]["MDSAttributeList"]["AttributeList"][
            "AVAType"
        ]["NOM_ATTR_SYS_SPECN"]["AttributeValue"]["SystemSpec"]["SystemSpecEntry_0"][
            "SystemSpecEntry"
        ]["SystemSpecEntryValue"]
        supported = {
            entry["MdibObjectSupportEntry"]["Type"]["OIDType"]: entry[
                "MdibObjectSupportEntry"
            ]["max_inst"]
            for key, entry in entries.items()
            if key.startswith("MdibObjectSupportEntry")
        }
        break

    assert supported is not None, "no MDSCreateEvent in the capture"
    assert supported.get("NOM_MOC_VMO_METRIC_ENUM") == 60
