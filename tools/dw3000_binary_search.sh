#!/system/bin/sh
# dw3000_binary_search.sh -- Search dw3000.ko binary for test/loopback symbols
#
# Searches the vendor dw3000.ko for strings and symbols related to:
# - Loopback mode (internal TX-to-RX path)
# - Continuous wave / continuous TX
# - Test mode registers
# - Register write functions
#
# Usage:
#   adb shell /data/local/tmp/dw3000_binary_search.sh

KO=/vendor/lib/modules/dw3000.ko

if [ ! -f "$KO" ]; then
    echo "ERROR: $KO not found"
    exit 1
fi

echo "=== DW3000 Binary Analysis ==="
echo "Module: $KO"
echo "Size: $(wc -c < $KO) bytes"
echo ""

echo "--- Symbol Table (test/loopback related) ---"
# Extract symbol names from .symtab
strings "$KO" | grep -i -E "loop|test|cw_|contin|diag|calib|tx_test|rx_test|debug|force|override" | sort -u | head -40

echo ""
echo "--- All function symbols (dw3000_*) ---"
strings "$KO" | grep "^dw3000_" | sort -u

echo ""
echo "--- Register-related strings ---"
strings "$KO" | grep -i -E "reg_write|reg_read|spi_write|spi_read|write_reg|read_reg" | sort -u | head -20

echo ""
echo "--- Configuration strings ---"
strings "$KO" | grep -i -E "config|mode|enable|disable|ctrl|control" | sort -u | head -30

echo ""
echo "--- debugfs file creation strings ---"
strings "$KO" | grep -i -E "debugfs|cir_|power_|chip_" | sort -u | head -20

echo ""
echo "--- Potential register addresses (hex constants) ---"
# Look for common DW3000 register addresses in strings
strings "$KO" | grep -E "^0x[0-9a-fA-F]{2,6}$" | sort -u | head -30

echo ""
echo "=== Done ==="
