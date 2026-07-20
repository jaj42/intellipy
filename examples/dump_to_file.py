#!/usr/bin/env python3
"""Record a monitor's live data to files.

The quickstart example: associate with an IntelliVue monitor, print the
signals it exposes, subscribe to some waveforms and write everything that
arrives to disk until the run is over.

    uv run python examples/dump_to_file.py --duration 60 --wave Pleth --wave ECG

Five files are produced in ``--outdir``:

``numerics.csv``
    One row per numeric value: ``time,label,handle,value,unit``.

``waves.jsonl``
    One JSON object per waveform block, keeping the block's own time and
    sample lists so nothing is resampled or interpolated on the way in.

``alarms.jsonl``
    One JSON object per active alarm, patient and technical.

``enumerations.jsonl``
    One JSON object per enumeration state -- ECG rhythm and ectopic status.
    These report a code rather than a number, so they do not fit the numeric
    CSV. Empty unless the monitor granted ``POLL_EXT_ENUM`` at association
    time (revision E.0 and later); check ``client.granted_poll_options``.

``demographics.json``
    The patient record, written separately so that identifiers stay out of
    the signal files. Skip it with ``--no-demographics``.

Times are seconds since the association started, as the monitor counts them.

Needs a real monitor on the other end -- there is no offline mode here. See
``intellipy-enumerate --pcap`` if you only want to decode a capture.
"""

import argparse
import csv
import json
import os
import sys

from intellipy.client import IntellivueClient


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Record IntelliVue numerics, waveforms, alarms and "
                    "enumeration states to files.",
    )
    parser.add_argument(
        "--transport", choices=("udp", "rs232"), default="udp",
        help="how to reach the monitor (default: udp)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="monitor address for udp, serial device for rs232 "
             "(default: 0.0.0.0, i.e. listen on every interface)",
    )
    parser.add_argument(
        "--port", type=int, default=24005,
        help="UDP port to bind (default: 24005)",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0,
        help="seconds any single read may block (default: 5)",
    )
    parser.add_argument(
        "--duration", type=float, default=60.0,
        help="seconds to record for (default: 60)",
    )
    parser.add_argument(
        "--outdir", default="recording",
        help="directory to write the output files into (default: recording)",
    )
    parser.add_argument(
        "--wave", action="append", dest="waves", metavar="LABEL",
        help="waveform to subscribe to, repeatable; defaults to the first "
             "--max-waves the monitor reports",
    )
    parser.add_argument(
        "--max-waves", type=int, default=2,
        help="how many waveforms to subscribe to when none are named "
             "(default: 2)",
    )
    parser.add_argument(
        "--no-demographics", action="store_true",
        help="do not request or write the patient record",
    )
    return parser.parse_args(argv)


def choose_waves(signals, requested, limit):
    """Decide which waveform labels to subscribe to.

    Explicitly requested labels win as given -- they are passed to the monitor
    untouched, since a label it does not recognise is simply ignored. Otherwise
    the first `limit` waveforms of the inventory are used.

    Parameters
    ----------
    signals: list of Signal
        The enumerated inventory.

    requested: list of str or None
        Labels from the command line.

    limit: int
        How many to pick when nothing was requested.

    Returns
    -------
    list of str

    """
    if requested:
        return requested

    labels = []
    for signal in signals:
        if signal.kind != "wave":
            continue
        label = signal.label_string or signal.label
        if label is not None and str(label) not in labels:
            labels.append(str(label))
    return labels[:limit]


class Recorder:
    """Writes each kind of sample to its own file.

    Opens the files eagerly so a permissions problem surfaces before the
    monitor starts streaming, and flushes after every write so a recording
    interrupted with Ctrl-C keeps everything received up to that point.
    """

    NUMERIC_FIELDS = ("time", "label", "handle", "value", "unit")

    def __init__(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        self.outdir = outdir
        self.counts = {"numeric": 0, "wave": 0, "alarm": 0, "enumeration": 0}

        self._numeric_file = open(
            os.path.join(outdir, "numerics.csv"), "w", newline="", encoding="utf-8"
        )
        self._numerics = csv.DictWriter(
            self._numeric_file, fieldnames=self.NUMERIC_FIELDS, extrasaction="ignore"
        )
        self._numerics.writeheader()

        self._waves = open(
            os.path.join(outdir, "waves.jsonl"), "w", encoding="utf-8"
        )
        self._alarms = open(
            os.path.join(outdir, "alarms.jsonl"), "w", encoding="utf-8"
        )
        # Enumeration objects report states (ECG rhythm, ectopic status)
        # rather than numbers, so they get their own stream.
        self._enums = open(
            os.path.join(outdir, "enumerations.jsonl"), "w", encoding="utf-8"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def write(self, sample):
        kind = sample["kind"]
        if kind == "numeric":
            self._numerics.writerow(sample)
            self._numeric_file.flush()
        elif kind == "wave":
            self._write_json(self._waves, sample)
        elif kind == "alarm":
            self._write_json(self._alarms, sample)
        elif kind == "enumeration":
            self._write_json(self._enums, sample)
        else:
            return
        self.counts[kind] += 1

    def write_demographics(self, demographics):
        path = os.path.join(self.outdir, "demographics.json")
        with open(path, "w", encoding="utf-8") as handle:
            # `attributes` is the raw decoded attribute tree, which is bulky
            # and not JSON-clean; the flat fields above it are the useful part.
            record = {
                key: value
                for key, value in demographics.items()
                if key != "attributes"
            }
            json.dump(record, handle, indent=2, default=str)
        return path

    @staticmethod
    def _write_json(stream, sample):
        json.dump(sample, stream, default=str)
        stream.write("\n")
        stream.flush()

    def close(self):
        for stream in (self._numeric_file, self._waves, self._alarms, self._enums):
            stream.close()


def main(argv=None):
    args = parse_args(argv)

    options = {"timeout": args.timeout, "portAddress": args.host}
    if args.transport == "udp":
        options["portNumber"] = args.port

    with IntellivueClient(transport=args.transport, **options) as client:
        print("associating...", flush=True)
        client.associate()

        signals = client.enumerate()
        print(f"\nmonitor exposes {len(signals)} signals:")
        for signal in signals:
            print(f"  {signal.kind:8s} {signal}")

        labels = choose_waves(signals, args.waves, args.max_waves)
        if labels:
            print(f"\nsubscribing to waveforms: {', '.join(labels)}")
            client.set_wave_priority(labels)
        else:
            print("\nno waveforms selected; recording numerics and alarms only")

        with Recorder(args.outdir) as recorder:
            if not args.no_demographics:
                demographics = client.get_patient_demographics()
                if demographics is None:
                    print("monitor did not return patient demographics")
                else:
                    path = recorder.write_demographics(demographics)
                    print(f"wrote patient record to {path}")

            print(f"\nrecording for {args.duration:g} s (Ctrl-C to stop early)...")
            try:
                for sample in client.stream(duration=args.duration):
                    recorder.write(sample)
            except KeyboardInterrupt:
                print("\ninterrupted")

            print(
                "\nrecorded "
                f"{recorder.counts['numeric']} numeric values, "
                f"{recorder.counts['wave']} waveform blocks, "
                f"{recorder.counts['alarm']} alarms, "
                f"{recorder.counts['enumeration']} enumeration states "
                f"into {args.outdir}/"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
