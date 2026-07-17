#!/usr/bin/env python3
"""
Reconstruct the acquisition data rate from a converted RENA text file.

The 9th column of a converted `.txt` (produced by `renaDataConvert` /
`RenaDataFormat::convertFile`) is the 42-bit hardware timestamp, clocked at
50 MHz (20 ns/tick). The span between a counter's first and last value is the
elapsed acquisition time; hits / elapsed is the readout rate.

IMPORTANT -- the timestamp counter is *per detector board* and is NOT
guaranteed to be synchronized across boards or nodes. Each independent counter
is identified by the (nodeId, fpgaId, renaId) triple, and only within one such
triple are timestamps comparable/monotonic. Naively taking a global min/max
across all boards is wrong: a single board whose counter is offset (e.g. it
missed the sync/reset) will stretch the apparent span by hundreds of seconds
and collapse the reported rate. This tool therefore works per (node,fpga,rena)
counter and reports a robust aggregate plus an explicit synchronization check.

This does no server RPCs and needs no rogue -- it is a single pure file pass.

Usage:
    python3 rate_profile.py run.txt                 # summary + rate profile
    python3 rate_profile.py run.txt --bin 0.5       # 0.5 s time bins
    python3 rate_profile.py run.txt --plot rate.pdf # also save a plot

Columns (whitespace separated):
    nodeId fpgaId renaId channel polarity phData uData vData timeStamp
"""

import argparse

TS_WRAP = 1 << 42        # 42-bit counter wrap period (~24.4 h @ 50 MHz)
WRAP_THRESH = 1 << 41    # a backward jump larger than this is a genuine wrap,
                         # not counter reordering (the largest real reorderings
                         # are ms-scale, ~6 orders of magnitude below this).

parser = argparse.ArgumentParser("RENA data-rate profile")
parser.add_argument("input", help="Converted .txt file")
parser.add_argument("--tick-ns", type=float, default=20.0,
                    help="Timestamp counter period in ns (50 MHz -> 20 ns/tick).")
parser.add_argument("--bin", type=float, default=1.0,
                    help="Time bin width in seconds for the rate-vs-time profile.")
parser.add_argument("--offset-factor", type=float, default=2.0,
                    help="Flag a counter as unsynchronized if its start offset "
                         "exceeds this many acquisition-durations from the median.")
parser.add_argument("--plot", type=str, default=None,
                    help="Optional path to save a rate-vs-time plot (PDF/PNG).")
args = parser.parse_args()

tick_s = args.tick_ns * 1e-9


