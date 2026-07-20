"""Signal enumeration for the IntelliVue Data Export protocol.

The monitor never announces its signal list on its own. You enumerate it by
issuing an *MDS Extended Poll* action (``NOM_ACT_POLL_MDIB_DATA_EXT``, action
code ``0xf13b``) against the MDS object -- once per object class you care about
-- with the *attribute group* set to ``ALL``. "ALL" means "return every
attribute of every object of this class". The monitor answers with a possibly
multi-packet ("linked") poll reply whose ``PollInfoList`` enumerates every
object, and each object (``ObservationPoll``) carries at least:

============================  ======  ========================================
attribute                     OID     meaning
============================  ======  ========================================
``NOM_ATTR_ID_HANDLE``        0x0921  the handle you subscribe with
``NOM_ATTR_ID_LABEL``         0x0924  32-bit physiological label id
``NOM_ATTR_ID_LABEL_STRING``  0x0927  short display string, e.g. ``"SpO2"``
``NOM_ATTR_UNIT_CODE``        0x0996  unit of measure (numerics and waveforms)
============================  ======  ========================================

One class is polled per signal kind:

===========  ==============================  ===
kind         object class                    OID
===========  ==============================  ===
numeric      ``NOM_MOC_VMO_METRIC_NU``       6
wave         ``NOM_MOC_VMO_METRIC_SA_RT``    9
alarm        ``NOM_MOC_VMO_AL_MON``          54
enumeration  ``NOM_MOC_VMO_METRIC_ENUM``     5
===========  ==============================  ===

Collecting the objects from the first full poll cycle *is* the enumeration.

Enumeration objects report a *state* rather than a number ("Sinus Rhythm",
"pair PVC's"). The monitor only answers polls against them when the client
asked for ``POLL_EXT_ENUM`` at association time; otherwise that one poll comes
back as a Remote Operation Error and the other classes enumerate as usual.

The collection routine is transport-agnostic: :func:`collect_enumeration` takes
``send``/``recv`` callables, so an offline pcap replay and a live socket run
byte-for-byte identical logic. Message encoding and decoding are delegated
unchanged to :class:`~intellipy.IntellivueDataFiles.IntellivueData.IntellivueData`.
"""

import argparse
import binascii
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

__all__ = [
    "Signal",
    "CLASS_POLLS",
    "harvest_inventory",
    "collect_enumeration",
    "format_inventory",
    "main",
]


#: Poll reply message types that carry enumerable objects. Linked (segmented)
#: replies arrive as ``ROLRS`` APDUs; the last segment of a cycle is a ``RORS``.
POLL_REPLY_TYPES = ("LinkedMDSExtendedPollActionResult", "MDSExtendedPollActionResult")

#: Final (unsegmented or last-segment) reply type, used to end a poll cycle.
FINAL_REPLY_TYPE = "MDSExtendedPollActionResult"

#: Object class -> (codec message template, signal kind). Polling each of these
#: with attribute group ``ALL`` yields the full inventory.
CLASS_POLLS = {
    "NOM_MOC_VMO_METRIC_NU": ("MDSExtendedPollActionNUMERIC", "numeric"),
    "NOM_MOC_VMO_METRIC_SA_RT": ("MDSExtendedPollActionWAVE", "wave"),
    "NOM_MOC_VMO_AL_MON": ("MDSExtendedPollActionALARM", "alarm"),
    "NOM_MOC_VMO_METRIC_ENUM": ("MDSExtendedPollActionENUM", "enumeration"),
}

#: A poll the monitor declines, e.g. an enumeration poll on an association that
#: did not negotiate ``POLL_EXT_ENUM``. It names no object class, so a refused
#: class can only be counted, not identified.
ERROR_REPLY_TYPE = "RemoteOperationError"


