#!/usr/bin/env python3
"""
analyze_baseline.py -- Analyze CIR baseline captures for artifact vs. reflection classification

Reads per-bin magnitude CSV from cir_stream_decode.py and computes:
  - Per-bin mean, std, CoV (coefficient of variation)
  - Temporal stability classification (artifact = low CoV, noise = high CoV)
  - Bin-to-bin correlation matrix for identifying coupled bins
  - Distance mapping from bin index to meters
  - Summary table for elevated bins

Usage:
  python3 analyze_baseline.py data/cir_captures/baseline_50ms_64bins_mags.csv
"""

import sys
import os
import csv
import math
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPEED_OF_LIGHT = 299792458.0
UWB_BANDWIDTH = 499.2e6
RANGE_PER_SAMPLE = SPEED_OF_LIGHT / UWB_BANDWIDTH


def load_magnitudes(path):
    frames = []
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        n_bins = len(header) - 1
        for row in reader:
            mags = [float(x) for x in row[1:]]
            frames.append(mags)
    return frames, n_bins


def bin_stats(frames, n_bins):
    stats = []
    for b in range(n_bins):
        vals = [f[b] for f in frames]
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        std = math.sqrt(var)
        cov = std / mean if mean > 0 else float('inf')
        mn = min(vals)
        mx = max(vals)
        stats.append({
            'bin': b,
            'mean': mean,
            'std': std,
            'cov': cov,
            'min': mn,
            'max': mx,
            'dist_m': b * RANGE_PER_SAMPLE,
        })
    return stats


def classify_bins(stats, global_mean):
    for s in stats:
        ratio = s['mean'] / global_mean if global_mean > 0 else 0
        if s['mean'] == 0:
            s['class'] = 'zero'
        elif ratio > 1.5 and s['cov'] < 0.15:
            s['class'] = 'stable_elevated'
        elif ratio > 1.5 and s['cov'] >= 0.15:
            s['class'] = 'variable_elevated'
        elif s['cov'] < 0.10:
            s['class'] = 'stable_floor'
        else:
            s['class'] = 'noise'


def cross_correlation(frames, n_bins, bin_a, bin_b):
    vals_a = [f[bin_a] for f in frames]
    vals_b = [f[bin_b] for f in frames]
    n = len(vals_a)
    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n
    cov = sum((vals_a[i] - mean_a) * (vals_b[i] - mean_b) for i in range(n)) / n
    std_a = math.sqrt(sum((v - mean_a) ** 2 for v in vals_a) / n)
    std_b = math.sqrt(sum((v - mean_b) ** 2 for v in vals_b) / n)
    if std_a * std_b == 0:
        return 0.0
    return cov / (std_a * std_b)


def analyze_peak_wins(frames, n_bins):
    win_counts = [0] * n_bins
    for f in frames:
        peak_idx = max(range(len(f)), key=lambda i: f[i])
        win_counts[peak_idx] += 1
    return win_counts


