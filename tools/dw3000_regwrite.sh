#!/system/bin/sh
# dw3000_regwrite.sh -- Write DW3000 registers via debugfs for test modes
#
# The DW3000 debugfs register files are READ-WRITE (unless DW3000_CHIPREG_RO).
# Write-protected (WP) registers can be written when chip is NOT active.
# Our patch 4 (bypass state check) may also affect the WP check.
#
# This tool writes to specific DW3000 registers to enable:
# - CW (continuous wave) tone transmission
# - Continuous frame transmission
# - Modified TX-to-RX timing
# - Custom receiver configuration
#
# CAUTION: Writing wrong values can crash the chip or kernel module.
# Always read register value first and restore it after experiments.
#
# Usage:
#   adb shell /data/local/tmp/dw3000_regwrite.sh test-write
#   adb shell /data/local/tmp/dw3000_regwrite.sh cw-on
#   adb shell /data/local/tmp/dw3000_regwrite.sh cw-off
#   adb shell /data/local/tmp/dw3000_regwrite.sh read <reg_addr>
#   adb shell /data/local/tmp/dw3000_regwrite.sh write <reg_addr> <value>

DEBUGFS=/sys/kernel/debug/dw3000

# Find chip directory
CHIP_DIR=""
for d in $DEBUGFS/spi*; do
    [ -d "$d" ] && CHIP_DIR="$d" && break
done

if [ -z "$CHIP_DIR" ]; then
    echo "ERROR: No DW3000 debugfs directory"
    exit 1
fi

echo "DW3000 debugfs: $CHIP_DIR"

# Read a register
read_reg() {
    local addr=$1
    cat "$CHIP_DIR/$addr" 2>/dev/null
}

# Write a register (echo value to the file)
write_reg() {
    local addr=$1
    local value=$2
    echo "  Writing $addr = $value"
    echo "$value" > "$CHIP_DIR/$addr" 2>&1
    local ret=$?
    if [ $ret -eq 0 ]; then
        echo "  Write OK. Readback: $(read_reg $addr)"
    else
        echo "  Write FAILED (ret=$ret)"
    fi
    return $ret
}

CMD=${1:-help}

case "$CMD" in
    test-write)
        echo "=== Testing Register Write Capability ==="
        echo ""

        # Test 1: Read SYS_STATUS (should be RO, write should fail)
        echo "Test 1: Read SYS_STATUS (0x44, likely RO)"
        echo "  Current: $(read_reg 0x44)"
        write_reg 0x44 "0x00000000"
        echo ""

        # Test 2: Read SYS_CFG (should be WP, write may work when inactive)
        echo "Test 2: Read SYS_CFG (0x10, WP)"
        SYS_CFG_ORIG=$(read_reg 0x10)
        echo "  Current: $SYS_CFG_ORIG"
        # Try writing the same value back (safe, no actual change)
        write_reg 0x10 "$SYS_CFG_ORIG"
        echo ""

        # Test 3: Read TX_TEST (may be writable for test modes)
        echo "Test 3: Read TX_TEST (0x70028)"
        TX_TEST_ORIG=$(read_reg 0x70028)
        echo "  Current: $TX_TEST_ORIG"
        echo ""

        # Test 4: Read CLK_CTRL
        echo "Test 4: Read CLK_CTRL (0x110004)"
        CLK_CTRL_ORIG=$(read_reg 0x110004)
        echo "  Current: $CLK_CTRL_ORIG"
        echo ""

        # Test 5: Check cir_config (known writable virtual register)
        echo "Test 5: Read/write cir_config"
        CIR_CFG=$(cat "$CHIP_DIR/cir_config" 2>/dev/null)
        echo "  Current: $CIR_CFG"
        # Try increasing CIR record count
        echo "count 128 filter 0x0 offset 0" > "$CHIP_DIR/cir_config" 2>&1
        echo "  After write: $(cat $CHIP_DIR/cir_config 2>/dev/null)"
        echo ""

        echo "=== Summary ==="
        echo "If writes returned 'Write OK' with matching readback,"
        echo "then register writes via debugfs ARE working."
        ;;

    cw-on)
        echo "=== Enable CW Tone ==="
        echo "WARNING: This sends continuous wave on the configured channel."
        echo ""

        # DW3000 CW tone procedure (from Decawave API):
        # 1. Disable RX (write fast command)
        # 2. Set TX_TEST register to enable CW mode
        # 3. Set PMSC/CLK for TX
        # 4. Issue TX_START command

        # Step 1: Read current TX_TEST
        TX_TEST=$(read_reg 0x70028)
        echo "TX_TEST current: $TX_TEST"

        # Step 2: Enable CW mode in TX_TEST
        # DW3000 TX_TEST register bits:
        # Bit 0: TX_ENTEST (enable TX test mode)
        # Bits 3:1: TX_TESTCODE (test code selection, 0 = CW tone)
        # For CW: write 0x01 (TX_ENTEST=1, TESTCODE=0)
        echo "Enabling CW tone (TX_TEST = 0x01)..."
        write_reg 0x70028 "0x01"

        # Step 3: Read back
        echo "TX_TEST after: $(read_reg 0x70028)"
        echo ""
        echo "If write succeeded, CW tone should be active on the configured channel."
        echo "Monitor with: cat $CHIP_DIR/power_stats"
        echo "Stop with: $0 cw-off"
        ;;

    cw-off)
        echo "=== Disable CW Tone ==="
        echo "Clearing TX_TEST..."
        write_reg 0x70028 "0x00"
        echo "TX_TEST after: $(read_reg 0x70028)"
        ;;

    read)
        if [ -z "$2" ]; then
            echo "Usage: $0 read <reg_addr>"
            echo "Example: $0 read 0x70028"
            exit 1
        fi
        echo "Register $2: $(read_reg $2)"
        ;;

    write)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "Usage: $0 write <reg_addr> <value>"
            echo "Example: $0 write 0x70028 0x01"
            exit 1
        fi
        echo "Current: $(read_reg $2)"
        write_reg "$2" "$3"
        ;;

    cir-expand)
        echo "=== Expand CIR Capture Size ==="
        echo "Current cir_config:"
        cat "$CHIP_DIR/cir_config" 2>/dev/null
        echo ""
        echo "Setting count=256..."
        echo "count 256 filter 0x0 offset 0" > "$CHIP_DIR/cir_config" 2>&1
        echo "New cir_config:"
        cat "$CHIP_DIR/cir_config" 2>/dev/null
        ;;

    help|*)
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  test-write    Test if register writes work via debugfs"
        echo "  cw-on         Enable CW tone (continuous wave TX)"
        echo "  cw-off        Disable CW tone"
        echo "  cir-expand    Increase CIR capture to 256 bins"
        echo "  read <addr>   Read a register"
        echo "  write <a> <v> Write a register"
        echo ""
        echo "Key registers:"
        echo "  0x10     SYS_CFG      System configuration"
        echo "  0x36     ACK_RESP_T   TX-to-RX delay control"
        echo "  0x44     SYS_STATUS   System status (RO)"
        echo "  0x70028  TX_TEST      TX test mode control"
        echo "  0x110004 CLK_CTRL     Clock control"
        ;;
esac
