#!/bin/bash
# deploy_modules.sh -- Replace vendor UWB modules with custom-built ones
#
# This replaces the vendor-signed modules (which fail MODULE_SIG_PROTECT due to
# vermagic mismatch on LineageOS) with modules built from source against the
# running kernel. After reboot, init loads them from modules.load in its own
# context, bypassing MODULE_SIG_PROTECT.
#
# Usage:
#   ./deploy_modules.sh              # uses modules from H1 build
#   ./deploy_modules.sh /path/to/modules  # uses modules from specified dir
#
# Prerequisites:
#   - Device accessible via: ssh h1 "adb shell su -c '...'"
#   - Root access (Magisk su)
#   - Modules built per BUILD.md
#
# What this script does:
#   1. Backs up original vendor modules to /data/local/tmp/vendor_modules_backup/
#   2. Remounts vendor_dlkm and system_dlkm as read-write
#   3. Copies our modules over the vendor ones
#   4. Verifies the replacement
#   5. Optionally reboots
#
# What this script does NOT do:
#   - It does NOT modify the boot image
#   - It does NOT touch modules.load or modules.dep
#   - Changes survive until factory reset or OTA update

set -e

# Module source locations on H1
H1_IEEE="/tmp/android14-kernel/net/ieee802154/ieee802154.ko"
H1_MAC="/tmp/android14-kernel/net/mac802154/mac802154.ko"
H1_MCPS="/tmp/dw3000-src/kernel/net/mcps802154/mcps802154.ko"
H1_FIRA="/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_fira.ko"
H1_NFCC="/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_nfcc_coex.ko"
H1_PCTT="/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_pctt.ko"
H1_DW3000="/tmp/dw3000-src/kernel/drivers/net/ieee802154/dw3000.ko"

PHONE_TMP=/data/local/tmp
VENDOR_MODS=/vendor/lib/modules
SYSTEM_MODS=/system_dlkm/lib/modules
BACKUP_DIR=/data/local/tmp/vendor_modules_backup

h1_adb() {
    ssh h1 "adb shell su -c '$*'" 2>&1
}

h1_push() {
    local src="$1" dst="$2"
    ssh h1 "adb push $src $dst" 2>&1
}

echo "=== UWB Module Deployment ==="
echo "Date: $(date)"
echo ""

# Verify root access
echo "--- Checking root access ---"
result=$(h1_adb "id")
if ! echo "$result" | grep -q "uid=0"; then
    echo "ERROR: No root access. Output: $result"
    echo "Open the Magisk app on the phone and grant su to shell first."
    exit 1
fi
echo "Root: OK"

# Verify modules exist on H1
echo "--- Checking build artifacts on H1 ---"
for mod in "$H1_IEEE" "$H1_MAC" "$H1_MCPS" "$H1_FIRA" "$H1_NFCC" "$H1_PCTT" "$H1_DW3000"; do
    if ! ssh h1 "test -f $mod" 2>/dev/null; then
        echo "ERROR: Missing $mod on H1. Run BUILD.md steps first."
        exit 1
    fi
done
echo "All 7 modules found on H1"

# Backup originals
echo ""
echo "--- Backing up vendor modules ---"
h1_adb "mkdir -p $BACKUP_DIR"
for mod in ieee802154.ko mac802154.ko mcps802154.ko \
    mcps802154_region_fira.ko mcps802154_region_nfcc_coex.ko \
    mcps802154_region_pctt.ko dw3000.ko; do
    echo "  Backing up $mod..."
    h1_adb "cp $VENDOR_MODS/$mod $BACKUP_DIR/ 2>/dev/null || true"
    h1_adb "cp $SYSTEM_MODS/$mod $BACKUP_DIR/system_${mod} 2>/dev/null || true"
done
echo "Backups at $BACKUP_DIR"

# Push custom modules to device
echo ""
echo "--- Pushing custom modules to device ---"
for mod in "$H1_IEEE" "$H1_MAC" "$H1_MCPS" "$H1_FIRA" "$H1_NFCC" "$H1_PCTT" "$H1_DW3000"; do
    name=$(basename "$mod")
    echo "  Pushing $name..."
    h1_push "$mod" "$PHONE_TMP/$name"
done

# Remount filesystems
echo ""
echo "--- Remounting vendor_dlkm and system_dlkm as read-write ---"
h1_adb "mount -o remount,rw /vendor_dlkm" || {
    echo "WARNING: vendor_dlkm remount failed. Trying alternative..."
    h1_adb "mount -o remount,rw /vendor" || true
}
h1_adb "mount -o remount,rw /system_dlkm" || {
    echo "WARNING: system_dlkm remount failed."
}

# Replace vendor modules
echo ""
echo "--- Replacing vendor modules ---"
for mod in mcps802154.ko mcps802154_region_fira.ko mcps802154_region_nfcc_coex.ko \
    mcps802154_region_pctt.ko dw3000.ko; do
    echo "  Replacing $VENDOR_MODS/$mod..."
    h1_adb "cp $PHONE_TMP/$mod $VENDOR_MODS/$mod"
done

# Replace system_dlkm modules (ieee802154, mac802154)
for mod in ieee802154.ko mac802154.ko; do
    echo "  Replacing $SYSTEM_MODS/$mod..."
    h1_adb "cp $PHONE_TMP/$mod $SYSTEM_MODS/$mod"
    # Also copy to vendor_dlkm in case it's loaded from there
    h1_adb "cp $PHONE_TMP/$mod $VENDOR_MODS/$mod 2>/dev/null || true"
done

# Verify replacements
echo ""
echo "--- Verifying ---"
for mod in ieee802154.ko mac802154.ko mcps802154.ko dw3000.ko; do
    vendor_size=$(h1_adb "stat -c %s $VENDOR_MODS/$mod 2>/dev/null || echo 0")
    custom_size=$(h1_adb "stat -c %s $PHONE_TMP/$mod 2>/dev/null || echo 0")
    if [ "$vendor_size" = "$custom_size" ]; then
        echo "  OK: $mod ($vendor_size bytes)"
    else
        echo "  WARN: $mod sizes differ (vendor=$vendor_size, custom=$custom_size)"
    fi
done

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Reboot the device for init to load the new modules:"
echo "  ssh h1 'adb reboot'"
echo ""
echo "After reboot, verify:"
echo "  ssh h1 'adb shell su -c \"cat /proc/modules | grep dw3000\"'"
echo "  ssh h1 'adb shell su -c \"ls /sys/kernel/debug/dw3000/\"'"
echo ""

read -p "Reboot now? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ssh h1 "adb reboot"
    echo "Rebooting..."
fi
