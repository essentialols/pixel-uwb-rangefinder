# Session 1 Decision Log

Complete record of every decision, approach, finding, and change.

## Timeline

### Phase 1: Source analysis (before on-device)

- **Decision:** Study DW3000 kernel driver source from AOSP before touching device
- **Rationale:** Understand the interface before writing tools (same as ToF project)
- **Finding:** CIR exposed via debugfs (not netlink), CIR RAM at 0x150000
- **Finding:** AOC only controls reset GPIO -- not a data mediator
- **Finding:** Testmode netlink commands (START_RX_DIAG etc.) available
- **Action:** Built 6 experiment tools targeting these interfaces

### Phase 2: On-device reconnaissance

- **Finding:** DW3000 is on SPI bus `spi16.0` (controller `10db0000.spi`)
- **Finding:** Device tree node: `dw3xxx_prod@0` (compatible: `decawave,dw3000`)
- **Finding:** NO driver bound to the SPI device
- **Finding:** `dw3000.ko` exists in vendor_dlkm but is NOT loaded
- **Finding:** Dependency chain: ieee802154 -> mac802154 -> mcps802154 -> dw3000
- **Finding:** ieee802154 from vendor fails: "exports protected symbol" (wrong vermagic)
- **Finding:** All subsequent modules fail: "unknown symbol" (deps not loaded)
- **Finding:** `dw3000_core_tests.ko` loaded fine (no external deps)

### Phase 3: Module building

- **Decision:** Build all modules from AOSP source against running kernel
- **Rationale:** Vendor modules signed for wrong kernel, need matching vermagic
- **Action:** Cloned GKI kernel (android14-6.1), prepared build env on H1
- **Action:** Built ieee802154.ko + mac802154.ko from kernel tree
- **Action:** Cloned DW3000 AOSP source, applied 3 patches for 5.10->6.1 API
- **Finding:** All 7 modules compile successfully
- **Patches applied:**
  1. `spi->controller->kworker` is pointer in 6.1 (was struct in 5.10)
  2. `spi_driver.remove()` returns void in 6.1 (was int)
  3. `spi->master->last_cs_enable` removed in 6.1

### Phase 4: Module loading attempts

- **Attempt 1:** insmod from adb shell su -> EPERM
- **Attempt 2:** Direct finit_module() syscall -> EPERM
- **Attempt 3:** Magisk post-fs-data.sh -> EPERM (runs as u:r:magisk:s0)
- **Attempt 4:** Same script with our custom-built modules -> EPERM
- **Finding:** MODULE_SIG_PROTECT blocks ALL non-init module loading on GKI 6.1
- **Finding:** Even unsigned modules built for the exact running kernel are blocked
- **Finding:** The check happens before vermagic comparison
- **Decision:** Need kernel-level fix (cannot work around from userspace)

### Phase 5: Relay analysis (multi-LLM consultation)

- **Sources:** Perplexity (GPT-5), Codex (Claude Opus), DeepSeek V3, Groq (Llama 3.3)
- **Key consensus:** vendor_dlkm is dm-verity protected, replacing modules won't work
- **Key insight (Perplexity):** Add `module.sig_enforce=0` to boot cmdline
- **Key insight (Codex):** EPERM may be SELinux + MODULE_SIG_PROTECT combined
- **Key insight (Codex):** Init doesn't bypass crypto signatures either
- **Recommendation:** Patch boot image or rebuild kernel
- **Decision:** Build custom GKI kernel with MODULE_SIG_PROTECT=n (cleanest fix)

### Phase 6: Boot image flash attempt

- **Finding:** Pre-existing `boot_modsig_bypass.img` on H1 (from May 17)
- **Decision:** Flash it to test (already there, quick to try)
- **Result:** Phone did not boot (image was from different session/kernel)
- **Lesson:** Never flash an unverified boot image from a previous session
- **Current state:** Phone needs physical force-reboot + fastboot restore

### Phase 7: Custom kernel build (in progress)

