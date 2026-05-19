# Pixel UWB Rangefinder -- Session Handover

**Date:** 2026-05-19 (session 1 -- tools built, pre-deployment)
**Project:** `~/Documents/GitHub/pixel-uwb-rangefinder`

## Current status: SESSION 1 -- TOOLS READY, AWAITING DEPLOYMENT

Source code analysis complete. Six experiment tools built. Awaiting first on-device run.

## Critical finding: debugfs CIR access path

The DW3000 driver exposes **raw CIR data through debugfs**, not netlink:

```
/sys/kernel/debug/dw3000/<spidev>/cir_data     # binary CIR records (read-only, blocks until data ready)
/sys/kernel/debug/dw3000/<spidev>/cir_config    # "count N filter 0xM offset D" (read/write)
/sys/kernel/debug/dw3000/<spidev>/power         # "0" or "1" (read/write)
/sys/kernel/debug/dw3000/<spidev>/0xNNNNNN      # individual register files (read/write)
```

### CIR data structure (from dw3000_cir.h)

```c
struct dw3000_cir_record {
    u8 real[3];  // 6.18 fixed-point signed
    u8 imag[3];  // 6.18 fixed-point signed
};
// Per-capture metadata: count, filter, ts, utime, fp_power1/2/3, offset,
// fp_index, pdoa, acc, type
```

### Key register addresses

| Register      | Address      | Description                                       |
| ------------- | ------------ | ------------------------------------------------- |
| DEV_ID        | 0x0          | Chip identification                               |
| SYS_CFG       | 0x10         | System config (PDOA mode, CIA enable)             |
| SYS_STATUS    | 0x44         | Event flags (CIA_DONE at bit 10)                  |
| RX_FINFO      | 0x4c         | RX frame info                                     |
| RX_TIME       | 0x64         | RX timestamp (5 bytes)                            |
| CIA_PDOA      | 0xc001c      | PDoA + TDoA results                               |
| CIA_DIAG0     | 0xc0020      | Clock offset PPM                                  |
| IP_DIAG0-8    | 0xc0028+     | IP diagnostic registers                           |
| **CIR_RAM**   | **0x150000** | **Raw CIR memory (the prize)**                    |
| DB_DIAG_SET_1 | 0x180000     | Full diagnostic set (0xe8 bytes)                  |
| DB_DIAG_SET_2 | 0x1800e8     | Second diagnostic set                             |
| CLK_CTRL      | 0x70036      | ACC_MEM_CLK_ON at bit 15 (enables CIR RAM access) |

### Testmode netlink commands (ieee802154 genl)

```
START_RX_DIAG (1)     STOP_RX_DIAG (2)     GET_RX_DIAG (3)     CLEAR_RX_DIAG (4)
OTP_READ (5)          OTP_WRITE (6)
START_TX_CWTONE (7)   STOP_TX_CWTONE (8)
START_CONTINUOUS_TX (9) STOP_CONTINUOUS_TX (10)
SET_HRP_PARAMS (23)   SET_CHANNEL (24)
```

RSSI data: `cir_pwr` (17-bit) + `pacc_cnt` (11-bit) + `prf_64mhz` (1-bit) + `dgc_dec` (3-bit)

### AOC role: GPIO only

AOC **does not mediate UWB data**. It only controls 4 GPIO operations for the DW3000 reset pin:

- GET_RESET_GPIO (0xCA), SET_RESET_GPIO (0xCB)
- GET_DIRECTION (0xCC), SET_DIRECTION (0xCD)

Direct SPI access to DW3000 goes through the kernel driver, not AOC.

## Built tools (ready to deploy)

| Tool                   | Type          | Experiment | Purpose                                                            |
| ---------------------- | ------------- | ---------- | ------------------------------------------------------------------ |
| `uwb_probe`            | C (aarch64)   | E001       | Full subsystem enumeration: devnodes, debugfs, SPI, netlink, dmesg |
| `uwb_recon.sh`         | Shell         | E002       | Quick no-compile recon: modules, debugfs, power state, CIR config  |
| `uwb_cir_read`         | C (aarch64)   | E003       | Read binary CIR data, decode 6.18 fixed-point, output CSV/JSON     |
| `uwb_diag`             | C (aarch64)   | E004       | Read key diagnostic registers, show chip ID and CIA state          |
| `uwb_regdump`          | C (aarch64)   | E005       | Dump all register files, diff mode for live register detection     |
| `tools/analyze_cir.py` | Python (host) | E006       | CIR analysis: peak detection, multipath, SNR, plotting             |

## Deployment commands

```bash
# Build all tools
make

# Deploy to device
make deploy

# Run reconnaissance
adb shell su -c "setenforce 0; sh /data/local/tmp/uwb_recon.sh"

# Run full probe
adb shell su -c /data/local/tmp/uwb_probe

# Read diagnostics
adb shell su -c /data/local/tmp/uwb_diag

# Dump all registers
adb shell su -c /data/local/tmp/uwb_regdump

# Read CIR (may need active ranging session)
adb shell su -c /data/local/tmp/uwb_cir_read

# Register diff (find live registers)
adb shell su -c "/data/local/tmp/uwb_regdump -d"
```

## Session 2 plan

1. Deploy and run E001-E005 on device
2. Identify actual debugfs path (spi device name)
3. Read chip ID to confirm DW3000 variant
4. Map which registers are readable vs locked
5. Attempt CIR read (may need active ranging or PCTT mode)
6. If CIR blocked: investigate testmode netlink as alternative path
