#!/system/bin/sh
# uwb_testmode_capture.sh -- Testmode continuous RX with energy sensing
#
# Uses DW3000 testmode (CMD_TESTMODE via mcps802154 netlink) for:
#   1. START_RX_DIAG: continuous promiscuous RX
#   2. Periodic GET_RX_DIAG: read accumulated RSSI/CIR power
#   3. Register-based energy sensing between diagnostics
#
# Testmode IS compiled in the vendor dw3000.ko (confirmed via binary
# analysis on H1). No kernel rebuild needed.
#
# IMPORTANT: must stop HAL before testmode (avoids scheduler conflict)
#
# Usage:
#   adb shell nohup /data/local/tmp/uwb_testmode_capture.sh [duration_s] &
#   Default: 60 seconds of continuous RX

DURATION=${1:-60}
OUT=/data/local/tmp/testmode_capture
DEVICE_DIR=/data/local/tmp

mkdir -p "$OUT"
echo $$ > "$OUT/pid.txt"
exec > "$OUT/log.txt" 2>&1

status() {
    echo "$(date '+%H:%M:%S') $1"
    echo "$(date '+%H:%M:%S') $1" > "$OUT/status.txt"
}

status "STARTING: testmode RX for ${DURATION}s"

# Step 1: Prepare chip
status "SETUP: permissive mode"
setenforce 0

# Step 2: Stop HAL to release scheduler
status "SETUP: stopping HAL"
stop vendor.uwb_hal 2>/dev/null
sleep 1

# Ensure debugfs is mounted
mount -t debugfs none /sys/kernel/debug 2>/dev/null

# Find chip debugfs
CHIP_DIR=$(ls -d /sys/kernel/debug/dw3000/spi* 2>/dev/null | head -1)
if [ -z "$CHIP_DIR" ]; then
    status "FAILED: no debugfs (modules may need reload)"
    # Try reloading modules
    for mod in mcps802154_region_pctt mcps802154_region_nfcc_coex mcps802154_region_fira dw3000; do
        rmmod $mod 2>/dev/null
    done
    insmod /vendor/lib/modules/dw3000.ko 2>/dev/null
    for mod in mcps802154_region_fira mcps802154_region_nfcc_coex mcps802154_region_pctt; do
        insmod /vendor/lib/modules/${mod}.ko 2>/dev/null
    done
    sleep 1
    CHIP_DIR=$(ls -d /sys/kernel/debug/dw3000/spi* 2>/dev/null | head -1)
fi

if [ -z "$CHIP_DIR" ]; then
    status "FAILED: still no debugfs"
    exit 1
fi
status "CHIP: $CHIP_DIR"

# Step 3: Start testmode RX
status "TESTMODE: starting RX diagnostics"
if [ -x "$DEVICE_DIR/pctt_inject" ]; then
    $DEVICE_DIR/pctt_inject --rx-diag > "$OUT/testmode_start.txt" 2>&1
    START_RESULT=$?
    cat "$OUT/testmode_start.txt"
    if [ $START_RESULT -ne 0 ]; then
        status "TESTMODE: start failed (result=$START_RESULT)"
        # Try starting HAL briefly to power up chip, then stop and retry
        status "RETRY: start HAL, wait, stop, retry"
        start vendor.uwb_hal
        sleep 3
        cmd uwb enable 2>/dev/null
        sleep 2
        stop vendor.uwb_hal
        sleep 1
        $DEVICE_DIR/pctt_inject --rx-diag > "$OUT/testmode_start_retry.txt" 2>&1
        cat "$OUT/testmode_start_retry.txt"
    fi
else
    status "ERROR: pctt_inject not found at $DEVICE_DIR/pctt_inject"
    exit 1
fi

# Step 4: Continuous energy sensing via register reads
status "SENSING: reading diagnostic registers for ${DURATION}s"
INTERVAL_US=500000  # 500ms
END_TIME=$(($(date +%s) + DURATION))

# CSV header
echo "sample,timestamp,ip_diag0,ip_diag1,ip_diag2,ip_diag8,cia_diag0,dgc_cfg,adc_dbg,sys_status" > "$OUT/energy.csv"

SAMPLE=0
while [ $(date +%s) -lt $END_TIME ]; do
    TS=$(date +%s%N 2>/dev/null || date +%s)

    D0=$(cat "$CHIP_DIR/0xc0028" 2>/dev/null || echo "ERR")
    D1=$(cat "$CHIP_DIR/0xc002c" 2>/dev/null || echo "ERR")
    D2=$(cat "$CHIP_DIR/0xc0030" 2>/dev/null || echo "ERR")
    D8=$(cat "$CHIP_DIR/0xc0048" 2>/dev/null || echo "ERR")
    CIA=$(cat "$CHIP_DIR/0xc0020" 2>/dev/null || echo "ERR")
    DGC=$(cat "$CHIP_DIR/0x30018" 2>/dev/null || echo "ERR")
    ADC=$(cat "$CHIP_DIR/0x3004c" 2>/dev/null || echo "ERR")
    SS=$(cat "$CHIP_DIR/0x44" 2>/dev/null || echo "ERR")

    echo "$SAMPLE,$TS,$D0,$D1,$D2,$D8,$CIA,$DGC,$ADC,$SS" >> "$OUT/energy.csv"

    if [ $((SAMPLE % 10)) -eq 0 ]; then
        status "SENSING: sample $SAMPLE, sys_status=$SS"
    fi

    SAMPLE=$((SAMPLE + 1))
    usleep $INTERVAL_US 2>/dev/null || sleep 0
done

# Step 5: Get RX diagnostic results
status "RESULTS: getting RX diagnostics"
if [ -x "$DEVICE_DIR/pctt_inject" ]; then
    $DEVICE_DIR/pctt_inject --rx-diag --stop > "$OUT/testmode_results.txt" 2>&1
    # Also get results before stopping
    $DEVICE_DIR/pctt_inject --testmode > "$OUT/testmode_get.txt" 2>&1
fi

# Step 6: Restart HAL
status "CLEANUP: restarting HAL"
start vendor.uwb_hal

# Metadata
cat > "$OUT/metadata.txt" <<METADATA
date: $(date)
duration_s: $DURATION
samples: $SAMPLE
mode: testmode_rx_diag
chip_dir: $CHIP_DIR
METADATA

status "DONE: $SAMPLE energy samples in $OUT/"
echo "Pull: adb pull $OUT/ data/cir_captures/testmode/"
echo "Analyze: python3 tools/analyze_energy.py data/cir_captures/testmode/energy.csv"
