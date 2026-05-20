#!/system/bin/sh
# uwb_energy_sense.sh -- Passive RF energy sensing via diagnostic registers
#
# Reads DW3000 diagnostic registers during FiRa RXPTO events to measure
# total received RF energy. Changes in energy indicate environmental
# changes (people, objects) without needing a second UWB device or
# preamble correlation.
#
# Key insight: the correlator accumulates during the 1.85ms RX window
# regardless of preamble detection. The total accumulated energy is
# in the diagnostic registers even on RXPTO (preamble timeout).
#
# Registers of interest:
#   IP_DIAG0-12: correlator diagnostic outputs
#   CIA_DIAG0:   clock offset estimator (COE_PPM)
#   DGC_DBG:     digital gain control debug (received power)
#   ADC_THRESH_DBG: ADC threshold debug (signal level)
#
# Usage:
#   adb shell /data/local/tmp/uwb_energy_sense.sh [n_samples] [interval_ms]
#   Default: 100 samples, 500ms interval

N=${1:-100}
INTERVAL_MS=${2:-500}
INTERVAL_US=$((INTERVAL_MS * 1000))
OUT=/data/local/tmp/energy_sense.csv

# Find chip debugfs
CHIP_DIR=$(ls -d /sys/kernel/debug/dw3000/spi* 2>/dev/null | head -1)
if [ -z "$CHIP_DIR" ]; then
    echo "ERROR: no DW3000 debugfs"
    exit 1
fi

echo "=== UWB Passive Energy Sensing ==="
echo "Chip: $CHIP_DIR"
echo "Samples: $N, Interval: ${INTERVAL_MS}ms"
echo ""

# Header
echo "sample,timestamp,ip_diag0,ip_diag1,ip_diag2,ip_diag8,ip_diag12,cia_diag0,dgc_cfg,adc_dbg,cir_pwr_raw" > "$OUT"

echo "sample  ip_diag0    ip_diag1    ip_diag2    cia_diag0   dgc_cfg     adc_dbg"
echo "------  ----------  ----------  ----------  ----------  ----------  ----------"

i=0
while [ $i -lt $N ]; do
    TS=$(date +%s%N 2>/dev/null || date +%s)

    # Read diagnostic registers
    D0=$(cat "$CHIP_DIR/0xc0028" 2>/dev/null || echo "ERR")
    D1=$(cat "$CHIP_DIR/0xc002c" 2>/dev/null || echo "ERR")
    D2=$(cat "$CHIP_DIR/0xc0030" 2>/dev/null || echo "ERR")
    D8=$(cat "$CHIP_DIR/0xc0048" 2>/dev/null || echo "ERR")
    D12=$(cat "$CHIP_DIR/0xc0058" 2>/dev/null || echo "ERR")
    CIA=$(cat "$CHIP_DIR/0xc0020" 2>/dev/null || echo "ERR")
    DGC=$(cat "$CHIP_DIR/0x30018" 2>/dev/null || echo "ERR")
    ADC=$(cat "$CHIP_DIR/0x3004c" 2>/dev/null || echo "ERR")

    # Also try to get CIR power from the accumulator
    # IP_DIAG2 contains CIR_PWR (bits 16:0) and RXPACC (bits 31:20) on DW3000
    CIR_PWR="$D2"

    printf "%5d   %-10s  %-10s  %-10s  %-10s  %-10s  %-10s\n" \
        $i "$D0" "$D1" "$D2" "$CIA" "$DGC" "$ADC"

    echo "$i,$TS,$D0,$D1,$D2,$D8,$D12,$CIA,$DGC,$ADC,$CIR_PWR" >> "$OUT"

    i=$((i + 1))
    usleep $INTERVAL_US 2>/dev/null || sleep 0
done

echo ""
echo "Saved $N samples to $OUT"
echo "Pull: adb pull $OUT"
echo ""
echo "Analysis: look for systematic changes in register values when"
echo "a person walks near the phone. Even small changes in ip_diag"
echo "values indicate received energy variation."
