#!/bin/bash
# setup_patched_module.sh - Swap vendor dw3000.ko for patched CIR version
# Run this after each device reboot to enable CIR capture
# Usage: ./tools/setup_patched_module.sh

set -e

echo "=== UWB Patched Module Setup ==="

# Mount debugfs
echo "Mounting debugfs..."
ssh h1 "adb shell 'su -c \"mount -t debugfs none /sys/kernel/debug 2>/dev/null || true\"'"

# Stop UWB HAL
echo "Stopping UWB HAL..."
ssh h1 "adb shell 'su -c \"setprop ctl.stop vendor.uwb_hal\"'"
sleep 2

# Swap module
echo "Removing vendor dw3000..."
ssh h1 "adb shell 'su -c \"rmmod dw3000 2>&1\"'"

echo "Loading patched dw3000_cir_stream_v3..."
ssh h1 "adb shell 'su -c \"insmod /data/local/tmp/dw3000_cir_stream_v3.ko 2>&1\"'"

# Restart HAL
echo "Restarting UWB HAL..."
ssh h1 "adb shell 'su -c \"setprop ctl.start vendor.uwb_hal\"'"
sleep 3

# Enable UWB
echo "Enabling UWB..."
ssh h1 "adb shell 'su -c \"cmd uwb enable-uwb\"'" 2>/dev/null
sleep 1

# Expand CIR to 256 bins
echo "Configuring CIR (256 bins)..."
ssh h1 "adb shell 'su -c \"echo \\\"count 256 filter 0x0 offset 0\\\" > /sys/kernel/debug/dw3000/cir_config\"'"

# Verify
echo ""
echo "=== Verification ==="
MODULE_SIZE=$(ssh h1 "adb shell 'su -c \"lsmod | grep dw3000 | head -1 | awk '{print \$2}'\"'" 2>/dev/null)
POWER=$(ssh h1 "adb shell 'su -c \"cat /sys/kernel/debug/dw3000/power\"'" 2>/dev/null)
CIR_CFG=$(ssh h1 "adb shell 'su -c \"cat /sys/kernel/debug/dw3000/cir_config\"'" 2>/dev/null)

echo "Module loaded: dw3000 (${MODULE_SIZE} bytes in memory)"
echo "Power: ${POWER}"
echo "CIR config: ${CIR_CFG}"
echo ""
echo "Ready for CIR capture. Start a session with:"
echo "  ssh h1 \"adb shell 'su -c \\\"cmd uwb start-fira-ranging-session -b -i 100 ...\\\"'\""
