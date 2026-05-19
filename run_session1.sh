#!/bin/bash
# run_session1.sh -- Deploy and run all session 1 experiments on Pixel 7 Pro
#
# Run from build host: ./run_session1.sh
# Requires: adb connected to rooted Pixel 7 Pro
#
# This script:
#   1. Builds all tools
#   2. Deploys to device
#   3. Runs E001-E005 sequentially, capturing output
#   4. Pulls results back to data/ directory

set -e
PHONE_DIR=/data/local/tmp
DATA_DIR=data/session1_$(date +%Y%m%d_%H%M%S)

echo "=== pixel-uwb-rangefinder: Session 1 ==="
echo "Date: $(date)"
echo ""

# Check ADB connection
echo "--- Checking ADB connection ---"
if ! adb devices | grep -q "device$"; then
    echo "ERROR: No device connected. Connect Pixel 7 Pro and try again."
    exit 1
fi
echo "Device connected."
echo ""

# Build
echo "--- Building tools ---"
make clean && make
echo ""

# Deploy
echo "--- Deploying to device ---"
make deploy
adb push uwb_testmode $PHONE_DIR/ 2>/dev/null || echo "(uwb_testmode not built yet)"
echo ""

# Ensure SELinux permissive
echo "--- Setting SELinux permissive ---"
adb shell su -c "setenforce 0"
echo ""

# Ensure debugfs mounted
echo "--- Ensuring debugfs is mounted ---"
adb shell su -c "mount -t debugfs none /sys/kernel/debug 2>/dev/null || true"
echo ""

# Create output directory
mkdir -p "$DATA_DIR"
echo "Output directory: $DATA_DIR"
echo ""

# E001: Full probe
echo "=== E001: UWB Subsystem Probe ==="
adb shell su -c $PHONE_DIR/uwb_probe 2>&1 | tee "$DATA_DIR/E001_probe.txt"
echo ""

# E002: Quick recon
echo "=== E002: Quick Recon ==="
adb shell su -c "sh $PHONE_DIR/uwb_recon.sh" 2>&1 | tee "$DATA_DIR/E002_recon.txt"
echo ""

# E004: Diagnostic registers
echo "=== E004: Diagnostic Registers ==="
adb shell su -c $PHONE_DIR/uwb_diag 2>&1 | tee "$DATA_DIR/E004_diag.txt"
echo ""

# E005: Full register dump
echo "=== E005: Register Dump ==="
adb shell su -c "$PHONE_DIR/uwb_regdump" 2>&1 | tee "$DATA_DIR/E005_regdump.csv"
echo ""

# E005b: Register diff (live register detection)
echo "=== E005b: Register Diff (2s gap) ==="
adb shell su -c "$PHONE_DIR/uwb_regdump -d" 2>&1 | tee "$DATA_DIR/E005b_regdiff.csv"
echo ""

# E003: CIR read attempt
echo "=== E003: CIR Read Attempt ==="
echo "(This may block if no active ranging session. Will timeout after 5s.)"
timeout 10 adb shell su -c "timeout 5 $PHONE_DIR/uwb_cir_read -q" 2>&1 | tee "$DATA_DIR/E003_cir.csv" || echo "CIR read timed out (expected if no ranging active)"
echo ""

# E007: Testmode / netlink probe
echo "=== E007: Testmode Netlink Probe ==="
if [ -f uwb_testmode ]; then
    adb shell su -c $PHONE_DIR/uwb_testmode -l 2>&1 | tee "$DATA_DIR/E007_testmode.txt"
else
    echo "(uwb_testmode not built)"
fi
echo ""

echo "=== Session 1 Complete ==="
echo "Results in: $DATA_DIR/"
ls -la "$DATA_DIR/"
echo ""
echo "Next steps:"
echo "  1. Review probe output for debugfs path and device state"
echo "  2. If CIR timed out: check if UWB HAL needs to be stopped"
echo "  3. Try: adb shell su -c 'stop vendor.uwb_hal' then re-run"
echo "  4. Run analyze_cir.py on any CIR data captured"
