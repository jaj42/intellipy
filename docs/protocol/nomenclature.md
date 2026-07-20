# Nomenclature tables

Nothing in this protocol travels as text. Every class, attribute, action, unit,
measurement and label is a number from the ISO/IEEE 11073-10101 nomenclature, and
these are the tables `intellipy` resolves them with. See {ref}`nomenclature` for how
the code space is organised, and {ref}`one code, several meanings <oid-overloading>` for why the same number can
mean two things.

Each table is loaded into a **bidirectional** dict at codec construction, so you can
look up either way:

```python
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

codec = IntellivueData()
codec.DataKeys["OIDType"]["NOM_MOC_VMS_MDS"]     # → b'\x00\x21'
codec.DataKeys["UNITType"]["NOM_DIM_PERCENT"]    # → the code
codec.DataKeys["TextId"]["Pleth"]                # → b'\x00\x02K\xb4'
```

| Table | Loaded into | Holds |
|---|---|---|
| `OIDTypes.txt` | `DataKeys["OIDType"]` | Object classes, attributes, actions |
| `EventTypes.txt` | `DataKeys["EventTypes"]` | Alarm and event codes |
| `SCADATypes.txt` | `DataKeys["SCADAType"]` | What a value measures |
| `UNITTypes.txt` | `DataKeys["UNITType"]` | Units of measure |
| `PhysioLabels.txt` | `DataKeys["TextId"]` | Physiological labels and display names |

:::{note}
These tables are the vendor's, transcribed. Where a code the monitor sends is missing
from them the codec keeps the raw bytes rather than failing, so one unknown private
attribute cannot derail a whole message. A handful of Philips private codes
(`0xF2E1`–`0xF2E3`) remain unidentified; see {doc}`../guides/demographics`.
:::

```{include} _generated/oid_types.md
```

```{include} _generated/event_types.md
```

```{include} _generated/scada_types.md
```

```{include} _generated/unit_types.md
```

```{include} _generated/physio_labels.md
```