- **Decision:** Build fresh GKI kernel with MODULE_SIG=n, MODULE_SIG_PROTECT=n
- **Also disabled:** CONFIG_DEBUG_INFO_BTF (host tool build failure)
- **Build env:** H1, 16 cores, aarch64-linux-gnu-gcc, libelf-dev
- **Source:** android.googlesource.com/kernel/common android14-6.1 (HEAD = 6.1.167)
- **Note:** Source is 6.1.167 but device runs 6.1.145. GKI is forward-compatible.

## Key files created

| File                   | Purpose                                 |
| ---------------------- | --------------------------------------- |
| `uwb_probe.c`          | Full subsystem enumeration (E001)       |
| `uwb_recon.sh`         | No-compile quick recon (E002)           |
| `uwb_cir_read.c`       | CIR data decoder (E003)                 |
| `uwb_diag.c`           | Diagnostic register reader (E004)       |
| `uwb_regdump.c`        | Register dump with diff mode (E005)     |
| `tools/analyze_cir.py` | CIR analysis and plotting (E006)        |
| `uwb_testmode.c`       | Netlink testmode probe (E007)           |
| `BUILD.md`             | Reproducible build instructions         |
| `RELAY_ANALYSIS.md`    | Multi-LLM bypass strategy analysis      |
| `RECOVERY.md`          | Boot image restore instructions         |
| `deploy_modules.sh`    | Vendor module replacement script        |
| `flash_and_test.sh`    | End-to-end flash + load + test pipeline |
| `pack_boot.py`         | Boot v4 image packer                    |
| `patches/0001-*.patch` | DW3000 5.10->6.1 API patch              |

### Phase 8: Boot image fix (post kernel build)

- **Finding:** Original kernel in boot.img is LZ4 compressed (16.6 MB -> 35.5 MB)
- **Finding:** Our pack_boot.py was packing uncompressed kernel (27.7 MB) -- wrong format!
- **Finding:** AVB vbmeta block exists after kernel at offset 0xfce000 -- must be preserved
- **Finding:** AVB footer at image end with "AVBf" magic -- must be preserved
- **Fix:** LZ4-compress our kernel (27.7 MB -> 13.4 MB), preserve AVB at same offset
- **Decision:** Also build v2 kernel with ieee802154+mac802154 as built-in (=y)
- **Rationale:** Fewer modules to load means fewer failure points

## What's proven vs unproven

### Proven

- DW3000 hardware exists and is on spi16.0
- Full module chain builds from AOSP source
- 3 API patches needed for kernel 5.10->6.1
- MODULE_SIG_PROTECT blocks ALL non-init module loading
- vendor_dlkm is dm-verity protected
- Verified boot is disabled (orange state)
- AOC only does GPIO for UWB (not a data path)

### Unproven (need custom kernel to test)

- Whether our built modules actually load and probe the DW3000
- Whether debugfs CIR interface works
- Whether CIR data contains usable signal
- Whether the DW3000 can be used for ranging without the Qorvo HAL
- The 6.1.167 kernel works with 6.1.145 vendor blobs

### Phase 9: Binary kernel patch (BREAKTHROUGH)
- **Decision:** Patch the running kernel binary instead of building from source
- **Rationale:** Same kernel = guaranteed vendor compatibility, only 16 bytes changed
- **Patch details:**
  - `module_sig_check()` at offset 0x17ace0: MOV W0, WZR; RET
  - `gki_is_module_protected_export()` at offset 0x17ae54: MOV W0, WZR; RET
- **Result:** ALL 7 UWB modules loaded by init at boot

### Phase 10: Accessing the DW3000
- CIR config write WORKS
- wpan0 interface exists and UP
- nl802154 registered, phy0 detected, HAL communicating
- Testmode not compiled in vendor build (ENOTSUP)
- Tracing and kprobes available for data capture
- Next: trigger UWB RX for CIR data

### Phase 11: DW3000 active, CIR capture blocked by short RX window
- DW3000 chip ID: deca0314 (DW3000 E0 variant)
- Full init captured via ftrace: channel 5, preamble_code 9
- RX window only 646us during mcps_start (calibration, not ranging)
- CIR requires actual frame reception with long RX window
- Next: build PCTT PER_RX session via mcps802154 netlink (family ID 34)
