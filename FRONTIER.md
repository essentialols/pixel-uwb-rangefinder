# Frontier Analysis -- What's Real, What's Not, What's Next

**Updated:** 2026-05-19, session 3 (cmd uwb discovery + diagnostic capture pipeline)

## Major discoveries this session

### 1. `cmd uwb` shell interface (NEW)

The Android UWB shell (`adb shell cmd uwb`) provides full control:

- `enable-uwb` / `disable-uwb` -- toggle UWB subsystem
- `start-fira-ranging-session` -- start FiRa ranging with full parameter control
- `enable-diagnostics-notification -r -a -c -s` -- enable RSSI, AoA, CIR, segment metrics
- `start-radar-session` -- radar mode (status_code=4, not supported on this chip)
- `get-specification-info` -- chip capabilities (diagnostics=true, rssi_reporting=true)

This bypasses the need for custom netlink tools (`pctt_inject`, `uwb_testmode`).
FiRa sessions start reliably at 5Hz with diagnostics enabled (`flags=39`).

### 2. Diagnostic notification flow confirmed

UCI diagnostic packets flow through the full stack:

```
DW3000 chip -> kernel driver -> UCI netlink -> Qorvo HAL -> Android UWB Service -> logcat
```

Each ranging round produces:

- 3 FrameReports (control, STS, data) with antenna_set=4
- RSSI in data frame (0 without responder, real values with one)
- CIR arrays present but empty (vendor module doesn't populate them)
- raw_ntf_data with 56-byte UCI notification payload

### 3. Vendor module testmode confirmed compiled in

Binary analysis of vendor dw3000.ko proved `dw3000_tm_cmd` is a global symbol.
`pctt_inject` testmode START_RX_DIAG returns error=0 (success). But:

- Getting results returns error=95 (Not supported)
- Chip doesn't stay powered after testmode command
- No CIR data through testmode path with vendor module

### 4. All modules built from source (session 1)

Successfully cross-compiled the entire UWB module chain from AOSP source
against the running LineageOS 6.1 kernel on H1:

```
ieee802154.ko, mac802154.ko, mcps802154.ko,
mcps802154_region_fira.ko, mcps802154_region_nfcc_coex.ko,
mcps802154_region_pctt.ko, dw3000.ko (3 patches for 5.10->6.1)
```

## Hard blockers

### MODULE_SIG_PROTECT

Both vendor-signed and custom-built modules are blocked by MODULE_SIG_PROTECT
on GKI 6.1. This enforcement:

- Applies to ALL non-init contexts (shell, magisk, service processes)
- Blocks both insmod AND rmmod from userspace
- Returns EPERM with no kernel log
- Only modules loaded by init during early boot pass

### Magisk module overlay doesn't help

Created Magisk module `uwb-dw3000-patched` at `/data/adb/modules/uwb-dw3000-patched/`.
But vendor_dlkm modules are loaded by init BEFORE Magisk's Magic Mount overlay runs.
Verified: existing pctt overlay shows different checksums (overlay inactive).

### dm-verity on vendor_dlkm

vendor_dlkm is on dm-5 (ext4, read-only). `mount -o remount,rw` fails.
fstab specifies `avb=vbmeta`. Bootloader is unlocked (verifiedbootstate=orange)
but dm-verity is still enforced for this partition.

### Debugfs register reads return zeros

With vendor module, all debugfs register files (rx_diag, tx_pwr, channel, etc.)
return 0x0. The `registers` file returns 0 bytes. `cir_data` is empty.
The vendor module's debugfs is stub implementations with no live SPI reads.

## What works now

| Capability               | Method                                         | Notes                                     |
| ------------------------ | ---------------------------------------------- | ----------------------------------------- |
| FiRa ranging at 5Hz      | `cmd uwb start-fira-ranging-session`           | Chip powers on, ranging rounds execute    |
| Diagnostic notifications | `enable-diagnostics-notification -r -a -c -s`  | flags=39, 3 frames/round                  |
| RSSI capture             | logcat parsing                                 | 0 without responder, real values with one |
| Raw UCI data             | raw_ntf_data in ranging reports                | 56-byte payload per round                 |
| Chip power control       | FiRa session start/stop                        | power=1 during session                    |
| Capture pipeline         | `uwb_diag_capture.sh` + `parse_diag_logcat.py` | 52 reports in 15s test                    |

## Dead ends (confirmed)

1. Module hot-swap from userspace (MODULE_SIG_PROTECT)
2. Magisk module overlay for vendor_dlkm (overlay happens after module load)
3. Vendor_dlkm remount (dm-verity enforced)
4. Direct register reads via debugfs (vendor module returns zeros)
5. `/dev/spi*` userspace SPI access (device nodes don't exist)
6. `/dev/kmem`, `/dev/mem`, `/proc/kcore` (not available on this GKI build)
7. kprobes on dw3000 functions (no functions in available_filter_functions)
8. Radar session mode (status_code=4, not supported)

## Paths forward (revised priority order)

### A. Get a second UWB device (HIGHEST VALUE)

With a responder, the existing `cmd uwb` pipeline would produce:

- Real RSSI values for distance estimation and presence detection
- Actual ranging measurements (distance, AoA)
- Populated diagnostic data (the chip only fills diagnostics on successful RX)
- No kernel modification needed

Any UWB phone works: iPhone 11+, Samsung S21+ UWB, Pixel 6/7/8/9 Pro.

### B. Flash custom boot image with MODULE_SIG_PROTECT=n

- Kernel source available, build env on H1
- Flash custom GKI image to allow our patched module
- Enables full CIR pipeline including binary patches
- Risk: could brick if done wrong

### C. Modify vendor_dlkm partition image offline

- dd out the partition, mount loopback, replace dw3000.ko, flash back
- Bootloader unlocked so flashing should work
- Requires knowing the exact partition device and layout

### D. UCI-level CIR extraction

- The Qorvo HAL sends vendor-specific UCI extensions
- logcat shows `Failed to parse received message: Unknown` after diagnostics
- These may contain CIR data that the Android UWB parser doesn't understand
- Could capture raw UCI bytes via HAL logging or snooping

## Verified facts (on-device)

| Finding                 | Detail                                                |
| ----------------------- | ----------------------------------------------------- |
| DW3000 SPI device       | `spi16.0` on bus `10db0000.spi`                       |
| Device tree node        | `dw3xxx_prod@0` (compatible: `decawave,dw3000`)       |
| Module dependency chain | ieee802154 -> mac802154 -> mcps802154 -> dw3000       |
| Modules loaded at boot  | All UWB modules loaded by init, refcount-protected    |
| Qorvo HAL PID           | 3698 (`android.hardware.qorvo.uwb.service`)           |
| Vendor service PID      | 3059 (`com.qorvo.uwb.vendorservice`)                  |
| Running kernel          | `6.1.145-android14-11-gec45f20f38ea-ab15260282`       |
| UWB chip capabilities   | diagnostics=true, channels=[5,9], aoa_capabilities=31 |
| Max sessions            | 5 concurrent ranging sessions                         |
