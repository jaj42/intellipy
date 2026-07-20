"""Smoke tests for building messages and classifying received ones.

Three things the codec does, and it is worth being precise about which is
which, because the obvious "write it then read it back" test does not apply:

``writeData(type, params)``
    Builds an APDU from a template. Some templates take a parameter dict, some
    must be called with no parameters at all -- ``ReleaseRequest``'s parameters
    are a list, and passing ``{}`` raises.

``getMessageType(data)``
    Classifies a **received** message. It keys off the ROSE reply types, so
    the client's *own* outbound polls come back as ``"Unknown"`` -- that is
    correct, not a defect, and it is pinned below so nobody "fixes" it.

``readData(data)``
    Parses a received message.

So the outbound messages are checked for being built consistently, and the
inbound ones are checked against real captured bytes.
"""

import pytest

#: Messages the client sends that take a parameter dict.
PARAMETERISED = [
    "MDSSinglePollAction",
    "MDSPatientDemographicsPoll",
    "MDSExtendedPollActionNUMERIC",
    "MDSExtendedPollActionWAVE",
    "MDSExtendedPollActionALARM",
    "MDSExtendedPollActionENUM",
    "MDSGetPriorityList",
]

#: Messages the client sends with no parameters. These sit at the session
#: layer rather than in the data phase.
SESSION_LEVEL = ["AssociationRequest", "ReleaseRequest"]

EXTENDED_POLLS = [n for n in PARAMETERISED if n.startswith("MDSExtendedPollAction")]


def test_codec_constructs(codec):
    """Building a codec parses five nomenclature files; none may be missing."""
    assert codec.MessageLists
    assert codec.MessageParameters
    assert codec.DataKeys


# -- building outbound messages --------------------------------------------


@pytest.mark.parametrize("message_type", PARAMETERISED)
def test_parameterised_messages_build(codec, message_type):
    assert codec.writeData(message_type, {})


@pytest.mark.parametrize("message_type", SESSION_LEVEL)
def test_session_level_messages_build(codec, message_type):
    assert codec.writeData(message_type)


@pytest.mark.parametrize("message_type", PARAMETERISED)
def test_data_phase_messages_are_wrapped_in_a_session_pdu(codec, message_type):
    """Data-phase APDUs start with the session identifier 0xE1."""
    assert bytes(codec.writeData(message_type, {}))[0] == 0xE1


@pytest.mark.parametrize("message_type", SESSION_LEVEL)
def test_session_level_messages_are_not(codec, message_type):
    """Association and release are session SPDUs with their own codes.

    Worth stating because "every message starts with 0xE1" is nearly true and
    wrong at exactly the two points where a connection is set up and torn down.
    """
    assert bytes(codec.writeData(message_type))[0] != 0xE1


@pytest.mark.parametrize("message_type", PARAMETERISED)
def test_writing_is_deterministic(codec, message_type):
    """Templates are shared and mutable, so a write must not leave state behind.

    ``writeData`` deep-copies its parameters for this reason; if that stopped
    happening, the second call would differ from the first.
    """
    assert bytes(codec.writeData(message_type, {})) == bytes(
        codec.writeData(message_type, {})
    )


@pytest.mark.parametrize("message_type", EXTENDED_POLLS)
def test_poll_number_is_honoured(codec, message_type):
    """Each class is polled under its own number so replies can be told apart."""
    first = bytes(codec.writeData(message_type, {"poll_number": 1}))
    second = bytes(codec.writeData(message_type, {"poll_number": 2}))

    assert first != second
    assert len(first) == len(second)


def test_extended_polls_differ_only_in_the_object_class(codec):
    """The four poll templates are one message with a single field changed.

    §4c measured this against the capture: the enumeration poll differs from
    the proven numeric poll by exactly one byte, the object class. Pinning it
    means a template edit that changes anything else shows up here.
    """
    written = {
        name: bytes(codec.writeData(name, {"poll_number": 1}))
        for name in EXTENDED_POLLS
    }
    assert len({len(value) for value in written.values()}) == 1

    reference = written["MDSExtendedPollActionNUMERIC"]
    for name, value in written.items():
        differing = sum(1 for a, b in zip(reference, value) if a != b)
        assert differing <= 1, f"{name} differs from the numeric poll in {differing} bytes"


