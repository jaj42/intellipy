# Finding out what a monitor exposes

Enumeration is how you discover a monitor's signals. If you want the *why* — why there
is no signal-list message and why polling attribute group `ALL` is the answer — read
{doc}`../concepts/enumeration` first. This page is the how.

## From the command line

The package installs a console script:

```console
$ uv run intellipy-enumerate --live
$ uv run intellipy-enumerate --live --transport rs232 --host /dev/ttyUSB0
$ uv run intellipy-enumerate --live --host 192.168.1.50 --timeout 10
```

It associates, enumerates, prints a table and releases. Useful as a first
connectivity check before writing any code.

## Offline, from a packet capture

The same decoder runs against a capture file, which is how the implementation is
verified without hardware:

```console
$ uv run intellipy-enumerate --pcap reference/intellivue_enumeration.pcapng
```

This needs **tshark** on `PATH` (`apt install tshark`, `brew install wireshark`).
Nothing else in the project does. Capture your own with:

```console
$ sudo tcpdump -i eth0 -w session.pcapng udp
```

The offline and live paths share one collection routine, so a capture that decodes
correctly is real evidence about the live path.

## From Python

```python
from intellipy.client import IntellivueClient

with IntellivueClient("udp") as client:
    client.associate()
    signals = client.enumerate()

for signal in signals:
    print(signal.kind, signal.handle, signal.label, signal.unit)
```

{meth}`~intellipy.client.IntellivueClient.enumerate` returns a list of
{class}`~intellipy.enumerate.Signal`, sorted by class then handle:

```python
Signal(kind="wave", oid_class="NOM_MOC_VMO_METRIC_SA_RT", mds_context=1,
       handle=986, label="PLETH wave label", label_string="Pleth",
       unit="- ( no dimension )", raw_attrs={...})
```

| Field | Use it for |
|---|---|
| `kind` | `"numeric"`, `"wave"`, `"alarm"`, `"enumeration"` |
| `handle` | Matching samples from {meth}`~intellipy.client.IntellivueClient.stream` |
| `label` | **Subscribing** — a nomenclature name the protocol tables know |
| `label_string` | Displaying to a human — may be localised |
| `mds_context` | Telling apart objects from a host monitor and a docked rack |
| `unit` | Interpreting values |
| `raw_attrs` | Debugging: every attribute name seen for this object |

## Picking waveforms to subscribe to

```python
waves = [s for s in signals if s.kind == "wave"]
client.set_wave_priority([str(s.label) for s in waves[:2]])
```

:::{warning}
Use `label`, not `label_string`. `set_wave_priority` resolves names through the
shipped `PhysioLabels.txt` table, where `"PLETH wave label"` and `"Pleth"` are both
keys. `label_string` is the monitor's display text: on the French-localised monitor in
the reference capture the arterial waveform displays as `PA`, which is not in the
table, and subscribing to it fails silently — no error, no samples.
:::

Read the list back to confirm what took effect:

```python
client.get_priority_list()
```

## Enumeration objects

The fourth class, `NOM_MOC_VMO_METRIC_ENUM`, reports ECG rhythm and ectopic status.
The monitor serves it only if `POLL_EXT_ENUM` was requested at association time —
which `intellipy` does by default — *and* only from software revision E.0:

```python
client = IntellivueClient("udp", request_enumerations=True)   # the default
client.associate()
if "POLL_EXT_ENUM" not in client.granted_poll_options:
    print("no enumeration objects from this monitor")
```

If the monitor declines, the enumeration poll comes back as a Remote Operation Error;
{func}`~intellipy.enumerate.collect_enumeration` treats that as one class that will
never answer and carries on with the rest, so nothing hangs.

## Enumerating a subset

Polling every class costs a round trip each. To ask for less:

```python
signals = client.enumerate(classes=["NOM_MOC_VMO_METRIC_SA_RT"], timeout=10.0)
```

## Using the collection routine directly

{func}`~intellipy.enumerate.collect_enumeration` takes `send`/`recv` callables rather
than a socket, so it can be driven by anything — a replayed capture, a test double, a
transport this library does not implement:

```python
from intellipy.enumerate import collect_enumeration, format_inventory
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

packets = iter(captured_packets)
inventory = collect_enumeration(
    send=lambda data: None,          # replay: sending is a no-op
    recv=lambda: next(packets),      # raises StopIteration at the end
    codec=IntellivueData(),
    timeout=5.0,
)
print(format_inventory(inventory))
```

`recv` should raise (or return falsy) rather than block forever; `OSError` and
`TimeoutError` end collection cleanly.

To decode packets you have already collected, without any send/receive dance at all,
use {func}`~intellipy.enumerate.harvest_inventory` — it skips anything that is not an
extended poll reply, so a whole raw capture can be fed in wholesale.

## Notes

- **Enumerate every session.** Handles are not stable across associations, and the
  inventory reflects what is configured *now*.
- **The inventory is not a list of live signals.** The reference capture shows twenty
  numeric objects on a bed measuring far fewer; the rest are configured but idle.
- **Waveforms appear before you subscribe.** Enumeration proves the object exists; the
  priority list decides whether samples flow.
