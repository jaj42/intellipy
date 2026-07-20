"""Tests that the package imports and finds its data files.

The src-layout restructure (§1) and the packaging work (§2) both hinge on one
thing: the codec's five ``.txt`` nomenclature tables have to be found relative
to the module, not the working directory. That is what let §3 delete the old
``os.chdir`` hack, and it is what makes an installed wheel work.

These tests run against the *installed* package, so they exercise the same
resolution path a user gets from ``pip install intellipy`` -- not the source
tree by accident.
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

#: Shipped as package data; the codec fails to construct without any of them.
DATA_FILES = [
    "OIDTypes.txt",
    "EventTypes.txt",
    "SCADATypes.txt",
    "UNITTypes.txt",
    "PhysioLabels.txt",
]


def test_package_imports():
    import intellipy

    assert intellipy


@pytest.mark.parametrize(
    "module",
    [
        "intellipy.client",
        "intellipy.enumerate",
        "intellipy.IntellivueDataFiles.IntellivueData",
        "intellipy.Sockets",
    ],
)
def test_public_modules_import(module):
    assert importlib.import_module(module)


def test_the_documented_entry_points_exist():
    """What the quickstart tells people to import."""
    from intellipy.client import IntellivueClient
    from intellipy.enumerate import Signal, collect_enumeration, harvest_inventory

    assert IntellivueClient
    assert all([Signal, collect_enumeration, harvest_inventory])


@pytest.mark.parametrize("filename", DATA_FILES)
def test_data_files_ship_beside_the_codec(filename):
    """Each table sits next to IntellivueData.py, wherever that is installed."""
    import intellipy.IntellivueDataFiles.IntellivueData as codec_module

    assert (Path(codec_module.__file__).parent / filename).is_file()


def test_data_files_resolve_without_a_working_directory(tmp_path):
    """A fresh interpreter, started elsewhere, can build a codec.

    Run as a subprocess with ``cwd`` set outside the repo, so nothing in the
    source tree can be found by relative path. This is the check that the
    ``os.chdir`` hack is really gone -- an in-process test could pass on
    leftover state from an earlier import.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData;"
            "codec = IntellivueData();"
            "print(codec.DataKeys['OIDType']['NOM_MOC_VMS_MDS'].hex())",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0021"


def test_the_enumerate_console_script_target_is_callable():
    """``intellipy-enumerate`` is declared in pyproject as this function."""
    from intellipy.enumerate import main

    assert callable(main)


def test_importing_the_codec_does_not_require_pyserial(monkeypatch):
    """The offline path must not drag in the serial transport.

    ``pyserial`` is a runtime dependency for RS232 only, and the enumerate
    CLI's ``--pcap`` mode imports the client lazily precisely so a pcap can be
    decoded without it.
    """
    for name in list(sys.modules):
        if name.startswith("serial"):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "serial", None)

    importlib.reload(importlib.import_module("intellipy.enumerate"))