def test_the_two_single_polls_target_different_classes(codec):
    """Demographics reuses the single-poll MessageList but not its target (§4b)."""
    demographics = bytes(codec.writeData("MDSPatientDemographicsPoll", {}))
    single = bytes(codec.writeData("MDSSinglePollAction", {}))

    assert demographics != single
    assert len(demographics) == len(single)


def test_association_request_is_the_longest_outbound_message(codec):
    """It carries the whole presentation/session negotiation, unlike the rest."""
    sizes = {name: len(codec.writeData(name, {})) for name in PARAMETERISED}
    sizes.update({name: len(codec.writeData(name)) for name in SESSION_LEVEL})
    assert max(sizes, key=sizes.get) == "AssociationRequest"


# -- classifying received messages -----------------------------------------


@pytest.mark.parametrize("message_type", EXTENDED_POLLS)
def test_outbound_polls_do_not_classify_as_themselves(codec, message_type):
    """``getMessageType`` is a receive-side function only.

    It distinguishes messages by their ROSE reply type, and a poll is an
    invocation, not a reply. So the client's own polls classify as "Unknown".
    Anything that round-trips a poll through ``getMessageType`` is confused
    about which direction the message travels.
    """
    assert codec.getMessageType(bytes(codec.writeData(message_type, {}))) == "Unknown"


def test_captured_replies_classify_correctly(codec, enumeration_payloads):
    """Against real monitor traffic, classification is the point."""
    types = [codec.getMessageType(p) for p in enumeration_payloads]

    assert "MDSCreateEvent" in types
    assert "MDSExtendedPollActionResult" in types
    assert "LinkedMDSExtendedPollActionResult" in types
    assert "Unknown" not in types


def test_captured_replies_all_parse(codec, enumeration_payloads):
    """Every payload in the fixture decodes without raising."""
    for payload in enumeration_payloads:
        parsed = codec.readData(payload)
        message = parsed[0] if isinstance(parsed, tuple) else parsed
        assert message


def test_read_data_returns_a_tuple_only_for_event_reports(codec, enumeration_payloads):
    """``readData`` has two different return shapes, chosen by message type.

    An event report -- ``MDSCreateEvent`` -- returns ``(message, params)``,
    where the params are what the acknowledgement has to echo back. Everything
    else returns the message dict alone. So ``message, _ = readData(...)``
    works on a create event and raises ValueError on a poll reply, which is a
    trap worth having written down.
    """
    shapes = {}
    for payload in enumeration_payloads:
        shapes[codec.getMessageType(payload)] = type(codec.readData(payload))

    assert shapes["MDSCreateEvent"] is tuple
    assert shapes["MDSExtendedPollActionResult"] is dict
    assert shapes["LinkedMDSExtendedPollActionResult"] is dict


def test_unknown_bytes_classify_as_unknown_rather_than_raising(codec):
    """A stray packet must not take down a receive loop.

    ``stream()`` classifies everything the socket hands it, including
    retransmissions and traffic from other devices on the same port.
    """
    assert codec.getMessageType(b"\x00" * 16) == "Unknown"
    assert codec.getMessageType(b"\xe1\x00" + b"\xff" * 20) == "Unknown"


@pytest.mark.parametrize("data", [b"", b"\xe1"])
def test_classifying_a_truncated_packet_does_not_raise(codec, data):
    """UDP can deliver a runt; it should be ignorable, not fatal."""
    try:
        codec.getMessageType(data)
    except Exception as error:  # noqa: BLE001 - the point is what escapes
        pytest.fail(f"getMessageType({data!r}) raised {error!r}")


def test_reading_an_unclassifiable_message_raises(codec):
    """``readData`` has no template for "Unknown" and says so.

    Callers must classify first and skip what they do not recognise --
    ``collect_enumeration`` and ``stream`` both do. Pinned because the failure
    is a bare KeyError, which is easy to mistake for a decode bug.
    """
    with pytest.raises(KeyError):
        codec.readData(b"\x00" * 16)
