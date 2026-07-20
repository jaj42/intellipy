# Installation

`intellipy` needs Python 3.10 or newer. Its only runtime dependencies are `numpy` and
`pyserial`.

## With uv (recommended)

[uv](https://docs.astral.sh/uv/) manages the interpreter, the virtual environment and
the lockfile in one tool, and the repository is set up for it.

```console
$ git clone <repository-url> intellipy
$ cd intellipy
$ uv sync
```

That creates `.venv/`, installs the package in editable mode and resolves
`uv.lock`. Nothing further needs activating — prefix commands with `uv run`:

```console
$ uv run python -c "import intellipy; print(intellipy.__file__)"
$ uv run intellipy-enumerate --help
```

To include the optional extras:

```console
$ uv sync --extra dev      # pytest, ruff
$ uv sync --extra docs     # sphinx, furo, myst-parser
$ uv sync --all-extras
```

## With pip

```console
$ python -m venv .venv && source .venv/bin/activate
$ pip install -e .
$ pip install -e ".[dev,docs]"     # with extras
```

## Verifying the install

The codec loads five nomenclature tables from package data at import time, and a
packaging mistake shows up here first:

```console
$ uv run python -c "
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData
codec = IntellivueData()
print(len(codec.DataKeys['OIDType']), 'OID entries loaded')"
```

Then run the offline decoder against the bundled capture — this exercises the codec
and the enumeration path end to end without a monitor:

```console
$ uv run intellipy-enumerate --pcap reference/intellivue_enumeration.pcapng
```

It should print a 25-signal table. This one command needs **tshark** (Wireshark's CLI)
on `PATH`; nothing else in the project does, including the test suite.

And the tests:

```console
$ uv run pytest
```

## Connecting to a monitor

**UDP.** The monitor broadcasts on port **24005**; the client binds it and waits.
Practically this means:

- The machine must be on the same network segment as the monitor, with broadcast
  traffic reaching it — this rarely survives a router or a wireless bridge.
- Nothing else may hold port 24005. Only one client per monitor at a time in general;
  a monitor serves a limited number of associations.
- Binding a privileged interface is not required (24005 is unprivileged), but a host
  firewall must allow inbound UDP.

**RS232.** Point the client at the serial device and make sure your user can open it:

```console
$ uv run python -c "
from intellipy.client import IntellivueClient
client = IntellivueClient('rs232', device='/dev/ttyUSB0')"
```

On Linux that usually means being in the `dialout` group. The serial path is
structurally complete but has not been exercised against hardware in this repository.

## Building the documentation

```console
$ uv run --extra docs intellipy-docs
```

or equivalently:

```console
$ uv run --extra docs sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`. The protocol tables under `docs/protocol/` are
regenerated from the package's own data files on every build, so they cannot go stale.
