"""A saver-free live client for the IntelliVue Data Export protocol.

:class:`IntellivueClient` drives one monitor session end to end::

    with IntellivueClient("udp") as client:
        client.associate()
        for signal in client.enumerate():
            print(signal)
        client.set_wave_priority(["Pleth"])
        for sample in client.stream(duration=60):
            print(sample)

It replaces the older :mod:`~intellipy.ConnectToIntellivueUDP` /
:mod:`~intellipy.ConnectToIntellivueRS232` drivers, which hard-wired a
``SaveProtocol`` and a collection thread. Here the transport is chosen at
construction, decoding is delegated unchanged to
:class:`~intellipy.IntellivueDataFiles.IntellivueData.IntellivueData`, and
:meth:`IntellivueClient.stream` simply *yields* decoded samples, leaving
threading and storage to the caller.

Samples are plain dicts, using the schema the queue-based consumers of the
original project already expect:

==========  ================================================================
kind        keys
==========  ================================================================
``numeric`` ``kind``, ``label``, ``handle``, ``time``, ``value``, ``unit``
``wave``    ``kind``, ``label``, ``handle``, ``time`` (list), ``wave`` (list)
``alarm``   ``kind``, ``label``, ``handle``, ``time``, ``code``, ``source``,
            ``alarm_type``, ``state``, ``text``
==========  ================================================================

Times are seconds elapsed since the association's relative time origin.

Only the UDP path can be verified against the reference capture; the RS232
path mirrors it structurally but is untested here (see the docs).
"""

import time

from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData
from intellipy.enumerate import (
    CLASS_POLLS,
    _attribute_value,
    _find,
    _iter_observations,
    collect_enumeration,
)

__all__ = ["IntellivueClient", "AssociationError"]

#: The monitor expresses every duration in 1/8000 s ticks.
TICKS_PER_SECOND = 8000

#: Poll replies carrying streamed observations.
POLL_REPLY_TYPES = ("MDSExtendedPollActionResult", "LinkedMDSExtendedPollActionResult")

#: Replies to a single (non-extended) poll, as used for patient demographics.
SINGLE_POLL_REPLY_TYPES = (
    "MDSSinglePollActionResult",
    "LinkedMDSSinglePollActionResult",
)

#: Extended-poll template per object class, in the order `stream` sends them.
STREAM_POLLS = (
    ("NOM_MOC_VMO_METRIC_NU", "MDSExtendedPollActionNUMERIC"),
    ("NOM_MOC_VMO_METRIC_SA_RT", "MDSExtendedPollActionWAVE"),
    ("NOM_MOC_VMO_AL_MON", "MDSExtendedPollActionALARM"),
)

#: Seconds of margin subtracted from the negotiated keep-alive period.
KEEP_ALIVE_MARGIN = 5.0


class AssociationError(RuntimeError):
    """Raised when the association handshake cannot be completed."""


def _is_leaf(value):
    """True for the dict entries that are real children, not `count`/`length`."""
    return isinstance(value, dict)


def _scale_factors(scale_range_spec):
    """Linear conversion ``y = a * x + b`` from a ``ScaleRangeSpec16``.

    Waveform samples arrive as scaled integers; this recovers the physiological
    value. Monitors that report an unset (string) bound get the identity.

    Parameters
    ----------
    scale_range_spec: dict
        ``NOM_ATTR_SCALE_SPECN_I16`` attribute value.

    Returns
    -------
    (a, b): tuple of float

    """
    upper = scale_range_spec["upper_absolute_value"]["FLOATType"]
    lower = scale_range_spec["lower_absolute_value"]["FLOATType"]
    if isinstance(upper, str) or isinstance(lower, str):
        return 1.0, 0.0

    x_range = (
        scale_range_spec["upper_scaled_value"] - scale_range_spec["lower_scaled_value"]
    )
    if not x_range:
        return 1.0, 0.0

    a = (upper - lower) / x_range
    b = lower - a * scale_range_spec["lower_scaled_value"]
    return a, b


