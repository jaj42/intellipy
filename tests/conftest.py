"""Fixtures shared across the suite.

The wire data all comes from ``reference/intellivue_enumeration.pcapng``, but
tests read it from committed hex files in ``tests/data/`` rather than from the
capture itself. Going through the capture would make the suite depend on
``tshark``, and a missing ``tshark`` makes tests *skip*, not fail -- so a CI
image without Wireshark would quietly stop checking the parts of the codec that
only real data exercises.
"""

from pathlib import Path

import pytest

from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

DATA = Path(__file__).parent / "data"


def load_payloads(name):
    """Read a ``tests/data/*.hex`` fixture into a list of payloads.

    One payload per line, hex-encoded; blank lines and ``#`` comments ignored.

    Parameters
    ----------
    name : str
        File name within ``tests/data``.

    Returns
    -------
    list of bytes
        Payloads in file order.
    """
    text = (DATA / name).read_text()
    return [
        bytes.fromhex(line.strip())
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


@pytest.fixture(scope="module")
def codec():
    """A codec instance.

    Module-scoped: constructing one parses five nomenclature tables, and no
    test mutates it.
    """
    return IntellivueData()


@pytest.fixture(scope="module")
def enumeration_payloads():
    """The captured enumeration exchange, in capture order."""
    return load_payloads("enumeration_replies.hex")
