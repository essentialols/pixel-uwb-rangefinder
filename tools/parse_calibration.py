#!/usr/bin/env python3
"""
parse_calibration.py -- Decode DW3000 UWB calibration data from Pixel 7 Pro

Parses the Qorvo HAL calibration config files and extracts:
- Per-antenna, per-channel, per-PRF delay values
- TX power settings (per-stage power control)
- PDoA (Phase Difference of Arrival) offsets and LUTs
- Antenna set configurations for AoA
- Crystal trim values
- WiFi coexistence parameters

The antenna delay values are critical for sub-centimeter ranging:
  physical_distance = (timestamp - antenna_delay) * c / 2
  where c = 299792458 m/s, one DW3000 tick = 1/(499.2e6 * 128) ≈ 15.65 ps
"""

import sys
import struct
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# DW3000 time unit: 1 / (499.2 MHz * 128) ≈ 15.6501 ps
DW3000_TICK_PS = 1e12 / (499.2e6 * 128)  # 15.6501 ps
DW3000_TICK_NS = DW3000_TICK_PS / 1000
SPEED_OF_LIGHT = 299792458.0  # m/s


@dataclass
class AntennaDelay:
    antenna: int
    channel: int
    prf: int
    delay_ticks: int
    delay_ns: float = 0.0
    delay_m: float = 0.0  # equivalent one-way distance
    tx_power: int = 0
    pg_count: int = 0
    pg_delay: int = 0

    def __post_init__(self):
        self.delay_ns = self.delay_ticks * DW3000_TICK_NS
        # One-way equivalent distance (antenna delay is round-trip divided by 2)
        self.delay_m = self.delay_ticks * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2


@dataclass
class PDoAOffset:
    ant_a: int
    ant_b: int
    channel: int
    offset_raw: int  # signed, units TBD (likely 1/4096 radian or similar)


@dataclass
class PDoALUT:
    ant_a: int
    ant_b: int
    channel: int
    entries: list  # list of (pdoa_raw, angle_raw) tuples
    raw_hex: str = ""


@dataclass
class AntennaConfig:
    index: int
    port: int
    selector_gpio: int
    selector_gpio_value: int


@dataclass
class CalibrationData:
    antenna_delays: list = field(default_factory=list)
    pdoa_offsets: list = field(default_factory=list)
    pdoa_luts: list = field(default_factory=list)
    antenna_configs: list = field(default_factory=list)
    xtal_trim: int = 0
    temperature_reference: int = 0
    smart_tx_power: bool = False
    auto_sleep_margin_us: int = 0
    restricted_channels: int = 0
    pll_locking: dict = field(default_factory=dict)
    ccc_config: dict = field(default_factory=dict)
    hal_config: dict = field(default_factory=dict)
    coex_config: dict = field(default_factory=dict)


def parse_tx_power(val: int) -> dict:
    """Decode 4-byte TX power register.

    Format: [coarse_gain_stage4 | fine_gain_stage3 | coarse_gain_stage2 | fine_gain_stage1]
    Each byte: bits[7:5] = coarse gain (0-7), bits[4:0] = fine gain (0-31)
    """
    stages = []
    for i in range(4):
        byte = (val >> (24 - 8*i)) & 0xFF
        coarse = (byte >> 5) & 0x07
        fine = byte & 0x1F
        stages.append({"coarse": coarse, "fine": fine, "raw": f"0x{byte:02X}"})
    return {"raw": f"0x{val:08X}", "stages": stages}


def decode_pdoa_lut(hex_str: str) -> list:
    """Decode PDoA LUT from colon-separated hex bytes.

    Format: pairs of (pdoa_value_le16, angle_value_le16) as little-endian int16.
    """
    try:
        data = bytes(int(x, 16) for x in hex_str.split(':'))
    except ValueError:
        return []

    entries = []
    for i in range(0, len(data) - 3, 4):
        pdoa = struct.unpack_from('<h', data, i)[0]
        angle = struct.unpack_from('<h', data, i + 2)[0]
        entries.append({"pdoa": pdoa, "angle": angle})
    return entries