def _demog_string(attributes, name):
    """A demographics String attribute, or None when blank.

    The monitor pads unset text fields to a lone NUL terminator rather than
    omitting them.
    """
    value = _attribute_value(attributes, name).get("String", {})
    if not isinstance(value, dict):
        return None
    text = str(value.get("value", "")).rstrip("\x00").strip()
    return text or None


def _demog_measure(attributes, name):
    """A ``PatMeasure`` as ``(value, unit)``; value is None when unset.

    Unset measurements carry the IEEE-1073 NaN code, which the codec surfaces
    as the string ``"Not a number"``, but still name their unit.
    """
    value = _attribute_value(attributes, name).get("PatMeasure", {})
    if not isinstance(value, dict):
        return None, None

    number = value.get("FLOATType")
    unit = value.get("UNITType")
    if isinstance(number, str):
        number = None
    return number, unit


def _demog_date(attributes, name):
    """A date of birth as ``YYYY-MM-DD``, or None when unset.

    ``AbsoluteTime`` is BCD; an all-zero record means "no date".
    """
    value = _attribute_value(attributes, name).get("AbsoluteTime", {})
    if not isinstance(value, dict):
        return None

    century = value.get("century", 0)
    year = value.get("year", 0)
    month = value.get("month", 0)
    day = value.get("day", 0)
    if not (century or year or month or day):
        return None
    return f"{century:02d}{year:02d}-{month:02d}-{day:02d}"


def _parse_demographics(observation):
    """Flatten a ``NOM_MOC_PT_DEMOG`` ``ObservationPoll`` into a plain dict."""
    attributes = observation.get("AttributeList", {})

    return {
        "handle": observation.get("Handle"),
        "state": _attribute_value(attributes, "NOM_ATTR_PT_DEMOG_ST").get(
            "PatDemoState"
        ),
        "patient_id": _demog_string(attributes, "NOM_ATTR_PT_ID"),
        "name_given": _demog_string(attributes, "NOM_ATTR_PT_NAME_GIVEN"),
        "name_family": _demog_string(attributes, "NOM_ATTR_PT_NAME_FAMILY"),
        "notes1": _demog_string(attributes, "NOM_ATTR_PT_NOTES1"),
        "notes2": _demog_string(attributes, "NOM_ATTR_PT_NOTES2"),
        "dob": _demog_date(attributes, "NOM_ATTR_PT_DOB"),
        "sex": _attribute_value(attributes, "NOM_ATTR_PT_SEX").get("PatientSex"),
        "patient_type": _attribute_value(attributes, "NOM_ATTR_PT_TYPE").get(
            "PatientType"
        ),
        "paced_mode": _attribute_value(attributes, "NOM_ATTR_PT_PACED_MODE").get(
            "PatPacedMode"
        ),
        "age": _demog_measure(attributes, "NOM_ATTR_PT_AGE"),
        "height": _demog_measure(attributes, "NOM_ATTR_PT_HEIGHT"),
        "weight": _demog_measure(attributes, "NOM_ATTR_PT_WEIGHT"),
        "bsa": _demog_measure(attributes, "NOM_ATTR_PT_BSA"),
        "bsa_formula": _attribute_value(attributes, "NOM_ATTR_PT_BSA_FORMULA").get(
            "PatBsaFormula"
        ),
        "attributes": attributes,
    }


