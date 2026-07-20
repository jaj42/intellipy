# Glossary

Every acronym you will meet in the Data Export guide, in this documentation, or in the
codec's own variable names.

```{glossary}
ACSE
  Association Control Service Element. The ISO layer that opens and closes an
  {term}`association`, and where poll profile options are negotiated. See
  {doc}`association`.

Association
  A negotiated session between one client and one monitor. Nothing can be polled
  outside one. Opened with an association request, kept alive by periodic traffic,
  ended by a release request.

Attribute
  One named, typed property of an {term}`object` — its handle, its label, its unit, its
  current value. Identified by an {term}`OID`.

Attribute group
  A predefined bundle of attributes that a poll can ask for as a unit. `ALL` means
  every attribute, which is what makes {doc}`enumeration` work.

AVA
  Attribute-Value-Assertion. One entry of an `AttributeList`: attribute id, length,
  value. The codec surfaces these as `AttributeList["AVAType"][name]["AttributeValue"]`.

BCD
  Binary-coded decimal. How the protocol encodes wall-clock times and dates —
  the year 2026 is the bytes `0x20 0x26`, not the integer 2026.

Compound value
  An {term}`object` reporting several related numbers under one label — a blood
  pressure's systolic, diastolic and mean. Members are distinguished by their
  {term}`SCADA type`.

Connect indication
  The broadcast a monitor sends on UDP port 24005 announcing itself and naming the
  data port a session will actually use.

Data Export protocol
  Philips' documented interface for streaming live data off an IntelliVue monitor.
  Built on ISO/IEEE 11073 with vendor extensions. What this library implements.

Enumeration (objects)
  The metric class `NOM_MOC_VMO_METRIC_ENUM`, reporting a *state* rather than a
  number — ECG rhythm and ectopic status. Not to be confused with:

Enumeration (of signals)
  Discovering what a monitor exposes, by polling each class with attribute group
  `ALL`. See {doc}`enumeration`.

Extended poll
  `NOM_ACT_POLL_MDIB_DATA_EXT`. A poll carrying a *period*: the monitor keeps
  reporting the requested class, unprompted, until that period expires. The protocol's
  closest thing to a subscription.

Handle
  A 16-bit integer identifying one {term}`object` within one {term}`MDS context`.
  Stable for the life of the association; not stable across associations.

Keep-alive
  Traffic sent purely to stop the monitor timing the {term}`association` out. Here, a
  single poll sent when nothing else has been sent recently.

Label
  See {term}`physiological label`. Note the distinction from {term}`label string`.

Label string
  `NOM_ATTR_ID_LABEL_STRING` — the text the *monitor* displays for an object. May be
  localised, and is not a key into the shipped nomenclature tables.

Linked result
  See {term}`ROLRS`.

MDIB
  Medical Data Information Base. The conceptual database of {term}`object`\s an
  {term}`MDS` exposes. Queried attribute-group by attribute-group; never downloaded
  whole.

MDS
  Medical Device System. The object representing the monitor itself
  (`NOM_MOC_VMS_MDS`), and the addressee of every request — even requests about its
  children.

MDS context
  Identifier distinguishing several device systems fronted by one connection, e.g. a
  host monitor and a docked rack. {term}`Handle`\s are unique only within a context.

MOC
  Managed Object Class. The class an {term}`object` belongs to, e.g.
  `NOM_MOC_VMO_METRIC_NU` for numerics.

Nomenclature
  The ISO/IEEE 11073-10101 code space in which every class, attribute, unit,
  measurement and label is a number. `NOM_*` names are the readable spelling of those
  numbers. See {ref}`nomenclature`.

NOM_PART_*
  A nomenclature *partition* — the sub-space a code is drawn from. `NOM_PART_OBJ` for
  objects and attributes, `NOM_PART_SCADA` for measurements, `NOM_PART_DIM` for units,
  `NOM_PART_EVT` for alarms. A bare code is ambiguous without its partition.

Numeric
  A measured scalar — heart rate, SpO₂, a pressure. Class `NOM_MOC_VMO_METRIC_NU`.

Object
  One thing the monitor measures or reports, holding {term}`attribute`\s and
  identified by a {term}`handle`. See {doc}`model`.

OID
  Object identifier: the 16-bit nomenclature code naming a class, an attribute or an
  action. The same code can mean different things in different positions — see
  {ref}`one code, several meanings <oid-overloading>`.

Physiological label
  `NOM_ATTR_ID_LABEL` — a 32-bit code naming what an object measures, with a short
  display form attached (`0x00024182` = `HR` = "Heart Rate"). The name to use when
  subscribing to a waveform.

Poll number
  A client-chosen integer echoed in a poll's replies, so replies to concurrent polls of
  different classes can be told apart.

Priority list
  The monitor's list of waveforms eligible for real-time export. Starts **empty**; set
  it or receive no waveform samples.

RelativeTime
  A duration or timestamp in ticks of 1/8000 s. Sample times are relative to the tick
  count captured at association.

ROER
  Remote Operation Error. The monitor declined the request — e.g. an enumeration poll
  on an association that never negotiated `POLL_EXT_ENUM`.

ROIV
  Remote Operation Invoke. A request. Everything the client sends.

ROLRS
  Remote Operation Linked Result. A reply segment with **more to come**. Long poll
  replies arrive as a run of these, terminated by a {term}`RORS`. Segments must be
  merged, not replaced.

RORS
  Remote Operation Result. A reply, and the **last** one for its invocation. Seeing it
  is how a client knows a poll cycle is complete.

ROSE
  Remote Operation Service Element. The ISO request/response framework carrying
  {term}`ROIV`/{term}`RORS`/{term}`ROER`/{term}`ROLRS`. See {ref}`rose`.

SCADA type
  A code naming the physiological quantity a *value* represents, e.g.
  `NOM_ECG_ELEC_POTL_II`. Distinguishes the members of a {term}`compound value`.

Single poll
  `NOM_ACT_POLL_MDIB_DATA`. One request, one snapshot. Used for demographics and as a
  {term}`keep-alive`.

SPpdu
  The session-layer PDU. Byte `0xE1` for data messages; association-phase messages use
  ISO session codes instead (`0x0D` connect, `0x0E` accept, …).

VMO
  Virtual Medical Object. 11073's term for a protocol-level object — a measured
  quantity, not a piece of hardware.

VMS
  Virtual Medical System. The system-level counterpart, as in `NOM_MOC_VMS_MDS`.

Wave / RTSA
  A real-time sampled waveform. Class `NOM_MOC_VMO_METRIC_SA_RT`; delivered as blocks
  of scaled integers plus the scaling and sampling period needed to interpret them.
```
