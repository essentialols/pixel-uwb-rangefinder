# Recovery: Restoring boot_orig.img

**Date:** 2026-05-19
**Issue:** Flashed `boot_modsig_bypass.img` to boot_a. Device did not boot.

## What happened

1. Found pre-existing `boot_modsig_bypass.img` on H1 (created 2026-05-17, probably from ToF project)
2. Flashed to `/dev/block/by-name/boot_a` via `dd`
3. Device did not boot (no ADB, no fastboot after 2+ minutes)
4. The image was likely built for a different kernel or not Magisk-patched

## Recovery steps (when at the phone)

### Option 1: Force reboot + fastboot restore (recommended)

```bash
# 1. Force reboot: hold power button 10-15 seconds
# 2. Phone should enter bootloader/fastbootd
# 3. From H1:
ssh h1 "fastboot flash boot_a /tmp/boot_orig.img && fastboot reboot"
```

### Option 2: If it enters fastbootd (not regular fastboot)

```bash
# On the phone screen: navigate to "Reboot to bootloader" then:
ssh h1 "fastboot flash boot_a /tmp/boot_orig.img && fastboot reboot"
```

### Option 3: If Android A/B fallback worked

```bash
# Phone may have auto-switched to boot_b and booted normally
# Check with:
ssh h1 "adb shell getprop ro.boot.slot_suffix"
# If it shows _b, just flash boot_a back:
ssh h1 "adb reboot bootloader"
ssh h1 "fastboot flash boot_a /tmp/boot_orig.img"
ssh h1 "fastboot set_active a"
ssh h1 "fastboot reboot"
```

### Option 4: Wipe and re-flash stock

If all else fails, the stock boot image is preserved at:

- `/tmp/boot_orig.img` on H1
- `/tmp/boot_orig_backup.img` on H1

## After recovery

The correct approach to disable MODULE_SIG_PROTECT is to build a custom
GKI kernel from source (not reuse an old patched image). See FRONTIER.md.

## Lesson learned

Never flash a boot image from a previous session without verifying:

1. It was built for the exact same kernel version
2. It was Magisk-patched (or Magisk will re-patch on first boot, which can fail)
3. It was tested before
