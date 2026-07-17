#!/usr/bin/env python3
"""
Reconstruct the acquisition data rate from a converted RENA text file.

The 9th column of a converted `.txt` (produced by `renaDataConvert` /
`RenaDataFormat::convertFile`) is the 42-bit hardware timestamp. That counter
runs at 50 MHz (20 ns/tick), so the span between the first and last timestamp
of a run is the elapsed acquisition wall-time. Dividing the hit count by that
elapsed time gives the readout rate.

This does no server RPCs and needs no rogue -- it is a pure file pass.

Usage:
    python3 rate_profile.py run.txt                 # summary + text rate profile
    python3 rate_profile.py run.txt --bin 0.5       # 0.5 s time bins
    python3 rate_profile.py run.txt --plot rate.pdf # also save a rate-vs-time plot

Columns (whitespace separated):
    nodeId fpgaId renaId channel polarity phData uData vData timeStamp
"""

import argparse

# 42-bit counter wrap period, for runs longer than ~24.4 hours @ 50 MHz.
TS_WRAP = 1 << 42

parser = argparse.ArgumentParser("RENA data-rate profile")
parser.add_argument("input", help="Converted .txt file")
parser.add_argument("--tick-ns", type=float, default=20.0,
                    help="Timestamp counter period in ns (50 MHz -> 20 ns/tick).")
parser.add_argument("--bin", type=float, default=1.0,
                    help="Time bin width in seconds for the rate-vs-time profile.")
parser.add_argument("--plot", type=str, default=None,
                    help="Optional path to save a rate-vs-time plot (PDF/PNG).")
args = parser.parse_args()

tick_s = args.tick_ns * 1e-9


def unwrap(seq):
    """Undo 42-bit counter wraps on a monotonically-increasing tick sequence."""
    out = []
    wrap = 0
    prev = None
    for v in seq:
        if prev is not None and prev - v > (TS_WRAP >> 1):
            wrap += TS_WRAP
        out.append(v + wrap)
        prev = v
    return out


# ---- read the file: keep (fpgaId, timeStamp) per hit ----------------------
per_fpga = {}          # fpga -> list of raw ticks (file order)
all_ticks = []         # every hit's raw tick, file order
with open(args.input) as f:
    for line in f:
        c = line.split()
        if len(c) < 9:
            continue
        fpga = int(c[1])
        ts = int(c[8])
        per_fpga.setdefault(fpga, []).append(ts)
        all_ticks.append(ts)

if not all_ticks:
    raise SystemExit("No hits found in file.")

# ---- global summary --------------------------------------------------------
g = unwrap(all_ticks)
g0, g1 = min(g), max(g)
elapsed = (g1 - g0) * tick_s
hits = len(g)

print(f"File            : {args.input}")
print(f"Tick period     : {args.tick_ns:g} ns ({1e3/args.tick_ns:g} MHz)")
print(f"Hits            : {hits:,}")
print(f"Timestamp span  : {g1 - g0:,} ticks")
print(f"Elapsed         : {elapsed:.3f} s")
if elapsed > 0:
    print(f"Mean hit rate   : {hits/elapsed:,.1f} hits/s")

# ---- per-FPGA breakdown ----------------------------------------------------
print("\nPer-FPGA:")
print(f"  {'fpga':>4}  {'hits':>10}  {'elapsed_s':>10}  {'hits/s':>12}")
for fpga in sorted(per_fpga):
    u = unwrap(per_fpga[fpga])
    e = (max(u) - min(u)) * tick_s
    r = len(u) / e if e > 0 else 0.0
    print(f"  {fpga:>4}  {len(u):>10,}  {e:>10.3f}  {r:>12,.1f}")

# ---- rate vs time (binned on the global timebase) --------------------------
nbins = max(1, int(elapsed / args.bin) + 1)
counts = [0] * nbins
for v in g:
    b = int(((v - g0) * tick_s) / args.bin)
    if b >= nbins:
        b = nbins - 1
    counts[b] += 1
rates = [c / args.bin for c in counts]

print(f"\nRate vs time ({args.bin:g} s bins):")
peak = max(rates) if rates else 0.0
for i, r in enumerate(rates):
    bar = "#" * int(40 * r / peak) if peak > 0 else ""
    print(f"  t={i*args.bin:7.1f}s  {r:9.1f} hits/s  {bar}")
print(f"\nPeak = {peak:,.1f} hits/s   Mean = {hits/elapsed:,.1f} hits/s" if elapsed > 0 else "")

# ---- optional plot ---------------------------------------------------------
if args.plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = [i * args.bin for i in range(nbins)]
    plt.figure(figsize=(10, 4))
    plt.plot(t, rates, drawstyle="steps-post")
    plt.xlabel("Time [s]")
    plt.ylabel("Hit rate [hits/s]")
    plt.title(f"{args.input}  ({hits:,} hits, {elapsed:.1f} s)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.plot)
    print(f"\nSaved plot to {args.plot}")
