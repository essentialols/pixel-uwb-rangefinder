# Next Session Guide

## Current State (2026-05-19)

CIR streaming pipeline operational. AOSP source analysis confirmed debugfs registers
are WRITABLE, opening new paths for chip configuration without kernel rebuilds.

### What's Working

- 5-patch binary dw3000.ko: CIR read on RXPTO during FiRa sessions
- CIR streaming at 16.7fps via cir_stream + cir_stream_decode.py
- Autonomous capture script (runs unattended, screen off)
- One-command analysis pipeline (analyze_capture.sh)
- Noise floor characterized: Rayleigh-distributed, white, independent

### NEW: Debugfs Register Writes (E025)

AOSP source confirms register files are read-write. Key writable registers:

- TX_TEST (0x70028): enable CW tone (write 0x01)
- ACK_RESP_T (0x36): TX-to-RX delay control
- cir_config: "count N filter 0xX offset Y" (up to 1016 CIR bins)
- SYS_CFG (0x10): system configuration (WP, writable when inactive)

### Why No Signal Yet

The DW3000 is half-duplex: TX and RX never overlap. Monostatic radar is impossible
for indoor distances (TX-to-RX dead zone > 300m). But CW tone via register write
may create antenna self-coupling detectable in the first few CIR bins.

## Quick Start: Autonomous Capture (no second device needed)

```bash
# 1. One-time push (ADB connected)
adb root
adb push cir_stream /data/local/tmp/
adb push tools/uwb_autonomous.sh tools/dw3000_regwrite.sh /data/local/tmp/
adb shell chmod +x /data/local/tmp/uwb_autonomous.sh /data/local/tmp/cir_stream /data/local/tmp/dw3000_regwrite.sh

# 2. First: test register writes
adb shell /data/local/tmp/dw3000_regwrite.sh test-write

# 3. Run autonomous capture (500 frames, 200ms interval, CW tone ON)
adb shell nohup /data/local/tmp/uwb_autonomous.sh 500 200 1 &
# disconnect ADB, screen off, walk away

# 4. Check status later
adb shell cat /data/local/tmp/uwb_capture/status.txt

# 5. Pull and analyze
adb pull /data/local/tmp/uwb_capture/ data/cir_captures/latest/
./tools/analyze_capture.sh data/cir_captures/latest/ \
    --baseline data/cir_captures/baseline_50ms_64bins_mags.csv
```

## Option A: Borrow a Second UWB Device

Any of these work as a FiRa responder:

- iPhone 11, 12, 13, 14, 15 (U1/U2 chip)
- Samsung Galaxy S21+, S22+, S23+, S24+ (UWB models only)
- Google Pixel 6 Pro, 7 Pro, 8 Pro, 9 Pro

Use the same autonomous script, just start a ranging app on the second device first.

### What to Expect with Signal

- CIR peak at bin = distance / 0.6m (one-way)
- SNR 20-30 dB (vs current 6.5 dB noise)
- Sharp peak with coherent phase (vs random noise)
- Multipath reflections as secondary peaks

## Option B: PCTT Continuous RX (No Second Device, Harder)

From E015-E018: PCTT PER_RX commands all pass, but chip stays at power=0 because
SET_SCHEDULER kills the FiRa session. Possible fix:

1. Start FiRa session (chip powered)
2. Send PCTT SET_SCHEDULER_REGIONS to ADD pctt region alongside fira (E018 crashed)
3. Alternative: binary-patch the scheduler to allow region coexistence

This path needs more investigation into the mcps802154 scheduler FSM.

## Option C: Build dw3000.ko from Source

Requires the exact kernel source (commit ec45f20f38ea, kernel 6.1.145).
Would enable:

- Testmode commands (CW tone, continuous TX, RX diagnostics)
- Custom TX_TO_RX_DELAY for pseudo-radar experiments
- Proper CIR read integration (no binary patching needed)
- Full register access for DW3000 configuration

## Files Reference

| File                            | Purpose                                     |
| ------------------------------- | ------------------------------------------- |
| tools/cir_stream.c              | Continuous CIR capture (binary output)      |
| tools/cir_stream_decode.py      | Decode binary stream, per-frame stats + CSV |
| tools/decode_cir.py             | Single-capture CIR decoder                  |
| tools/analyze_baseline.py       | Per-bin mean/std/CoV classification         |
| tools/cir_average.py            | Incoherent magnitude averaging              |
| tools/cir_diff.py               | Differential analysis (baseline vs test)    |
| tools/cir_phase_analysis.py     | I/Q phase distribution analysis             |
| tools/cir_noise_characterize.py | Receiver noise characterization             |
| tools/uwb_link_budget.py        | Radar link budget calculator                |
| tools/cir_processing.py         | Signal processing library (CIRProcessor)    |
| tools/reflector_experiment.sh   | On-device A/B capture script                |
| tools/uwb_hotswap_capture.sh    | End-to-end laptop pipeline                  |
| EXPERIMENTS.yaml                | All 23 experiments documented               |
| CIR_CAPTURE_STATUS.md           | Current status and findings                 |
