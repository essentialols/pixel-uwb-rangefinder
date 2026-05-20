# Frontier Analysis -- What's Real, What's Not, What's Next

**Updated:** 2026-05-20, session 4 (MODULE_SIG_PROTECT bypassed, full CIR pipeline working)

## BREAKTHROUGH: MODULE_SIG_PROTECT bypassed via kernel binary patch

**4-byte kernel patch** disables GKI module signature protection:

- Offset `0x17aee4` in decompressed kernel Image
- Replaced `cset w0, ne` (0x1a9f07e0) with `mov w0, #1` (0x52800020)
- Function `gki_is_module_unprotected_symbol` now always returns true
- PAC (paciasp/autiasp) preserved, only the return value is forced
- Flashed via `fastboot flash boot_a` (slot b unusable due to empty system partitions)
- Boot_a backup at `~/boot_a_original_backup.img` on H1

**Result:** `rmmod dw3000` and `insmod dw3000_cir_stream_v3.ko` both succeed.
Patched module produces 1600-byte CIR frames (256 bins x 6 bytes + 48-byte header)
and 3208 bytes via cir_stream in a single capture window.

**Recovery:** If boot fails, fastboot → `fastboot flash boot_a boot_a_original_backup.img`

## Major discoveries (session 3)

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

| Capability               | Method                                         | Notes                                       |
| ------------------------ | ---------------------------------------------- | ------------------------------------------- |
| FiRa ranging at 5Hz      | `cmd uwb start-fira-ranging-session`           | Chip powers on, ranging rounds execute      |
| Module rmmod/insmod      | v2 kernel patch (MODULE_SIG_PROTECT bypass)    | Vendor binary modules only (ABI must match) |
| CIR frame pipeline       | patched vendor dw3000.ko + cir_stream          | 45 frames at 5Hz, zero I/Q without signal   |
| SPI bus access           | TX_PWR = 0xd3d35fd3 via debugfs                | Proves SPI reads work with patched module   |
| Diagnostic notifications | `enable-diagnostics-notification -r -a -c -s`  | flags=39, 3 frames/round                    |
| RSSI capture             | logcat parsing                                 | 0 without responder, real values with one   |
| Capture pipeline         | `uwb_diag_capture.sh` + `parse_diag_logcat.py` | 52 reports in 15s test                      |

## The frontier: what's just beyond reach

The exact boundary of what we've achieved:

- CIR frame STRUCTURE works (timestamps, counters, 256-bin allocation)
- CIR frame DATA is zero (accumulator not read by driver on RXPTO)
- Root cause pinpointed to ONE ARM64 instruction (TBZ at vendor binary offset 0x253b8)
- Source-built modules crash (ABI mismatch between 6.1.167 build and 6.1.145 device)
- Binary patches exist but the RXPTO+CIA combination crashes

**New patch created and tested (session 4b):**

- RXPTO handler at file offset 0x20ff4-0x210bc (204 bytes)
- read_frame_cir_data at file offset 0x25388 (268 bytes)
- 4-part patch: CIA NOP + x0=dw + x1=stack_info + BL read_frame_cir_data
- v2 (NULL info): kernel panic (null deref on info->flags)
- v3 (SP as info): no crash but mutex deadlock

**Mutex deadlock:** The CIR data flow has a structural deadlock:

1. Debugfs reader holds `cir->mutex` and waits on `cir->complete`
2. RXPTO handler (our patch) calls `read_frame_cir_data` which tries
   `mutex_lock_interruptible(&cir->mutex)` and BLOCKS
3. Neither can proceed: classic producer-consumer deadlock

**The real fix** requires calling the LOW-LEVEL functions directly from the
RXPTO handler, bypassing the mutex/completion mechanism:

1. `dw3000_acc_clken(dw, true)` (enable accumulator clock)
2. `dw3000_read_cir_data(dw, stsMode, prf)` (SPI read of accumulator)
3. `dw3000_acc_clken(dw, false)` (disable clock)
4. `dw3000_complete_cir_data(dw)` (signal completion WITHOUT mutex)

This needs ~8 instructions: too many to fit in the 3-instruction patch slot.
Requires finding dead code space in the module for a trampoline, or
replacing the entire RXPTO epilogue.

**Hardware constraint confirmed:** DW3000 accumulator is only populated during
active RX (while antenna is listening). After RXPTO fires, the chip transitions
to IDLE and the accumulator may be cleared. The driver must read it during or
immediately after the RX window, before the state machine clears it.

## Why CIR is empty even with diagnostics enabled

The diagnostic CIR/RSSI/AoA fields are only populated on **successful packet reception**
(RXFCG event). Without a responder device, the initiator transmits and times out. No
received packets means no CIR data in diagnostics.

