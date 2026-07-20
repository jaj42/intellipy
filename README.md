# intellipy

A Python implementation of the **Philips IntelliVue Data Export protocol** — the
documented, vendor-supported interface for streaming live physiological data
(numerics, waveforms, and alarms) off IntelliVue-family patient monitors
(X2, MP-series, MX-series) over UDP or RS232.

`intellipy` associates with a monitor, enumerates the signals it exposes, subscribes
to waveforms, and decodes the ISO/IEEE 11073-based message stream into plain Python
values. It is a read-oriented, interoperability/clinical-data-export tool — it does
not configure or control the monitor's clinical function.

## Status

This project is being restructured into a modern packaged library. The protocol codec,
the high-level client, live enumeration, the example scripts and the documentation are
in place; the test suite is being filled out.

## Documentation

```console
uv sync --extra docs
uv run intellipy-docs --serve      # builds, then serves on localhost:8000
```

The docs cover both the API and the protocol itself — a glossary and primer for MDS,
RORS, extended polls and the 11073 nomenclature, guides for recording and real-time
processing, and lookup tables generated from the package's own nomenclature files.
They are published to GitHub Pages from `main` by `.github/workflows/docs.yml`.

## Layout

```
src/intellipy/                     the package (import name: intellipy)
  IntellivueDataFiles/
    IntellivueData.py              the protocol codec (read/write message templates)
    *.txt                          OID / event / SCADA / unit / physio-label tables
  ConnectionProtocol.py            abstract connection base class
  ConnectToIntellivueUDP.py        UDP driver (legacy)
  ConnectToIntellivueRS232.py      RS232 driver (legacy)
  Sockets/                         UDP / RS232 / base socket wrappers
  SaveProto.py                     queue-based save protocol example
  client.py                        the supported high-level client
  enumerate.py                     signal enumeration + `intellipy-enumerate` CLI
  _docs.py                         `intellipy-docs` documentation build entry point
docs/                              Sphinx sources (Furo + MyST)
examples/                          record-to-file and real-time processing scripts
tests/                             pytest suite; fixtures decode without hardware
reference/                         a sample packet capture (offline decode fixture)
```

## Attribution

Originally created by Uday Agrawal, Adewole Oyalowo, and the Asaad Lab
(2015-2016, part of the pyMIND project) under the MIT License. Continued and
repackaged by Jona Joachim. See [LICENSE](LICENSE).

## License

MIT — see [LICENSE](LICENSE).
