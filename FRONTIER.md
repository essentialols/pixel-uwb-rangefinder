# Frontier Analysis -- What's Real, What's Not, What's Next

**Date:** 2026-05-19, session 1 (on-device results)

## Critical finding: kernel module signature mismatch

The DW3000 kernel modules exist on the filesystem but **cannot be loaded** because
LineageOS replaced the kernel. The vendor modules are signed for
`6.1.145-android14-11-g66d850f9dea9` but the running kernel is
`6.1.145-android14-11-gec45f20f38ea`. `MODULE_SIG_PROTECT` blocks loading.

**Consequence:** No debugfs, no CIR access, no netlink interface. The entire
kernel-based access path we designed tools for is blocked until we resolve
the module loading issue.

## Verified facts (on-device, session 1)

### Hardware confirmed

- DW3000 is on **SPI bus spi16.0** (`/sys/bus/spi/devices/spi16.0`)
- SPI controller at `10db0000.spi` (SPI master 16)
- Device tree node: `dw3xxx_prod@0` (compatible: `decawave,dw3000`)
- Power supplies: S2MPG13 PMIC, AOC gpiochip (reset GPIO)
- **No driver bound** to the SPI device (no `driver` symlink)

### Module status

- `dw3000.ko` -- present at `/vendor_dlkm/lib/modules/dw3000.ko` (648KB) -- **NOT loaded**
- `mcps802154.ko` -- present at `/vendor_dlkm/lib/modules/mcps802154.ko` (407KB) -- **NOT loaded**
- `mcps802154_region_fira.ko` -- present -- **NOT loaded**
- `mcps802154_region_pctt.ko` -- present -- **NOT loaded**
- `mcps802154_region_nfcc_coex.ko` -- present -- **NOT loaded**
- `ieee802154.ko` -- present at `/system_dlkm/lib/modules/ieee802154.ko` -- **NOT loaded**
- `mac802154.ko` -- present at `/system_dlkm/lib/modules/mac802154.ko` -- **NOT loaded**
- `dw3000_core_tests.ko` -- **LOADED** (no deps, loaded at boot by init)

### Module dependency chain

```
ieee802154 (no deps)
  -> mac802154 (depends: ieee802154)
    -> mcps802154 (depends: mac802154)
      -> dw3000 (depends: mcps802154)
      -> mcps802154_region_fira (depends: mcps802154)
      -> mcps802154_region_pctt (depends: mcps802154)
```

### Qorvo HAL architecture

- HAL binary: `/vendor/bin/hw/android.hardware.qorvo.uwb.service` (338KB)
- Runs as user `uwb` with `NET_ADMIN NET_RAW` capabilities
- Uses `libnl.so` for **nl802154 netlink** communication with kernel
- References `dw3000-hal` source paths (Qorvo's proprietary HAL)
- Has `helper_open`/`helper_start` functions that manage the kernel stack
- **Currently idle** -- HAL is running but nl802154 family doesn't exist
- No direct SPI FDs open (only binder sockets)

### Kernel info

- Kernel: `6.1.145-android14-11-gec45f20f38ea-ab15260282` (LineageOS)
- 62 loadable modules total
- `CONFIG_MODULE_SIG=y`, `CONFIG_MODULE_SIG_PROTECT=y`
- `CONFIG_MODULE_SIG_FORCE` is NOT set
- `modules_disabled=0` (loading nominally allowed)
- `CONFIG_MAC802154=m` (compiled as module, not built-in)

## Dead ends

1. **insmod from shell** -- EPERM from MODULE_SIG_PROTECT signature verification
2. **finit_module() syscall directly** -- Same EPERM
3. **Copy to /tmp then insmod** -- Same EPERM
4. **system_dlkm vs vendor_dlkm** -- Both have same vermagic mismatch
5. **/dev/mem** -- Does not exist on this Android build
6. **/dev/spidev** -- spidev module also can't be loaded

## Paths forward (ranked by feasibility)

### A. Build modules from AOSP source for this kernel (RECOMMENDED)

- The DW3000 driver + full MAC stack is open-source in AOSP
- Need: kernel headers for `6.1.145-android14-11-gec45f20f38ea`
- LineageOS publishes kernel source: check `kernel_google_gs201` repo
- Build ieee802154 + mac802154 + mcps802154 + dw3000 as modules
- Sign with the LineageOS signing key (or disable module sig verify)
- **This is the correct long-term fix**

### B. Magisk module to load at boot

- Create a Magisk module that loads the vendor .ko files during early boot
- May work because `dw3000_core_tests.ko` DID load during init
- The signature check might only apply to post-boot loading
- Quick to try, may not work if sig check applies to init too

### C. Disable module signature verification

- Kernel config has `MODULE_SIG_FORCE` NOT set
- May be possible to flip `CONFIG_MODULE_SIG_PROTECT` via kernel patch
- Requires kernel rebuild (same as option A)

### D. Use stock Google kernel + vendor modules

- Switch to stock Pixel kernel where signatures match
- Would require reflashing boot partition
- Fastest path to get modules loaded

### E. Userspace SPI access via custom kernel module

- Write a minimal char device driver that provides raw SPI access
- Build it against the LineageOS kernel headers
- This bypasses the entire mac/mcps stack but gives us raw register access
- Could read CIR_RAM (0x150000) directly via SPI

## Next session priorities

1. Check if LineageOS kernel source is available for this exact build
2. Attempt to build ieee802154 + mac802154 + mcps802154 + dw3000 from AOSP source
3. If build succeeds, test loading on device
4. Alternative: try Magisk boot-time module injection
