# pixel-uwb-rangefinder

Low-level tools for using the Qorvo DW3000 Ultra-Wideband transceiver on a rooted Pixel 7 Pro as a precision radio rangefinder.

**Goal: extract raw Channel Impulse Response (CIR) data and achieve sub-centimeter ranging precision from a phone's UWB chip.**

The Pixel 7 Pro's UWB module is a Qorvo (formerly Decawave) DW3000, used by Android for digital car keys, Nearby Share, and spatial awareness. These tools bypass the Android UWB HAL, talk directly to the kernel driver via reverse-engineered netlink/ioctl interfaces, and extract raw radio-domain measurements that Android never exposes.

**No app, no HAL, no UI.** Pure kernel interfaces + raw RF impulse data.

## Results

| Metric              | Stock  | This project                                             |
| ------------------- | ------ | -------------------------------------------------------- |
| Raw CIR access      | No     | **Yes** (16.7fps streaming via 5-patch binary dw3000.ko) |
| CIR bins per frame  | 0      | **64** (expandable to 1016 via cir_config)               |
| Noise floor         | N/A    | **Characterized** (Rayleigh, sigma=0.264, white)         |
| Multipath profiling | No     | **Ready** (CIRProcessor with leading-edge detection)     |
| Ranging precision   | ~10 cm | Pending (needs second UWB device for signal)             |
| Angle of Arrival    | No     | PDoA extraction ready, needs signal                      |
| Experiments         | 0      | **25** (E001-E025, 4 sessions)                           |

## Background: why UWB is the RF analog of ToF laser

| Property           | VL53L1 (laser ToF)                                  | DW3000 (UWB radio)                          |
| ------------------ | --------------------------------------------------- | ------------------------------------------- |
| Medium             | 940nm VCSEL photons                                 | 6.5/8 GHz RF pulses                         |
| Raw data           | 24-bin photon histogram                             | ~1000-sample CIR (Channel Impulse Response) |
| Time resolution    | ~250 ps/bin                                         | ~1 ns (500 MHz bandwidth)                   |
| Range              | 0--5 m                                              | 0--50+ m                                    |
| Multipath          | Histogram tail analysis                             | CIR multipath peaks                         |
| Precision (stock)  | 11 mm                                               | ~100 mm                                     |
| Precision (target) | 2.3 um (achieved)                                   | < 10 mm                                     |
| Key insight        | Histogram bins encode distance + surface properties | CIR encodes distance + environment geometry |

The CIR is literally the radio equivalent of the ToF photon histogram: a time-domain profile showing when reflected energy arrives. Each peak in the CIR corresponds to a propagation path. The first path = direct line-of-sight distance. Later peaks = reflections off walls, furniture, people.

## Hardware

| Component       | Detail                                                         |
| --------------- | -------------------------------------------------------------- |
| UWB chip        | Qorvo DW3000                                                   |
| Protocol        | IEEE 802.15.4z (HRP UWB)                                       |
| Frequency       | Channel 5 (6489.6 MHz) and Channel 9 (7987.2 MHz)              |
| Bandwidth       | 499.2 MHz                                                      |
| Kernel driver   | `dw3000.ko` (SPI, open-source in AOSP)                         |
| MAC layer       | `mcps802154.ko` (IEEE 802.15.4 MAC)                            |
| FiRa stack      | `mcps802154_region_fira.ko` (FiRa Consortium ranging protocol) |
| PCTT stack      | `mcps802154_region_pctt.ko` (PHY Compliance Test Tool)         |
| AOC integration | `aoc_uwb_platform_drv.ko`, `aoc_uwb_service_dev.ko`            |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system design, data flow, and file organization.

## Quickstart

```bash
# Prerequisites: rooted Pixel 7 Pro (Magisk), patched dw3000.ko, cross-compiled cir_stream

# 1. Push tools to device
adb root
adb push cir_stream tools/uwb_autonomous.sh tools/dw3000_regwrite.sh /data/local/tmp/
adb shell chmod +x /data/local/tmp/uwb_autonomous.sh /data/local/tmp/cir_stream

# 2. Run autonomous capture (500 frames, 200ms interval, 256 CIR bins)
adb shell nohup /data/local/tmp/uwb_autonomous.sh 500 200 0 256 &

# 3. Disconnect ADB, screen off, walk away. Check status later:
adb shell cat /data/local/tmp/uwb_capture/status.txt

# 4. Pull and analyze
adb pull /data/local/tmp/uwb_capture/ data/cir_captures/latest/
./tools/analyze_capture.sh data/cir_captures/latest/
```

