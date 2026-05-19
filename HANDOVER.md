# Pixel UWB Rangefinder -- Session Handover

**Date:** 2026-05-19 (session 1 -- on-device results)
**Project:** `~/Documents/GitHub/pixel-uwb-rangefinder`
**Device:** Pixel 7 Pro on H1 (serial: 28071FDH3000R7), accessible via `ssh h1 "adb shell ..."`

## Current status: BLOCKED -- kernel module signature mismatch

DW3000 hardware confirmed alive on SPI bus. All tools deployed and run.
**The kernel modules (dw3000.ko, mcps802154.ko, ieee802154.ko, mac802154.ko)
cannot be loaded** because LineageOS replaced the kernel and the vendor
modules are signed for a different build. `MODULE_SIG_PROTECT` blocks loading.

No debugfs. No netlink. No CIR access. The entire kernel-based path is blocked.

## What we confirmed on-device

| Finding           | Detail                                                                     |
| ----------------- | -------------------------------------------------------------------------- |
| DW3000 SPI device | `spi16.0` on bus `10db0000.spi`                                            |
| Device tree node  | `dw3xxx_prod@0` (compatible: `decawave,dw3000`)                            |
| SPI controller    | SPI master 16, platform `10db0000.spi`                                     |
| Chip power        | S2MPG13 PMIC + AOC GPIO for reset                                          |
| Driver binding    | **NONE** -- no driver bound to spi16.0                                     |
| Module files      | All present in `/vendor_dlkm/lib/modules/` and `/system_dlkm/lib/modules/` |
| Module loading    | **BLOCKED** by MODULE_SIG_PROTECT (vermagic mismatch)                      |
| Running kernel    | `6.1.145-android14-11-gec45f20f38ea-ab15260282` (LineageOS)                |
| Module vermagic   | `6.1.145-android14-11-g66d850f9dea9-ab401307b609` (stock vendor)           |
| Qorvo HAL         | Running but idle (nl802154 netlink family not registered)                  |
| HAL architecture  | Uses libnl.so -> nl802154 netlink -> kernel ieee802154 stack               |
| nl802154          | **Does not exist** (modules not loaded)                                    |
| dw3000_core_tests | Loaded at boot (no deps, loaded by init)                                   |

## Access via H1

```bash
# Run any command on the Pixel 7 Pro
ssh h1 "adb shell su -c '<command>'"

# Deploy a file
scp <file> h1:/tmp/ && ssh h1 "adb push /tmp/<file> /data/local/tmp/"
```

## Unblocking strategy

**Recommended: build modules from AOSP source for the LineageOS kernel.**

The full chain is open-source:

1. `ieee802154.ko` -- Linux kernel tree
2. `mac802154.ko` -- Linux kernel tree
3. `mcps802154.ko` -- AOSP `kernel/google-modules/uwb/qorvo/dw3000/mac/`
4. `dw3000.ko` -- AOSP `kernel/google-modules/uwb/qorvo/dw3000/kernel/drivers/net/ieee802154/`
5. FiRa/PCTT regions -- AOSP `kernel/google-modules/uwb/qorvo/dw3000/mac/`

Need the LineageOS kernel headers matching `6.1.145-android14-11-gec45f20f38ea`.

## Session 1 experiment results

| ID   | Tool         | Result                                               |
| ---- | ------------ | ---------------------------------------------------- |
| E001 | uwb_probe    | DW3000 found on spi16.0, no driver bound, no debugfs |
| E002 | uwb_recon.sh | Confirmed module list, no ieee802154 class           |
| E004 | uwb_diag     | No debugfs to read (requires driver)                 |
| E005 | uwb_regdump  | No debugfs to dump (requires driver)                 |
| E007 | uwb_testmode | nl802154 family not registered (modules not loaded)  |
| E003 | uwb_cir_read | Not attempted (requires debugfs)                     |
