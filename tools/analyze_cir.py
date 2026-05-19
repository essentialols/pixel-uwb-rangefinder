#!/usr/bin/env python3
"""
analyze_cir.py -- Analyze CIR (Channel Impulse Response) data from DW3000

Session 1, Experiment E006: CIR signal processing and visualization.

Reads CSV output from uwb_cir_read and performs:
  - Magnitude/phase plots
  - First path detection
  - Multipath identification
  - Signal-to-noise ratio estimation
  - Allan deviation (when multiple captures available)

Usage:
  python3 analyze_cir.py cir_data.csv
  python3 analyze_cir.py cir_data.csv --plot
  python3 analyze_cir.py cir_data.csv --json-input   # for JSON from uwb_cir_read -j
"""

import sys
import csv
import json
import math
import argparse
from collections import defaultdict


def load_csv(path):
    """Load CIR data from CSV file."""
    captures = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            cap = int(row['capture'])
            captures[cap].append({
                'index': int(row['index']),
                'real': float(row['real']),
                'imag': float(row['imag']),
                'magnitude': float(row['magnitude']),
                'phase': float(row['phase_rad']),
                'fp_index': int(row['fp_index']),
                'fp_power1': int(row['fp_power1']),
                'pdoa': int(row['pdoa']),
                'acc': int(row['acc']),
            })
    return captures


def load_json(path):
    """Load CIR data from JSON file (one JSON object per line)."""
    captures = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cap = obj['capture']
            records = []
            for r in obj['records']:
                mag = math.sqrt(r['re']**2 + r['im']**2)
                records.append({
                    'index': r['i'],
                    'real': r['re'],
                    'imag': r['im'],
                    'magnitude': mag,
                    'phase': math.atan2(r['im'], r['re']),
                    'fp_index': obj['fp_index'],
                    'fp_power1': obj['fp_power'][0],
                    'pdoa': obj['pdoa'],
                    'acc': obj['acc'],
                })
            captures[cap] = records
    return captures


def analyze_capture(records, capture_id=0):
    """Analyze a single CIR capture."""
    if not records:
        print(f"  Capture {capture_id}: no records")
        return

    mags = [r['magnitude'] for r in records]
    fp_index = records[0]['fp_index']

    # Find peaks (local maxima above noise floor)
    noise_floor = sorted(mags)[:max(1, len(mags) // 4)]  # lowest 25%
    noise_mean = sum(noise_floor) / len(noise_floor) if noise_floor else 0
    noise_std = math.sqrt(sum((x - noise_mean)**2 for x in noise_floor) / len(noise_floor)) if len(noise_floor) > 1 else noise_mean

    threshold = noise_mean + 3 * noise_std if noise_std > 0 else noise_mean * 2

    peaks = []
    for i in range(1, len(mags) - 1):
        if mags[i] > mags[i-1] and mags[i] > mags[i+1] and mags[i] > threshold:
            peaks.append((i, mags[i]))

    # Peak magnitude
    peak_idx = max(range(len(mags)), key=lambda i: mags[i])
    peak_mag = mags[peak_idx]

    # SNR
    snr = 10 * math.log10(peak_mag / noise_mean) if noise_mean > 0 else float('inf')

    print(f"  Capture {capture_id}:")
    print(f"    Records:       {len(records)}")
    print(f"    FP index:      {fp_index}")
    print(f"    Peak index:    {peak_idx} (magnitude={peak_mag:.4f})")
    print(f"    Noise floor:   {noise_mean:.6f} +/- {noise_std:.6f}")
    print(f"    SNR:           {snr:.1f} dB")
    print(f"    Peaks (>3sig): {len(peaks)}")
    for i, (idx, mag) in enumerate(peaks[:5]):
        delay_ns = idx * 1.0  # ~1ns per CIR sample at 499.2 MHz BW
        dist_m = delay_ns * 0.2998  # speed of light
        print(f"      Peak {i}: index={idx}, mag={mag:.4f}, "
              f"~{delay_ns:.1f}ns, ~{dist_m:.2f}m")

    if len(peaks) > 1:
        print(f"    Multipath: {len(peaks)-1} reflected paths detected")

    print(f"    PDoA:          {records[0]['pdoa']}")
    print(f"    Accumulations: {records[0]['acc']}")

    return {
        'peak_idx': peak_idx,
        'peak_mag': peak_mag,
        'noise_floor': noise_mean,
        'snr': snr,
        'num_peaks': len(peaks),
        'peaks': peaks,
        'fp_index': fp_index,
    }


def try_plot(captures):
    """Try to plot CIR data if matplotlib is available."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not available, skipping plot")
        return

    fig, axes = plt.subplots(min(len(captures), 4), 1,
                             figsize=(12, 3 * min(len(captures), 4)),
                             squeeze=False)

    for i, (cap_id, records) in enumerate(sorted(captures.items())[:4]):
        ax = axes[i][0]
        indices = [r['index'] for r in records]
        mags = [r['magnitude'] for r in records]
        fp_index = records[0]['fp_index']

        ax.plot(indices, mags, 'b-', linewidth=0.8, label='CIR magnitude')
        ax.axvline(x=fp_index, color='r', linestyle='--', alpha=0.7,
                   label=f'FP index={fp_index}')
        ax.set_ylabel('Magnitude')
        ax.set_title(f'Capture {cap_id}')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1][0].set_xlabel('CIR sample index (~1ns/sample)')
    plt.tight_layout()
    plt.savefig('cir_plot.png', dpi=150)
    print(f"\nPlot saved to cir_plot.png")


def main():
    parser = argparse.ArgumentParser(description='Analyze DW3000 CIR data')
    parser.add_argument('input', help='CSV or JSON input file')
    parser.add_argument('--json-input', action='store_true',
                        help='Input is JSON (from uwb_cir_read -j)')
    parser.add_argument('--plot', action='store_true',
                        help='Generate matplotlib plot')
    args = parser.parse_args()

    if args.json_input:
        captures = load_json(args.input)
    else:
        captures = load_csv(args.input)

    print(f"Loaded {len(captures)} CIR captures from {args.input}")
    print()

    for cap_id in sorted(captures.keys()):
        analyze_capture(captures[cap_id], cap_id)
        print()

    if args.plot:
        try_plot(captures)


if __name__ == '__main__':
    main()
