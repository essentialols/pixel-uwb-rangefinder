#!/system/bin/sh
# Try to send raw 802.15.4 frame and capture resulting DW3000 activity
echo > /sys/kernel/debug/tracing/trace
echo 1 > /sys/kernel/debug/tracing/events/dw3000/enable
echo 1 > /sys/kernel/debug/tracing/tracing_on

# Bring up wpan0
ip link set wpan0 up 2>/dev/null
sleep 1

# Send a few bytes to the broadcast address
# This may fail but will trigger DW3000 TX activity
echo -ne '\x01\x02\x03\x04\x05' | socat - UDP6:[ff02::1%wpan0]:1234 2>/dev/null
# Or use raw socket approach
echo "hello" > /dev/wpan0 2>/dev/null

sleep 2
echo 0 > /sys/kernel/debug/tracing/tracing_on
echo "=== TRACE ==="
cat /sys/kernel/debug/tracing/trace | grep dw3000 | head -40
echo "=== CIR ==="
cat /sys/kernel/debug/dw3000/cir_config 2>/dev/null
echo "=== POWER ==="
cat /sys/kernel/debug/dw3000/power 2>/dev/null
