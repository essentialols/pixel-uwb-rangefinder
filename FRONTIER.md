# Frontier Analysis -- What's Real, What's Not, What's Next

**Date:** 2026-05-19, session 0 (pre-reconnaissance)

## Verified facts (from AOSP source, not on-device)

- DW3000 driver is open-source in AOSP google-modules
- Full FiRa + PCTT MAC stack is open-source
- AOC has UWB bridge modules (aoc_uwb_platform_drv, aoc_uwb_service_dev)
- Kernel modules are loaded at boot (in pantah-kernel prebuilts)
- DW3000 uses SPI bus (not I2C like VL53L1)
- DW3000 datasheet documents CIR accumulator at register 0x15:00 (publicly available)

## Unknown (must verify on-device)

- Whether CIR register readback is accessible or locked by firmware
- Whether Android UWB service holds exclusive access to the SPI bus
- Whether AOC mediates all UWB communication or if direct SPI access is possible
- Which netlink families are registered and which commands are accepted
- Whether PCTT mode can be used for single-device RF measurements
- DW3000 firmware version loaded by Pixel (may differ from reference)
- Whether Google stripped netlink commands (like they stripped ToF ioctls)

## Dead ends (nothing yet)

(No experiments run yet)

## Next leads (ranked by feasibility)

1. **Device node enumeration** -- 5 min, zero risk, first thing to try
2. **dmesg UWB messages** -- reveals power-on sequence, firmware load, errors
3. **netlink family discovery** -- `NLCTRL` can list registered families without side effects
4. **PCTT mode** -- single-device PHY test mode may allow CIR capture without a ranging partner
5. **DW3000 chip ID read** -- SPI register 0x00:00, confirms hardware is alive and accessible
6. **CIR accumulator read** -- SPI register 0x15:00, the prize. May need an active ranging session.
