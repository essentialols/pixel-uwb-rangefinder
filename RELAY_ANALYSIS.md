# Relay Analysis: MODULE_SIG_PROTECT Bypass Strategies

**Date:** 2026-05-19
**Sources:** Perplexity (GPT-5), Codex (Claude Opus agent), DeepSeek V3, Groq (Llama 3.3)

## Consensus findings

### 1. vendor_dlkm is AVB/dm-verity protected -- do NOT replace modules there

All relays agree: `/vendor_dlkm` is a verified partition (AVB with `vbmeta`).
Replacing `.ko` files will either:

- Not persist across reboot (dm-verity detects modifications)
- Cause a bootloop (verification fails)
- Be silently reverted

**Our deploy_modules.sh approach will likely fail.** We need a different strategy.

### 2. EPERM is likely SELinux + MODULE_SIG_PROTECT combined

Codex (most detailed) points out that the EPERM we see may be SELinux's
`module_load` permission check, not just MODULE_SIG_PROTECT's signature check.
Only `vendor_modprobe` domain has the right SELinux permissions for module loading.

Diagnostic commands to disambiguate:

```bash
avbctl get-verity
avbctl get-verification
getprop ro.boot.verifiedbootstate
dmesg | grep -E 'avc: denied|module|Protected symbol|version magic'
```

### 3. init does NOT bypass MODULE_SIG_PROTECT

Contrary to our assumption, init doesn't get a free pass on module signatures.
The vendor modules loaded at boot because they were properly signed for
the stock kernel AND loaded in the `vendor_modprobe` SELinux domain.

### 4. Best approach: boot image cmdline patch

Perplexity recommends adding `module.sig_enforce=0` to the kernel command line
in the boot image. This would:

- Disable signature enforcement globally
- Allow insmod from any root context
- Avoid dm-verity issues (modifying boot.img, not vendor_dlkm)
- Allow rapid iteration (compile -> push -> insmod -> test)

### 5. Alternative: rebuild kernel with drivers built-in

Codex recommends building the drivers as `=y` (built-in, not modules) in the
kernel config. This eliminates the module loading problem entirely but requires
a full kernel rebuild and boot.img flash.

## Ranked approaches (revised)

### A. Patch boot.img cmdline (BEST -- fast iteration)

1. Extract current boot.img
2. Unpack, add `module.sig_enforce=0` to cmdline
3. Repack and flash
4. After reboot: insmod from /data/local/tmp works
5. Rapid iteration: change code -> compile -> push -> insmod

### B. Build kernel with modules built-in (MOST RELIABLE)

1. Already have kernel source on H1
2. Change CONFIG_IEEE802154=m to =y, CONFIG_MAC802154=m to =y
3. Build custom GKI image
4. Flash boot.img
5. Only need to modprobe mcps802154 + dw3000 (or build those in too)

### C. Repack vendor_boot ramdisk (CORRECT Android way)

1. The official Android method for boot-time module loading
2. Put modules in vendor ramdisk's /lib/modules/
3. Loaded by init in vendor_modprobe domain
4. Most complex but most "correct"

### D. Disable dm-verity + replace vendor_dlkm modules

1. `adb disable-verity` or `avbctl disable-verification`
2. Reboot
3. Remount vendor_dlkm rw
4. Replace modules
5. Reboot
6. Risky: may affect other vendor partitions

## Decision: Approach A (cmdline patch)

Fastest path to working modules. We already have:

- Built modules on H1
- Magisk can patch boot images (that's how it works)
- Just need to add one kernel cmdline parameter

## Implementation plan

```bash
# 1. On device, use Magisk Manager to add kernel cmdline param
# OR manually extract, patch, and flash boot.img

# 2. After flashing:
adb shell su -c 'insmod /data/local/tmp/ieee802154.ko'
adb shell su -c 'insmod /data/local/tmp/mac802154.ko'
adb shell su -c 'insmod /data/local/tmp/mcps802154.ko'
adb shell su -c 'insmod /data/local/tmp/dw3000.ko'

# 3. Verify:
adb shell su -c 'cat /proc/modules | grep dw3000'
adb shell su -c 'ls /sys/kernel/debug/dw3000/'
```