class IntellivueClient:
    """A live connection to one IntelliVue monitor.

    Parameters
    ----------
    transport: str
        ``"udp"`` or ``"rs232"``.

    portAddress: str
        Monitor address for UDP (default ``0.0.0.0``, i.e. listen on every
        interface for the monitor's connect indication), or the serial device
        node for RS232.

    portNumber: int
        UDP port to bind; the monitor announces its data port in the connect
        indication and the socket is retargeted there. Unused for RS232.

    timeout: float
        Seconds any single `receive` may block. Bounds the enumeration and
        streaming loops so they cannot hang on a silent monitor.

    Attributes
    ----------
    keep_alive_time: float
        Longest silence the monitor tolerates, in seconds, negotiated in the
        association response.

    initial_time: dict
        Absolute wall-clock time reported by the monitor at association.

    relative_initial_time: int
        Monitor tick count at association; the origin all sample times are
        measured from.

    """

    def __init__(
        self,
        transport="udp",
        portAddress=None,
        portNumber=24005,
        timeout=5.0,
        device=None,
    ):
        self.transport = transport
        self.timeout = timeout
        self.codec = IntellivueData()

        if transport == "udp":
            from intellipy.Sockets.UDP import UDP

            self.socket = UDP(
                portAddress="0.0.0.0" if portAddress is None else portAddress,
                portNumber=portNumber,
                timeout=timeout,
            )
        elif transport == "rs232":
            from intellipy.Sockets.RS232 import RS232

            self.socket = RS232(device or portAddress, timeout=timeout)
        else:
            raise ValueError(f"unknown transport {transport!r}; use 'udp' or 'rs232'")

        self.associated = False
        self.keep_alive_time = 0.0
        self.initial_time = None
        self.relative_initial_time = 0

        # Object metadata (label, and for waves the sampling rate and scaling)
        # arrives once, in the first poll cycle; later cycles carry bare values.
        # Cache it by handle so those can still be decoded and labelled.
        self._wave_info = {}
        self._numeric_labels = {}

    # -- connection lifecycle ------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def associate(self):
        """Perform the association handshake.

        Over UDP the monitor speaks first: it broadcasts a connect indication
        naming its data port, which the socket is then retargeted to. Over
        RS232 there is no discovery step, so the request goes out immediately.
        Both paths then expect an association response followed by an MDS
        create event, which must be acknowledged.

        Returns
        -------
        bool
            True once associated.

        Raises
        ------
        AssociationError
            If the monitor refuses, releases, or never answers.

        """
        if self.transport == "udp":
            self._await_connect_indication()

        self.socket.send(self.codec.writeData("AssociationRequest"))
        self._complete_association()
        self.associated = True
        return True

    def _await_connect_indication(self):
        """Listen on the broadcast port until a monitor announces itself."""
        self.socket.bind()

        deadline = time.monotonic() + max(self.timeout, 1.0) * 4
        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if not message:
                continue

            message_type = self.codec.getMessageType(message)
            if message_type == "ConnectIndicationEvent":
                _, portNumber, portAddress = self.codec.readData(message)
                self.socket.portAddress = portAddress
                self.socket.portNumber = portNumber
                return
            if message_type in ("ReleaseRequest", "AssociationAbort"):
                raise AssociationError(f"monitor sent {message_type} before associating")

        raise AssociationError("no ConnectIndicationEvent received from any monitor")

    def _complete_association(self):
        """Read the association response + MDS create event, acknowledge them."""
        response = None
        deadline = time.monotonic() + max(self.timeout, 1.0) * 4

        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if not message:
                continue

            message_type = self.codec.getMessageType(message)

            if message_type == "AssociationResponse":
                response = self.codec.readData(message)
                self.keep_alive_time = (
                    response["AssocRespUserData"]["MDSEUserInfoStd"][
                        "supported_aprofiles"
                    ]["AttributeList"]["AVAType"]["NOM_POLL_PROFILE_SUPPORT"][
                        "AttributeValue"
                    ]["PollProfileSupport"]["min_poll_period"]["RelativeTime"]
                    / TICKS_PER_SECOND
                )

            elif message_type == "MDSCreateEvent":
                create_event, parameters = self.codec.readData(message)
                attributes = create_event["MDSCreateInfo"]["MDSAttributeList"][
                    "AttributeList"
                ]["AVAType"]
                self.initial_time = attributes["NOM_ATTR_TIME_ABS"]["AttributeValue"][
                    "AbsoluteTime"
                ]
                self.relative_initial_time = attributes["NOM_ATTR_TIME_REL"][
                    "AttributeValue"
                ]["RelativeTime"]

                # The create event must be acknowledged or the monitor keeps
                # re-announcing itself instead of accepting polls.
                self.socket.send(
                    self.codec.writeData("MDSCreateEventResult", parameters)
                )
                if response is not None:
                    return

            elif message_type in ("AssociationRefuse", "AssociationAbort"):
                raise AssociationError(f"monitor sent {message_type}")

        raise AssociationError("association was not completed before timeout")

    def close(self):
        """Release the association and close the socket.

        Safe to call more than once, and safe to call on a client that never
        associated.

        """
        if self.associated:
            try:
                self.socket.send(self.codec.writeData("ReleaseRequest"))
                self._drain_until(("ReleaseResponse", "AssociationAbort"))
            except OSError:
                pass
            self.associated = False

        try:
            self.socket.close()
        except OSError:
            pass

    def _drain_until(self, message_types, timeout=None):
        """Read and discard messages until one of `message_types` shows up."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if message and self.codec.getMessageType(message) in message_types:
                return True
        return False

    # -- discovery and subscription -----------------------------------------

    def enumerate(self, classes=None, timeout=None):
        """Ask the monitor which signals it exposes.

        Runs the same :func:`~intellipy.enumerate.collect_enumeration` routine
        the offline pcap decoder uses, over this client's socket.

        Parameters
        ----------
        classes: sequence of str, optional
            Object classes to poll; defaults to numerics, waveforms and alarms.

        timeout: float, optional
            Wall-clock budget for the reply loop. Defaults to the client's
            timeout.

        Returns
        -------
        list of Signal
            Every object the monitor reported, ordered by class then handle.

        """
        budget = self.timeout if timeout is None else timeout
        inventory = collect_enumeration(
            self.socket.send,
            self.socket.receive,
            self.codec,
            classes=classes,
            timeout=budget,
        )
        return sorted(
            inventory.values(),
            key=lambda signal: (str(signal.oid_class), signal.handle or 0),
        )

    def set_wave_priority(self, labels):
        """Subscribe to a set of waveforms by label.

        The monitor streams only the waveforms on its real-time priority list,
        which starts out empty -- so without this call :meth:`stream` yields
        numerics and alarms but no waves.

        Parameters
        ----------
        labels: sequence of str
            Waveform labels, e.g. ``["Pleth", "ECG MCL"]``, as reported by
            :meth:`enumerate`.

        Returns
        -------
        dict or None
            The decoded ``MDSSetPriorityListResult``, or None if the monitor
            did not confirm within the timeout.

        """
        self.socket.send(
            self.codec.writeData(
                "MDSSetPriorityListWAVE", {"TextIdLabel": list(labels)}
            )
        )

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if not message:
                continue
            if self.codec.getMessageType(message) == "MDSSetPriorityListResult":
                return self.codec.readData(message)
        return None

    def get_priority_list(self):
        """Read back the monitor's current real-time priority list."""
        self.socket.send(self.codec.writeData("MDSGetPriorityList"))

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if not message:
                continue
            if self.codec.getMessageType(message) == "MDSGetPriorityListResult":
                return self.codec.readData(message)
        return None

    # -- patient demographics -------------------------------------------------

    def get_patient_demographics(self):
        """Ask the monitor who the current patient is.

        Sends a single poll against the ``NOM_MOC_PT_DEMOG`` object and decodes
        its Patient Demographics attribute group. Unset fields come back as
        ``None`` rather than as the protocol's blank strings and NaNs, so an
        unadmitted bed yields a dict of mostly ``None``.

        The returned values are patient identifiers -- name, medical record
        number, date of birth. Handle and store them accordingly.

        Returns
        -------
        dict or None
            Demographics, or None if the monitor did not answer within the
            timeout. Keys: ``state``, ``patient_id``, ``name_given``,
            ``name_family``, ``dob``, ``sex``, ``patient_type``,
            ``paced_mode``, ``age``, ``height``, ``weight``, ``bsa``,
            ``bsa_formula``, ``notes1``, ``notes2``, ``handle``. Each of
            ``age``/``height``/``weight``/``bsa`` is a ``(value, unit)`` pair.
            ``attributes`` holds the raw decoded attribute list.

        """
        self.socket.send(self.codec.writeData("MDSPatientDemographicsPoll"))

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                message = self.socket.receive()
            except TimeoutError:
                continue
            if not message:
                continue
            if self.codec.getMessageType(message) not in SINGLE_POLL_REPLY_TYPES:
                continue

            decoded = self.codec.readData(message)
            reply = _find(decoded, "PollMdibDataReply")
            if not isinstance(reply, dict):
                continue
            if reply.get("Type", {}).get("OIDType") != "NOM_MOC_PT_DEMOG":
                continue

            for _, observation in _iter_observations(decoded):
                return _parse_demographics(observation)
        return None

    # -- streaming -----------------------------------------------------------

    def stream(self, duration=None, classes=None):
        """Yield decoded samples for as long as the monitor keeps sending them.

        Sends one extended poll per object class, then decodes replies as they
        arrive, emitting one dict per numeric value, waveform block or alarm
        entry. Keep-alive polls are injected automatically so the association
        survives quiet periods.

        Parameters
        ----------
        duration: float, optional
            Seconds to stream for. None (the default) streams until the
            monitor aborts or the caller stops consuming the generator.

        classes: sequence of str, optional
            Object classes to poll; defaults to numerics, waveforms and alarms.

        Yields
        ------
        dict
            A sample; see the module docstring for the per-kind schema.

        """
        wanted = set(CLASS_POLLS if classes is None else classes)
        poll_ticks = int((duration or 60 * 60 * 72) * TICKS_PER_SECOND)

        for poll_number, (oid_class, message_type) in enumerate(STREAM_POLLS, start=1):
            if oid_class in wanted:
                self.socket.send(
                    self.codec.writeData(
                        message_type,
                        {"RelativeTime": poll_ticks, "poll_number": poll_number},
                    )
                )

        started = time.monotonic()
        last_sent = started
        # A keep-alive is due before the negotiated period elapses; the margin
        # absorbs round-trip delay.
        keep_alive_period = max(self.keep_alive_time - KEEP_ALIVE_MARGIN, 1.0)

        while duration is None or time.monotonic() - started < duration:
            try:
                message = self.socket.receive()
            except TimeoutError:
                message = None
            except OSError:
                break

            if message:
                message_type = self.codec.getMessageType(message)

                if message_type == "AssociationAbort":
                    break
                if message_type in POLL_REPLY_TYPES:
                    yield from self._decode_poll_reply(self.codec.readData(message))

            if self.keep_alive_time and time.monotonic() - last_sent > keep_alive_period:
                self.socket.send(self.codec.writeData("MDSSinglePollAction"))
                last_sent = time.monotonic()

    def stream_to_queues(self, numeric_queue=None, wave_queue=None, alarm_queue=None,
                         duration=None):
        """Run :meth:`stream` and fan samples out into queues by kind.

        Blocks until the stream ends. Run it in a thread to feed the
        queue/generator pipelines the original project is built around; each
        queue gets a final ``None`` sentinel so consumers written as
        ``iter(queue.get, None)`` terminate cleanly.

        Parameters
        ----------
        numeric_queue, wave_queue, alarm_queue: queue.Queue, optional
            Destinations per sample kind. Samples whose queue is None are
            dropped.

        duration: float, optional
            Passed through to :meth:`stream`.

        """
        queues = {
            "numeric": numeric_queue,
            "wave": wave_queue,
            "alarm": alarm_queue,
        }
        try:
            for sample in self.stream(duration=duration):
                queue = queues.get(sample["kind"])
                if queue is not None:
                    queue.put(sample)
        finally:
            for queue in queues.values():
                if queue is not None:
                    queue.put(None)

    # -- decoding ------------------------------------------------------------

    def _relative_seconds(self, ticks):
        """Monitor ticks -> seconds since the association's time origin."""
        return (ticks - self.relative_initial_time) / TICKS_PER_SECOND

    def _decode_poll_reply(self, message):
        """Dispatch one decoded poll reply to the parser for its object class."""
        reply = _find(message, "PollMdibDataReplyExt")
        if not isinstance(reply, dict):
            return

        oid_class = reply.get("Type", {}).get("OIDType")
        timestamp = self._relative_seconds(reply.get("RelativeTime", 0))

        parsers = {
            "NOM_MOC_VMO_METRIC_NU": self._parse_numerics,
            "NOM_MOC_VMO_METRIC_SA_RT": self._parse_waves,
            "NOM_MOC_VMO_AL_MON": self._parse_alarms,
        }
        parser = parsers.get(oid_class)
        if parser is None:
            return

        for _, observation in _iter_observations(message):
            yield from parser(observation, timestamp)

    def _parse_numerics(self, observation, timestamp):
        """Yield numeric samples from one ``ObservationPoll``.

        A numeric object holds either a single value or a compound one (blood
        pressure, say, reporting systolic/diastolic/mean together). Compound
        members share the object's label, so the SCADA type is appended to keep
        each series distinct -- matching the labels downstream consumers use.
        """
        attributes = observation.get("AttributeList", {})
        handle = observation.get("Handle")

        # Only the first poll cycle names the object; remember it for the rest.
        label = _attribute_value(attributes, "NOM_ATTR_ID_LABEL").get("TextId")
        if label:
            self._numeric_labels[handle] = label
        else:
            label = self._numeric_labels.get(handle)

        single = _attribute_value(attributes, "NOM_ATTR_NU_VAL_OBS").get("NuObsValue")
        if isinstance(single, dict):
            yield {
                "kind": "numeric",
                "label": str(label),
                "handle": handle,
                "time": timestamp,
                "value": single.get("FLOATType"),
                "unit": single.get("UNITType"),
            }

        compound = _attribute_value(attributes, "NOM_ATTR_NU_CMPD_VAL_OBS").get(
            "NuObsValCmp", {}
        )
        if isinstance(compound, dict):
            for entry in compound.values():
                if not _is_leaf(entry):
                    continue
                value = entry.get("NuObsValue", {})
                scada_type = value.get("SCADAType", "")
                yield {
                    "kind": "numeric",
                    "label": f"{label}_{str(scada_type).split('_')[-1]}",
                    "handle": handle,
                    "time": timestamp,
                    "value": value.get("FLOATType"),
                    "unit": value.get("UNITType"),
                }

    def _remember_wave_info(self, observation):
        """Cache scaling/sampling metadata for a waveform object.

        Only the first poll cycle carries these attributes, so they are stored
        per handle and reused for every later sample block from that handle.
        """
        attributes = observation.get("AttributeList", {})
        handle = observation.get("Handle")
        info = self._wave_info.setdefault(handle, {})

        # Each attribute is only recorded when actually present, so a later,
        # metadata-free cycle never blanks what an earlier one established.
        scale_spec = _attribute_value(attributes, "NOM_ATTR_SCALE_SPECN_I16").get(
            "ScaleRangeSpec16"
        )
        if isinstance(scale_spec, dict):
            info["conversion"] = _scale_factors(scale_spec)

        label = _attribute_value(attributes, "NOM_ATTR_ID_LABEL").get("TextId")
        if label:
            info["label"] = label

        unit = _attribute_value(attributes, "NOM_ATTR_UNIT_CODE").get("UNITType")
        if unit:
            info["unit"] = unit

        sample_period = _attribute_value(attributes, "NOM_ATTR_TIME_PD_SAMP").get(
            "RelativeTime"
        )
        if sample_period:
            info["sampling_rate"] = TICKS_PER_SECOND / sample_period

    def _wave_sample(self, handle, label, values, timestamp):
        """Build one wave sample, scaling values and timestamping each point."""
        info = self._wave_info.get(handle, {})
        a, b = info.get("conversion", (1.0, 0.0))
        sampling_rate = info.get("sampling_rate")

        if sampling_rate:
            step = 1.0 / sampling_rate
            times = [timestamp + i * step for i in range(len(values))]
        else:
            # No sampling period seen yet: stamp the whole block at its arrival.
            times = [timestamp] * len(values)

        return {
            "kind": "wave",
            "label": label,
            # The object's own label, kept alongside `label` because a compound
            # wave labels each series by SCADA type instead (see `_parse_waves`).
            "object_label": info.get("label"),
            "handle": handle,
            "time": times,
            "wave": [a * value + b for value in values],
            "unit": info.get("unit"),
        }

    def _parse_waves(self, observation, timestamp):
        """Yield waveform sample blocks from one ``ObservationPoll``."""
        self._remember_wave_info(observation)

        attributes = observation.get("AttributeList", {})
        handle = observation.get("Handle")
        info = self._wave_info.get(handle, {})

        single = _attribute_value(attributes, "NOM_ATTR_SA_VAL_OBS").get("SaObsValue")
        if isinstance(single, dict):
            values = single.get("PhysioValue", {}).get("VariableData", {}).get("value")
            if values is not None:
                label = info.get("label") or single.get("SCADAType")
                yield self._wave_sample(handle, str(label), list(values), timestamp)

        compound = _attribute_value(attributes, "NOM_ATTR_SA_CMPD_VAL_OBS").get(
            "SaObsValueCmp", {}
        )
        if isinstance(compound, dict):
            for entry in compound.values():
                if not _is_leaf(entry):
                    continue
                value = entry.get("SaObsValue", {})
                values = (
                    value.get("PhysioValue", {}).get("VariableData", {}).get("value")
                )
                if values is None:
                    continue
                # Compound waves are identified by SCADA type, not by the
                # object label, which they share.
                yield self._wave_sample(
                    handle, str(value.get("SCADAType")), list(values), timestamp
                )

    def _parse_alarms(self, observation, timestamp):
        """Yield one sample per active alarm in an alarm-monitor object."""
        attributes = observation.get("AttributeList", {})
        handle = observation.get("Handle")

        lists = (
            ("NOM_ATTR_AL_MON_P_AL_LIST", "patient"),
            ("NOM_ATTR_AL_MON_T_AL_LIST", "technical"),
        )
        for attribute_name, alarm_kind in lists:
            alarm_list = _attribute_value(attributes, attribute_name).get(
                "DevAlarmList", {}
            )
            if not isinstance(alarm_list, dict):
                continue

            for index, entry in enumerate(
                value for value in alarm_list.values() if _is_leaf(value)
            ):
                alarm = entry.get("DevAlarmEntry", {})
                text = alarm.get("StrAlMonInfo", {}).get("String", {})
                yield {
                    "kind": "alarm",
                    "label": f"{alarm_kind}_{index}",
                    "handle": handle,
                    "time": timestamp,
                    "code": alarm.get("al_code"),
                    "source": alarm.get("al_source"),
                    "alarm_type": alarm.get("AlertType"),
                    "state": alarm.get("AlertState"),
                    "text": text.get("value") if isinstance(text, dict) else None,
                }


if __name__ == "__main__":
    pass
