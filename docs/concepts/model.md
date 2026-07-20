# The information model

## MDS, MDIB, objects

A monitor speaking Data Export presents itself as a **Medical Device System (MDS)** —
one object representing the whole device. In the nomenclature it is
`NOM_MOC_VMS_MDS`, and it is the object every request in this protocol is *addressed
to*, even when the data you want lives elsewhere.

Everything the MDS knows is its **MDIB** (Medical Data Information Base): a tree of
**managed objects**, one per thing the monitor measures or reports. The MDIB is not a
file you download; it is a conceptual database you query attribute-group by
attribute-group.

Objects belong to **classes** (their `MOC`, Managed Object Class). The four that
matter for data export:

| Class | OID | Holds |
|---|---|---|
| `NOM_MOC_VMO_METRIC_NU` | 6 | Numerics — heart rate, SpO₂, a blood pressure triplet |
| `NOM_MOC_VMO_METRIC_SA_RT` | 9 | Real-time sampled waveforms — ECG, Pleth, ABP, Resp |
| `NOM_MOC_VMO_AL_MON` | 54 | The alarm monitor, whose attributes are the active alarm lists |
| `NOM_MOC_VMO_METRIC_ENUM` | 5 | Enumerations — a *state* rather than a number (ECG rhythm) |

Plus one non-metric class this library reads: `NOM_MOC_PT_DEMOG`, the patient
demographics record (see {doc}`../guides/demographics`).

`VMO` stands for Virtual Medical Object and `VMS` for Virtual Medical System — the
"virtual" is 11073's way of saying these are protocol-level abstractions, not
hardware. A `NOM_MOC_VMO_METRIC_NU` object does not correspond to a physical module;
it corresponds to *one measured quantity that the monitor is currently producing*.

## Handles and MDS contexts

Within a class, each object is identified by a **handle** — a 16-bit integer, stable
for as long as the object exists. `SpO2` on the captured monitor is handle 33749;
heart rate is 33459; the ABP waveform is 2332. Handles are what you match samples
against once data is flowing.

Handles are only unique within one **MDS context**. A monitor can front several
device systems — a host monitor plus a docked module rack or transport monitor — and
each gets a context id; the poll reply nests objects under a `SingleContextPoll`
naming it. This is not a corner case: the reference capture has objects in contexts 0
*and* 1, with the ECG waveform in one and the arterial pressure waveform in the other.
`intellipy` therefore keys its inventory on `(class, context, handle)`, not on the
handle alone.

## Attributes and AVAs

An object is a bag of **attributes**, each identified by an OID and carrying a typed
value. Reading a poll reply means walking an **AttributeList**, whose entries are
**AVAs** (Attribute-Value-Assertions) — a triple of *attribute id*, *length*, *value*:

```
AttributeList
  count = 6, length = 84
  AVAType
    NOM_ATTR_ID_HANDLE        →  33749
    NOM_ATTR_ID_LABEL         →  "Arterial Oxigen Saturation"
    NOM_ATTR_ID_LABEL_STRING  →  "SpO₂"
    NOM_ATTR_UNIT_CODE        →  "% ( percentage )"
    NOM_ATTR_NU_VAL_OBS       →  { FLOATType: 98.0, UNITType: …, MeasurementState: … }
    …
```

(The codec resolves the numeric codes to their nomenclature entries as it parses, so
what you actually get back is a dict of names and Python values, not raw integers.
`NOM_ATTR_ID_LABEL_STRING` is the monitor's own display text and may be localised;
`NOM_ATTR_ID_LABEL` is a nomenclature code and is not.)

The attributes worth knowing by name:

| Attribute | Meaning |
|---|---|
| `NOM_ATTR_ID_HANDLE` | The object's handle |
| `NOM_ATTR_ID_LABEL` | *What* it measures, as a 32-bit physiological label |
| `NOM_ATTR_ID_LABEL_STRING` | The short display string, e.g. `"SpO2"` |
| `NOM_ATTR_UNIT_CODE` | Unit of measure |
| `NOM_ATTR_NU_VAL_OBS` | A numeric's observed value |
| `NOM_ATTR_NU_CMPD_VAL_OBS` | A *compound* numeric's values (see below) |
| `NOM_ATTR_SA_VAL_OBS` | A waveform's block of samples |
| `NOM_ATTR_SCALE_SPECN_I16` | How to convert those samples to physical units |
| `NOM_ATTR_TIME_PD_SAMP` | Sampling period, in monitor ticks |
| `NOM_ATTR_VAL_ENUM_OBS` | An enumeration object's state |
| `NOM_ATTR_AL_MON_P_AL_LIST` | Active *patient* alarms |
| `NOM_ATTR_AL_MON_T_AL_LIST` | Active *technical* alarms |

