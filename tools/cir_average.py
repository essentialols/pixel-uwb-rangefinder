#!/usr/bin/env python3
"""
cir_average.py -- Incoherent averaging of CIR magnitude captures

Averages N frames of CIR magnitude data to improve SNR. Random noise averages
toward zero (in power domain), while consistent signals grow. SNR improves by
approximately sqrt(N) for incoherent averaging.

Also computes the standard error of each bin to identify bins whose mean
is statistically significant above the overall noise floor.

Usage:
  python3 cir_average.py data/cir_captures/baseline_50ms_64bins_mags.csv
  python3 cir_average.py data/cir_captures/baseline_50ms_64bins_mags.csv --window 10
"""

import sys
import os
import csv
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
    parser = argparse.ArgumentParser(description="Incoherent CIR averaging")
    parser.add_argument('input', help='Per-bin magnitudes CSV')
    parser.add_argument('--window', type=int, default=0,
                        help='Rolling window size (0 = all frames)')
    parser.add_argument('--output', type=str, help='Save averaged profile CSV')
    args = parser.parse_args()

    data = load_magnitudes(args.input)
    n_frames, n_bins = data.shape

    print(f"Loaded {n_frames} frames x {n_bins} bins")

    if args.window > 0 and args.window < n_frames:
        print(f"\n=== Rolling window analysis (window={args.window}) ===")
        for start in range(0, n_frames - args.window + 1, args.window):
            end = start + args.window
            chunk = data[start:end]
            avg = np.mean(chunk, axis=0)
            peak_bin = np.argmax(avg)
            peak_mag = avg[peak_bin]
            noise_floor = np.mean(np.sort(avg)[:n_bins // 4])
            snr = 10 * np.log10(peak_mag / noise_floor) if noise_floor > 0 else 0
            print(f"  frames {start:3d}-{end-1:3d}: peak bin={peak_bin:2d} "
                  f"mag={peak_mag:.4f} SNR={snr:.1f}dB")

    # Full average
    power = data ** 2
    avg_power = np.mean(power, axis=0)
    avg_mag = np.sqrt(avg_power)
    avg_mag_simple = np.mean(data, axis=0)
    std_mag = np.std(data, axis=0)
    se_mag = std_mag / np.sqrt(n_frames)

    noise_bins = np.sort(avg_mag_simple)[:n_bins // 4]
    noise_floor = np.mean(noise_bins)
    noise_std = np.std(noise_bins)

    print(f"\n=== Full Average ({n_frames} frames, SNR gain ~{np.sqrt(n_frames):.1f}x) ===")
    print(f"  Noise floor: {noise_floor:.4f} +/- {noise_std:.4f}")
    print(f"  SNR improvement: {10*np.log10(np.sqrt(n_frames)):.1f} dB")

    print(f"\n{'bin':>4s} {'avg_mag':>8s} {'std':>8s} {'SE':>8s} {'z_above_nf':>10s} "
          f"{'dist_m':>7s} {'sig':>4s}")
    print("-" * 58)

    significant = []
    for b in range(n_bins):
        z = (avg_mag_simple[b] - noise_floor) / se_mag[b] if se_mag[b] > 0 else 0
        sig = "***" if z > 5 else "**" if z > 3 else "*" if z > 2 else ""
        dist = b * RANGE_PER_SAMPLE
        print(f"{b:4d} {avg_mag_simple[b]:8.4f} {std_mag[b]:8.4f} {se_mag[b]:8.4f} "
              f"{z:+10.2f} {dist:7.2f} {sig:>4s}")
        if z > 3:
            significant.append({'bin': b, 'mag': avg_mag_simple[b], 'z': z,
                               'dist_m': dist})

    print(f"\n=== Significantly Elevated Bins (z > 3) ===")
    if significant:
        for s in significant:
            print(f"  bin {s['bin']:2d}: mean={s['mag']:.4f}, z={s['z']:+.1f}, "
                  f"dist={s['dist_m']:.2f}m")
        print(f"\n  NOTE: high z-scores with low CoV indicate persistent CIR RAM")
        print(f"  artifacts, not signal. Real reflections would show higher magnitude")
        print(f"  AND higher variance (thermal noise modulation of signal).")
    else:
        print("  None found above noise floor")

    # SNR after averaging
    peak_idx = np.argmax(avg_mag_simple)
    peak_mag = avg_mag_simple[peak_idx]
    snr_averaged = 10 * np.log10(peak_mag / noise_floor) if noise_floor > 0 else 0
    snr_single = np.mean([
        10 * np.log10(np.max(data[i]) / np.mean(np.sort(data[i])[:n_bins // 4]))
        for i in range(n_frames)
    ])

    print(f"\n=== SNR Comparison ===")
    print(f"  Single-frame mean SNR: {snr_single:.1f} dB")
    print(f"  Averaged SNR ({n_frames} frames): {snr_averaged:.1f} dB")
    print(f"  Theoretical improvement: {10*np.log10(np.sqrt(n_frames)):.1f} dB")
    print(f"  Actual improvement: {snr_averaged - snr_single:.1f} dB")

    if args.output:
        with open(args.output, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['bin', 'avg_magnitude', 'std', 'se', 'z_score', 'dist_m'])
            for b in range(n_bins):
                z = (avg_mag_simple[b] - noise_floor) / se_mag[b] if se_mag[b] > 0 else 0
                w.writerow([b, f"{avg_mag_simple[b]:.6f}", f"{std_mag[b]:.6f}",
                           f"{se_mag[b]:.6f}", f"{z:.3f}",
                           f"{b * RANGE_PER_SAMPLE:.3f}"])
        print(f"\nSaved averaged profile to {args.output}")


if __name__ == '__main__':
    main()
