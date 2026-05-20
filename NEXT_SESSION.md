# Next Session Guide

## Current State (2026-05-20, session 5)

**Stable trampoline during active ranging.** v7a module (trampoline_only with
acc_clken only) survives 12+ seconds of FiRa ranging without crash. CIR data
extraction blocked by spinlock/SPI sleep incompatibility and vendor integrity check.

### What's Working

- Kernel patch: `gki_is_module_unprotected_symbol` always returns true (boot_a)
- Module swap: `rmmod dw3000` + `insmod` works after HAL kill
- v7a trampoline: stable during active ranging (no cir_config written)
- cir_config write: works with trampoline_only layout (0xf9402288 at 0x215c0)
- FiRa ranging via `cmd uwb` at 5Hz
- Diagnostic notifications with RSSI via logcat

### What's Blocked

- CIR data read: all SPI functions sleep (mutex_lock, spi_sync), can't call
  from spinlock-held RXPTO context
- With cir_config written: acc_clken crashes (mutex contention during ranging)
- Vendor integrity check: only ONE specific trampoline layout passes; any
  other RXPTO handler modifications cause cir_config to spin at 100% CPU

### Module Swap After Reboot

```bash
ssh h1 "adb shell 'su -c \"
setprop ctl.stop vendor.uwb_hal
sleep 1
kill -9 \$(pidof android.hardware.qorvo.uwb.service)
sleep 1
rmmod dw3000_core_tests
rmmod dw3000
insmod /data/local/tmp/dw3000_cir_v7a.ko
mount -t debugfs debugfs /sys/kernel/debug
setprop ctl.start vendor.uwb_hal
sleep 2
\"'"
```

### Recovery

```bash
ssh h1 "fastboot flash boot_a ~/boot_a_original_backup.img && fastboot reboot"
```

### Modules on Device (/data/local/tmp/)

| File                    | Description                      | Status                 |
| ----------------------- | -------------------------------- | ---------------------- |
| dw3000_vendor.ko        | Unpatched vendor module          | Reference              |
| dw3000_cir_v7a.ko       | trampoline_only + acc_clken only | STABLE (no cir_config) |
| dw3000_cir_v8c.ko       | spinlock removal attempt         | Fails integrity check  |
| dw3000_tramp_only.ko    | Full trampoline, dw+64 check     | cir_config works       |
| dw3000_cir_stream_v3.ko | Session 3/4 patched module       | Legacy, zero I/Q       |

## Highest-Value Paths Forward

### 1. Second UWB Device (ZERO RISK, INSTANT RESULTS)

With a responder, UCI diagnostics provide CIR/RSSI/AoA through the standard
Android stack. No kernel modification needed. Any UWB phone works (iPhone 11+,
Samsung S21+ UWB, Pixel 6/7/8/9 Pro).

### 2. Find Exact LineageOS Kernel Source

Need source matching `6.1.145-android14-11-gec45f20f38ea-ab15260282`.
Would allow building a module with correct ABI, bypassing all binary patching.
Check LineageOS build manifests for the exact kernel commit.

### 3. Exploit Trampoline Timing

The trampoline_only layout passes the integrity check and acc_clken works when
mutex is uncontested. Potential approach:

- Trampoline enables acc clock (fast mutex trylock succeeds)
- Userspace poller reads CIR data immediately after RXPTO via debugfs
- Requires tight timing coordination
