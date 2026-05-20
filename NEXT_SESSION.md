# Next Session Guide

## Current State (2026-05-20, session 4)

**MODULE_SIG_PROTECT BYPASSED.** Patched kernel running on boot_a.
Patched dw3000_cir_stream_v3.ko loads and produces CIR data.
Full pipeline: cmd uwb session + debugfs CIR + cir_stream capture.

### What's Working

- Kernel patch: `gki_is_module_unprotected_symbol` always returns true
- `rmmod dw3000` and `insmod dw3000_cir_stream_v3.ko` both succeed
- CIR: 1600-byte frames (256 bins x 6-byte I/Q + 48-byte header)
- cir_stream: 3208 bytes captured in single window
- FiRa ranging via `cmd uwb` at 5Hz
- Diagnostic notifications with RSSI
- debugfs needs manual mount: `mount -t debugfs none /sys/kernel/debug`

### Important: Module Swap After Reboot

After each reboot, the vendor module is loaded by init. To use the patched module:

```bash
ssh h1 "adb shell 'su -c \"
mount -t debugfs none /sys/kernel/debug
setprop ctl.stop vendor.uwb_hal
sleep 2
rmmod dw3000
insmod /data/local/tmp/dw3000_cir_stream_v3.ko
setprop ctl.start vendor.uwb_hal
sleep 2
cmd uwb enable-uwb
\"'"
```

### Recovery

If boot fails: fastboot mode, then:

```bash
ssh h1 "fastboot flash boot_a ~/boot_a_original_backup.img && fastboot reboot"
```

## Quick Start: CIR Capture

```bash
# 1. Swap module (after reboot)
# [run the module swap commands above]

# 2. Configure CIR
ssh h1 "adb shell 'su -c \"
echo \\\"count 256 filter 0x0 offset 0\\\" > /sys/kernel/debug/dw3000/cir_config
cmd uwb enable-diagnostics-notification -r -a -c -s
cmd uwb start-fira-ranging-session -i 100 -c 9 -t controller -r initiator -a 4660 -d 22136 -u ds-twr -l 200 -s 25 -R enabled &
sleep 3
\"'"

# 3. Stream CIR data
ssh h1 "adb shell 'su -c \"timeout 10 /data/local/tmp/cir_stream\"'" > data/cir_captures/latest.bin

# 4. Decode
python3 tools/cir_stream_decode.py data/cir_captures/latest.bin

# 5. Stop session
ssh h1 "adb shell 'su -c \"cmd uwb stop-all-ranging-sessions\"'"
```

## Next Steps

1. **Automate module swap**: Create Magisk service.sh to auto-swap after boot
2. **Long CIR captures**: Run 60+ second captures for environmental analysis
3. **Analyze noise-floor CIR**: Compare with/without objects near antenna
4. **Second UWB device**: Would unlock real signal CIR with ranging data
