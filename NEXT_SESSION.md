# Next Session Guide

## Current State (2026-05-19, session 3)

Device is operational. `cmd uwb` shell provides full UWB control without custom tools.
Diagnostic capture pipeline built and validated (52 reports in 15s test).
CIR access blocked by MODULE_SIG_PROTECT (can't load patched module).

### What's Working

- FiRa ranging via `cmd uwb start-fira-ranging-session` at 5Hz
- Diagnostic notifications with RSSI (needs responder for real values)
- Capture pipeline: `uwb_diag_capture.sh` + `parse_diag_logcat.py`
- Device accessible via `ssh h1 "adb shell su -c '...'"`, root works

### What's Not Working

- CIR data (debugfs cir_data empty with vendor module)
- Module hot-swap (MODULE_SIG_PROTECT blocks rmmod/insmod)
- Radar session mode (not supported on this chip)
- Direct register reads (vendor debugfs returns zeros)

## Quick Start: Diagnostic Capture

```bash
cd ~/Documents/GitHub/pixel-uwb-rangefinder

# 60-second capture
./tools/uwb_diag_capture.sh 60

# Parse results
python3 tools/parse_diag_logcat.py data/diag_captures/<latest>/raw_logcat.txt
```

## Quick Start: Manual FiRa Session

```bash
# Enable UWB
ssh h1 "adb shell su -c 'cmd uwb enable-uwb'"

# Enable diagnostics
ssh h1 "adb shell su -c 'cmd uwb enable-diagnostics-notification -r -a -c -s'"

# Start session (blocking, shows reports in terminal)
ssh h1 "adb shell su -c 'cmd uwb start-fira-ranging-session -b \
    -i 100 -c 9 -t controller -r initiator \
    -a 4660 -d 22136 -u ds-twr -l 200 -s 25 -R enabled'"

# Stop
ssh h1 "adb shell su -c 'cmd uwb stop-ranging-session 100'"
```

## Highest-Value Next Steps

### 1. Get a second UWB device (BEST ROI)

Any UWB phone as a responder would unlock:

- Real RSSI values for presence detection
- Actual distance/AoA measurements
- Populated diagnostic data (chip only fills on successful RX)
- No kernel modification needed

### 2. Flash custom kernel (unlocks CIR)

Build GKI kernel with MODULE_SIG_PROTECT=n, flash it.
Then load our patched dw3000.ko for full CIR pipeline.

### 3. Explore vendor UCI extensions

The logcat shows "Failed to parse received message: Unknown" after
diagnostic packets. These may contain vendor-specific CIR data.
Capture raw HAL traffic to investigate.

## Files Reference

| File                          | Purpose                                               |
| ----------------------------- | ----------------------------------------------------- |
| tools/uwb_diag_capture.sh     | End-to-end diagnostic capture (host-side)             |
| tools/parse_diag_logcat.py    | Parse logcat into ranging/diagnostic CSVs             |
| tools/cir_stream.c            | Continuous CIR capture (needs patched module)         |
| tools/cir_stream_decode.py    | Decode binary CIR stream                              |
| tools/pctt_inject (on device) | Netlink testmode command sender                       |
| FRONTIER.md                   | Full analysis of what works, dead ends, paths forward |
| EXPERIMENTS.yaml              | All experiments documented                            |
