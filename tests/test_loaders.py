"""Tests for the nomenclature tables loaded from the shipped .txt files.

Each loader builds a *bidirectional* dict: code -> name and name -> code in one
mapping. That works only because the two sides use different Python types --
str on one side, bytes or int on the other -- so they cannot collide.

The tables are less uniform than they look, and the differences are the whole
point of this file:

* ``EventTypes`` keys its codes as **ints**; ``OIDType``, ``SCADAType``,
  ``UNITType`` and ``TextId`` key theirs as **bytes**.
* ``UNITType`` maps codes to **display text** (``'% ( percentage )'``), not to
  the ``NOM_DIM_*`` names -- those never become keys at all.
* ``TextId`` is the only table that is *not* a clean round trip, which is the
  defect §6b was about.

Also checked: the files resolve via ``__file__``, so an installed wheel finds
them regardless of the working directory.
"""

import pytest

#: Tables whose two sides agree: ``m[m[name]] == name`` for every name.
ROUND_TRIP_TABLES = ["OIDType", "EventTypes", "SCADAType", "UNITType"]

ALL_TABLES = ROUND_TRIP_TABLES + ["TextId"]


@pytest.mark.parametrize(
    "name, code",
    [
        ("NOM_MOC_VMS_MDS", b"\x00\x21"),
        ("NOM_MOC_VMO_METRIC_NU", b"\x00\x06"),
        ("NOM_MOC_VMO_METRIC_SA_RT", b"\x00\x09"),
        ("NOM_MOC_VMO_AL_MON", b"\x00\x36"),
        ("NOM_MOC_PT_DEMOG", b"\x00\x2a"),
        # Added in §4c for the enumeration objects.
        ("NOM_MOC_VMO_METRIC_ENUM", b"\x00\x05"),
        ("NOM_ATTR_VAL_ENUM_OBS", b"\x09\x9e"),
    ],
)
def test_oid_types_are_keyed_both_ways(codec, name, code):
    """The object classes the library polls, and their 16-bit codes."""
    oids = codec.DataKeys["OIDType"]
    assert oids[name] == code
    assert oids[code] == name


def test_scada_types_are_keyed_by_bytes(codec):
    scada = codec.DataKeys["SCADAType"]
    assert scada["NOM_ECG_ELEC_POTL_II"] == b"\x01\x02"
    assert scada[b"\x01\x02"] == "NOM_ECG_ELEC_POTL_II"


def test_event_types_are_keyed_by_int_not_bytes(codec):
    """Unlike every other table, event codes stay plain ints.

    ``loadEventTypes`` is the one loader that does not call ``set16``, so a
    lookup with ``b'\\x00\\x04'`` misses where ``4`` hits.
    """
    events = codec.DataKeys["EventTypes"]
    code = events["NOM_EVT_ABSENT"]
    assert isinstance(code, int)
    assert events[code] == "NOM_EVT_ABSENT"
    assert b"\x00\x04" not in events


@pytest.mark.parametrize(
    "code, text",
    [
        (b"\x02\x20", "% ( percentage )"),
        (b"\x0a\xa0", "bpm ( beats per minute used e.g. for HR/PULSE )"),
        (b"\x0f\x20", "mmHg ( mm mercury )"),
        (b"\x10\xb2", "mV ( milli-volt )"),
    ],
)
def test_unit_codes_resolve_to_display_text(codec, code, text):
    """Units map code <-> printable text. The real ones from the capture."""
    units = codec.DataKeys["UNITType"]
    assert units[code] == text
    assert units[text] == code


def test_unit_names_are_not_keys_at_all(codec):
    """``NOM_DIM_*`` names appear in the file but never in the mapping.

    UNITTypes.txt is two lines per entry -- the display text, then the name and
    code -- and the loader zips *text* against code, dropping the name. So
    looking a unit up by its nomenclature name silently returns nothing, which
    is worth knowing before writing ``units["NOM_DIM_PERCENT"]``.
    """
    units = codec.DataKeys["UNITType"]
    assert "NOM_DIM_PERCENT" not in units
    assert "NOM_DIM_BEAT_PER_MIN" not in units


def test_physio_labels_map_code_to_description(codec):
    """TextId resolves a 32-bit label code to a readable description.

    These four are the capture's waveforms, so the values are real.
    """
    labels = codec.DataKeys["TextId"]
    assert labels[b"\x00\x02\x01\x4b"] == "ECG Lead MCL"
    assert labels[b"\x00\x02\x4a\x14"] == "Arterial Blood Pressure (ABP)"
    assert labels[b"\x00\x02\x4b\xb4"] == "PLETH wave label"
    assert labels[b"\x00\x02\x50\x00"] == "Imedance RESP wave"


def test_physio_label_codes_are_four_bytes(codec):
    """Label codes are 32-bit, unlike the 16-bit OID, SCADA and unit codes."""
    code = codec.DataKeys["TextId"]["Heart Rate"]
    assert isinstance(code, bytes)
    assert len(code) == 4


@pytest.mark.parametrize("table", ALL_TABLES)
def test_tables_are_non_empty_and_have_both_sides(codec, table):
    """A loader that found no file, or parsed nothing, fails here.

    Otherwise the first symptom is a ``KeyError`` deep inside a decode, far
    from the cause.
    """
    mapping = codec.DataKeys[table]
    assert mapping
    assert any(isinstance(k, str) for k in mapping)
    assert any(not isinstance(k, str) for k in mapping)


@pytest.mark.parametrize("table", ROUND_TRIP_TABLES)
def test_name_and_code_sides_agree(codec, table):
    """``m[m[name]] == name`` for every name in these four tables.

    This is what lets a code and its name be used interchangeably against them
    -- and it is exactly the property ``TextId`` lacks.
    """
    mapping = codec.DataKeys[table]
    for name in [k for k in mapping if isinstance(k, str)]:
        assert mapping[mapping[name]] == name


def test_textid_is_the_one_table_without_that_property(codec):
    """TextId has more name keys than code keys, so it cannot round trip.

    Each code contributes both a description and a display symbol to the name
    side, and descriptions are not unique either. The measured gap is large --
    roughly half the name keys do not map back to themselves -- which is why
    :class:`Signal` carries ``label_code`` rather than re-deriving the code
    from a string. See test_labels.py for what that broke in practice.
    """
    labels = codec.DataKeys["TextId"]
    names = [k for k in labels if isinstance(k, str)]
    codes = [k for k in labels if not isinstance(k, str)]

    assert len(names) > len(codes)
    assert [n for n in names if labels.get(labels[n]) != n]


def test_tables_load_from_package_data_not_the_working_directory(
    tmp_path, monkeypatch
):
    """Constructing a codec from an unrelated cwd works.

    The loaders resolve their .txt files relative to ``__file__``, which is why
    §3 could delete the old ``os.chdir`` hack and why the wheel only needs to
    ship the files as package data.
    """
    from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

    monkeypatch.chdir(tmp_path)
    elsewhere = IntellivueData()
    assert elsewhere.DataKeys["OIDType"]["NOM_MOC_VMS_MDS"] == b"\x00\x21"
