"""Generate the protocol reference tables from the package's own data files.

The nomenclature tables and the message-template catalog in ``docs/protocol/``
are not written by hand: they are rendered at build time from
``intellipy/IntellivueDataFiles/*.txt`` and from the codec's ``MessageLists`` /
``MessageParameters``, so the documentation cannot drift from the code.

``conf.py`` calls :func:`generate` before Sphinx reads the source tree. Output
goes to ``docs/protocol/_generated/`` (git-ignored) and is pulled into the
narrative pages with MyST ``{include}`` directives.
"""

import os

from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

#: Where the package keeps its nomenclature tables.
PACKAGE_DATA = os.path.join(
    os.path.dirname(os.path.abspath(__import__("intellipy").__file__)),
    "IntellivueDataFiles",
)


def _read_pairs(filename):
    """Read a ``NAME number`` table, one entry per line."""
    path = os.path.join(PACKAGE_DATA, filename)
    entries = []
    with open(path) as handle:
        for line in handle:
            fields = line.split()
            if len(fields) >= 2:
                entries.append((fields[0], int(fields[1])))
    return entries


def _read_units():
    """Read ``UNITTypes.txt``: a symbol/description line, then a ``NAME number``.

    Example::

        %  ( percentage )
        NOM_DIM_PERCENT 544
    """
    path = os.path.join(PACKAGE_DATA, "UNITTypes.txt")
    entries = []
    previous = ""
    with open(path) as handle:
        for line in handle:
            fields = line.split()
            if len(fields) >= 2 and fields[0].startswith("NOM_DIM"):
                symbol = previous.split("(")[0].strip()
                description = previous.partition("(")[2].rpartition(")")[0].strip()
                entries.append((fields[0], int(fields[1]), symbol, description))
            previous = line
    return entries


def _table(header, rows):
    """Render a Markdown table, escaping the cell separator."""
    def cell(value):
        return str(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _write(target_dir, name, title, intro, body):
    path = os.path.join(target_dir, name)
    with open(path, "w") as handle:
        handle.write(f"## {title}\n\n{intro}\n\n{body}")
    return path


def _generate_oid_types(target_dir):
    entries = _read_pairs("OIDTypes.txt")
    rows = [(name, number, f"0x{number:04X}") for name, number in entries]
    _write(
        target_dir,
        "oid_types.md",
        "Object identifiers (`OIDTypes.txt`)",
        "Object classes, attribute identifiers and action types. The same 16-bit "
        "code space carries all three, which is why an OID is only unambiguous "
        f"in context (see {{ref}}`one code, several meanings <oid-overloading>`). {len(rows)} entries.",
        _table(["Name", "Code", "Hex"], rows),
    )


def _generate_event_types(target_dir):
    entries = _read_pairs("EventTypes.txt")
    rows = [(name, number, f"0x{number:04X}") for name, number in entries]
    _write(
        target_dir,
        "event_types.md",
        "Event and alarm codes (`EventTypes.txt`)",
        f"Codes reported in the `al_code` field of an alarm entry. {len(rows)} entries.",
        _table(["Name", "Code", "Hex"], rows),
    )


def _generate_scada_types(target_dir):
    entries = _read_pairs("SCADATypes.txt")
    rows = [(name, number, f"0x{number:04X}") for name, number in entries]
    _write(
        target_dir,
        "scada_types.md",
        "Measurement identifiers (`SCADATypes.txt`)",
        "The physiological quantity a value represents, e.g. `NOM_ECG_LEAD_II` or "
        "`NOM_PRESS_BLD_ART_ABP_MEAN`. Compound objects use these to tell their "
        f"members apart. {len(rows)} entries.",
        _table(["Name", "Code", "Hex"], rows),
    )


def _generate_unit_types(target_dir):
    entries = _read_units()
    rows = [
        (name, number, f"0x{number:04X}", f"`{symbol}`" if symbol else "", description)
        for name, number, symbol, description in entries
    ]
    _write(
        target_dir,
        "unit_types.md",
        "Units of measure (`UNITTypes.txt`)",
        f"Values of `NOM_ATTR_UNIT_CODE` and of the `UNITType` field. {len(rows)} entries.",
        _table(["Name", "Code", "Hex", "Symbol", "Meaning"], rows),
    )


def _generate_physio_labels(target_dir):
    """Render the label table from the codec's own parse of PhysioLabels.txt."""
    codec = IntellivueData()

    # `TextId` is bidirectional: code -> description, and short label -> code.
    labels = codec.DataKeys["TextId"]
    descriptions = {
        code: text for code, text in labels.items() if isinstance(code, bytes)
    }
    short_labels = {}
    for text, code in labels.items():
        if isinstance(text, str) and isinstance(code, bytes):
            short_labels.setdefault(code, text)

    rows = [
        (
            "0x" + code.hex().upper(),
            f"`{short_labels.get(code, '')}`" if short_labels.get(code) else "",
            description,
        )
        for code, description in sorted(descriptions.items())
    ]
    _write(
        target_dir,
        "physio_labels.md",
        "Physiological labels (`PhysioLabels.txt`)",
        "Values of `NOM_ATTR_ID_LABEL`, the 32-bit identifier naming what an "
        "object measures. The short label is what appears on the monitor screen "
        f"and what {{meth}}`~intellipy.client.IntellivueClient.set_wave_priority` "
        f"expects. {len(rows)} entries.",
        _table(["Code", "Short label", "Description"], rows),
    )


def _generate_message_templates(target_dir):
    """Catalog the codec's message templates and the polls they encode."""
    codec = IntellivueData()

    rows = []
    for name in sorted(codec.MessageLists):
        parameters = codec.MessageParameters.get(name)
        if isinstance(parameters, dict):
            oids = parameters.get("OIDType")
            target = " → ".join(oids) if isinstance(oids, list) else str(oids or "")
            action = parameters.get("action_type", "")
            command = parameters.get("CMDType", "")
        else:
            target = action = command = ""

        rows.append(
            (
                f"`{name}`",
                " → ".join(codec.MessageLists[name]),
                f"`{command}`" if command else "",
                f"`{action}`" if action else "",
                f"`{target}`" if target else "",
            )
        )

    _write(
        target_dir,
        "message_templates.md",
        "Message templates",
        "Every message `writeData`/`readData` knows how to build or parse, with "
        "the layer chain it encodes and, for the ones intellipy sends, the "
        "command they carry. Templates without a command are ones only the "
        f"monitor sends. {len(rows)} templates.",
        _table(
            ["Template", "Layers", "Command", "Action", "Object → class → group"],
            rows,
        ),
    )


def generate(docs_dir):
    """Write every generated page into ``<docs_dir>/protocol/_generated``."""
    target_dir = os.path.join(docs_dir, "protocol", "_generated")
    os.makedirs(target_dir, exist_ok=True)

    _generate_oid_types(target_dir)
    _generate_event_types(target_dir)
    _generate_scada_types(target_dir)
    _generate_unit_types(target_dir)
    _generate_physio_labels(target_dir)
    _generate_message_templates(target_dir)
    return target_dir


if __name__ == "__main__":
    print(generate(os.path.dirname(os.path.abspath(__file__))))