def parse_config(text: str) -> CalibrationData:
    """Parse a Qorvo calibration config file."""
    cal = CalibrationData()
    antenna_info = {}  # temp storage for antenna port/gpio

    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        if '=' not in line:
            continue

        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip()

        # CCC config
        if key.startswith('[CCC]'):
            cal.ccc_config[key[5:]] = val
            continue

        # HAL config
        if key.startswith('[HAL]'):
            cal.hal_config[key[5:]] = val
            continue

        # Antenna delay/power: antN.chM.prfK.param
        import re
        m = re.match(r'ant(\d+)\.ch(\d+)\.prf(\d+)\.(ant_delay|tx_power|pg_count|pg_delay)', key)
        if m:
            ant, ch, prf, param = int(m[1]), int(m[2]), int(m[3]), m[4]
            # Find or create entry
            entry = None
            for d in cal.antenna_delays:
                if d.antenna == ant and d.channel == ch and d.prf == prf:
                    entry = d
                    break
            if entry is None:
                entry = AntennaDelay(antenna=ant, channel=ch, prf=prf, delay_ticks=0)
                cal.antenna_delays.append(entry)

            if param == 'ant_delay':
                entry.delay_ticks = int(val)
                entry.__post_init__()
            elif param == 'tx_power':
                entry.tx_power = int(val, 0)
            elif param == 'pg_count':
                entry.pg_count = int(val)
            elif param == 'pg_delay':
                entry.pg_delay = int(val, 0)
            continue

        # Antenna port/gpio: antN.param
        m = re.match(r'ant(\d+)\.(port|selector_gpio|selector_gpio_value)', key)
        if m:
            ant, param = int(m[1]), m[2]
            if ant not in antenna_info:
                antenna_info[ant] = {'index': ant}
            antenna_info[ant][param] = int(val)
            continue

        # PDoA offset: antN.antM.chK.pdoa_offset
        m = re.match(r'ant(\d+)\.ant(\d+)\.ch(\d+)\.pdoa_offset', key)
        if m:
            cal.pdoa_offsets.append(PDoAOffset(
                ant_a=int(m[1]), ant_b=int(m[2]),
                channel=int(m[3]), offset_raw=int(val)
            ))
            continue

        # PDoA LUT: antN.antM.chK.pdoa_lut
        m = re.match(r'ant(\d+)\.ant(\d+)\.ch(\d+)\.pdoa_lut', key)
        if m:
            entries = decode_pdoa_lut(val)
            cal.pdoa_luts.append(PDoALUT(
                ant_a=int(m[1]), ant_b=int(m[2]),
                channel=int(m[3]), entries=entries,
                raw_hex=val
            ))
            continue

        # PLL locking code
        m = re.match(r'ch(\d+)\.pll_locking_code', key)
        if m:
            cal.pll_locking[f"ch{m[1]}"] = int(val)
            continue

        # Scalar params
        if key == 'xtal_trim':
            cal.xtal_trim = int(val, 0)
        elif key == 'temperature_reference':
            cal.temperature_reference = int(val)
        elif key == 'smart_tx_power':
            cal.smart_tx_power = bool(int(val))
        elif key == 'auto_sleep_margin':
            cal.auto_sleep_margin_us = int(val)
        elif key == 'restricted_channels':
            cal.restricted_channels = int(val)
        elif key.startswith('coex_'):
            cal.coex_config[key] = val

    # Build antenna configs
    for idx in sorted(antenna_info.keys()):
        info = antenna_info[idx]
        cal.antenna_configs.append(AntennaConfig(
            index=idx,
            port=info.get('port', 0),
            selector_gpio=info.get('selector_gpio', 0),
            selector_gpio_value=info.get('selector_gpio_value', 0)
        ))

    return cal


