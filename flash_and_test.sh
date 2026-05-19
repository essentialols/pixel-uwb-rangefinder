#!/bin/bash
# flash_and_test.sh -- Flash custom kernel + load UWB modules + run probe
#
# This is the end-to-end script for getting UWB CIR access on the Pixel 7 Pro.
# It assumes:
#   1. Custom kernel Image built on H1 (MODULE_SIG_PROTECT disabled)
#   2. UWB kernel modules built on H1
#   3. Phone accessible via ssh h1 "adb ..."
#   4. Root access via Magisk su
#
# Usage:
#   ./flash_and_test.sh              # full flow: flash kernel + load modules + test
#   ./flash_and_test.sh --skip-flash # just load modules + test (kernel already flashed)
#   ./flash_and_test.sh --restore    # restore original boot image

set -e

SKIP_FLASH=0
RESTORE=0

for arg in "$@"; do
    case $arg in
        --skip-flash) SKIP_FLASH=1 ;;
        --restore) RESTORE=1 ;;
    esac
done

h1_adb() {
    ssh h1 "adb shell su -c '$*'" 2>&1
}

# H1 paths
KERNEL_IMAGE="/tmp/android14-kernel/arch/arm64/boot/Image"
BOOT_ORIG="/tmp/boot_orig.img"
BOOT_CUSTOM="/tmp/boot_custom_nosig.img"
PHONE_TMP="/data/local/tmp"

# Module paths on H1
H1_MODS=(
    "/tmp/android14-kernel/net/ieee802154/ieee802154.ko"
    "/tmp/android14-kernel/net/mac802154/mac802154.ko"
    "/tmp/dw3000-src/kernel/net/mcps802154/mcps802154.ko"
    "/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_fira.ko"
    "/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_nfcc_coex.ko"
    "/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_pctt.ko"
    "/tmp/dw3000-src/kernel/drivers/net/ieee802154/dw3000.ko"
)

if [ "$RESTORE" = "1" ]; then
    echo "=== Restoring original boot image ==="
    h1_adb "dd if=$PHONE_TMP/boot_orig.img of=/dev/block/by-name/boot_a bs=4096"
    echo "Rebooting..."
    ssh h1 "adb reboot"
    echo "Done. Original kernel restored."
    exit 0
fi

echo "=== UWB Module Loading Pipeline ==="
echo "Date: $(date)"

# Check root
echo ""
echo "--- Checking root access ---"
result=$(h1_adb "id")
if ! echo "$result" | grep -q "uid=0"; then
    echo "ERROR: No root. Open Magisk app on phone first."
    exit 1
fi
echo "Root: OK"

if [ "$SKIP_FLASH" = "0" ]; then
    echo ""
    echo "--- Checking kernel Image ---"
    if ! ssh h1 "test -f $KERNEL_IMAGE" 2>/dev/null; then
        echo "ERROR: Kernel Image not found at $KERNEL_IMAGE"
        echo "Build it first: see BUILD.md"
        exit 1
    fi
    ssh h1 "ls -la $KERNEL_IMAGE" 2>&1

    echo ""
    echo "--- Packing boot.img ---"
    # Copy pack_boot.py to H1 if needed
    scp pack_boot.py h1:/tmp/ 2>/dev/null || true
    ssh h1 "python3 /tmp/pack_boot.py --kernel $KERNEL_IMAGE --orig $BOOT_ORIG --output $BOOT_CUSTOM" 2>&1

    echo ""
    echo "--- Backing up current boot image ---"
    h1_adb "dd if=/dev/block/by-name/boot_a of=$PHONE_TMP/boot_before_flash.img bs=4096" || true

    echo ""
    echo "--- Pushing and flashing custom kernel ---"
    ssh h1 "adb push $BOOT_CUSTOM $PHONE_TMP/boot_custom_nosig.img" 2>&1
    h1_adb "dd if=$PHONE_TMP/boot_custom_nosig.img of=/dev/block/by-name/boot_a bs=4096"
    echo "Kernel flashed. Rebooting..."

    ssh h1 "adb reboot" 2>&1

    echo "Waiting for device..."
    until ssh h1 "adb shell su -c 'echo ready'" 2>/dev/null | grep -q ready; do
        sleep 5
    done
    echo "Device booted with custom kernel!"
fi

echo ""
echo "--- Pushing UWB modules ---"
for mod in "${H1_MODS[@]}"; do
    name=$(basename "$mod")
    ssh h1 "adb push $mod $PHONE_TMP/$name" 2>&1 | grep -v "^$"
done

echo ""
echo "--- Loading UWB modules ---"
for mod in ieee802154 mac802154 mcps802154 \
           mcps802154_region_fira mcps802154_region_nfcc_coex \
           mcps802154_region_pctt dw3000; do
    echo -n "  $mod.ko: "
    result=$(h1_adb "/data/local/tmp/load_module /data/local/tmp/${mod}.ko 2>&1")
    echo "$result"
done

echo ""
echo "--- Verifying loaded modules ---"
h1_adb "cat /proc/modules | grep -iE 'dw3000|mcps|802154'"

echo ""
echo "--- Checking debugfs ---"
h1_adb "ls -la /sys/kernel/debug/dw3000/ 2>/dev/null || echo 'No debugfs (driver may not have probed)'"

echo ""
echo "--- Running UWB probe ---"
h1_adb "$PHONE_TMP/uwb_probe"

echo ""
echo "--- Running UWB diagnostics ---"
h1_adb "$PHONE_TMP/uwb_diag"

echo ""
echo "=== Pipeline complete ==="