:::{important}
**Metadata is sent once.** Labels, units, sampling period and scaling appear in the
*first* poll cycle after a poll is issued; later cycles carry bare values. A client
that does not cache them per handle will see every sample after the first come back
unlabelled and unscaled. {class}`~intellipy.client.IntellivueClient` caches them for
you; if you write your own decoder, this is the first thing that will bite you.
:::

## Simple and compound objects

Some objects report one number; others report several that belong together. An
invasive blood pressure is one object with one label ("ABP") reporting systolic,
diastolic and mean as a **compound** value (`NOM_ATTR_NU_CMPD_VAL_OBS`). Its members
are told apart not by label — they share it — but by their **SCADA type**, the code
naming the physiological quantity: `NOM_PRESS_BLD_ART_ABP_SYS`, `…_DIA`, `…_MEAN`.

`intellipy` flattens compounds into one sample per member, labelled
`{object label}_{last word of the SCADA type}` — `ABP_SYS`, `ABP_DIA`, `ABP_MEAN` —
which is what downstream consumers of the original project expect. Compound
*waveforms* work the same way, except the sample's `label` is the full SCADA type and
the object's own name is kept alongside it as `object_label`.

(nomenclature)=
## Nomenclature: what all those `NOM_*` names are

Nothing in this protocol is transmitted as text. Every class, attribute, unit,
measurement, alarm and physiological label is a number drawn from the **ISO/IEEE
11073-10101 nomenclature**, and the `NOM_*` names are just the human-readable spelling
of those numbers. `NOM_DIM_PERCENT` is 544; `NOM_MOC_VMS_MDS` is 33.

The nomenclature is divided into **partitions**, so a bare 16-bit code is ambiguous
until you know which partition it came from. The one used for object and attribute
identifiers is `NOM_PART_OBJ`; measurements come from `NOM_PART_SCADA`, units from
`NOM_PART_DIM`, alarms from `NOM_PART_EVT`. `intellipy` ships one lookup table per
partition, and {doc}`../protocol/nomenclature` renders all of them.

Philips extends the standard nomenclature with private codes, conventionally at
`0xF000` and above. Those are documented in the vendor's Data Export guide, not in the
ISO standard.

(oid-overloading)=
:::{admonition} One code space, several meanings
:class: caution

Because object classes, attributes and actions all draw on `NOM_PART_OBJ`, the same
number can mean different things in different positions. `0xF001` (61441) is
`NOM_ATTR_POLL_PROFILE_EXT` inside an association response but `NOM_ATTR_PT_ID_INT`
inside the patient demographics group. The codec resolves this by tracking which
object class a reply was polled from — a real bug found while implementing
{doc}`../guides/demographics`.
:::

## Labels versus SCADA types

Two different naming systems appear on every object, and confusing them is easy:

**Physiological label** (`NOM_ATTR_ID_LABEL`, from `PhysioLabels.txt`)
: A 32-bit code for what the object *is*, with a short screen label attached —
  `0x00024182` = `HR` = "Heart Rate". The **code** is what identifies the object and
  what a priority list carries; the readable forms are renderings of it, and neither
  is a reliable key back — see {doc}`../guides/enumeration`.

**SCADA type** (from `SCADATypes.txt`)
: A 16-bit code for what a *particular value* represents —
  `NOM_ECG_ELEC_POTL_II` for the lead II potential, `NOM_PRESS_BLD_ART_ABP_MEAN` for
  mean arterial pressure. Used to disambiguate compound members.

An object labelled `ECG Lead MCL` can carry a value typed `NOM_ECG_ELEC_POTL_II`;
they are answering different questions.

## Time

The monitor counts in **ticks of 1/8000 s**. Two clocks matter:

- **Relative time** — a free-running tick counter. The MDS create event reports its
  value at association; every sample timestamp is measured from that origin.
  {class}`~intellipy.client.IntellivueClient` converts these to *seconds since
  association* before yielding a sample.
- **Absolute time** — a BCD wall-clock record (century, year, month, day, …), also
  reported at association, so relative times can be anchored to real time if needed.

Waveform blocks carry one timestamp for the whole block; per-sample times are
reconstructed from the sampling period, which is why `NOM_ATTR_TIME_PD_SAMP` must be
cached.
