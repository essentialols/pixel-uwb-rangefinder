#!/bin/bash
# build_testmode.sh -- End-to-end: pull symvers, rebuild dw3000.ko with testmode, deploy
#
# Requires: device connected via ADB, H1 (build server) reachable via SSH
#
# What this does:
#   1. Pull /proc/Module.symvers from device (kernel symbol versions)
#   2. Copy to H1 build server
#   3. Rebuild dw3000.ko with CONFIG_MCPS802154_TESTMODE=y on H1
#   4. Pull built .ko back to laptop
#   5. Push to device and hot-swap
#
# The testmode-enabled module adds dw3000_tm_cmd handler with:
#   - START_RX_DIAG: continuous promiscuous RX (captures all UWB frames)
#   - START_TX_CWTONE: continuous wave transmission
#   - START_CONTINUOUS_TX: continuous frame transmission
#
# Usage:
#   ./tools/build_testmode.sh          # full pipeline
#   ./tools/build_testmode.sh --build  # build only (already have symvers on H1)
#   ./tools/build_testmode.sh --deploy # deploy only (already have .ko)

set -e

H1=h1
BUILD_DIR=/tmp/dw3000-src/kernel
KERNEL_DIR=/tmp/android14-kernel
DEVICE_DIR=/data/local/tmp

MODE=${1:-full}

# Step 1: Pull Module.symvers from device
if [ "$MODE" = "full" ] || [ "$MODE" = "--pull" ]; then
    echo "=== Step 1: Pull Module.symvers from device ==="
    if ! adb devices | grep -q "device$"; then
        echo "ERROR: No device connected"
        exit 1
    fi
    adb root 2>/dev/null || true
    sleep 1

    # Try /proc/Module.symvers first, then generate from modules
    adb shell "cat /proc/Module.symvers 2>/dev/null || cat /proc/kallsyms 2>/dev/null | head -5" > /tmp/device_symvers_raw.txt
    LINES=$(wc -l < /tmp/device_symvers_raw.txt)
    echo "  Got $LINES symbol entries"

    if [ "$LINES" -lt 10 ]; then
        echo "  /proc/Module.symvers not available, generating from loaded modules..."
        # Extract CRCs from loaded modules on device
        adb shell "for m in /vendor/lib/modules/*.ko /system_dlkm/lib/modules/*.ko; do \
            modinfo -F vermagic \$m 2>/dev/null; done" | head -1 > /tmp/device_vermagic.txt
        echo "  Device vermagic: $(cat /tmp/device_vermagic.txt)"
    fi

    echo "  Copying to H1..."
    scp /tmp/device_symvers_raw.txt $H1:/tmp/device_symvers.txt
fi

# Step 2: Build on H1
if [ "$MODE" = "full" ] || [ "$MODE" = "--build" ]; then
    echo ""
    echo "=== Step 2: Build dw3000.ko with testmode on H1 ==="
    ssh $H1 "cd $BUILD_DIR/drivers/net/ieee802154 && \
        make -C $KERNEL_DIR \
        ARCH=arm64 \
        CROSS_COMPILE=aarch64-linux-gnu- \
        M=$BUILD_DIR/drivers/net/ieee802154 \
        KBUILD_EXTRA_SYMBOLS='/tmp/device_symvers.txt /tmp/all_symvers.txt' \
        CONFIG_MCPS802154_TESTMODE=y \
        KBUILD_MODPOST_WARN=1 \
        KCFLAGS='-I$BUILD_DIR/include -I/tmp/dw3000-src/mac/include' \
        -j8 2>&1" | tee /tmp/build_log.txt

    # Check result
    if ssh $H1 "test -f $BUILD_DIR/drivers/net/ieee802154/dw3000.ko"; then
        echo "  BUILD SUCCESS"
        ssh $H1 "ls -la $BUILD_DIR/drivers/net/ieee802154/dw3000.ko"

        # Verify testmode is included
        TESTMODE_SYMS=$(ssh $H1 "strings $BUILD_DIR/drivers/net/ieee802154/dw3000.ko | grep -c dw3000_tm_cmd")
        echo "  Testmode symbols: $TESTMODE_SYMS"

        echo "  Pulling .ko to laptop..."
        scp $H1:$BUILD_DIR/drivers/net/ieee802154/dw3000.ko build/dw3000_testmode.ko
        echo "  Saved: build/dw3000_testmode.ko"
    else
        echo "  BUILD FAILED (check /tmp/build_log.txt)"
        echo "  Common fix: need device Module.symvers for proper symbol resolution"
        exit 1
    fi
fi

# Step 3: Deploy to device
if [ "$MODE" = "full" ] || [ "$MODE" = "--deploy" ]; then
    echo ""
    echo "=== Step 3: Deploy testmode-enabled dw3000.ko ==="

    if [ ! -f build/dw3000_testmode.ko ]; then
        echo "ERROR: build/dw3000_testmode.ko not found"
        exit 1
    fi

    if ! adb devices | grep -q "device$"; then
        echo "ERROR: No device connected"
        exit 1
    fi

    adb root 2>/dev/null || true
    sleep 1

    echo "  Pushing module..."
    adb push build/dw3000_testmode.ko $DEVICE_DIR/

    echo "  Hot-swapping..."
    adb shell setenforce 0
    adb shell stop vendor.uwb_hal 2>/dev/null || true
    sleep 1

    for mod in mcps802154_region_pctt mcps802154_region_nfcc_coex mcps802154_region_fira dw3000; do
        adb shell rmmod $mod 2>/dev/null && echo "    Removed $mod"
    done

    adb shell insmod $DEVICE_DIR/dw3000_testmode.ko && echo "    Loaded dw3000 (testmode)" || {
        echo "    FAILED: CRC/vermagic mismatch. Need exact kernel match."
        echo "    Falling back to vendor module..."
        adb shell insmod /vendor/lib/modules/dw3000.ko
    }

    for mod in mcps802154_region_fira mcps802154_region_nfcc_coex mcps802154_region_pctt; do
        adb shell insmod /vendor/lib/modules/${mod}.ko 2>/dev/null
    done

    adb shell start vendor.uwb_hal
    sleep 2
    adb shell cmd uwb enable 2>/dev/null
    adb shell "mount -t debugfs none /sys/kernel/debug 2>/dev/null"

    echo ""
    echo "=== Testmode commands available ==="
    echo "  $DEVICE_DIR/pctt_inject --rx-diag    # start continuous promiscuous RX"
    echo "  $DEVICE_DIR/pctt_inject --cw         # start CW tone"
    echo "  $DEVICE_DIR/pctt_inject --stop       # stop"
fi
