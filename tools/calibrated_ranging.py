#!/usr/bin/env python3
"""
calibrated_ranging.py -- Apply DW3000 calibration data to CIR-based ranging

Uses the extracted Pixel 7 Pro calibration (antenna delays, PDoA LUTs)
to correct raw CIR measurements for sub-centimeter accuracy.

Usage:
  from calibrated_ranging import CalibratedRanger
  ranger = CalibratedRanger(channel=9, prf=64, antenna=0)
  distance = ranger.correct_distance(raw_tof_ticks)
  angle = ranger.pdoa_to_angle(pdoa_raw, ant_pair=(1, 2))
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional


# DW3000 physical constants
SPEED_OF_LIGHT = 299792458.0  # m/s
DW3000_TICK_PS = 1e12 / (499.2e6 * 128)  # ~15.6501 ps per DW3000 clock tick
DW3000_TICK_NS = DW3000_TICK_PS / 1000
UWB_BANDWIDTH = 499.2e6  # Hz


# Pixel 7 Pro calibration data (extracted from /vendor/etc/uwb/UWB-calibration.conf)
# Antenna delay in DW3000 ticks
ANTENNA_DELAYS = {
    # (antenna, channel, prf): delay_ticks
    (0, 5, 16): 16447, (0, 5, 64): 16462,
    (0, 9, 16): 16409, (0, 9, 64): 16444,
    (1, 5, 16): 16465, (1, 5, 64): 16465,
    (1, 9, 16): 16414, (1, 9, 64): 16427,
    (2, 5, 16): 16450, (2, 5, 64): 16450,
    (2, 9, 16): 16450, (2, 9, 64): 16450,
    (3, 5, 16): 16450, (3, 5, 64): 16450,
    (3, 9, 16): 16450, (3, 9, 64): 16450,
}

# PDoA offsets (antenna pair → channel → offset)
PDOA_OFFSETS = {
    (1, 2, 5): -2520, (1, 2, 9): 1874,
    (1, 3, 5): -3080, (1, 3, 9): 3214,
}

# PDoA LUT data (decoded from hex)
# Format: list of (pdoa_raw, angle_raw) pairs
# pdoa_raw and angle_raw are signed int16
PDOA_LUTS = {}  # Populated from parse_calibration.py output

# Crystal trim
XTAL_TRIM_VENDOR = 23
XTAL_TRIM_FACTORY = 0x27  # 39

# Antenna hardware config
# antenna → (port, gpio, gpio_value)
ANTENNA_HW = {
    0: (0, 7, 0),
    1: (0, 7, 1),
    2: (1, 6, 0),
    3: (1, 6, 1),
}

# HAL antenna set mapping (from calibration)
# antenna_set value in diagnostics → physical antenna(s)
# antenna_set 3 and 4 alternate in ranging (from empirical observation)
# set 6 used for single-antenna ranging
ANTENNA_SETS = {
    3: [0, 1],  # Port 0 antennas
    4: [2, 3],  # Port 1 antennas
    6: [0],     # Default single antenna
}


@dataclass
class RangingResult:
    """Calibration-corrected ranging result."""
    raw_tof_ticks: float
    antenna_delay_ticks: float
    corrected_tof_ticks: float
    distance_m: float
    distance_mm: float
    antenna: int
    channel: int
    prf: int
    temperature_correction_mm: float = 0.0


@dataclass
class AoAResult:
    """Angle of Arrival result from PDoA."""
    pdoa_raw: float
    pdoa_corrected: float  # After offset correction
    angle_deg: float
    antenna_pair: Tuple[int, int]
    channel: int


class CalibratedRanger:
    """Apply device-specific calibration to UWB ranging measurements."""

    def __init__(self, channel: int = 9, prf: int = 64, antenna: int = 0,
                 temperature_c: float = 25.0):
        self.channel = channel
        self.prf = prf
        self.antenna = antenna
        self.temperature_c = temperature_c

        # Look up antenna delay
        key = (antenna, channel, prf)
        if key in ANTENNA_DELAYS:
            self.ant_delay_ticks = ANTENNA_DELAYS[key]
        else:
            # Fallback to default
            self.ant_delay_ticks = 16450
            print(f"Warning: no calibration for ant{antenna}/ch{channel}/prf{prf}, "
                  f"using default {self.ant_delay_ticks}")

        self.ant_delay_m = self.ant_delay_ticks * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2

    def correct_distance(self, raw_tof_ticks: float,
                        remote_ant_delay_ticks: Optional[float] = None) -> RangingResult:
        """
        Apply antenna delay correction to raw ToF measurement.

        For SS-TWR: distance = (tof_raw - ant_delay_local - ant_delay_remote) * c / 2
        For DS-TWR: antenna delays partially cancel but still need correction.

        Args:
            raw_tof_ticks: Raw time-of-flight in DW3000 ticks
            remote_ant_delay_ticks: Remote device's antenna delay (if known)
        """
        if remote_ant_delay_ticks is None:
            # Assume symmetric setup (same antenna type)
            remote_ant_delay_ticks = self.ant_delay_ticks

        # Subtract both antenna delays (each adds to the measured ToF)
        corrected_tof = raw_tof_ticks - self.ant_delay_ticks - remote_ant_delay_ticks

        # Temperature correction
        # DW3000 crystal drift: ~1.5 ppm/°C from reference temperature
        temp_ref = 85  # From calibration
        temp_diff = self.temperature_c - temp_ref
        # Crystal frequency drift causes proportional range error
        ppm_per_c = 1.5  # Typical for TCXO
        range_correction_ppm = temp_diff * ppm_per_c
        temp_correction_m = corrected_tof * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2 * range_correction_ppm * 1e-6

        # Convert to distance
        distance_m = corrected_tof * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2

        return RangingResult(
            raw_tof_ticks=raw_tof_ticks,
            antenna_delay_ticks=self.ant_delay_ticks,
            corrected_tof_ticks=corrected_tof,
            distance_m=distance_m,
            distance_mm=distance_m * 1000,
            antenna=self.antenna,
            channel=self.channel,
            prf=self.prf,
            temperature_correction_mm=temp_correction_m * 1000,
        )

    def pdoa_to_angle(self, pdoa_raw: float, ant_pair: Tuple[int, int] = (1, 2)) -> AoAResult:
        """
        Convert raw PDoA value to angle using calibration LUT and offset.

        Args:
            pdoa_raw: Raw phase difference of arrival value
            ant_pair: Antenna pair (a, b)
        """
        # Apply offset correction
        key = (ant_pair[0], ant_pair[1], self.channel)
        offset = PDOA_OFFSETS.get(key, 0)
        pdoa_corrected = pdoa_raw - offset

        # LUT interpolation (if available)
        lut_key = f"ant{ant_pair[0]}_ant{ant_pair[1]}_ch{self.channel}"
        if lut_key in PDOA_LUTS and PDOA_LUTS[lut_key]:
            lut = PDOA_LUTS[lut_key]
            # Linear interpolation through LUT
            pdoa_vals = np.array([e[0] for e in lut])
            angle_vals = np.array([e[1] for e in lut])
            angle_raw = np.interp(pdoa_corrected, pdoa_vals, angle_vals)
        else:
            # Without LUT, assume linear mapping
            # Typical: ±pi phase maps to ±90 degrees
            # 2679 raw ≈ 90 degrees (from calibration LUT endpoints)
            angle_raw = pdoa_corrected * 90.0 / 2679.0

        return AoAResult(
            pdoa_raw=pdoa_raw,
            pdoa_corrected=pdoa_corrected,
            angle_deg=float(angle_raw),
            antenna_pair=ant_pair,
            channel=self.channel,
        )

    def cir_to_distance(self, cir_complex: np.ndarray, fp_index: int,
                       remote_ant_delay_ticks: Optional[float] = None) -> RangingResult:
        """
        Convert CIR first-path index to calibrated distance.

        Args:
            cir_complex: Complex CIR samples
            fp_index: First path index from hardware CIA
            remote_ant_delay_ticks: Remote device's antenna delay
        """
        # Convert fp_index (CIR sample index) to DW3000 ticks
        # Each CIR sample = 1/bandwidth ≈ 2.003 ns
        # In DW3000 ticks: 2.003 ns / 15.65 ps ≈ 128 ticks per CIR sample
        ticks_per_sample = 128  # = 499.2 MHz * 128 / 499.2 MHz

        raw_tof_ticks = fp_index * ticks_per_sample
        return self.correct_distance(raw_tof_ticks, remote_ant_delay_ticks)


def print_calibration_report():
    """Print a summary of calibration constants."""
    print("=== Pixel 7 Pro DW3000 Calibration Summary ===\n")

    print("Antenna delays (equivalent one-way distance):")
    for (ant, ch, prf), ticks in sorted(ANTENNA_DELAYS.items()):
        dist_m = ticks * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2
        print(f"  ant{ant} ch{ch} prf{prf}: {ticks} ticks = {dist_m:.6f} m")

    print("\nInter-config delay differences:")
    for ant in range(4):
        entries = [(k, v) for k, v in ANTENNA_DELAYS.items() if k[0] == ant]
        for i, (k1, v1) in enumerate(entries):
            for k2, v2 in entries[i+1:]:
                diff = abs(v1 - v2)
                diff_mm = diff * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2 * 1000
                if diff > 0:
                    print(f"  ant{ant}: ch{k1[1]}/prf{k1[2]} vs ch{k2[1]}/prf{k2[2]}: "
                          f"{diff} ticks = {diff_mm:.1f} mm")

    print("\nPDoA offsets:")
    for (a, b, ch), offset in sorted(PDOA_OFFSETS.items()):
        print(f"  ant{a}-ant{b} ch{ch}: {offset:+d}")

    print(f"\nCrystal trim: {XTAL_TRIM_VENDOR} (vendor) / {XTAL_TRIM_FACTORY} (factory)")
    print(f"DW3000 tick: {DW3000_TICK_PS:.4f} ps = {DW3000_TICK_NS:.6f} ns")
    print(f"Distance per tick (one-way): {DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT * 1000:.4f} mm")


if __name__ == '__main__':
    print_calibration_report()

    print("\n=== Ranging Simulation ===\n")

    # Simulate a 3-meter range measurement with SS-TWR
    ranger = CalibratedRanger(channel=9, prf=64, antenna=0, temperature_c=25.0)

    # Raw ToF for 3 meters (round-trip):
    # time = 2 * distance / c = 2 * 3 / 3e8 = 20 ns
    # In DW3000 ticks: 20e-9 / 15.65e-12 = 1278 ticks
    # Plus two antenna delays: 16444 * 2 = 32888 ticks
    true_distance = 3.0
    true_tof_ticks = 2 * true_distance / (SPEED_OF_LIGHT * DW3000_TICK_PS * 1e-12)
    raw_tof_with_delays = true_tof_ticks + 2 * ranger.ant_delay_ticks

    result = ranger.correct_distance(raw_tof_with_delays)
    print(f"True distance: {true_distance:.3f} m")
    print(f"Raw ToF: {raw_tof_with_delays:.0f} ticks")
    print(f"Antenna delay: {ranger.ant_delay_ticks} ticks ({ranger.ant_delay_m:.6f} m)")
    print(f"Corrected: {result.distance_m:.6f} m = {result.distance_mm:.3f} mm")
    print(f"Error: {abs(result.distance_m - true_distance) * 1000:.3f} mm")
    print(f"Temperature correction: {result.temperature_correction_mm:.3f} mm")

    # Test AoA
    print("\n=== AoA Simulation ===\n")
    aoa = ranger.pdoa_to_angle(1000, ant_pair=(1, 2))
    print(f"PDoA raw: {aoa.pdoa_raw}")
    print(f"PDoA corrected: {aoa.pdoa_corrected:.1f}")
    print(f"Angle: {aoa.angle_deg:.1f}°")
