#!/usr/bin/env python3
"""
analyze_energy.py -- Analyze passive RF energy sensing data

Reads CSV from uwb_energy_sense.sh and looks for:
- Baseline energy level and variance
- Anomalous readings (potential presence detection)
- Temporal patterns (periodic interference, drift)

Usage:
  python3 tools/analyze_energy.py data/energy_sense.csv
"""

import sys
import csv
import argparse
import numpy as np


def parse_hex_or_err(val):
    if val == 'ERR' or not val:
        return None
    try:
        val = val.strip()
        if val.startswith('0x') or val.startswith('0X'):
            return int(val, 16)
        return int(val)
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Analyze energy sensing data")
    parser.add_argument('input', help='CSV from uwb_energy_sense.sh')
    args = parser.parse_args()

    rows = []
    with open(args.input) as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for key, val in row.items():
                if key in ('sample', 'timestamp'):
                    parsed[key] = val
                else:
                    parsed[key] = parse_hex_or_err(val)
            rows.append(parsed)

    n = len(rows)
    print(f"=== Passive Energy Sensing Analysis ===")
    print(f"Samples: {n}")
    print()

    reg_names = [k for k in rows[0].keys() if k not in ('sample', 'timestamp')]

    print(f"{'register':>15s} {'valid':>5s} {'min':>12s} {'max':>12s} {'mean':>12s} {'std':>10s} {'unique':>6s}")
    print("-" * 75)

    interesting = []
    for reg in reg_names:
        vals = [r[reg] for r in rows if r[reg] is not None]
        if not vals:
            print(f"{reg:>15s} {'0':>5s} {'N/A':>12s}")
            continue

        arr = np.array(vals)
        n_unique = len(np.unique(arr))
        mean = np.mean(arr)
        std = np.std(arr)
        cov = std / mean if mean != 0 else 0

        print(f"{reg:>15s} {len(vals):5d} {np.min(arr):12.0f} {np.max(arr):12.0f} "
              f"{mean:12.1f} {std:10.1f} {n_unique:6d}")

        if n_unique > 1 and len(vals) > 5:
            interesting.append((reg, arr, cov))

    print()
    print(f"=== Registers with Variation ===")
    if interesting:
        for reg, arr, cov in sorted(interesting, key=lambda x: -x[2]):
            print(f"  {reg}: CoV={cov:.4f}, range={np.min(arr):.0f}-{np.max(arr):.0f}")
            if cov > 0.1:
                print(f"    HIGH VARIATION: potential presence/environmental sensitivity")
    else:
        print(f"  No varying registers (all constant or all errors)")
        print(f"  This may indicate registers are not updating during RXPTO,")
        print(f"  or debugfs reads return cached values.")

    # Temporal analysis
    if interesting:
        print()
        print(f"=== Temporal Analysis (first varying register) ===")
        reg, arr, _ = interesting[0]
        n_vals = len(arr)
        if n_vals > 10:
            first_half = arr[:n_vals//2]
            second_half = arr[n_vals//2:]
            print(f"  {reg}: first half mean={np.mean(first_half):.1f}, second half mean={np.mean(second_half):.1f}")
            t_diff = abs(np.mean(first_half) - np.mean(second_half))
            pooled_std = np.sqrt((np.std(first_half)**2 + np.std(second_half)**2) / 2)
            if pooled_std > 0:
                t_stat = t_diff / pooled_std * np.sqrt(n_vals / 2)
                print(f"  t-statistic: {t_stat:.2f} (>2 suggests environmental change)")


if __name__ == '__main__':
    main()
