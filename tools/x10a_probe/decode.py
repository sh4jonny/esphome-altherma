"""Decode raw X10A frames with the ESPAltherma E_EJ definition table.

Usage: python3 decode.py erga_e_ej_def.txt <frames.json> [<frames2.json> ...]
erga_e_ej_def.txt: field table extracted from ESPAltherma beta
definitions/Altherma(ERGA E EHV-EHB-EHVZ E_EJ series 04-08kW).h,
including the commented-out entries. conv 119 is decoded signed (#543).
Several frame files are shown side by side (e.g. idle vs. compressor running).
"""
import json
import re
import sys


def u(d, n, be=0):
    return d[0] if n == 1 else ((d[0] << 8 | d[1]) if be else (d[1] << 8 | d[0]))


def s(d, n, be=0):
    v = u(d, n, be)
    return v - 65536 if n == 2 and v & 0x8000 else v


def p2t(p):  # ESPAltherma convertPress2Temp (R32)
    return -2.6989493795556e-07 * p**6 + 4.26383417104661e-05 * p**5 \
        - 0.00262978346547749 * p**4 + 0.0805858127503585 * p**3 \
        - 1.31924457284073 * p**2 + 13.4157368435437 * p - 51.1813011169434


def conv(c, d, n):
    if c in (114, 119) and n == 2 and d[0] == 0 and d[1] == 0x80:
        return "---"
    if 300 <= c <= 307:
        return "ON" if d[0] & (1 << (c % 10)) else "off"
    return {
        101: lambda: s(d, n), 103: lambda: s(d, n) / 256, 105: lambda: round(s(d, n) * 0.1, 2),
        114: lambda: round(s(d, n) / 256 * 10, 2), 119: lambda: round(s(d, n) / 256, 2),
        151: lambda: u(d, n), 152: lambda: u(d, n, 1), 161: lambda: u(d, n, 1) * 0.5,
        211: lambda: "OFF" if d[0] == 0 else d[0], 215: lambda: f"{d[0]:02X}",
        203: lambda: f"type {d[0]}", 204: lambda: f"code {d[0]:02X}", 217: lambda: f"mode {d[0]}",
        219: lambda: f"cap {d[0]}", 310: lambda: d[0] >> 4, 311: lambda: d[0] & 15,
        315: lambda: f"mode {d[0] >> 4}", 405: lambda: round(p2t(s(d, n) * 0.1), 2),
    }.get(c, lambda: f"conv{c}?")()


defs = []
for line in open(sys.argv[1]):
    m = re.match(r'\{(0x[0-9A-Fa-f]+),(\d+),(\d+),(\d+),(-?\d+),"(.*)"\}', line.strip())
    if m:
        defs.append((int(m[1], 16), int(m[2]), int(m[3]), int(m[4]), m[6]))
snaps = [json.load(open(f)) for f in sys.argv[2:]]

for reg in sorted({int(k, 16) for sn in snaps for k in sn}):
    frames = [bytes.fromhex("".join(sn.get(f"0x{reg:02X}", {}).get("frame") or [])) for sn in snaps]
    if not any(frames):
        continue
    print(f"\n=== 0x{reg:02X}  len={frames[0][2] if frames[0] else '?'}  data={' '.join(f'{b:02X}' for b in frames[0][3:-1])}")
    used = set()
    for r, off, c, n, name in defs:
        if r != reg:
            continue
        used.update(range(off, off + n))
        vals = []
        for fr in frames:
            data = fr[3:-1]
            vals.append(conv(c, data[off:off + n], n) if off + n <= len(data) else "n/a")
        if "Not in use" in name and all(v in (0, "off", "OFF", "00") for v in vals):
            continue
        print(f"  {off:>2} c{c:<3} {name[:44]:<44} " + " | ".join(str(v) for v in vals))
    for i, b in enumerate(frames[0][3:-1]):
        if i not in used and any(fr[3 + i] for fr in frames if len(fr) > 3 + i):
            print(f"  {i:>2} UNMAPPED byte: " + " | ".join(f"{fr[3 + i]:02X}" for fr in frames))