See [NEXT_SESSION.md](NEXT_SESSION.md) for detailed setup and [ARCHITECTURE.md](ARCHITECTURE.md) for system design.

## Kernel driver source

The DW3000 driver and full MAC/FiRa stack are open-source in AOSP:

- **Driver:** [kernel/google-modules/uwb/qorvo/dw3000](https://android.googlesource.com/kernel/google-modules/uwb/qorvo/dw3000/)
- **Branch:** `android-gs-pantah-5.10-android14-qpr3`
- **Structure:**
  - `kernel/drivers/` -- DW3000 SPI driver, register access, CIR readback
  - `mac/` -- Full IEEE 802.15.4z MAC with FiRa ranging, scheduling, crypto
  - `mac/fira_access.c` -- FiRa ranging session control
  - `mac/fira_frame.c` -- Frame construction/parsing
  - `mac/fira_sts.c` -- Scrambled Timestamp Sequence (security)

## Reverse engineering strategy

Based on the methodology proven in [pixel-tof-rangefinder](../pixel-tof-rangefinder) (220+ experiments, 9 sessions):

### Session 1: Reconnaissance (next)

1. **Enumerate device nodes:** Find `/dev/` entries, sysfs interfaces, netlink families for the UWB subsystem
2. **Map ioctl/netlink surface:** What commands does the driver accept? Which are compiled out on the Pixel build?
3. **Identify power-on sequence:** How does Android initialize the DW3000? SPI bus, GPIO reset, firmware loading
4. **Check AOC involvement:** The AOC has `aoc_uwb_platform_drv.ko` -- is UWB routed through the sensor hub or directly via SPI?
5. **Read kernel source:** The DW3000 driver is open-source. Map the register access functions, CIR readback paths, diagnostic registers
6. **Probe without Android:** Can we talk to the DW3000 directly without the Android UWB service running?

### Session 2: First ranging measurement

7. **Build a probe tool:** Minimal C program that opens the netlink/SPI interface and triggers a single ranging exchange
8. **Two-device ranging:** UWB needs a responder. Options: second phone, UWB dev kit, or self-ranging via loopback/reflection
9. **Extract CIR:** Read the DW3000's CIR accumulator registers after a successful ranging exchange
10. **Baseline measurement:** Stock precision at known distances (1m, 2m, 5m, 10m)

### Session 3: Raw data and signal processing

11. **CIR analysis:** Implement leading-edge detection, peak extraction, multipath identification
12. **Clock drift compensation:** DW3000 uses crystal oscillator -- characterize and compensate
13. **Noise floor characterization:** Allan deviation analysis on ranging data (same method as ToF)
14. **First path power estimation:** Use CIR shape to estimate NLOS (non-line-of-sight) conditions

### Session 4+: Advanced applications

15. **Through-wall detection:** CIR multipath analysis to detect objects behind walls
16. **Material characterization:** Different materials produce different CIR signatures (like ToF surface fingerprints)
17. **Angle of Arrival:** If the DW3000 supports PDoA (Phase Difference of Arrival), extract angular measurements
18. **Indoor positioning:** Combine multiple ranging measurements for 2D/3D positioning

## Key technical questions to answer

1. **Is CIR data accessible on this firmware?** The DW3000 has CIR accumulator registers, but Google may have disabled readback.
2. **Can we range without Android UWB service?** Or is the SPI bus locked by the HAL?
3. **Does the AOC mediate UWB access?** The `aoc_uwb_*` modules suggest the AOC may be in the path.
4. **What's the register map?** The DW3000 User Manual (publicly available from Qorvo) documents the full register set, including CIR memory at offset 0x15:00.
5. **STS (Scrambled Timestamp Sequence) -- can we bypass it?** FiRa ranging uses STS for security. For self-ranging experiments, we need to either configure matching STS keys or use non-STS modes.

## References

- [Qorvo DW3000 product page](https://www.qorvo.com/products/p/DW3000) -- datasheet, user manual
- [IEEE 802.15.4z-2020](https://standards.ieee.org/standard/802_15_4z-2020.html) -- HRP UWB PHY amendment
- [FiRa Consortium](https://www.firaconsortium.org/) -- UWB ranging interoperability specs
- [AOSP DW3000 kernel driver](https://android.googlesource.com/kernel/google-modules/uwb/qorvo/dw3000/) -- full source
- [pixel-tof-rangefinder](../pixel-tof-rangefinder) -- sister project, methodology reference
