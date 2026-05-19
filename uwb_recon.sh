#!/system/bin/sh
# uwb_recon.sh -- UWB reconnaissance script for Pixel 7 Pro
#
# Session 1, Experiment E002: Quick on-device enumeration without compilation.
# Run directly on device: adb shell su -c sh /data/local/tmp/uwb_recon.sh
#
# No writes, read-only. Safe to run.

echo "=== UWB Reconnaissance -- Pixel 7 Pro ==="
echo "Date: $(date)"
echo ""

echo "--- Kernel modules ---"
lsmod 2>/dev/null | grep -iE "dw3000|mcps|uwb|aoc_uwb" || \
    cat /proc/modules | grep -iE "dw3000|mcps|uwb|aoc_uwb"
echo ""

echo "--- SPI devices ---"
ls -la /sys/bus/spi/devices/ 2>/dev/null
for dev in /sys/bus/spi/devices/*/; do
    [ -f "$dev/modalias" ] && echo "  $dev -> $(cat $dev/modalias)"
    [ -L "$dev/driver" ] && echo "  driver -> $(readlink -f $dev/driver)"
done
echo ""

echo "--- Debugfs DW3000 ---"
if [ -d /sys/kernel/debug/dw3000 ]; then
    echo "FOUND: /sys/kernel/debug/dw3000"
    ls -la /sys/kernel/debug/dw3000/
    for subdir in /sys/kernel/debug/dw3000/*/; do
        [ -d "$subdir" ] || continue
        echo ""
        echo "  Device: $subdir"
        ls -la "$subdir" 2>/dev/null | head -30
        # Read CIR config
        if [ -f "${subdir}cir_config" ]; then
            echo "  CIR config: $(cat ${subdir}cir_config)"
        fi
        # Read power state
        if [ -f "${subdir}power" ]; then
            echo "  Power state: $(cat ${subdir}power)"
        fi
        # Count register files
        regcount=$(ls "${subdir}" 2>/dev/null | grep -c '^0x')
        echo "  Register files: $regcount"
        # Try chip ID
        if [ -f "${subdir}0x0" ]; then
            echo "  Chip ID (reg 0x0): $(cat ${subdir}0x0 2>/dev/null)"
        fi
    done
else
    echo "NOT FOUND: /sys/kernel/debug/dw3000"
    echo "Searching broader..."
    find /sys/kernel/debug -maxdepth 4 \( -name '*dw3*' -o -name '*uwb*' -o -name '*mcps*' \) 2>/dev/null
fi
echo ""

echo "--- IEEE 802.15.4 interfaces ---"
ls -la /sys/class/ieee802154/ 2>/dev/null
echo ""

echo "--- WPAN network interfaces ---"
ip link show 2>/dev/null | grep -A2 -iE 'wpan|uwb'
echo ""

echo "--- Android UWB service ---"
ps -A 2>/dev/null | grep -iE 'uwb'
echo ""

echo "--- dmesg: UWB/DW3000 (last 40) ---"
dmesg 2>/dev/null | grep -iE 'dw3000|uwb|qorvo|802\.15\.4|mcps' | tail -40
echo ""

echo "--- dmesg: SPI probe ---"
dmesg 2>/dev/null | grep -iE 'spi.*probe\|spi.*dw\|spi.*qorvo' | tail -10
echo ""

echo "--- SELinux mode ---"
getenforce 2>/dev/null
echo ""

echo "=== RECON COMPLETE ==="