def print_report(cal: CalibrationData):
    """Print a human-readable calibration report."""
    print("=" * 70)
    print("DW3000 UWB Calibration Report - Pixel 7 Pro (Cheetah)")
    print("=" * 70)

    print(f"\nCrystal trim: {cal.xtal_trim} (0x{cal.xtal_trim:02X})")
    print(f"Temperature reference: {cal.temperature_reference} C")
    print(f"Smart TX power: {cal.smart_tx_power}")
    print(f"Auto sleep margin: {cal.auto_sleep_margin_us} us")

    # Antenna hardware config
    print(f"\n--- Antenna Hardware ---")
    for ac in cal.antenna_configs:
        print(f"  ant{ac.index}: port={ac.port}, GPIO{ac.selector_gpio}={ac.selector_gpio_value}")

    # Antenna delays
    print(f"\n--- Antenna Delays ---")
    print(f"  {'Ant':>3} {'Ch':>3} {'PRF':>4} {'Ticks':>6} {'ns':>8} {'m equiv':>10} {'TX Power':>12}")
    for d in sorted(cal.antenna_delays, key=lambda x: (x.antenna, x.channel, x.prf)):
        tx_str = f"0x{d.tx_power:08X}" if d.tx_power else "off"
        print(f"  {d.antenna:3d} {d.channel:3d} {d.prf:4d} {d.delay_ticks:6d} "
              f"{d.delay_ns:8.3f} {d.delay_m:10.6f} {tx_str:>12}")

    # Delay differences (critical for ranging calibration)
    print(f"\n--- Delay Differences (same antenna, between configs) ---")
    by_ant = {}
    for d in cal.antenna_delays:
        by_ant.setdefault(d.antenna, []).append(d)
    for ant in sorted(by_ant.keys()):
        delays = by_ant[ant]
        if len(delays) < 2:
            continue
        print(f"  ant{ant}:")
        for i, a in enumerate(delays):
            for b in delays[i+1:]:
                diff_ticks = abs(a.delay_ticks - b.delay_ticks)
                diff_mm = diff_ticks * DW3000_TICK_PS * 1e-12 * SPEED_OF_LIGHT / 2 * 1000
                print(f"    ch{a.channel}/prf{a.prf} vs ch{b.channel}/prf{b.prf}: "
                      f"{diff_ticks} ticks = {diff_mm:.1f} mm")

    # PDoA offsets
    if cal.pdoa_offsets:
        print(f"\n--- PDoA Offsets ---")
        for p in cal.pdoa_offsets:
            status = "calibrated" if p.offset_raw != 0 else "uncalibrated"
            print(f"  ant{p.ant_a}-ant{p.ant_b} ch{p.channel}: {p.offset_raw:+6d} ({status})")

    # PDoA LUTs
    if cal.pdoa_luts:
        print(f"\n--- PDoA Lookup Tables ---")
        for lut in cal.pdoa_luts:
            print(f"  ant{lut.ant_a}-ant{lut.ant_b} ch{lut.channel}: "
                  f"{len(lut.entries)} entries")
            if lut.entries:
                pdoa_range = (min(e['pdoa'] for e in lut.entries),
                             max(e['pdoa'] for e in lut.entries))
                angle_range = (min(e['angle'] for e in lut.entries),
                              max(e['angle'] for e in lut.entries))
                print(f"    PDoA range: [{pdoa_range[0]}, {pdoa_range[1]}]")
                print(f"    Angle range: [{angle_range[0]}, {angle_range[1]}]")

    # HAL antenna set config
    if cal.hal_config:
        print(f"\n--- HAL Antenna Set Configuration ---")
        print(f"  AoA capability: {cal.hal_config.get('aoa_capability', '?')}")
        print(f"  AoA restricted channels: {cal.hal_config.get('aoa_restricted_channels', '?')}")
        # Group by channel and mode
        for ch in [5, 9]:
            for mode in ['range', 'azimuth', 'elevation', 'azimuth_elevation']:
                key_prefix = f'ant_sets.ch{ch}.{mode}'
                entries = {k: v for k, v in cal.hal_config.items() if k.startswith(key_prefix)}
                if entries:
                    vals = ", ".join(f"{k.split('.')[-1]}={v}" for k, v in sorted(entries.items()))
                    print(f"  ch{ch} {mode}: {vals}")

    # Coexistence
    if cal.coex_config:
        print(f"\n--- WiFi Coexistence ---")
        for k, v in sorted(cal.coex_config.items()):
            print(f"  {k}: {v}")

    # CCC config
    if cal.ccc_config:
        print(f"\n--- CCC (Car Connectivity Consortium) ---")
        for k, v in sorted(cal.ccc_config.items()):
            print(f"  {k}: {v}")


def main():
    if len(sys.argv) < 2:
        # Default: read from stdin
        text = sys.stdin.read()
    else:
        text = Path(sys.argv[1]).read_text()

    cal = parse_config(text)

    if '--json' in sys.argv:
        # JSON output
        out = asdict(cal)
        # Convert enums/custom to serializable
        print(json.dumps(out, indent=2, default=str))
    else:
        print_report(cal)


if __name__ == '__main__':
    main()
