#!/system/bin/sh
# dw3000_explore_regs.sh -- Explore DW3000 register space for loopback/test capabilities
#
# Reads key DW3000 registers to understand chip state and find test mode controls.
# Must be run on-device after mounting debugfs and loading dw3000.ko.
#
# DW3000 register map (from public Decawave documentation):
#   0x00:     DEV_ID (chip ID, should read deca0314 or deca0324)
#   0x04:     EUI64 (extended unique identifier)
#   0x10:     SYS_CFG (system configuration, PDOA, CIA controls)
#   0x1C:     SYS_TIME (system time counter)
#   0x24:     TX_FCTRL (TX frame control)
#   0x44:     SYS_STATUS (system event status register)
#   0x4C:     RX_FINFO (RX frame info)
#   0x64:     RX_TIME (RX timestamp)
#   0x70000:  PMSC_CTRL0 (power management, clock control)
#   0x70004:  PMSC_CTRL1
#   0x70036:  CLK_CTRL (clock enables, ACC_MEM_CLK_ON at bit 15)
#   0xC0000:  CIA_CONF (CIA configuration)
#   0xC0004:  CIA_CTRL (CIA control)
#   0x150000: ACC_MEM (accumulator memory base)
#
# Key registers for test/loopback investigation:
#   0x30:     TX_ANTD (TX antenna delay)
#   0x34:     SYS_STATE (system state machine)
#   0x36:     ACK_RESP_T (ACK response time, controls TX-to-RX delay!)
#   0x70000:  PMSC_CTRL0 (power/clock control, may have test enables)
#   0x70010:  PMSC_TXFINESEQ (TX fine sequence control)
#   0x70020:  PMSC_RXFINESEQ (RX fine sequence control)
#
# Usage:
#   adb push tools/dw3000_explore_regs.sh /data/local/tmp/
#   adb shell chmod +x /data/local/tmp/dw3000_explore_regs.sh
#   adb shell /data/local/tmp/dw3000_explore_regs.sh

DEBUGFS=/sys/kernel/debug/dw3000

# Find the SPI device subdirectory
CHIP_DIR=""
for d in $DEBUGFS/spi*; do
    if [ -d "$d" ]; then
        CHIP_DIR="$d"
        break
    fi
done

if [ -z "$CHIP_DIR" ]; then
    echo "ERROR: No DW3000 debugfs directory found"
    echo "Try: mount -t debugfs none /sys/kernel/debug"
    exit 1
fi

echo "=== DW3000 Register Explorer ==="
echo "Chip directory: $CHIP_DIR"
echo ""

# Read a register file
read_reg() {
    local name=$1
    local addr=$2
    local desc=$3
    local val=$(cat "$CHIP_DIR/$addr" 2>/dev/null)
    if [ -n "$val" ]; then
        printf "  %-15s [%-8s] = %-20s  %s\n" "$name" "$addr" "$val" "$desc"
    else
        printf "  %-15s [%-8s] = ERROR                %s\n" "$name" "$addr" "$desc"
    fi
}

echo "--- Core Identification ---"
read_reg "DEV_ID" "0x0" "Chip ID (expect deca0314/deca0324)"
read_reg "EUI" "0x4" "Extended unique ID"

echo ""
echo "--- System Configuration ---"
read_reg "SYS_CFG" "0x10" "System config (PDOA, CIA, PHR mode)"
read_reg "SYS_STATE" "0x34" "System state machine"
read_reg "SYS_STATUS" "0x44" "Event status (CIA_DONE, RX events)"
read_reg "SYS_TIME" "0x1c" "System time counter"

echo ""
echo "--- TX Configuration ---"
read_reg "TX_FCTRL" "0x24" "TX frame control"
read_reg "TX_ANTD" "0x30" "TX antenna delay"
read_reg "ACK_RESP_T" "0x36" "ACK response time (TX-to-RX delay!)"

echo ""
echo "--- RX Configuration ---"
read_reg "RX_FINFO" "0x4c" "RX frame info"
read_reg "RX_TIME" "0x64" "RX timestamp"

echo ""
echo "--- Clock and Power Management ---"
read_reg "CLK_CTRL" "0x70036" "Clock control (ACC_MEM_CLK_ON bit 15)"
read_reg "PMSC_CTRL0" "0x70000" "Power management ctrl 0"
read_reg "PMSC_CTRL1" "0x70004" "Power management ctrl 1"

echo ""
echo "--- CIA (Channel Impulse Analyzer) ---"
read_reg "CIA_CONF" "0xc0000" "CIA configuration"
read_reg "CIA_DIAG0" "0xc0020" "CIA diagnostic 0"
read_reg "CIA_PDOA" "0xc001c" "CIA PDoA + first path"

echo ""
echo "--- Test and Calibration ---"
read_reg "OTP_CTRL" "0x90000" "OTP control"
read_reg "OTP_STAT" "0x90004" "OTP status"

echo ""
echo "--- Searching for Test Mode Registers ---"
echo "Checking if debugfs register files are writable..."
# Try writing to a safe register (read-only status register)
echo "test" > "$CHIP_DIR/0x44" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  WARNING: Register files appear WRITABLE"
    echo "  This opens the path to register-level control"
else
    echo "  Register files are READ-ONLY via debugfs"
fi

echo ""
echo "--- Full Register Directory ---"
echo "Listing all available register files:"
ls "$CHIP_DIR/" | head -50

echo ""
echo "--- Register Count ---"
TOTAL=$(ls "$CHIP_DIR/" | wc -l)
echo "Total register files: $TOTAL"

echo ""
echo "--- CIR Data Check ---"
if [ -f "$CHIP_DIR/cir_data" ]; then
    echo "  cir_data file exists"
    ls -la "$CHIP_DIR/cir_data"
fi
if [ -f "$CHIP_DIR/cir_config" ]; then
    echo "  cir_config file exists"
    cat "$CHIP_DIR/cir_config" 2>/dev/null
fi

echo ""
echo "=== Done ==="
echo ""
echo "Key findings to look for:"
echo "  1. Is ACK_RESP_T configurable? (controls TX-to-RX delay)"
echo "  2. Are register files writable? (enables register-level control)"
echo "  3. What test/calibration registers exist?"
echo "  4. Can CLK_CTRL enable accumulator clock independently?"
