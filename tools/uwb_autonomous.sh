#!/system/bin/sh
# uwb_autonomous.sh -- Autonomous CIR capture (runs unattended, screen off)
#
# Push once, start once, disconnect ADB, come back later for data.
# Everything runs in the background with no interactive prompts.
#
# Setup (from laptop, one time):
#   adb root
#   adb push tools/uwb_autonomous.sh /data/local/tmp/
#   adb push cir_stream /data/local/tmp/
#   adb push tools/dw3000_regwrite.sh /data/local/tmp/
#   adb shell chmod +x /data/local/tmp/uwb_autonomous.sh
#   adb shell chmod +x /data/local/tmp/cir_stream
#   adb shell chmod +x /data/local/tmp/dw3000_regwrite.sh
#
# Start (from laptop):
#   adb shell nohup /data/local/tmp/uwb_autonomous.sh &
#   # safe to disconnect ADB now
#
# Check status (reconnect ADB later):
#   adb shell cat /data/local/tmp/uwb_capture/status.txt
#
# Pull data (when done):
#   adb pull /data/local/tmp/uwb_capture/ ./data/cir_captures/autonomous/
#
# Stop early:
#   adb shell kill $(adb shell cat /data/local/tmp/uwb_capture/pid.txt)

# --- Configuration ---
N_FRAMES=${1:-500}          # total frames to capture (0 = infinite)
FIRA_INTERVAL=${2:-200}     # FiRa ranging interval in ms
CW_MODE=${3:-0}             # 1 = enable CW tone before capture
OUT=/data/local/tmp/uwb_capture
DEVICE_DIR=/data/local/tmp
SESSION_ID=$((RANDOM % 9000 + 1000))
DEST_ADDR=$((RANDOM % 9000 + 1000))

# --- Setup output directory ---
mkdir -p "$OUT"
echo $$ > "$OUT/pid.txt"
exec > "$OUT/log.txt" 2>&1

status() {
    echo "$(date '+%H:%M:%S') $1"
    echo "$(date '+%H:%M:%S') $1" > "$OUT/status.txt"
}

status "STARTING: $N_FRAMES frames, interval=${FIRA_INTERVAL}ms, cw=$CW_MODE"

# --- Step 1: Module hot-swap ---
status "HOTSWAP: setting permissive"
setenforce 0

status "HOTSWAP: stopping HAL"
stop vendor.uwb_hal 2>/dev/null
sleep 1

status "HOTSWAP: removing modules"
for mod in mcps802154_region_pctt mcps802154_region_nfcc_coex mcps802154_region_fira dw3000; do
    rmmod $mod 2>/dev/null && echo "  removed $mod"
done

status "HOTSWAP: loading patched modules"
if [ -f "$DEVICE_DIR/dw3000_patched.ko" ]; then
    insmod "$DEVICE_DIR/dw3000_patched.ko" || { status "FAILED: insmod dw3000"; exit 1; }
else
    insmod /vendor/lib/modules/dw3000.ko 2>/dev/null
fi

for mod in mcps802154_region_fira mcps802154_region_nfcc_coex mcps802154_region_pctt; do
    insmod /vendor/lib/modules/${mod}.ko 2>/dev/null
done

# --- Step 2: Start HAL and UWB ---
status "HAL: starting"
start vendor.uwb_hal
sleep 3

cmd uwb enable 2>/dev/null
sleep 1

mount -t debugfs none /sys/kernel/debug 2>/dev/null

# Verify CIR path exists
if [ ! -f /sys/kernel/debug/dw3000/*/cir_data ] && [ ! -d /sys/kernel/debug/dw3000 ]; then
    status "FAILED: no debugfs cir_data"
    exit 1
fi

# --- Step 3: Optional CW tone ---
if [ "$CW_MODE" = "1" ]; then
    status "CW: enabling continuous wave tone"
    $DEVICE_DIR/dw3000_regwrite.sh cw-on >> "$OUT/log.txt" 2>&1
    sleep 1
fi

# --- Step 4: Expand CIR if possible ---
status "CIR: expanding capture size"
CHIP_DIR=$(ls -d /sys/kernel/debug/dw3000/spi* 2>/dev/null | head -1)
if [ -n "$CHIP_DIR" ] && [ -f "$CHIP_DIR/cir_config" ]; then
    echo "count 128 filter 0x0 offset 0" > "$CHIP_DIR/cir_config" 2>/dev/null
    echo "cir_config: $(cat $CHIP_DIR/cir_config 2>/dev/null)"
fi

# --- Step 5: Start FiRa session ---
status "FIRA: starting session $SESSION_ID"
cmd uwb enable-diagnostics-notification -c -r -a 2>/dev/null

cmd uwb start-fira-ranging-session -b -i $SESSION_ID -c 9 -t controller \
    -r initiator -a 0x1234 -d 0x$DEST_ADDR -u ss-twr -l $FIRA_INTERVAL -R enabled &
FIRA_PID=$!
echo $FIRA_PID > "$OUT/fira_pid.txt"
sleep 2

# --- Step 6: Capture CIR data ---
status "CAPTURE: starting $N_FRAMES frames"
$DEVICE_DIR/cir_stream $N_FRAMES > "$OUT/capture.bin" 2>"$OUT/capture_log.txt"
CAPTURE_SIZE=$(wc -c < "$OUT/capture.bin" 2>/dev/null)

status "CAPTURE: done, $CAPTURE_SIZE bytes"

# --- Step 7: Cleanup ---
kill $FIRA_PID 2>/dev/null
cmd uwb stop-fira-ranging-session -i $SESSION_ID 2>/dev/null

if [ "$CW_MODE" = "1" ]; then
    status "CW: disabling"
    $DEVICE_DIR/dw3000_regwrite.sh cw-off >> "$OUT/log.txt" 2>&1
fi

# --- Step 8: Save metadata ---
cat > "$OUT/metadata.txt" <<METADATA
date: $(date)
frames: $N_FRAMES
fira_interval: $FIRA_INTERVAL
cw_mode: $CW_MODE
session_id: $SESSION_ID
capture_bytes: $CAPTURE_SIZE
kernel: $(uname -r)
METADATA

status "DONE: $CAPTURE_SIZE bytes in $OUT/capture.bin"
echo "Pull with: adb pull $OUT/ ./data/cir_captures/autonomous/"