@dataclass
class Signal:
    """One enumerated object exposed by the monitor.

    Attributes
    ----------
    kind : str
        ``"numeric"``, ``"wave"``, ``"alarm"``, ``"enumeration"`` or
        ``"unknown"``, derived from `oid_class`.
    oid_class : str
        Object class the signal was polled from, e.g. ``NOM_MOC_VMO_METRIC_NU``.
    mds_context : int
        MDS context id the object lives in (from its ``SingleContextPoll``).
    handle : int
        Object handle -- the identifier used to subscribe to this signal.
    label : str or int or None
        Physiological label (``NOM_ATTR_ID_LABEL``) resolved through
        ``PhysioLabels.txt``, e.g. ``"PLETH wave label"``. Human-readable, and
        always English regardless of the monitor's own language.
    label_code : bytes or None
        The same label as the monitor sent it: a raw 32-bit nomenclature code.
        **This is what to subscribe with** -- see
        :meth:`~intellipy.client.IntellivueClient.set_wave_priority`. `label` is
        a lookup of this and cannot always be turned back into it, since 34 of
        the 757 known codes share a description with another code.
    label_string : str or None
        Display string the *monitor* sent (``NOM_ATTR_ID_LABEL_STRING``), e.g.
        ``"Pleth"`` -- or ``"PA"``, ``"FC"`` on a French-localised monitor.
        Localised, and not a name the protocol tables know: for display only.
    unit : str or None
        Unit of measure (``NOM_ATTR_UNIT_CODE``), e.g. ``NOM_DIM_PERCENT``.
    raw_attrs : set of str
        Names of every attribute seen for this object across linked replies.
    """

    kind: str
    oid_class: str
    mds_context: int
    handle: int
    label: object = None
    label_code: bytes = None
    label_string: str = None
    unit: str = None
    raw_attrs: set = field(default_factory=set)

    @property
    def key(self):
        """Identity of this signal: ``(oid_class, mds_context, handle)``."""
        return (self.oid_class, self.mds_context, self.handle)

    def __str__(self):
        unit = f" [{self.unit}]" if self.unit else ""
        return f"{self.label_string or self.label or '?'} (handle {self.handle}){unit}"


