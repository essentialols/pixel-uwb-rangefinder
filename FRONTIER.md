# Frontier Analysis -- What's Real, What's Not, What's Next

**Date:** 2026-05-19, session 1 (on-device results + module build)

## Major achievement: all modules built from source

Successfully cross-compiled the entire UWB module chain from AOSP source
against the running LineageOS 6.1 kernel on H1 (16-core, aarch64 cross-compiler):

```
ieee802154.ko     -- from kernel/common (android14-6.1)
mac802154.ko      -- from kernel/common (android14-6.1)
mcps802154.ko     -- from AOSP google-modules/uwb/qorvo/dw3000 (pantah branch)
mcps802154_region_fira.ko
mcps802154_region_nfcc_coex.ko
mcps802154_region_pctt.ko
dw3000.ko         -- with 3 patches for 5.10->6.1 API changes
```

Build location on H1:

- Kernel tree: `/tmp/android14-kernel/`
- DW3000 source: `/tmp/dw3000-src/`
- ieee802154.ko: `/tmp/android14-kernel/net/ieee802154/ieee802154.ko`
- mac802154.ko: `/tmp/android14-kernel/net/mac802154/mac802154.ko`
- mcps/dw3000: `/tmp/dw3000-src/kernel/{net,drivers}/.../`

### Patches applied to dw3000_spi.c (5.10 -> 6.1 API changes)

1. `spi->master->last_cs_enable` removed (member doesn't exist in 6.1)
2. `dw3000_spi_remove()` return type changed from `int` to `void`
3. `spi->controller->kworker.task` changed to `kworker->task` (pointer in 6.1)

## Blocker: MODULE_SIG_PROTECT

Both vendor-signed and our custom-built (unsigned) modules are blocked by
`MODULE_SIG_PROTECT` on GKI 6.1. This enforcement:

- Applies to ALL non-init contexts (shell, magisk, service processes)
- Applies even to unsigned modules built for the exact running kernel
- Returns EPERM from finit_module() with NO kernel log message
- Only modules loaded by init during early boot pass

The Magisk `post-fs-data.sh` runs in `u:r:magisk:s0` context which is
NOT treated as init context by the kernel's module loading code.

### What we tried

1. insmod from adb shell su -- EPERM
2. Direct finit_module() syscall -- EPERM
3. Magisk post-fs-data.sh script -- EPERM (runs as magisk context, not init)
4. Copying modules to /data/local/tmp -- same EPERM
5. Loading vendor modules (signed for wrong kernel) -- "exports protected symbol" or EPERM

### What works

- `dw3000_core_tests.ko` loads because it's in the vendor `modules.load` and
  is loaded by `init` during early boot (the ONLY context that passes sig check)

## Current device state

**Phone is in recovery mode with unauthorized ADB.** Needs physical interaction
to either navigate recovery menu or reboot. The Magisk `su` binary stopped
working (likely unrelated to our module -- Magisk on this build may need app
interaction to set up su for first use after reboot).

## Verified facts (on-device)

| Finding                 | Detail                                          |
| ----------------------- | ----------------------------------------------- |
| DW3000 SPI device       | `spi16.0` on bus `10db0000.spi`                 |
| Device tree node        | `dw3xxx_prod@0` (compatible: `decawave,dw3000`) |
| Module dependency chain | ieee802154 -> mac802154 -> mcps802154 -> dw3000 |
| Modules on filesystem   | All present in `/vendor_dlkm/lib/modules/`      |
| Qorvo HAL               | Uses `libnl.so` -> `nl802154` netlink           |
| Running kernel          | `6.1.145-android14-11-gec45f20f38ea-ab15260282` |

## Dead ends

1. Loading modules from any non-init context -- MODULE_SIG_PROTECT blocks
2. Vendor-signed modules -- wrong vermagic AND protected symbol exports
3. Unsigned modules -- EPERM regardless of vermagic match

## Paths forward (revised)

### A. Add modules to init's modules.load (RECOMMENDED)

The modules.load file at `/vendor_dlkm/lib/modules/modules.load` is read by init
at boot. `dw3000.ko` is already listed but its dependencies fail. If we can:

1. Replace the vendor ieee802154.ko/mac802154.ko/mcps802154.ko/dw3000.ko with our
   custom-built versions (which have correct vermagic for this kernel)
2. These would be loaded by init (passing MODULE_SIG_PROTECT)
3. Requires remounting vendor_dlkm as read-write

### B. Build a custom GKI kernel with MODULE_SIG_PROTECT=n

- Kernel source is at `android.googlesource.com/kernel/common` commit `ec45f20f38ea`
- Already have the build environment set up on H1
- Would need to flash the new boot image (GKI Image)
- Most reliable long-term solution

### C. Patch init.insmod to load from /data/local/tmp

- The init.insmod.sh script could be modified to load our modules
- Requires boot image modification (ramdisk)

### D. KernelSU instead of Magisk

- KernelSU patches the kernel itself, giving true init-level module loading
- Would require kernel rebuild anyway

## When you're next at the phone

1. **Reboot from recovery** -- select "Reboot system now" from recovery menu
2. **Open Magisk app** -- this should set up the `su` binary
3. **Grant su to shell** -- `adb shell su -c id` should trigger a prompt in Magisk app
4. **Remove our Magisk module** -- `su -c 'rm -rf /data/adb/modules/uwb-modules'`
5. **Try option A** -- remount vendor_dlkm and replace modules with our built ones
