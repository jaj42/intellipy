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

This project is being restructured into a modern packaged library. The protocol codec
and connection drivers are working; packaging, a clean high-level client, live
enumeration, examples, and documentation are in progress.

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
reference/                         a sample packet capture (offline decode fixture)
```

## Attribution

Originally created by Uday Agrawal, Adewole Oyalowo, and the Asaad Lab
(2015-2016, part of the pyMIND project) under the MIT License. Continued and
repackaged by Jona Joachim. See [LICENSE](LICENSE).

## License

MIT — see [LICENSE](LICENSE).
