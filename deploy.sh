#!/bin/bash
# deploy.sh -- Push all compiled tools and scripts to device
#
# Usage: ./deploy.sh

set -e

if ! adb devices | grep -q "device$"; then
    echo "ERROR: No adb device connected"
    exit 1
fi

adb root 2>/dev/null || true
sleep 1

DEST=/data/local/tmp

echo "=== Deploying UWB tools ==="

# Binaries
for bin in build/*; do
    name=$(basename $bin)
    echo "  $name"
    adb push "$bin" "$DEST/$name" >/dev/null
    adb shell chmod +x "$DEST/$name"
done

# Shell scripts
for sh in tools/uwb_autonomous.sh tools/uwb_testmode_capture.sh tools/uwb_energy_sense.sh tools/dw3000_regwrite.sh tools/dw3000_explore_regs.sh tools/dw3000_binary_search.sh tools/reflector_experiment.sh; do
    name=$(basename $sh)
    echo "  $name"
    adb push "$sh" "$DEST/$name" >/dev/null
    adb shell chmod +x "$DEST/$name"
done

echo ""
echo ""
echo "=== Deployed. Quick start ==="
echo ""
echo "  Option 1: Testmode continuous RX (RECOMMENDED, no second device)"
echo "    adb shell nohup $DEST/uwb_testmode_capture.sh 60 &"
echo "    adb pull $DEST/testmode_capture/ data/cir_captures/testmode/"
echo "    python3 tools/analyze_energy.py data/cir_captures/testmode/energy.csv"
echo ""
echo "  Option 2: FiRa CIR streaming (256 bins)"
echo "    adb shell nohup $DEST/uwb_autonomous.sh 500 200 0 256 &"
echo "    adb pull $DEST/uwb_capture/ data/cir_captures/latest/"
echo "    ./tools/analyze_capture.sh data/cir_captures/latest/"
