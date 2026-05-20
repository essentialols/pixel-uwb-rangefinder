# Next Session Guide

## Current State (2026-05-19)

The CIR streaming pipeline is fully operational but captures only receiver thermal
noise because monostatic radar is physically impossible with the DW3000 in FiRa mode.

### What's Working

- 5-patch binary dw3000.ko: CIR read on RXPTO during FiRa sessions
- CIR streaming at 16.7fps via cir_stream + cir_stream_decode.py
- Module hot-swap procedure (setenforce 0, stop HAL, rmmod chain, insmod, start HAL)
- Noise floor fully characterized: Rayleigh-distributed, white, independent frames
- Analysis tools: baseline stats, averaging, differential, phase, noise, link budget

### Why No Signal

The DW3000 is half-duplex: TX and RX never overlap. After transmitting, the chip waits
200-500us before opening the RX window. In that time, any indoor reflection (speed of
light round-trip < 100ns for 15m) arrives and is lost. The RX window only sees thermal
noise from the receiver frontend.

## Option A: Borrow a Second UWB Device (RECOMMENDED)

Any of these work as a FiRa responder:

- iPhone 11, 12, 13, 14, 15 (U1/U2 chip)
- Samsung Galaxy S21+, S22+, S23+, S24+ (UWB models only)
- Google Pixel 6 Pro, 7 Pro, 8 Pro, 9 Pro

### Quick Start with Second Device

1. On the second device, install a UWB ranging app (or use `cmd uwb` if rooted)
2. On the Pixel 7 Pro, run the hot-swap and capture:
   ```bash
   ./tools/uwb_hotswap_capture.sh 100 200
   ```
3. Analyze the capture:
   ```bash
   python3 tools/cir_stream_decode.py data/cir_captures/*/capture.bin \
     --csv stats.csv --magnitudes mags.csv --full
   python3 tools/cir_diff.py --baseline data/cir_captures/baseline_50ms_64bins_mags.csv \
     --test mags.csv
   ```

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
