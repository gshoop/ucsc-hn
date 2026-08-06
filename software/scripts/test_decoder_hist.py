"""End-to-end test: fabricate batcher-framed RENA AND-mode packets and
verify the RenaDataDecoder histogram / per-channel count accumulation."""

import sys
import time
import rogue
import rogue.interfaces.stream as ris
import ucsc_hn_lib

print("Loaded lib:", ucsc_hn_lib.__file__)


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def rena_packet(fpga, rena, channels, pha_vals, u=100, v=200, ts=12345):
    """Build an AND-mode (0xC8) RENA packet with valid CRC."""
    pkt = bytearray()
    pkt.append(0xC8)
    pkt.append(((fpga & 0x3F) << 1) | (rena & 1))

    # Timestamp: 6 bytes of 7 bits, MSB first
    for i in range(6):
        pkt.append((ts >> (7 * (5 - i))) & 0x7F)

    # Fast trigger list: 36 bits packed into 6 bytes of 6 bits, MSB first
    trig = 0
    for ch in channels:
        trig |= 1 << ch
    for i in range(6):
        pkt.append((trig >> (6 * (5 - i))) & 0x3F)

    # Per-channel data in ascending channel order: PHA, U, V (2 bytes of 6 bits each)
    for ch, pha in sorted(zip(channels, pha_vals)):
        for val in (pha, u, v):
            pkt.append((val >> 6) & 0x3F)
            pkt.append(val & 0x3F)

    c = crc8(pkt)
    pkt.append(c >> 4)
    pkt.append(c & 0x0F)
    pkt.append(0xFF)

    assert len(pkt) == 17 + 6 * len(channels), "bad AND mode packet length"
    return pkt


def batcher_frame(packets):
    """Wrap RENA packets in an AxiStreamBatcher V1 super-frame,
    mirroring what RenaDataEmulator fabricates."""
    buf = bytearray()
    buf += bytes([0x21, 0, 0, 0, 0, 0, 0, 0])  # header: version 1, width code 2

    for pkt in packets:
        count = len(pkt)
        buf += pkt
        while len(buf) % 8 != 0:  # pad to 64-bit width
            buf.append(0)
        buf += count.to_bytes(4, 'little')
        buf += bytes([0, 0, 0, 0x02])  # tdest, fUser, lUser, width

    return buf


class Source(ris.Master):
    def send(self, data):
        frame = self._reqFrame(len(data), True)
        frame.write(data, 0)
        self._sendFrame(frame)


class Sink(ris.Slave):
    def _acceptFrame(self, frame):
        pass


dec = ucsc_hn_lib.RenaDataDecoder(1)
src = Source()
snk = Sink()

src >> dec
dec >> snk

dec.setHistChannel(5, 1, 12)
dec.setHistEnable(1)

# 100 events on channel 12 with PHA 1000, plus channel 20 with PHA 2000
for i in range(100):
    pkt = rena_packet(fpga=5, rena=1, channels=[12, 20], pha_vals=[1000, 2000])
    src.send(batcher_frame([pkt]))

# Events on the other rena of the same fpga must not enter the histogram
for i in range(7):
    pkt = rena_packet(fpga=5, rena=0, channels=[12], pha_vals=[1000])
    src.send(batcher_frame([pkt]))

time.sleep(0.5)

ok = True

def check(name, got, exp):
    global ok
    status = "OK " if got == exp else "FAIL"
    if got != exp:
        ok = False
    print(f"{status} {name}: got {got}, expected {exp}")

check("rxFrameCount", dec.getRxFrameCount(), 107)
check("rxDropCount", dec.getRxDropCount(), 0)

hist = dec.getHistogram()
check("hist[1000]", hist[1000], 100)
check("hist[2000]", hist[2000], 0)      # channel 20 not selected
check("hist sum", sum(hist), 100)       # rena 0 events excluded

counts = dec.getChanCountList(5, 1)
check("counts[12]", counts[12], 100)
check("counts[20]", counts[20], 100)
check("counts sum", sum(counts), 200)
check("chanCount(5,0,12)", dec.getChanCount(5, 0, 12), 7)

# Changing the monitored channel clears the histogram and retargets
dec.setHistChannel(5, 1, 20)
check("hist cleared on retarget", sum(dec.getHistogram()), 0)

pkt = rena_packet(fpga=5, rena=1, channels=[20], pha_vals=[2000])
src.send(batcher_frame([pkt]))
time.sleep(0.2)
check("hist[2000] after retarget", dec.getHistogram()[2000], 1)

# Disable stops accumulation
dec.setHistEnable(0)
src.send(batcher_frame([rena_packet(fpga=5, rena=1, channels=[20], pha_vals=[2000])]))
time.sleep(0.2)
check("hist frozen when disabled", dec.getHistogram()[2000], 1)

# Reset clears counters
dec.resetChanCounts()
check("chan counts cleared", sum(dec.getChanCountList(5, 1)), 0)

print("\nALL PASS" if ok else "\nFAILURES PRESENT")
sys.exit(0 if ok else 1)
