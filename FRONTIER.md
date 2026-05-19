# Frontier Analysis -- What's Real, What's Not, What's Next

**Date:** 2026-05-19, session 1 (tools built, pre-deployment)

## Verified facts (from AOSP source analysis)

### Driver architecture

- DW3000 driver is **fully open-source** in AOSP google-modules (GPLv2 + Qorvo commercial dual-license)
- Uses SPI bus (not I2C) -- different from VL53L1 ToF which uses I2C
- Registers as ieee802154 PHY device
- Creates wpan network interface
- Full FiRa + PCTT MAC stack is open-source

### CIR access path (confirmed in source)

- `dw3000_cir_data` struct holds complex I/Q CIR samples (6.18 fixed-point, 3 bytes each)
- Exposed via debugfs: `cir_data` (binary read, blocks until available), `cir_config` (text r/w)
- Default 20 CIR records per capture, configurable
- CIR RAM at register `0x150000`
- CIR data includes: fp_index, fp_power1/2/3, PDoA, timestamp, accumulation count
- ACC_MEM_CLK_ON bit (CLK_CTRL register) must be set to read CIR RAM

### Diagnostic access (confirmed in source)

- Full diagnostic register set (DB_DIAG) at `0x180000` (0xe8 bytes per set, two sets)
- CIA registers: DIAG0 (clock offset PPM), TDOA, PDOA, IP diagnostics
- All registers exposed as individual debugfs files (read/write)
- Testmode netlink: START/STOP/GET/CLEAR_RX_DIAG, CW tone, continuous TX

### AOC role (confirmed in source)

- AOC only handles DW3000 reset GPIO (4 commands: get/set pin, get/set direction)
- NOT a data mediator -- all UWB data goes through kernel SPI driver directly

### Kernel module set

- `dw3000.ko` -- SPI driver
- `mcps802154.ko` -- IEEE 802.15.4 MAC
- `mcps802154_region_fira.ko` -- FiRa ranging
- `mcps802154_region_pctt.ko` -- PHY Compliance Test Tool
- `mcps802154_region_nfcc_coex.ko` -- NFC coexistence
- `aoc_uwb_platform_drv.ko` -- AOC GPIO bridge
- `aoc_uwb_service_dev.ko` -- AOC GPIO service

## Unknown (must verify on-device)

1. **Is debugfs mounted and accessible?** Need root + possibly `mount -t debugfs none /sys/kernel/debug`
2. **What is the SPI device name?** (e.g., spi0.0, spi1.0, spi2.0) -- determines debugfs path
3. **Is the DW3000 powered on at boot?** Or does the Android UWB HAL control power?
4. **Are all debugfs register files readable?** Google may have restricted some
5. **Does cir_data block or return empty without active ranging?** Source shows it blocks on a completion
6. **DW3000 chip variant?** DW3000 vs DW3720 vs DW3120 -- firmware and CIR differ
7. **Is the Android UWB HAL service holding exclusive SPI access?**
8. **Does PCTT mode work for single-device CIR capture?**
9. **Are testmode netlink commands compiled in?** (Google stripped ToF ioctls -- may strip these too)

## Dead ends (nothing confirmed yet)

(No experiments run yet)

## Next leads (ranked by feasibility)

### Immediate (run on-device)

1. **uwb_recon.sh** -- zero risk, no compilation, answers questions 1-3 immediately
2. **uwb_probe** -- comprehensive enumeration, answers questions 1-4
3. **uwb_diag** -- read chip ID (question 6), check register accessibility (question 4)
4. **uwb_regdump -d** -- find live/changing registers, understand chip state

### If debugfs works

5. **uwb_cir_read** -- attempt CIR capture (answers question 5)
6. **uwb_cir_read -c 64** -- larger CIR window for better multipath resolution

### If CIR blocked (needs active ranging)

7. **PCTT mode via netlink** -- single-device PHY test mode may trigger CIR capture
8. **Testmode RX_DIAG** -- alternative to CIR for diagnostic data
9. **Power on via debugfs** -- write "1" to power file, then try CIR
10. **Kill Android UWB HAL** -- stop competing service, take direct control

### If testmode also blocked

11. **BPF kprobe on CIR read function** -- intercept CIR data from kernel memory (proven on ToF project)
12. **Direct SPI register access** -- bypass driver, read CIR_RAM at 0x150000 directly
