#!/bin/bash
# analyze_capture.sh -- One-command analysis of autonomous CIR capture
#
# Runs the full analysis pipeline on data pulled from the device:
#   1. Decode binary stream to per-frame stats + magnitude CSV
#   2. Baseline analysis (per-bin mean/std/CoV classification)
#   3. Noise characterization (Rayleigh fit, correlation, thresholds)
#   4. Phase analysis (if raw captures available)
#   5. CIRProcessor signal processing
#   6. Differential analysis (if baseline exists)
#   7. Summary report
#
# Usage:
#   # Pull data first:
#   adb pull /data/local/tmp/uwb_capture/ data/cir_captures/latest/
#   # Analyze:
#   ./tools/analyze_capture.sh data/cir_captures/latest/
#   # With baseline comparison:
#   ./tools/analyze_capture.sh data/cir_captures/latest/ --baseline data/cir_captures/baseline_50ms_64bins_mags.csv

set -e

DIR=${1:?Usage: $0 <capture_dir> [--baseline <baseline_mags.csv>]}
BASELINE=""

shift
while [ $# -gt 0 ]; do
    case "$1" in
        --baseline) BASELINE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ ! -f "$DIR/capture.bin" ]; then
    echo "ERROR: $DIR/capture.bin not found"
    echo "Pull data first: adb pull /data/local/tmp/uwb_capture/ $DIR/"
    exit 1
fi

REPORT="$DIR/report.txt"
echo "=== CIR Capture Analysis ===" | tee "$REPORT"
echo "Directory: $DIR" | tee -a "$REPORT"
echo "Date: $(date)" | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Show metadata if available
if [ -f "$DIR/metadata.txt" ]; then
    echo "--- Capture Metadata ---" | tee -a "$REPORT"
    cat "$DIR/metadata.txt" | tee -a "$REPORT"
    echo "" | tee -a "$REPORT"
fi

# Step 1: Decode binary stream
echo "--- Step 1: Decoding binary stream ---" | tee -a "$REPORT"
python3 tools/cir_stream_decode.py "$DIR/capture.bin" \
    --csv "$DIR/stats.csv" \
    --magnitudes "$DIR/magnitudes.csv" 2>&1 | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Step 2: Baseline analysis
echo "--- Step 2: Per-bin analysis ---" | tee -a "$REPORT"
python3 tools/analyze_baseline.py "$DIR/magnitudes.csv" \
    --output "$DIR/bin_analysis.csv" 2>&1 | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Step 3: Noise characterization
echo "--- Step 3: Noise characterization ---" | tee -a "$REPORT"
python3 tools/cir_noise_characterize.py "$DIR/magnitudes.csv" 2>&1 | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Step 4: Incoherent averaging
echo "--- Step 4: Averaged profile ---" | tee -a "$REPORT"
python3 tools/cir_average.py "$DIR/magnitudes.csv" \
    --output "$DIR/averaged.csv" 2>&1 | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Step 5: CIRProcessor
echo "--- Step 5: CIRProcessor per-frame ---" | tee -a "$REPORT"
python3 tools/process_baseline.py \
    --magnitudes "$DIR/magnitudes.csv" \
    --stats "$DIR/stats.csv" 2>&1 | head -40 | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Step 6: Differential analysis (if baseline provided)
if [ -n "$BASELINE" ] && [ -f "$BASELINE" ]; then
    echo "--- Step 6: Differential analysis vs baseline ---" | tee -a "$REPORT"
    python3 tools/cir_diff.py \
        --baseline "$BASELINE" \
        --test "$DIR/magnitudes.csv" \
        --output "$DIR/diff.csv" 2>&1 | tee -a "$REPORT"
    echo "" | tee -a "$REPORT"
else
    echo "--- Step 6: Skipped (no baseline provided) ---" | tee -a "$REPORT"
    echo "  Use --baseline <path> for differential analysis" | tee -a "$REPORT"
    echo "" | tee -a "$REPORT"
fi

# Step 7: Summary
echo "--- Summary ---" | tee -a "$REPORT"
FRAME_COUNT=$(wc -l < "$DIR/stats.csv" 2>/dev/null)
FRAME_COUNT=$((FRAME_COUNT - 1))
BIN_COUNT=$(head -1 "$DIR/magnitudes.csv" 2>/dev/null | tr ',' '\n' | wc -l)
BIN_COUNT=$((BIN_COUNT - 1))
CAPTURE_SIZE=$(wc -c < "$DIR/capture.bin" 2>/dev/null)

echo "  Frames: $FRAME_COUNT" | tee -a "$REPORT"
echo "  Bins per frame: $BIN_COUNT" | tee -a "$REPORT"
echo "  Capture size: $CAPTURE_SIZE bytes" | tee -a "$REPORT"
echo "" | tee -a "$REPORT"

# Check for signal detection
if [ -f "$DIR/bin_analysis.csv" ]; then
    ELEVATED=$(grep -c "elevated" "$DIR/bin_analysis.csv" 2>/dev/null || echo 0)
    echo "  Elevated bins: $ELEVATED" | tee -a "$REPORT"
fi

echo "" | tee -a "$REPORT"
echo "Output files:" | tee -a "$REPORT"
ls -la "$DIR/"*.csv "$DIR/"*.txt 2>/dev/null | tee -a "$REPORT"
echo "" | tee -a "$REPORT"
echo "Full report saved to: $REPORT"
