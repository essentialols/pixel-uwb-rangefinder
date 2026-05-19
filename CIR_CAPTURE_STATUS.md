# CIR Capture Status

## Current State (2026-05-19)

We have **two working paths** to CIR data, both require a second UWB device:

### Path 1: UCI Diagnostic Notifications (RECOMMENDED)

- **Status**: Pipeline verified end-to-end, CIR array empty due to no responder
- **How**: `cmd uwb enable-diagnostics-notification -c -r -a` + start FiRa session
- **Where**: Logcat `uwb_core::uci::notification: Received diagnostic packet`
- **Format**: ParsedDiagnosticNtfPacket → FrameReport → cir[] array
- **Pros**: Works through stock Android UWB stack, no kernel mods needed
- **Cons**: Needs a real UWB frame reception

### Path 2: debugfs cir_data

- **Status**: File exists, blocks until CIR available, returns I/O error when chip idle
- **How**: `cat /sys/kernel/debug/dw3000/cir_data` during active RX
- **Format**: Binary struct with header + N×6-byte I/Q records (6.18 fixed-point)
- **Pros**: Raw hardware data, configurable via cir_config
- **Cons**: Timing-dependent, chip must be actively receiving

## What We Need

**A second UWB device** to act as ranging partner. Options:

1. Another Android phone with UWB (Pixel 6 Pro+, Samsung S21+, iPhone 11+)
2. Qorvo DWM3000 evaluation board (~$30-50)
3. Apple U1 AirTag (triggers UWB when in proximity to iPhone)
4. Any FiRa-compatible UWB device

## What Works Without a Partner

| Feature                  | Status                                           |
| ------------------------ | ------------------------------------------------ |
| Start FiRa session       | OK - `cmd uwb` shell                             |
| UCI diagnostics pipeline | OK - logcat shows ParsedDiagnosticNtfPacket      |
| TX frame reports         | OK - RSSI/AoA/CIR fields present (TX has no CIR) |
| RX frame reports         | Empty - no frames received (no responder)        |
| Calibration data         | Extracted - 4 antennas, delays, PDoA LUTs        |
| Radar mode               | Fails (status_code=4)                            |
| DL-TDoA mode             | Fails (status_code=2)                            |
| PCTT PER_RX              | EBUSY (HAL holds scheduler)                      |
| debugfs register reads   | I/O error (chip idle between slots)              |

## Calibration Data Extracted

```
4 antennas, 2 SPI ports, GPIO-switched
Channels: 5 and 9, PRF: 16 and 64 MHz
Antenna delays: 16409-16465 ticks (~257 ns, ~38.5m equiv)
Inter-config variation: up to 124mm (ch5/prf64 vs ch9/prf16)
PDoA LUTs: ant1-ant2, ant1-ant3 (31 entries each, ±90°)
Crystal trim: 23 (vendor) / 0x27=39 (factory)
AoA capability: 2 (azimuth + elevation)
```

## Architecture Understanding

```
Android App → UwbManager → UWB Service (APEX)
  → UCI HAL (uwb_core Rust) → Qorvo vendor HAL (libuci_jni.so)
    → netlink (mcps802154, family 34) → kernel mcps802154
      → FiRa region → dw3000 driver → SPI → DW3000 chip
                                         ↓
                              debugfs cir_data (blocked by driver state)
```

UCI diagnostic notifications flow back UP through this stack and appear in logcat.
