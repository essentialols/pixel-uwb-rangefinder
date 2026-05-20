# Architecture

## System Overview

```
                    On-Device (Pixel 7 Pro, rooted)
                    ================================
cmd uwb start-fira-ranging-session
        |
        v
  UWB Service (APEX) --> UCI HAL (uwb_core Rust)
        |
        v
  Vendor HAL (libuci_jni.so) --> netlink (mcps802154, family 34)
        |
        v
  mcps802154.ko --> mcps802154_region_fira.ko
        |
        v
  dw3000.ko (5 binary patches)
    Patch 1: RXPTO handler redirect to trampoline
    Patch 2: 11-instruction trampoline in dw3000_spitests space
    Patch 3: CIA flag check bypass in read_frame_cir_data
    Patch 4: debugfs state check bypass in reg_op
    Patch 5: completion.done reset for streaming (with NULL safety)
        |
        v                          v
  SPI bus (spi16.0)          debugfs /sys/kernel/debug/dw3000/
        |                     |-- cir_data (blocking read, CIR I/Q)
        v                     |-- cir_config (count/filter/offset)
  DW3000 chip (E0)           |-- 0x* (register files, read-WRITE)
  deca0314                   |-- power_stats
                              |-- chip_info

                    On-Laptop (analysis)
                    ====================
  adb pull capture.bin
        |
        v
  cir_stream_decode.py --> stats.csv + magnitudes.csv
        |
        v
  analyze_capture.sh (runs full pipeline)
    |-- analyze_baseline.py (per-bin classification)
    |-- cir_noise_characterize.py (Rayleigh fit, correlation)
    |-- cir_average.py (incoherent averaging)
    |-- process_baseline.py (CIRProcessor: leading edge, multipath)
    |-- cir_diff.py (differential: baseline vs test)
```

## Data Flow

### Capture

1. FiRa session transmits frame, opens 1.85ms RX window, gets RXPTO (no responder)
2. Binary-patched RXPTO handler calls `dw3000_read_frame_cir_data` via trampoline
3. CIR data (48-byte header + N x 6-byte I/Q records) written to `dw->cir_data`
4. Trampoline resets `completion.done = 0` for next frame
5. `cir_stream` opens/closes debugfs `cir_data` per frame, writes length-prefixed binary to stdout

### CIR Data Format

```
Header (48 bytes):
  count(u32) filter(u32) ts(u64) utime(u64)
  fp_power1(u32) fp_power2(u32) fp_power3(u32) offset(s32)
  fp_index(u16) pdoa(u16) acc(u16) type(u8) dummy(u8)

Records (6 bytes each):
  real[3] (6.18 signed fixed-point, little-endian)
  imag[3] (6.18 signed fixed-point, little-endian)

Decode: value = int.from_bytes(raw, 'little', signed=True) / (1 << 18)
```

### Stream Format

cir_stream outputs: `[4-byte LE length][raw CIR data]` per frame, to stdout.

## Key Technical Findings

### What Works

- CIR streaming at 16.7fps with 64 bins (expandable to 1016 via cir_config)
- Module hot-swap: setenforce 0, stop HAL, rmmod chain, insmod patched, start HAL
- Debugfs register files are READ-WRITE (AOSP confirmed, flag system: RO=2, WP=4)
- Noise floor is real Rayleigh-distributed thermal noise (sigma ratio 1.049)

### What Doesn't Work (Without Second Device)

- Monostatic radar: TX-to-RX dead zone > 300m blocks all indoor reflections
- CW tone: orthogonal to PN preamble code, won't produce CIR peaks
- CMD_TESTMODE: dw3000_testmode.o not linked (CONFIG_MCPS802154_TESTMODE disabled)
- PCTT continuous RX: scheduler conflict kills FiRa, chip powers down
- Fast commands (CMD_RX): different SPI format, unreachable via debugfs writes

## File Organization

```
pixel-uwb-rangefinder/
  *.c              Session 1-3 experiment tools (probe, diag, netlink, PCTT)
  tools/
    cir_stream.c          On-device: continuous CIR binary capture
    cir_reader.c          On-device: single blocking CIR read
    pctt_inject.c         On-device: testmode/PCTT netlink commands
    uwb_autonomous.sh     On-device: full unattended capture pipeline
    dw3000_regwrite.sh    On-device: register read/write/CW tone
    dw3000_explore_regs.sh On-device: register survey
    dw3000_binary_search.sh On-device: binary symbol analysis
    cir_stream_decode.py  Laptop: decode binary stream to CSV
    decode_cir.py         Laptop: decode single CIR capture
    analyze_baseline.py   Laptop: per-bin statistics
    cir_average.py        Laptop: incoherent averaging
    cir_diff.py           Laptop: differential analysis
    cir_phase_analysis.py Laptop: I/Q phase distribution
    cir_noise_characterize.py Laptop: noise floor characterization
    cir_processing.py     Laptop: CIRProcessor library (leading edge, multipath)
    process_baseline.py   Laptop: CIRProcessor batch runner
    uwb_link_budget.py    Laptop: radar link budget calculator
    analyze_capture.sh    Laptop: one-command full analysis pipeline
    analyze_cir.py        Laptop: legacy CIR analysis
  data/cir_captures/      Captured data and analysis results
  EXPERIMENTS.yaml        25 experiments documented (E001-E025)
  CIR_CAPTURE_STATUS.md   Current technical status
  NEXT_SESSION.md         Quickstart guide for next session
```
