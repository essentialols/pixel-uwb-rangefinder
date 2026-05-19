# Requirements: UWB Precision Ranging on Pixel 7 Pro DW3000

## Hard Constraints (non-negotiable)

1. **Hardware: Pixel 7 Pro only.** No external sensors, no custom boards, no eval kits, no additional hardware of any kind. The phone we have is the phone we use.

2. **Budget: $0.** No purchases. Software-only solutions.

3. **Sensor: Qorvo DW3000 UWB transceiver on this phone.** This is the only UWB radio available. We work with what's on the device.

4. **Goal: Extract raw Channel Impulse Response (CIR) data and achieve sub-centimeter ranging precision.** Stock Android UWB gives ~10cm precision. We want raw CIR access for multipath analysis, environment characterization, and precision improvement.

5. **Interface: ADB over USB or network to the rooted Pixel 7 Pro (h1).** All tools run on the phone via `adb shell` or are cross-compiled and pushed.

## What We Have

- Rooted Pixel 7 Pro (LineageOS, Magisk, SELinux permissive)
- DW3000 UWB transceiver (Channel 5: 6.5 GHz, Channel 9: 8 GHz)
- Full kernel source for DW3000 driver, MAC layer, and FiRa stack (AOSP)
- SPI bus access (kernel driver uses SPI, not I2C like the ToF sensor)
- Proven methodology from ToF project (220+ experiments, 2.3um precision achieved)

## What Has Been Proven (from ToF project, transferable)

- Direct kernel-driver access bypassing HAL/framework produces dramatically better results
- Allan deviation analysis correctly identifies noise types and integration limits
- BPF/kprobe techniques can extract data from kernel memory without modifying drivers
- Experiment-driven methodology with numbered trials and CSV capture works

## What Counts as Success

- Raw CIR readback from the DW3000 with identifiable multipath peaks
- Demonstrated ranging precision improvement over stock Android UWB
- Empirically validated results (not theoretical or simulated)

## What Does NOT Count

- Buying new hardware (second UWB device for ranging is the one exception we may need to address creatively)
- Theoretical bandwidth claims without measured validation
- Android API-level access (we want kernel-direct or lower)

## Open Question: Ranging Partner

UWB two-way ranging requires a responder device. Options to explore:

- Android UWB APIs on a second device (if available)
- DW3000 self-test / loopback modes documented in the Qorvo user manual
- PCTT (PHY Compliance Test Tool) mode for single-device RF characterization
- Reflection-based ranging (if the chip supports it)
