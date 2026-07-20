#!/usr/bin/env python3
"""
IntelliVue Data Export -- signal ENUMERATION.

How enumeration works:

    The monitor never sends a "here is my signal list" message on its own.
    You enumerate by issuing an *MDS Extended Poll* action
    (NOM_ACT_POLL_MDIB_DATA_EXT, action code 0xf13b) against the MDS object,
    once per object class you care about, with the *attribute group* set to
    ALL (OID 0x0000). "ALL" means "return every attribute of every object of
    this class". The monitor answers with a (possibly multi-packet, "linked")
    poll reply whose PollInfoList enumerates every object, and each object
    (ObservationPoll) carries its:

        NOM_ATTR_ID_HANDLE        (0x0921) -- the handle you subscribe with
        NOM_ATTR_ID_LABEL         (0x0924) -- 32-bit physio label id (-> name)
        NOM_ATTR_ID_LABEL_STRING  (0x0927) -- short display string, e.g. "SpO2"
        NOM_ATTR_UNIT_CODE        (0x0996) -- unit (for waveforms/numerics)
        NOM_ATTR_ID_TYPE, SCALE_SPECN, METRIC_SPECN, COLOR, ...

    Poll one class per signal kind:
        numerics  -> NOM_MOC_VMO_METRIC_NU     (OID 6)
        waveforms -> NOM_MOC_VMO_METRIC_SA_RT  (OID 9)
        alarms    -> NOM_MOC_VMO_AL_MON        (OID 54)

    Collecting the objects from the first full poll cycle == the enumeration.

This reuses the existing codec in intellipy/IntellivueDataFiles/IntellivueData.py
(writeData / readData / getMessageType) unchanged.

Usage:
    # Offline: prove the decode against the capture
    python3 enumerate_signals.py --pcap intellivue_enumeration.pcapng

    # Live: enumerate a real monitor (must already be associated -- see notes)
    from enumerate_signals import harvest_inventory
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATAFILES = os.path.join(HERE, "intellipy", "IntellivueDataFiles")
sys.path.insert(0, DATAFILES)


def _make_codec():
    # IntellivueData loads its .txt lookup tables relative to CWD, so chdir first.
    cwd = os.getcwd()
    os.chdir(DATAFILES)
    try:
        from IntellivueData import IntellivueData
        return IntellivueData()
    finally:
        os.chdir(cwd)


POLL_REPLY_TYPES = ("LinkedMDSExtendedPollActionResult", "MDSExtendedPollActionResult")


def _find(d, name):
    if isinstance(d, dict):
        for k, v in d.items():
            if k == name:
                return v
            if isinstance(v, dict):
                r = _find(v, name)
                if r is not None:
                    return r
    return None


def _iter_observations(msg):
    """Yield (mds_context, ObservationPoll dict) for every object in a poll reply."""
    pil = _find(msg, "PollInfoList")
    if not isinstance(pil, dict):
        return
    for sk, sv in pil.items():
        if not sk.startswith("SingleContextPoll"):
            continue
        scp = sv.get("SingleContextPoll", sv) if isinstance(sv, dict) else {}
        ctx = scp.get("MdsContext")
        pinfo = scp.get("poll_info", {})
        if not isinstance(pinfo, dict):
            continue
        for ok, ov in pinfo.items():
            if not ok.startswith("ObservationPoll"):
                continue
            op = ov.get("ObservationPoll", ov) if isinstance(ov, dict) else {}
            yield ctx, op


def _ava(attr_list, name):
    """Pull AttributeList[AVAType][name][AttributeValue] safely."""
    if not isinstance(attr_list, dict):
        return {}
    avat = attr_list.get("AVAType", {})
    if not isinstance(avat, dict):
        return {}
    entry = avat.get(name, {})
    if not isinstance(entry, dict):
        return {}
    val = entry.get("AttributeValue", {})
    return val if isinstance(val, dict) else {}


def harvest_inventory(codec, packets):
    """
    packets: iterable of raw APDU bytes (UDP payloads) from the monitor.
    Returns {(class, mds_context, handle): {label, labelstr, unit, attrs}}.

    Feed it every reply datagram of a poll cycle; linked replies span several
    datagrams and are merged here by (class, context, handle).
    """
    inv = {}
    for data in packets:
        if codec.getMessageType(data) not in POLL_REPLY_TYPES:
            continue
        try:
            msg = codec.readData(data)
        except Exception:
            continue
        t = _find(msg, "Type")
        cls = t.get("OIDType") if isinstance(t, dict) else "?"
        for ctx, op in _iter_observations(msg):
            handle = op.get("Handle")
            al = op.get("AttributeList", {})
            rec = inv.setdefault((cls, ctx, handle), {})
            label = _ava(al, "NOM_ATTR_ID_LABEL").get("TextId")
            lstr = _ava(al, "NOM_ATTR_ID_LABEL_STRING").get("String", {})
            lstr = lstr.get("value") if isinstance(lstr, dict) else None
            unit = _ava(al, "NOM_ATTR_UNIT_CODE").get("UNITType")
            if label:
                rec["label"] = label
            if lstr:
                rec["labelstr"] = lstr
            if unit:
                rec["unit"] = unit
            avat = al.get("AVAType", {}) if isinstance(al, dict) else {}
            if isinstance(avat, dict):
                rec.setdefault("attrs", set()).update(avat.keys())
    return inv


def print_inventory(inv):
    print(f"{'CLASS':<26}{'ctx':>4}{'handle':>8}  {'disp':<10} label / unit")
    print("-" * 100)
    for (cls, ctx, h), r in sorted(inv.items(),
                                   key=lambda x: (str(x[0][0]), x[0][1] or 0, x[0][2] or 0)):
        unit = r.get("unit", "")
        print(f"{str(cls):<26}{ctx!s:>4}{h!s:>8}  {str(r.get('labelstr','')):<10} "
              f"{r.get('label','?')}" + (f"  [{unit}]" if unit else ""))
    print("-" * 100)
    from collections import Counter
    print("counts:", dict(Counter(k[0] for k in inv)), "| total objects:", len(inv))


def _read_pcap_payloads(path):
    """Extract monitor->client UDP payloads from a pcap/pcapng via tshark."""
    import subprocess
    import binascii
    out = subprocess.check_output(
        ["tshark", "-r", path, "-Y", "udp && data.data", "-T", "fields",
         "-e", "udp.srcport", "-e", "udp.dstport", "-e", "data.data"],
        text=True, stderr=subprocess.DEVNULL)
    payloads = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2]:
            payloads.append(binascii.unhexlify(parts[2].replace(":", "")))
    return payloads


def main():
    ap = argparse.ArgumentParser(description="IntelliVue signal enumeration")
    ap.add_argument("--pcap", default=os.path.join(HERE, "intellivue_enumeration.pcapng"),
                    help="pcap/pcapng of an enumeration exchange (needs tshark)")
    args = ap.parse_args()

    codec = _make_codec()
    payloads = _read_pcap_payloads(args.pcap)
    print(f"read {len(payloads)} UDP payloads from {os.path.basename(args.pcap)}\n")
    inv = harvest_inventory(codec, payloads)
    print_inventory(inv)


if __name__ == "__main__":
    main()
