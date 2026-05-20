#!/system/bin/sh
# reflector_experiment.sh -- Automated CIR capture with/without reflector
#
# Run on the Pixel 7 Pro via adb shell. Captures CIR data in two phases:
#   Phase 1: baseline (no reflector, environment only)
#   Phase 2: reflector placed at specified distance
#
# Outputs binary capture files for each phase. Analyze with:
#   python3 tools/cir_stream_decode.py baseline.bin --csv baseline_stats.csv --magnitudes baseline_mags.csv
#   python3 tools/cir_stream_decode.py reflector.bin --csv reflector_stats.csv --magnitudes reflector_mags.csv
#   python3 tools/cir_diff.py --baseline baseline_mags.csv --test reflector_mags.csv
#
# Prerequisites:
#   - Patched dw3000.ko loaded (5-patch binary recipe)
#   - cir_stream binary pushed to /data/local/tmp/
#   - FiRa ranging session started
#
# Usage:
#   adb push tools/reflector_experiment.sh /data/local/tmp/
#   adb shell chmod +x /data/local/tmp/reflector_experiment.sh
#   adb shell /data/local/tmp/reflector_experiment.sh [n_frames] [output_dir]

N_FRAMES=${1:-50}
OUT_DIR=${2:-/data/local/tmp/cir_experiment}
CIR_STREAM=/data/local/tmp/cir_stream

mkdir -p "$OUT_DIR"

echo "=== CIR Reflector Experiment ==="
echo "Frames per phase: $N_FRAMES"
echo "Output: $OUT_DIR"
echo ""

# Check prerequisites
if [ ! -x "$CIR_STREAM" ]; then
    echo "ERROR: cir_stream not found at $CIR_STREAM"
    echo "Build and push: adb push cir_stream /data/local/tmp/"
    exit 1
fi

if [ ! -f /sys/kernel/debug/dw3000/cir_data ]; then
    echo "ERROR: debugfs cir_data not found"
    echo "Mount debugfs: mount -t debugfs none /sys/kernel/debug"
    exit 1
fi

# Check if FiRa session is running (power stats show activity)
POWER=$(cat /sys/kernel/debug/dw3000/power_stats 2>/dev/null | head -1)
echo "Power stats: $POWER"

echo ""
echo "=== Phase 1: BASELINE (no reflector) ==="
echo "Remove any metal objects near the phone."
echo "Press Enter when ready..."
read dummy

echo "Capturing $N_FRAMES frames..."
$CIR_STREAM $N_FRAMES > "$OUT_DIR/baseline.bin" 2>"$OUT_DIR/baseline_log.txt"
BASELINE_SIZE=$(wc -c < "$OUT_DIR/baseline.bin")
echo "Baseline captured: $BASELINE_SIZE bytes"
cat "$OUT_DIR/baseline_log.txt"

echo ""
echo "=== Phase 2: REFLECTOR ==="
echo "Place a metal plate/foil/can at the desired distance from the phone."
echo "Keep it perpendicular to the phone's back (UWB antenna is near top)."
echo "Press Enter when ready..."
read dummy

echo "Capturing $N_FRAMES frames..."
$CIR_STREAM $N_FRAMES > "$OUT_DIR/reflector.bin" 2>"$OUT_DIR/reflector_log.txt"
REFLECTOR_SIZE=$(wc -c < "$OUT_DIR/reflector.bin")
echo "Reflector captured: $REFLECTOR_SIZE bytes"
cat "$OUT_DIR/reflector_log.txt"

echo ""
echo "=== Phase 3: CONTROL (reflector removed) ==="
echo "Remove the reflector. Press Enter when ready..."
read dummy

echo "Capturing $N_FRAMES frames..."
$CIR_STREAM $N_FRAMES > "$OUT_DIR/control.bin" 2>"$OUT_DIR/control_log.txt"
CONTROL_SIZE=$(wc -c < "$OUT_DIR/control.bin")
echo "Control captured: $CONTROL_SIZE bytes"
cat "$OUT_DIR/control_log.txt"

echo ""
echo "=== Done ==="
echo "Files saved to $OUT_DIR/"
echo ""
echo "Pull and analyze:"
echo "  adb pull $OUT_DIR/ data/cir_captures/experiment/"
echo "  python3 tools/cir_stream_decode.py data/cir_captures/experiment/baseline.bin \\"
echo "    --csv data/cir_captures/experiment/baseline_stats.csv \\"
echo "    --magnitudes data/cir_captures/experiment/baseline_mags.csv"
echo "  python3 tools/cir_stream_decode.py data/cir_captures/experiment/reflector.bin \\"
echo "    --csv data/cir_captures/experiment/reflector_stats.csv \\"
echo "    --magnitudes data/cir_captures/experiment/reflector_mags.csv"
echo "  python3 tools/cir_diff.py --baseline data/cir_captures/experiment/baseline_mags.csv \\"
echo "    --test data/cir_captures/experiment/reflector_mags.csv"