The binary-patched module worked differently: it hooked the **RXPTO** (preamble timeout)
interrupt, which fires every ranging round even without a responder. This gave
noise-floor CIR data from the open receive window. The standard UCI diagnostic path
does not read CIR on timeout events.

The Qorvo HAL has full CIR parsing code (`get_cir_window_sample`, `uci_diag_ntf_add_cir`,
`get_cirs_diag`) but never gets data from the kernel because the kernel only reads
CIR accumulator on RXFCG, which requires an actual received signal.

The "Unknown" message (header 1,0,8) in logcat is a vendor core notification,
not CIR data. strace on HAL fails (ptrace blocked by SELinux).

## Dead ends (confirmed)

1. Module hot-swap from userspace (MODULE_SIG_PROTECT blocks both insmod and rmmod)
2. Magisk module overlay for vendor_dlkm (overlay happens after module load)
3. Vendor_dlkm remount (dm-verity enforced, fstab specifies avb=vbmeta)
4. Direct register reads via debugfs (vendor module returns zeros for all registers)
5. `/dev/spi*` userspace SPI access (device nodes don't exist)
6. `/dev/kmem`, `/dev/mem`, `/proc/kcore` (not available on this GKI build)
7. kprobes on dw3000 functions (no functions in available_filter_functions)
8. Radar session mode (status_code=4, not supported by this chip)
9. UCI diagnostic CIR without responder (CIR only populated on successful RX)
10. strace on HAL process (ptrace blocked by SELinux)
11. nlmon netlink monitoring (RTNETLINK operation not permitted)

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

### D. Noise-floor CIR (requires B or C first)

The binary-patched module reads CIR on RXPTO, giving noise-floor data
useful for environmental sensing. This path requires either custom kernel (B)
or partition modification (C) to bypass MODULE_SIG_PROTECT.

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

## Root cause: CIA flag check blocks CIR on RXPTO (session 4 deep analysis)

Source analysis of `dw3000_read_frame_cir_data()` (dw3000_core.c:6801) reveals:

```c
if (!(dw->rx.flags & DW3000_RX_FLAG_CIA)) {
    rc = -ENODATA;
    goto read_frame_cir_error;
}
```

The CIA (Channel Impulse Analysis) algorithm only runs on successful packet reception
(RXFCG). On RXPTO (preamble timeout), the CIA flag is never set, so
`dw3000_read_frame_cir_data` returns -ENODATA and skips the accumulator read entirely.

**This explains why binary patches produce frames with valid headers but zero I/Q:**
the patched RXPTO handler calls `read_frame_cir_data`, but the CIA check immediately
returns without reading the accumulator.

### Fix required

Bypass the CIA check for RXPTO reads by either:

1. NOP the conditional branch in the vendor binary (find TBZ/CBZ for CIA flag)
2. Build from source with CIA check removed (blocked by kernel version mismatch 6.1.167 vs 6.1.145)
3. Also need `dw3000_acc_clken(dw, true)` before the read (accumulator clock must be on)

Source-built module from AOSP (compiled on H1) works but can't load due to
modversions CRC mismatch. Vermagic patching and \_\_versions transplant attempted
but kernel rejects mismatched symbol CRCs. Need exact kernel source match or
a way to disable modversion checking.

### Attempted fixes (session 4)

1. **CIA-bypass-only** (vendor .ko + NOP at 0x253b8): loads but CIR blocks forever
   because RXPTO handler doesn't call read_frame_cir_data.
2. **Combined** (RXPTO patches + CIA bypass): device crash. The 52-byte binary patches
   interact badly with the CIA bypass.
3. **Source-built, vermagic patched**: modversions CRC mismatch rejected.
4. **Source-built + check_version kernel bypass**: vermagic mismatch rejected.
5. **Source-built + correct UTS_RELEASE**: crashes on insmod (struct ABI mismatch
   between AOSP 6.1.167 and device 6.1.145 headers). Kernel panic on probe.
6. **check_version + same_magic kernel bypass**: broke rmmod (same_magic patch has
   side effects on module unloading path).

### Key finding: magiskboot repack non-determinism

Successive `magiskboot repack` runs produce different LZ4-compressed kernel sizes
(16567065, 16567069, 16567070, 16567073). Only the FIRST repack from the original
boot partition reliably produces a bootable image. Subsequent repacks from
already-repacked boot fail to load kernel patches correctly. Always repack from
the original `/tmp/patched_boot_v2.img` (known working).

### Working state (v2 kernel)

Boot partition has single-patch kernel (MODULE_SIG_PROTECT bypass at 0x17aee4).
rmmod/insmod work for same-version vendor binary modules. Source-built modules
crash due to struct ABI mismatch.

### Remaining path to non-zero CIR

**Binary patch of vendor module is the ONLY viable path.** Source-built modules crash
due to kernel version ABI mismatch. The fix needs a NEW binary patch that:

1. Finds the CIA check TBZ (at 0x253b8 in vendor binary) and NOPs it
2. Adds the read_frame_cir_data call to the RXPTO handler WITHOUT using the existing
   52-byte patches (which crash when combined with CIA bypass)
3. The new RXPTO patch must be a minimal trampoline: save regs, call
   read_frame_cir_data, restore regs, return to original RXPTO flow

## Session 5 progress (2026-05-20)

### v5b/v5c crash root cause: TWO bugs found

**Bug 1: Spinlock deadlock.** The trampoline at 0x215b8 redirected from 0x210a0
(inside a `_raw_spin_lock_irqsave` section) and jumped to 0x210ac (epilogue),
SKIPPING `_raw_spin_unlock_irqrestore` at 0x210a8. The permanently-held spinlock
caused hard lockup on next access. Full RXPTO handler flow:

```
0x21090: BL _raw_spin_lock_irqsave   # LOCK
0x21094: LDRB w8, [x21]              # read flag
0x21098: MOV x1, x0                  # save IRQ flags
0x2109c: CBZ w8, 0x210c0             # if flag==0, error path
0x210a0: STRB wzr, [x21]             # clear flag  <-- REDIRECT POINT
0x210a4: MOV x0, x19                 # lock ptr
0x210a8: BL _raw_spin_unlock_irqrestore  # UNLOCK (SKIPPED by v5b!)
0x210ac: LDP... (epilogue)           <-- v5b jumped here, lock still held
```

**Bug 2: Wrong register for dw struct.** The RXPTO handler computes:

- `x20 = x0` (dw struct base, saved at 0x2100c)
- `x19 = x0 + 0x2B08` (rx sub-struct for spinlock, computed at 0x21010)

All v5 patches used x19 for dw struct access. This passed a pointer 0x2B08 bytes
INTO the struct to acc_clken and read_cir_data, causing memory corruption.
Correct register is x20.

### v6b: first stable trampoline with active ranging

Fixed both bugs. Trampoline saves IRQ flags (x1), does CIR work with x20
(correct dw base), restores flags, executes displaced STRB, then branches to
0x210a4 for proper spin_unlock + epilogue. **Survived 12+ seconds of 5Hz
FiRa ranging without crash.**

### v6c: debugfs non-blocking read

Added NOP of `wait_for_completion_interruptible` in `dw3000_dbgfs_cir_data`
(0x292a0) so CIR data reads return immediately instead of blocking on
completion signal. The trampoline doesn't call `complete()` (relocated kernel
symbol, can't be called from patched code).

### Critical discovery: CIA NOP was in wrong function

The TBZ at 0x253b8 (previously thought to be in dw3000_read_frame_cir_data)
is actually in **rx_get_measurement** (file 0x25388, 292 bytes). The actual
dw3000_read_frame_cir_data is at file 0x1e40c (1176 bytes) and has NO CIA
flag check. Our trampoline calls dw3000_read_cir_data directly, bypassing
read_frame_cir_data, so the CIA NOP was never needed.

### Mysterious cir_config sensitivity to dead code bytes

Changing 4 bytes at 0x215c0 (dead code in dw3000_testmode_continuous_tx_start)
from the original 0xa9017bfd to specific values breaks cir_config write:

| Value at 0x215c0 | Encoding              | cir_config |
| ---------------- | --------------------- | ---------- |
| 0xa9017bfd       | STP (original)        | works      |
| 0xf9402288       | LDR x8, [x20, #64]    | works      |
| 0xf9402289       | LDR x9, [x20, #64]    | works      |
| 0xf955ba88       | LDR x8, [x20, #11120] | HANGS      |
| 0xd503201f       | NOP                   | HANGS      |

Root cause unknown. Possibly vendor module integrity check.

### cir_config allocation makes acc_clken crash

With cir_config written, acc_clken crashes during active ranging (hard-lock).
Without cir_config, acc_clken survives 12+ seconds. cir_config allocates a
struct at dw+11120 which may modify state read by acc_clken.

### Session 5 stable configuration

- v7a module: trampoline_only with read_cir_data NOPed (acc_clken only)
- No cir_config written
- Ranging sessions run stably with RXPTO trampoline active

### Next steps

1. Read CIR accumulator directly via SPI from trampoline (bypass read_cir_data)
2. Find dw3000_reg_read function addresses for direct SPI access
3. Or: determine what dw+11120 allocation changes that breaks acc_clken
4. Second UWB device still highest-value path for real CIR data
