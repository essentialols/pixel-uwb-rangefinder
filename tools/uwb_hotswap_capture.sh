#!/bin/bash
# uwb_hotswap_capture.sh -- End-to-end UWB CIR capture from laptop
#
# Full pipeline:
#   1. Push patched modules and tools to device
#   2. Hot-swap kernel modules (setenforce 0, stop HAL, rmmod chain, insmod patched)
#   3. Start HAL, enable UWB, mount debugfs
#   4. Start FiRa ranging session with diagnostics
#   5. Capture CIR data via cir_stream
#   6. Pull data and run analysis
#
# Prerequisites:
#   - adb root working (Magisk rooted Pixel 7 Pro)
#   - Cross-compiled binaries: cir_stream, cir_reader
#   - Patched dw3000.ko in modules/ directory
#
# Usage:
#   ./tools/uwb_hotswap_capture.sh [n_frames] [fira_interval_ms]
#
# Default: 50 frames, 200ms FiRa interval (~10s capture)

set -e

N_FRAMES=${1:-50}
FIRA_INTERVAL=${2:-200}
SESSION_ID=$((RANDOM % 9000 + 1000))
DEST_ADDR=$((RANDOM % 9000 + 1000))
DEVICE_DIR=/data/local/tmp
OUTPUT_DIR=data/cir_captures/$(date +%Y%m%d_%H%M%S)

echo "=== UWB CIR Capture Pipeline ==="
echo "Frames: $N_FRAMES, FiRa interval: ${FIRA_INTERVAL}ms"
echo "Output: $OUTPUT_DIR"
echo ""

# Step 0: Check adb
if ! adb devices | grep -q "device$"; then
    echo "ERROR: No adb device connected"
    exit 1
fi

# Ensure adb root
adb root 2>/dev/null || true
sleep 1

# Step 1: Push binaries
echo "--- Step 1: Push binaries ---"
for f in cir_stream cir_reader; do
    if [ -f "$f" ]; then
        adb push "$f" "$DEVICE_DIR/" 2>/dev/null
        adb shell chmod +x "$DEVICE_DIR/$f"
        echo "  Pushed $f"
    fi
done

# Push reflector experiment script
adb push tools/reflector_experiment.sh "$DEVICE_DIR/" 2>/dev/null || true
adb shell chmod +x "$DEVICE_DIR/reflector_experiment.sh" 2>/dev/null || true

# Step 2: Hot-swap modules
echo ""
echo "--- Step 2: Hot-swap kernel modules ---"
echo "  Setting permissive mode..."
adb shell setenforce 0

echo "  Stopping UWB HAL..."
adb shell stop vendor.uwb_hal 2>/dev/null || true
sleep 1

echo "  Removing modules (rmmod chain)..."
for mod in mcps802154_region_pctt mcps802154_region_nfcc_coex mcps802154_region_fira dw3000; do
    adb shell rmmod $mod 2>/dev/null && echo "    Removed $mod" || echo "    $mod not loaded (OK)"
done

echo "  Loading patched dw3000.ko..."
if [ -f modules/dw3000_patched.ko ]; then
    adb push modules/dw3000_patched.ko "$DEVICE_DIR/" 2>/dev/null
    adb shell insmod "$DEVICE_DIR/dw3000_patched.ko" && echo "    Loaded dw3000 (patched)" || {
        echo "ERROR: Failed to load patched dw3000.ko"
        exit 1
    }
else
    echo "  WARNING: modules/dw3000_patched.ko not found, using existing module"
    adb shell insmod /vendor/lib/modules/dw3000.ko 2>/dev/null || true
fi

echo "  Loading region modules..."
for mod in mcps802154_region_fira mcps802154_region_nfcc_coex mcps802154_region_pctt; do
    adb shell insmod /vendor/lib/modules/${mod}.ko 2>/dev/null && echo "    Loaded $mod" || true
done

# Step 3: Start HAL and enable UWB
echo ""
echo "--- Step 3: Start HAL, enable UWB ---"
adb shell start vendor.uwb_hal
sleep 2

adb shell cmd uwb enable 2>/dev/null || true
sleep 1

adb shell "mount -t debugfs none /sys/kernel/debug 2>/dev/null" || true

# Verify cir_data exists
if ! adb shell test -f /sys/kernel/debug/dw3000/cir_data; then
    echo "ERROR: debugfs cir_data not found"
    exit 1
fi
echo "  cir_data available"

# Step 4: Start FiRa session with diagnostics
echo ""
echo "--- Step 4: Start FiRa session ---"
adb shell cmd uwb enable-diagnostics-notification -c -r -a 2>/dev/null || true

echo "  Starting FiRa ranging session (session=$SESSION_ID, interval=${FIRA_INTERVAL}ms)..."
adb shell "cmd uwb start-fira-ranging-session -b -i $SESSION_ID -c 9 -t controller \
    -r initiator -a 0x1234 -d 0x$DEST_ADDR -u ss-twr -l $FIRA_INTERVAL -R enabled" &
FIRA_PID=$!
sleep 2

# Step 5: Capture CIR data
echo ""
echo "--- Step 5: Capture CIR ($N_FRAMES frames) ---"
adb shell "$DEVICE_DIR/cir_stream $N_FRAMES > $DEVICE_DIR/capture.bin 2>$DEVICE_DIR/capture_log.txt"
echo "  Capture complete"

# Step 6: Pull data
echo ""
echo "--- Step 6: Pull data ---"
mkdir -p "$OUTPUT_DIR"
adb pull "$DEVICE_DIR/capture.bin" "$OUTPUT_DIR/" 2>/dev/null
adb pull "$DEVICE_DIR/capture_log.txt" "$OUTPUT_DIR/" 2>/dev/null

# Stop FiRa session
kill $FIRA_PID 2>/dev/null || true
adb shell cmd uwb stop-fira-ranging-session -i $SESSION_ID 2>/dev/null || true

# Step 7: Analyze
echo ""
echo "--- Step 7: Analyze ---"
if [ -f "$OUTPUT_DIR/capture.bin" ]; then
    python3 tools/cir_stream_decode.py "$OUTPUT_DIR/capture.bin" \
        --csv "$OUTPUT_DIR/stats.csv" \
        --magnitudes "$OUTPUT_DIR/magnitudes.csv" 2>&1 | tee "$OUTPUT_DIR/analysis.txt"

    echo ""
    echo "  Running baseline analysis..."
    python3 tools/analyze_baseline.py "$OUTPUT_DIR/magnitudes.csv" \
        --output "$OUTPUT_DIR/bin_analysis.csv" 2>&1 | tee -a "$OUTPUT_DIR/analysis.txt"
fi

echo ""
echo "=== Done ==="
echo "Data saved to $OUTPUT_DIR/"
echo ""
echo "For reflector experiment:"
echo "  adb shell $DEVICE_DIR/reflector_experiment.sh $N_FRAMES"
echo "  adb pull $DEVICE_DIR/cir_experiment/ $OUTPUT_DIR/reflector_test/"
