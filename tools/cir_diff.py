#!/usr/bin/env python3
"""
cir_diff.py -- Differential CIR analysis: compare two captures to detect changes

Subtracts a baseline CIR magnitude profile from a test capture to isolate new
peaks caused by reflectors or environmental changes. Reports bins where the
difference exceeds a configurable threshold.

Usage:
  python3 cir_diff.py --baseline data/cir_captures/baseline_50ms_64bins_mags.csv \
                       --test data/cir_captures/reflector_30cm_mags.csv
"""

import sys
import os
import csv
import math
import argparse
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPEED_OF_LIGHT = 299792458.0
UWB_BANDWIDTH = 499.2e6
RANGE_PER_SAMPLE = SPEED_OF_LIGHT / UWB_BANDWIDTH


def load_magnitudes(path):
    frames = []
    with open(path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            mags = [float(x) for x in row[1:]]
            frames.append(mags)
    return np.array(frames)


def main():
    parser = argparse.ArgumentParser(description="Differential CIR analysis")
    parser.add_argument('--baseline', required=True, help='Baseline magnitudes CSV')
    parser.add_argument('--test', required=True, help='Test magnitudes CSV')
    parser.add_argument('--threshold', type=float, default=3.0,
                        help='Detection threshold in baseline std devs (default: 3.0)')
    parser.add_argument('--output', type=str, help='Save diff CSV')
    args = parser.parse_args()

    base = load_magnitudes(args.baseline)
    test = load_magnitudes(args.test)

    n_base, n_bins_base = base.shape
    n_test, n_bins_test = test.shape
    n_bins = min(n_bins_base, n_bins_test)

    base = base[:, :n_bins]
    test = test[:, :n_bins]

    base_mean = np.mean(base, axis=0)
    base_std = np.std(base, axis=0)
    test_mean = np.mean(test, axis=0)
    test_std = np.std(test, axis=0)

    diff = test_mean - base_mean
    base_std_safe = np.where(base_std > 0, base_std, 0.001)
    z_score = diff / base_std_safe

    print(f"Baseline: {n_base} frames x {n_bins} bins")
    print(f"Test:     {n_test} frames x {n_bins} bins")
    print()

    print(f"{'bin':>4s} {'base_mean':>9s} {'test_mean':>9s} {'diff':>8s} {'z_score':>8s} "
          f"{'dist_m':>7s} {'flag':>6s}")
    print("-" * 60)

    detections = []
    for b in range(n_bins):
        dist_m = b * RANGE_PER_SAMPLE
        flag = ""
        if abs(z_score[b]) > args.threshold:
            flag = " ***" if diff[b] > 0 else " ---"
            detections.append({
                'bin': b,
                'diff': diff[b],
                'z': z_score[b],
                'dist_m': dist_m,
                'direction': 'up' if diff[b] > 0 else 'down',
            })
        print(f"{b:4d} {base_mean[b]:9.4f} {test_mean[b]:9.4f} {diff[b]:+8.4f} "
              f"{z_score[b]:+8.2f} {dist_m:7.2f}{flag}")

    print(f"\n=== Detections (|z| > {args.threshold}) ===")
    if detections:
        up = [d for d in detections if d['direction'] == 'up']
        down = [d for d in detections if d['direction'] == 'down']
        if up:
            print(f"  New peaks (signal increase):")
            for d in up:
                print(f"    bin {d['bin']:2d}: +{d['diff']:.4f} (z={d['z']:+.1f}), "
                      f"dist={d['dist_m']:.2f}m = {d['dist_m']*100:.0f}cm")
        if down:
            print(f"  Reduced bins (signal decrease):")
            for d in down:
                print(f"    bin {d['bin']:2d}: {d['diff']:.4f} (z={d['z']:+.1f}), "
                      f"dist={d['dist_m']:.2f}m")
    else:
        print("  No significant differences detected")

    if args.output:
        with open(args.output, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['bin', 'base_mean', 'base_std', 'test_mean', 'test_std',
                        'diff', 'z_score', 'dist_m'])
            for b in range(n_bins):
                w.writerow([b, f"{base_mean[b]:.6f}", f"{base_std[b]:.6f}",
                           f"{test_mean[b]:.6f}", f"{test_std[b]:.6f}",
                           f"{diff[b]:.6f}", f"{z_score[b]:.3f}",
                           f"{b * RANGE_PER_SAMPLE:.3f}"])
        print(f"\nSaved diff to {args.output}")


if __name__ == '__main__':
    main()
