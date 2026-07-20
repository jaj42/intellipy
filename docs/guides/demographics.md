# Patient demographics

The monitor knows who is admitted to the bed, and will tell you: name, medical record
number, date of birth, sex, age, height, weight, body surface area, pacing mode and
free-text notes.

:::{warning}
**This returns directly identifying patient data.** Everything on this page is subject
to whatever governs patient data where you work — GDPR, HIPAA, your institution's
research approvals. `intellipy` imposes no policy and applies no de-identification;
handling is yours.

`intellipy-dump` writes demographics to their own `demographics.json`,
deliberately separate from the signal streams, so the identifying file can be
withheld, encrypted or deleted independently of the physiological recording. Pass
`--no-demographics` to skip it entirely.
:::

## Requesting it

```python
with IntellivueClient("udp") as client:
    client.associate()
    record = client.get_patient_demographics()
```

One {ref}`single poll <polls>` against the `NOM_MOC_PT_DEMOG` object — no extended
poll, no subscription. Returns a flat dict, or `None` if the monitor did not answer
within the timeout.

## What comes back

This is the real record from the reference capture — an unadmitted bed:

```python
{
    "handle": 80,
    "state": "DISCHARGED",
    "patient_id": None,
    "name_given": None,
    "name_middle": None,
    "name_family": None,
    "dob": None,
    "sex": "SEX_UNKNOWN",
    "patient_type": "ADULT",
    "paced_mode": "PAT_NOT_PACED",
    "age":    (None, "years ..."),
    "height": (None, "cm ..."),
    "weight": (None, "kg ..."),
    "bsa":    (None, "m2 ..."),
    "bsa_formula": "BSA_FORMULA_DUBOIS",
    "notes1": None,
    "notes2": None,
    "attributes": {...},
}
```

| Key | Notes |
|---|---|
| `state` | `ADMITTED`, `DISCHARGED`, … — whether there is a patient at all |
| `patient_id` | Medical record number as the monitor holds it |
| `name_given`, `name_middle`, `name_family` | |
| `dob` | `"YYYY-MM-DD"`, decoded from BCD |
| `sex`, `patient_type`, `paced_mode`, `bsa_formula` | Decoded enum names |
| `age`, `height`, `weight`, `bsa` | `(value, unit)` pairs |
| `notes1`, `notes2` | Free text — clinically entered, so treat as identifying |
| `attributes` | The raw decoded attribute tree, for anything not mapped above |

**Unset fields are `None`.** The protocol expresses "unset" as a blank string or an
IEEE-1073 NaN, and the client normalises both — so an empty bed yields a dict of mostly
`None` rather than a mix of `""`, `"Not a number"` and missing keys. Note that units
survive even when values do not: the monitor still says heights are in centimetres.

## Checking before you use it

```python
record = client.get_patient_demographics()

if record is None:
    print("no answer from the monitor")
elif record["state"] != "ADMITTED":
    print(f"no patient admitted (state: {record['state']})")
else:
    print(record["patient_id"], record["name_family"])
```

Do not infer admission from a populated name: a discharged bed can retain
demographics. `state` is the field that answers the question.

## What is verified, and what is not

The reference capture contains a real demographics exchange (frames 53 and 54), and it
is what this implementation was built against:

- **The request** is byte-identical to the one the monitor's own client sends, apart
  from the caller-chosen invoke id and poll number.
- **The reply parses completely.** Before this work, those five frames were the only
  `MDSSinglePollActionResult` messages the codec failed on; now all of them decode.
- **The captured bed was `DISCHARGED`**, so identifiers were blank while units,
  patient type and BSA formula were populated — which is what the test pins down.

:::{note}
**Value decoding of a populated record is not verified against hardware.** The capture
carries no admitted patient, so the structure, types and units are confirmed but the
actual decoding of a real name or date of birth rests on the specification. If you run
this against an admitted bed and something reads wrong, that is where to look.
:::

Two implementation notes worth knowing if you go digging:

- **`0xF001` is overloaded.** It means `NOM_ATTR_POLL_PROFILE_EXT` in an association
  response but `NOM_ATTR_PT_ID_INT` in the demographics group. The codec disambiguates
  by tracking which object class a reply was polled from ({ref}`one code, several meanings <oid-overloading>`).
- **One attribute remains unidentified.** `0xF2E1` (62177) sits in the Philips private
  range; by position and type it is very likely the encounter id, but that is an
  inference, so it is left as a raw OID in `attributes` rather than guessed at.
  `0xF2E2` and `0xF2E3` likewise.

`0x095F` was in the same position until it was resolved as
`NOM_ATTR_PT_NAME_MIDDLE`, using ISO 11073-10101's published term codes — which are
the attribute codes offset by +65536, a relationship every code the vendor guide does
tabulate agrees with.
