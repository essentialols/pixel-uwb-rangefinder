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

## Session 3: Single-Device CIR Capture Attempts (2026-05-19)

### What we tried without a second device

| Approach                        | Result                                                                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| PCTT PER_RX (continuous RX)     | All 5 netlink steps pass after fixing bugs + binary patching vendor module. Chip doesn't start: FSM start_stop_request cleared after HAL restart |
| debugfs cir_data during FiRa    | I/O error: driver holds SPI lock, chip in deep sleep between slots                                                                               |
| ftrace/kprobes on CIR functions | Confirmed CIR only read on successful frame RX, never on RXPTO. Testmode not compiled                                                            |
| UCI vendor commands / radar     | No vendor cmd interface in cmd uwb. Radar fails status_code=4 (not supported)                                                                    |
| Raw SPI to CIR_RAM              | Not attempted: /dev/mem doesn't exist, driver holds SPI lock                                                                                     |

### Key ftrace finding

Each FiRa slot: wakeup -> TX (TXFRS) -> RX enable (1.85ms) -> RXPTO -> deep sleep (480ms).
CIR accumulator IS populated during the 1.85ms RX window (even with no signal), but the driver
only reads it on successful frame reception, not on RXPTO.

### Best remaining path: RXPTO CIR hook

Binary-patch dw3000.ko to call CIR read on RXPTO interrupt (before deep sleep). This works with
existing FiRa sessions, no second device needed. The CIR accumulator contains noise floor data
from each RX window. 4/4 relays agree this is the strongest approach.

### Alternative: PCTT with HAL-started chip

Run PCTT immediately after HAL starts a FiRa session (while chip is still online). The NOP-patched
PCTT module bypasses the ENETDOWN check; if start_stop_request is still true, the chip should stay
powered for continuous RX.

## What We Need (revised)

**Either** a second UWB device **or** a patched dw3000.ko that reads CIR on RXPTO.

### Unblocking options (ranked by effort)

1. **Get a DWM3000 eval board** (~$30-50 from Qorvo/Mouser). Acts as ranging responder.
   CIR capture works immediately via existing UCI diagnostics pipeline.
2. **Disable dm-verity + replace dw3000.ko** with source-patched version that reads CIR on
   RXPTO. Requires: `avbctl disable-verity`, reboot, remount vendor_dlkm rw, copy patched
   module, reboot. Source patch: add `dw3000_read_frame_cir_data(dw, NULL, 0)` call in
   `dw3000_isr_handle_rxto_event` before `mcps802154_rx_timeout`.
3. **Build dw3000.ko from exact kernel source** (commit ec45f20f38ea) with matching
   vermagic/CRCs for hot-swap via rmmod+insmod (proven to work in this session).

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