def main():
    parser = argparse.ArgumentParser(description="Analyze CIR baseline for artifacts")
    parser.add_argument('input', help='Per-bin magnitudes CSV from cir_stream_decode.py')
    parser.add_argument('--output', type=str, help='Save analysis CSV')
    args = parser.parse_args()

    frames, n_bins = load_magnitudes(args.input)
    n_frames = len(frames)

    print(f"Loaded {n_frames} frames x {n_bins} bins from {args.input}")
    print()

    stats = bin_stats(frames, n_bins)
    all_means = [s['mean'] for s in stats if s['mean'] > 0]
    global_mean = sum(all_means) / len(all_means) if all_means else 0
    global_median = sorted(all_means)[len(all_means) // 2] if all_means else 0

    classify_bins(stats, global_median)

    # Peak win analysis
    wins = analyze_peak_wins(frames, n_bins)

    print(f"Global magnitude stats:")
    print(f"  Mean across bins: {global_mean:.4f}")
    print(f"  Median across bins: {global_median:.4f}")
    print()

    print(f"{'bin':>4s} {'mean':>8s} {'std':>8s} {'CoV':>6s} {'min':>8s} {'max':>8s} "
          f"{'dist_m':>7s} {'wins':>4s} {'class':>18s}")
    print("-" * 82)

    for s in stats:
        w = wins[s['bin']]
        flag = " ***" if s['class'] in ('stable_elevated', 'variable_elevated') else ""
        print(f"{s['bin']:4d} {s['mean']:8.4f} {s['std']:8.4f} {s['cov']:6.3f} "
              f"{s['min']:8.4f} {s['max']:8.4f} {s['dist_m']:7.2f} {w:4d} "
              f"{s['class']:>18s}{flag}")

    # Elevated bins summary
    elevated = [s for s in stats if 'elevated' in s['class']]
    print(f"\n=== Elevated Bins ({len(elevated)}) ===")
    if elevated:
        for s in elevated:
            print(f"  bin {s['bin']:2d}: mean={s['mean']:.4f}, CoV={s['cov']:.3f}, "
                  f"dist={s['dist_m']:.2f}m, class={s['class']}")

        # Cross-correlation between elevated bins
        if len(elevated) > 1:
            print(f"\n=== Cross-Correlation Between Elevated Bins ===")
            for i in range(len(elevated)):
                for j in range(i + 1, len(elevated)):
                    ba, bb = elevated[i]['bin'], elevated[j]['bin']
                    r = cross_correlation(frames, n_bins, ba, bb)
                    print(f"  bin{ba} vs bin{bb}: r={r:+.3f}")

    # Artifact vs. reflection analysis
    print(f"\n=== Interpretation ===")
    stable_elevated = [s for s in stats if s['class'] == 'stable_elevated']
    variable_elevated = [s for s in stats if s['class'] == 'variable_elevated']

    if stable_elevated:
        print(f"  Stable elevated bins (CoV < 0.15): likely CIR accumulator artifacts")
        print(f"    or fixed environmental reflections (phone case, PCB, antenna)")
        for s in stable_elevated:
            print(f"    bin {s['bin']}: {s['dist_m']:.2f}m = {s['dist_m']*100:.0f}cm from antenna")

    if variable_elevated:
        print(f"  Variable elevated bins (CoV >= 0.15): likely noise peaks or")
        print(f"    time-varying environmental reflections")
        for s in variable_elevated:
            print(f"    bin {s['bin']}: {s['dist_m']:.2f}m, CoV={s['cov']:.3f}")

    # Check for near-field artifacts (bins 0-5)
    near_field = [s for s in stats[:6] if s['mean'] > global_median * 1.3]
    if near_field:
        print(f"  Near-field elevated ({len(near_field)} bins): antenna/package crosstalk")

    # Temporal consistency check
    print(f"\n=== Temporal Consistency ===")
    max_cov = max(s['cov'] for s in stats if s['mean'] > 0)
    min_cov = min(s['cov'] for s in stats if s['mean'] > 0)
    mean_cov = sum(s['cov'] for s in stats if s['mean'] > 0 and s['cov'] < float('inf')) / \
               len([s for s in stats if s['mean'] > 0 and s['cov'] < float('inf')])
    print(f"  CoV range: {min_cov:.3f} to {max_cov:.3f} (mean: {mean_cov:.3f})")
    very_stable = [s for s in stats if s['cov'] < 0.05 and s['mean'] > 0]
    print(f"  Very stable bins (CoV < 0.05): {len(very_stable)}")
    for s in very_stable:
        print(f"    bin {s['bin']}: mean={s['mean']:.4f}, CoV={s['cov']:.3f}")

    if args.output:
        with open(args.output, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['bin', 'mean', 'std', 'cov', 'min', 'max', 'dist_m', 'wins', 'class'])
            for s in stats:
                w.writerow([s['bin'], f"{s['mean']:.6f}", f"{s['std']:.6f}", f"{s['cov']:.4f}",
                           f"{s['min']:.6f}", f"{s['max']:.6f}", f"{s['dist_m']:.3f}",
                           wins[s['bin']], s['class']])
        print(f"\nSaved analysis to {args.output}")


if __name__ == '__main__':
    main()
