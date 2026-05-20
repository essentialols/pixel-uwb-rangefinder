#!/bin/bash
# uwb_diag_capture.sh - Capture UWB diagnostic data via cmd uwb + logcat
# Runs on the host, captures data from device via H1
# Usage: ./tools/uwb_diag_capture.sh [duration_sec] [output_dir]

DURATION=${1:-60}
OUTPUT_DIR=${2:-data/diag_captures/$(date +%Y%m%d_%H%M%S)}
SESSION_ID=$((RANDOM % 9000 + 1000))
INTERVAL_MS=200

mkdir -p "$OUTPUT_DIR"

echo "=== UWB Diagnostic Capture ==="
echo "Duration: ${DURATION}s, Session: $SESSION_ID, Interval: ${INTERVAL_MS}ms"
echo "Output: $OUTPUT_DIR"

# Enable UWB
ssh h1 "adb shell su -c 'cmd uwb enable-uwb'" 2>/dev/null
sleep 1

# Enable diagnostics (RSSI + AoA + CIR + segment metrics)
ssh h1 "adb shell su -c 'cmd uwb enable-diagnostics-notification -r -a -c -s'" 2>/dev/null

# Clear logcat buffer
ssh h1 "adb logcat -c" 2>/dev/null

# Start FiRa ranging session (non-blocking)
echo "Starting FiRa session $SESSION_ID..."
ssh h1 "adb shell su -c 'cmd uwb start-fira-ranging-session \
    -i $SESSION_ID -c 9 -t controller -r initiator \
    -a 4660 -d 22136 -u ds-twr -l $INTERVAL_MS -s 25 \
    -R enabled'" 2>/dev/null &
SESSION_PID=$!

sleep 2

# Capture logcat for diagnostics and ranging data
echo "Capturing diagnostics for ${DURATION}s..."
timeout "$DURATION" ssh h1 "adb logcat -v time 2>&1" \
    | grep --line-buffered -E 'uwb.*diagnostic|UwbSession|onRangeData|ParsedDiagnostic|RSSI|frame_reports' \
    > "$OUTPUT_DIR/raw_logcat.txt" 2>/dev/null &
LOGCAT_PID=$!

# Also capture ranging reports via blocking session output
timeout "$DURATION" ssh h1 "adb shell su -c 'cmd uwb get-all-ranging-session-reports'" \
    > "$OUTPUT_DIR/ranging_reports.txt" 2>/dev/null &

# Capture debugfs state snapshots every 5 seconds
echo "timestamp,power,cir_config,rx_diag" > "$OUTPUT_DIR/debugfs_snapshots.csv"
END_TIME=$((SECONDS + DURATION))
while [ $SECONDS -lt $END_TIME ]; do
    TS=$(date +%s.%N)
    POWER=$(ssh h1 "adb shell su -c 'cat /sys/kernel/debug/dw3000/power'" 2>/dev/null | tr -d '\r\n')
    CIR_CFG=$(ssh h1 "adb shell su -c 'cat /sys/kernel/debug/dw3000/cir_config'" 2>/dev/null | tr -d '\r\n')
    RX_DIAG=$(ssh h1 "adb shell su -c 'cat /sys/kernel/debug/dw3000/rx_diag'" 2>/dev/null | tr -d '\r\n')
    echo "$TS,$POWER,$CIR_CFG,$RX_DIAG" >> "$OUTPUT_DIR/debugfs_snapshots.csv"
    sleep 5
done

# Stop session
echo "Stopping session..."
ssh h1 "adb shell su -c 'cmd uwb stop-ranging-session $SESSION_ID'" 2>/dev/null
kill $SESSION_PID $LOGCAT_PID 2>/dev/null
wait 2>/dev/null

# Count results
LINES=$(wc -l < "$OUTPUT_DIR/raw_logcat.txt" 2>/dev/null || echo 0)
echo ""
echo "=== Capture Complete ==="
echo "Logcat lines: $LINES"
echo "Output: $OUTPUT_DIR/"
ls -la "$OUTPUT_DIR/"