def median(sorted_xs):
    n = len(sorted_xs)
    if n == 0:
        return 0.0
    return sorted_xs[n // 2] if n % 2 else 0.5 * (sorted_xs[n // 2 - 1] + sorted_xs[n // 2])


# ---------------------------------------------------------------------------
# Single pass. Each (node,fpga,rena) counter is monotonic in file order, so the
# first timestamp we see for a counter is its minimum (its acquisition start).
# We bin every hit on a time axis relative to *its own* counter's start, which
# folds an offset board back onto the real acquisition timeline instead of
# smearing it across hundreds of seconds.
# ---------------------------------------------------------------------------
first = {}      # src -> first (== min) raw timestamp
last_raw = {}   # src -> last raw timestamp (for wrap detection)
wrap = {}       # src -> accumulated wrap offset
last_ext = {}   # src -> last wrap-extended timestamp (== max, monotonic)
count = {}      # src -> hit count
chans = {}      # src -> set of channels seen
node_hits = {}  # node -> hit count

bins = {}       # bin index -> hits (acquisition-relative time)
total = 0

with open(args.input) as f:
    for line in f:
        c = line.split()
        if len(c) < 9:
            continue
        node = c[0]
        src = (c[0], c[1], c[2])   # node / fpga / rena
        ts = int(c[8])
        total += 1
        node_hits[node] = node_hits.get(node, 0) + 1

        if src not in first:
            first[src] = ts
            last_raw[src] = ts
            wrap[src] = 0
            last_ext[src] = ts
            count[src] = 0
            chans[src] = set()
        elif last_raw[src] - ts > WRAP_THRESH:
            wrap[src] += TS_WRAP
        last_raw[src] = ts
        last_ext[src] = ts + wrap[src]
        count[src] += 1
        chans[src].add(c[3])

        t = (ts + wrap[src] - first[src]) * tick_s
        b = int(t / args.bin)
        bins[b] = bins.get(b, 0) + 1

if total == 0:
    raise SystemExit("No hits found in file.")

# ---- per-counter spans and robust aggregate rate --------------------------
spans = {s: (last_ext[s] - first[s]) * tick_s for s in first}
span_list = sorted(spans.values())
med_span = median(span_list)

# Two robust rate estimates that ignore inter-board offsets:
#  - total hits over the median counter span
#  - sum of each counter's own (hits / its own span)
rate_median = total / med_span if med_span > 0 else 0.0
rate_sum = sum(count[s] / spans[s] for s in first if spans[s] > 0)

active_channels = sum(len(chans[s]) for s in first)
per_chan = rate_median / active_channels if active_channels else 0.0

print(f"File              : {args.input}")
print(f"Tick period       : {args.tick_ns:g} ns ({1e3/args.tick_ns:g} MHz)")
print(f"Total hits        : {total:,}")
print(f"Counters (n/f/r)  : {len(first)}    active channels: {active_channels}")
print(f"Acquisition span  : {med_span:.3f} s  (median of per-counter spans; "
      f"min {span_list[0]:.3f}, max {span_list[-1]:.3f})")
print(f"Aggregate rate    : {rate_median:,.1f} hits/s  (total / median span)")
print(f"                    {rate_sum:,.1f} hits/s  (sum of per-counter rates)")
if active_channels:
    print(f"Mean per-channel  : {per_chan:,.1f} Hz")

# ---- per-node summary ------------------------------------------------------
print("\nPer-node:")
print(f"  {'node':>4}  {'hits':>12}  {'counters':>8}  {'span_s':>8}  {'start_offset_s':>14}")
min_start = min(first.values())
node_srcs = {}
for s in first:
    node_srcs.setdefault(s[0], []).append(s)
for node in sorted(node_srcs, key=int):
    srcs = node_srcs[node]
    sp = sorted(spans[s] for s in srcs)
    off = sorted((first[s] - min_start) * tick_s for s in srcs)
    print(f"  {node:>4}  {node_hits[node]:>12,}  {len(srcs):>8}  "
          f"{sp[0]:>7.1f}-{sp[-1]:.1f}  {off[0]:>7.1f}-{off[-1]:.1f}")

# ---- timestamp synchronization check --------------------------------------
offsets = {s: (first[s] - min_start) * tick_s for s in first}
med_off = median(sorted(offsets.values()))
thresh = args.offset_factor * med_span
outliers = sorted((o, s) for s, o in offsets.items() if abs(o - med_off) > thresh)

print("\nSynchronization check:")
off_vals = sorted(offsets.values())
print(f"  Counter start offsets span {off_vals[0]:.1f} .. {off_vals[-1]:.1f} s.")
if outliers:
    print(f"  WARNING: {len(outliers)} counter(s) offset > {thresh:.1f} s "
          f"({args.offset_factor:g}x acquisition) from the group -- these boards")
    print(f"           did not share the timestamp sync/reset. Their data is valid;")
    print(f"           the offset only corrupts any GLOBAL-min/max timebase math.")
    for o, s in outliers:
        print(f"             node{s[0]}/fpga{s[1]}/rena{s[2]}  start=+{o:.1f} s")
else:
    print("  OK: all counters started within one acquisition-duration of each other.")

# ---- rate vs time (acquisition-relative) ----------------------------------
nbins = max(bins) + 1 if bins else 1
rates = [(bins.get(i, 0)) / args.bin for i in range(nbins)]
peak = max(rates) if rates else 0.0
print(f"\nRate vs time (acquisition-relative, {args.bin:g} s bins):")
for i, r in enumerate(rates):
    bar = "#" * int(40 * r / peak) if peak > 0 else ""
    print(f"  t={i*args.bin:7.1f}s  {r:12,.1f} hits/s  {bar}")
print(f"\nPeak = {peak:,.1f} hits/s   Aggregate = {rate_median:,.1f} hits/s")

# ---- optional plot ---------------------------------------------------------
if args.plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = [i * args.bin for i in range(nbins)]
    plt.figure(figsize=(10, 4))
    plt.plot(t, rates, drawstyle="steps-post")
    plt.xlabel("Time into acquisition [s]")
    plt.ylabel("Hit rate [hits/s]")
    plt.title(f"{args.input}  ({total:,} hits, {med_span:.1f} s)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.plot)
    print(f"\nSaved plot to {args.plot}")