def _find(node, name):
    """Depth-first search for the first value stored under key `name`."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == name:
                return value
            if isinstance(value, dict):
                found = _find(value, name)
                if found is not None:
                    return found
    return None


def _iter_observations(msg):
    """Yield ``(mds_context, ObservationPoll)`` for every object in a reply."""
    poll_info_list = _find(msg, "PollInfoList")
    if not isinstance(poll_info_list, dict):
        return
    for context_key, context_value in poll_info_list.items():
        if not context_key.startswith("SingleContextPoll"):
            continue
        if not isinstance(context_value, dict):
            continue
        context = context_value.get("SingleContextPoll", context_value)
        poll_info = context.get("poll_info", {})
        if not isinstance(poll_info, dict):
            continue
        for obs_key, obs_value in poll_info.items():
            if not obs_key.startswith("ObservationPoll"):
                continue
            if not isinstance(obs_value, dict):
                continue
            yield context.get("MdsContext"), obs_value.get("ObservationPoll", obs_value)


def _attribute_value(attribute_list, name):
    """Pull ``AttributeList[AVAType][name][AttributeValue]``, tolerating gaps."""
    if not isinstance(attribute_list, dict):
        return {}
    ava_types = attribute_list.get("AVAType", {})
    if not isinstance(ava_types, dict):
        return {}
    entry = ava_types.get(name, {})
    if not isinstance(entry, dict):
        return {}
    value = entry.get("AttributeValue", {})
    return value if isinstance(value, dict) else {}


def _reply_class(msg):
    """Object class a poll reply pertains to, from its ``Type.OIDType``."""
    type_field = _find(msg, "Type")
    if isinstance(type_field, dict):
        return type_field.get("OIDType")
    return None


def _merge_observations(inventory, msg):
    """Fold every object of one decoded poll reply into `inventory`.

    Linked replies split a poll cycle across several packets, so objects are
    merged by ``(class, context, handle)`` rather than overwritten.
    """
    oid_class = _reply_class(msg)
    kind = CLASS_POLLS.get(oid_class, (None, "unknown"))[1]

    for context, observation in _iter_observations(msg):
        handle = observation.get("Handle")
        attribute_list = observation.get("AttributeList", {})
        key = (oid_class, context, handle)
        signal = inventory.get(key)
        if signal is None:
            signal = Signal(
                kind=kind, oid_class=oid_class, mds_context=context, handle=handle
            )
            inventory[key] = signal

        label_attribute = _attribute_value(attribute_list, "NOM_ATTR_ID_LABEL")
        label = label_attribute.get("TextId")
        if label:
            signal.label = label
        # The raw code, kept because it is what goes back on the wire.
        label_code = label_attribute.get("TextId_code")
        if label_code:
            signal.label_code = label_code

        label_string = _attribute_value(
            attribute_list, "NOM_ATTR_ID_LABEL_STRING"
        ).get("String", {})
        if isinstance(label_string, dict) and label_string.get("value"):
            signal.label_string = label_string["value"]

        unit = _attribute_value(attribute_list, "NOM_ATTR_UNIT_CODE").get("UNITType")
        if unit:
            signal.unit = unit

        ava_types = (
            attribute_list.get("AVAType", {}) if isinstance(attribute_list, dict) else {}
        )
        if isinstance(ava_types, dict):
            signal.raw_attrs.update(ava_types.keys())


def harvest_inventory(codec, packets, inventory=None):
    """Decode poll replies into an inventory of :class:`Signal` objects.

    Packets that are not extended-poll replies -- and packets the codec cannot
    decode -- are skipped, so a raw capture can be fed in wholesale.

    Parameters
    ----------
    codec : IntellivueData
        Codec instance used for `getMessageType` and `readData`.
    packets : iterable of bytes
        Raw APDUs (UDP payloads / serial frames) received from the monitor.
    inventory : dict, optional
        Existing inventory to merge into. A new one is created if omitted.

    Returns
    -------
    dict
        Maps ``(oid_class, mds_context, handle)`` to :class:`Signal`.
    """
    if inventory is None:
        inventory = {}
    for data in packets:
        if codec.getMessageType(data) not in POLL_REPLY_TYPES:
            continue
        try:
            msg = codec.readData(data)
        except Exception:
            continue
        _merge_observations(inventory, msg)
    return inventory


def collect_enumeration(send, recv, codec, classes=None, timeout=5.0):
    """Run a full enumeration exchange over arbitrary transport callables.

    Sends one extended poll per object class (each with a distinct poll number
    so replies can be told apart), then reads replies until every class has
    returned its final ``RORS`` segment or `timeout` elapses.

    Parameters
    ----------
    send : callable
        ``send(bytes) -> None``. Writes one APDU to the monitor.
    recv : callable
        ``recv() -> bytes``. Reads one APDU. Should raise on timeout (a bare
        ``socket.timeout``/``OSError`` ends collection cleanly) rather than
        block forever.
    codec : IntellivueData
        Codec used to build the polls and decode the replies.
    classes : sequence of str, optional
        Object classes to poll. Defaults to all keys of :data:`CLASS_POLLS`.
    timeout : float, optional
        Overall wall-clock budget in seconds for the reply loop.

    Returns
    -------
    dict
        Maps ``(oid_class, mds_context, handle)`` to :class:`Signal`.
    """
    if classes is None:
        classes = tuple(CLASS_POLLS)

    for poll_number, oid_class in enumerate(classes, start=1):
        message_type = CLASS_POLLS[oid_class][0]
        send(codec.writeData(message_type, {"poll_number": poll_number}))

    inventory = {}
    pending = set(classes)
    refused = 0
    deadline = time.monotonic() + timeout

    while len(pending) > refused and time.monotonic() < deadline:
        try:
            data = recv()
        except (OSError, TimeoutError):
            break
        if not data:
            continue

        message_type = codec.getMessageType(data)
        if message_type == ERROR_REPLY_TYPE:
            # One poll will never be answered; stop waiting on one class. Which
            # one is unknowable from the error, so this only ends the loop once
            # every still-pending class has been accounted for.
            refused += 1
            continue
        if message_type not in POLL_REPLY_TYPES:
            continue
        try:
            msg = codec.readData(data)
        except Exception:
            continue

        _merge_observations(inventory, msg)
        if message_type == FINAL_REPLY_TYPE:
            pending.discard(_reply_class(msg))

    return inventory


def format_inventory(inventory):
    """Render an inventory as a human-readable table."""
    lines = [
        f"{'CLASS':<26}{'ctx':>4}{'handle':>8}  {'disp':<10} label / unit",
        "-" * 100,
    ]
    for signal in sorted(
        inventory.values(),
        key=lambda s: (str(s.oid_class), s.mds_context or 0, s.handle or 0),
    ):
        unit = f"  [{signal.unit}]" if signal.unit else ""
        lines.append(
            f"{str(signal.oid_class):<26}{signal.mds_context!s:>4}"
            f"{signal.handle!s:>8}  {str(signal.label_string or ''):<10} "
            f"{signal.label or '?'}{unit}"
        )
    lines.append("-" * 100)
    counts = Counter(s.oid_class for s in inventory.values())
    lines.append(f"counts: {dict(counts)} | total objects: {len(inventory)}")
    return "\n".join(lines)


def read_pcap_payloads(path):
    """Extract UDP payloads from a pcap/pcapng capture.

    Requires ``tshark`` on ``PATH``. Used only by the offline ``--pcap`` mode;
    the live path and the test suite do not need it.

    Parameters
    ----------
    path : str
        Path to a pcap/pcapng file of an enumeration exchange.

    Returns
    -------
    list of bytes
        Payloads in capture order.
    """
    try:
        output = subprocess.check_output(
            [
                "tshark", "-r", path,
                "-Y", "udp && data.data",
                "-T", "fields",
                "-e", "udp.srcport",
                "-e", "udp.dstport",
                "-e", "data.data",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError("tshark is required to read a pcap; install Wireshark's CLI")

    payloads = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[2]:
            payloads.append(binascii.unhexlify(fields[2].replace(":", "")))
    return payloads


def _enumerate_from_pcap(path):
    codec = IntellivueData()
    payloads = read_pcap_payloads(path)
    print(f"read {len(payloads)} UDP payloads from {os.path.basename(path)}\n")
    return harvest_inventory(codec, payloads)


def _enumerate_live(transport, host, port, timeout):
    # Imported lazily: the live path pulls in the socket stack, while the
    # offline path needs nothing but the codec.
    from intellipy.client import IntellivueClient

    options = {"timeout": timeout}
    if transport == "udp":
        options["portAddress"] = host
        options["portNumber"] = port
    else:
        options["portAddress"] = host

    with IntellivueClient(transport=transport, **options) as client:
        client.associate()
        return {signal.key: signal for signal in client.enumerate(timeout=timeout)}


def main(argv=None):
    """Command line entry point for ``intellipy-enumerate``."""
    parser = argparse.ArgumentParser(
        description="Enumerate the signals an IntelliVue monitor exposes."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--pcap", metavar="PATH",
        help="decode an offline capture of an enumeration exchange (needs tshark)",
    )
    source.add_argument(
        "--live", action="store_true",
        help="associate with a real monitor and enumerate it",
    )
    parser.add_argument(
        "--transport", choices=("udp", "rs232"), default="udp",
        help="transport for --live (default: udp)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="monitor address for --live; serial device for rs232 (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=24005,
        help="UDP port for --live (default: 24005)",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0,
        help="seconds to wait for poll replies (default: 5)",
    )
    args = parser.parse_args(argv)

    if args.pcap:
        inventory = _enumerate_from_pcap(args.pcap)
    else:
        inventory = _enumerate_live(
            args.transport, args.host, args.port, args.timeout
        )

    print(format_inventory(inventory))
    return 0 if inventory else 1


if __name__ == "__main__":
    sys.exit(main())
