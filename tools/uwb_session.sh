#!/bin/bash
# uwb_session.sh -- Start UWB ranging session and capture all data
#
# Usage: ./uwb_session.sh [host] [session_type] [duration_secs]
#   host: SSH host (default: h1)
#   session_type: fira-init|fira-resp (default: fira-init)
#   duration_secs: how long to run (default: 10)
#
# Captures:
#   - Ranging reports from cmd uwb
#   - Logcat UWB messages
#   - Power stats before/after
#   - CIR data attempts

HOST="${1:-h1}"
SESSION_TYPE="${2:-fira-init}"
DURATION="${3:-10}"
OUTPUT_DIR="data/captures/$(date +%Y%m%d_%H%M%S)"
SESSION_ID=42

ADB="ssh $HOST adb"
ADB_SU="ssh $HOST \"adb shell su -c\""

mkdir -p "$OUTPUT_DIR"
echo "=== UWB Session Capture ==="
echo "Host: $HOST"
echo "Type: $SESSION_TYPE"
echo "Duration: ${DURATION}s"
echo "Output: $OUTPUT_DIR"

# Pre-session state
echo "--- Pre-session power stats ---" | tee "$OUTPUT_DIR/power_stats.txt"
ssh "$HOST" "adb shell su -c 'cmd uwb get-power-stats'" 2>&1 | tee -a "$OUTPUT_DIR/power_stats.txt"

# Enable diagnostics (CIR + RSSI + AoA)
echo "Enabling diagnostics..."
ssh "$HOST" "adb shell su -c 'cmd uwb enable-diagnostics-notification -c -r -a'" 2>&1

# Start logcat capture in background
echo "Starting logcat capture..."
ssh "$HOST" "adb logcat -c"  # Clear logcat buffer
ssh "$HOST" "adb logcat -v time" > "$OUTPUT_DIR/logcat.txt" 2>&1 &
LOGCAT_PID=$!

# Build ranging command based on session type
case "$SESSION_TYPE" in
    fira-init)
        CMD="cmd uwb start-fira-ranging-session -b -i $SESSION_ID -c 9 -t controller -r initiator -a 1234 -d 5678 -u ss-twr -l 200 -e none -R enabled -o static"
        ;;
    fira-resp)
        CMD="cmd uwb start-fira-ranging-session -b -i $SESSION_ID -c 9 -t controlee -r responder -a 5678 -d 1234 -u ss-twr -l 200 -e none -R enabled -o static"
        ;;
    *)
        echo "Unknown session type: $SESSION_TYPE"
        exit 1
        ;;
esac

echo "Starting ranging session (${DURATION}s)..."
echo "CMD: $CMD"

# Start ranging in background, capture output
ssh "$HOST" "adb shell su -c '$CMD'" > "$OUTPUT_DIR/ranging_output.txt" 2>&1 &
RANGING_PID=$!

# Wait for session to start
sleep 2

# Try CIR read during session
echo "Attempting CIR read..."
ssh "$HOST" "adb shell su -c 'timeout 3 dd if=/sys/kernel/debug/dw3000/cir_data bs=1 count=4096 2>/dev/null'" > "$OUTPUT_DIR/cir_raw.bin" 2>&1 &

# Collect mid-session diagnostics
ssh "$HOST" "adb shell su -c 'cat /sys/kernel/debug/dw3000/power 2>/dev/null'" > "$OUTPUT_DIR/mid_power.txt" 2>&1
ssh "$HOST" "adb shell su -c 'dmesg | grep -i dw3000 | tail -20'" > "$OUTPUT_DIR/mid_dmesg.txt" 2>&1

# Wait for duration
echo "Waiting ${DURATION}s..."
sleep "$DURATION"

# Stop session
echo "Stopping session..."
ssh "$HOST" "adb shell su -c 'cmd uwb stop-ranging-session $SESSION_ID'" 2>&1

# Post-session state
echo "" >> "$OUTPUT_DIR/power_stats.txt"
echo "--- Post-session power stats ---" | tee -a "$OUTPUT_DIR/power_stats.txt"
ssh "$HOST" "adb shell su -c 'cmd uwb get-power-stats'" 2>&1 | tee -a "$OUTPUT_DIR/power_stats.txt"

# Stop logcat
kill $LOGCAT_PID 2>/dev/null
wait $RANGING_PID 2>/dev/null

# Extract relevant logcat entries
grep -iE 'uwb|uci|qorvo|dw3000' "$OUTPUT_DIR/logcat.txt" > "$OUTPUT_DIR/logcat_uwb.txt" 2>/dev/null

# Parse ranging output
REPORT_COUNT=$(grep -c "Ranging Result" "$OUTPUT_DIR/ranging_output.txt" 2>/dev/null || echo 0)
echo ""
echo "=== Session Summary ==="
echo "Ranging reports: $REPORT_COUNT"
echo "CIR raw data size: $(wc -c < "$OUTPUT_DIR/cir_raw.bin" 2>/dev/null || echo 0) bytes"
echo "UWB logcat lines: $(wc -l < "$OUTPUT_DIR/logcat_uwb.txt" 2>/dev/null || echo 0)"

# Run decoder on ranging output if available
if [ -f tools/decode_range_ntf.py ]; then
    echo ""
    echo "--- Decoded range notifications ---"
    python3 tools/decode_range_ntf.py "$OUTPUT_DIR/ranging_output.txt" 2>/dev/null | tail -20
fi

echo ""
echo "Output saved to $OUTPUT_DIR/"
ls -la "$OUTPUT_DIR/"
