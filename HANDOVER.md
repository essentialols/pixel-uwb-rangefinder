# Pixel UWB Rangefinder -- Session Handover

**Date:** 2026-05-19 (initial setup)
**Project:** `~/Documents/GitHub/pixel-uwb-rangefinder`

## Current status: SESSION 0 -- PRE-RECONNAISSANCE

No on-device experiments yet. Project structure created, strategy defined, kernel source identified.

## What we know (from AOSP source review, not on-device)

### Kernel modules (loaded on Pixel 7 Pro)

```
dw3000.ko                        # Qorvo DW3000 SPI driver
mcps802154.ko                    # IEEE 802.15.4 MAC layer
mcps802154_region_fira.ko        # FiRa ranging protocol
mcps802154_region_nfcc_coex.ko   # NFC coexistence
mcps802154_region_pctt.ko        # PHY Compliance Test Tool
aoc_uwb_platform_drv.ko          # AOC-UWB platform bridge
aoc_uwb_service_dev.ko           # AOC-UWB service device
```

### Driver source location

AOSP: `kernel/google-modules/uwb/qorvo/dw3000/`
Branch: `android-gs-pantah-5.10-android14-qpr3`

### Key source files to study

```
kernel/drivers/         # DW3000 SPI register access, power management
mac/fira_access.c       # FiRa ranging session lifecycle
mac/fira_frame.c        # TWR frame construction/parsing
mac/fira_session.c      # Session state machine
mac/fira_sts.c          # Scrambled Timestamp Sequence (security)
mac/mcps_main.c         # MAC entry point
mac/ops.c               # netlink operations handler
```

### What the ToF project taught us

- **Direct driver access** (bypassing HAL) is the key to raw data. For ToF, this meant lwis ioctls instead of CameraX.
- **The first measurement** is the hardest part. Everything after that is optimization.
- **Register dumps** early. Map the accessible register space before writing any signal processing.
- **Power sequencing matters.** The ToF sensor needed the camera stack to prime regulators before we could take over. UWB may have similar dependencies.
- **Google strips features.** The Pixel ToF kernel had only 5 of 17 ioctls. Expect the UWB driver to be similarly reduced.

## First session plan

1. `adb shell ls -la /dev/ | grep -i uwb` -- find device nodes
2. `adb shell ls -la /sys/class/ | grep -i uwb` -- find sysfs interfaces
3. `adb shell cat /proc/modules | grep -iE "dw3000|mcps|uwb|aoc_uwb"` -- confirm module loading
4. `adb shell dmesg | grep -iE "dw3000|uwb|qorvo"` -- check boot messages
5. Study the DW3000 kernel driver source for ioctl/netlink entry points
6. Build `uwb_probe.c` -- first tool to read chip ID via SPI
