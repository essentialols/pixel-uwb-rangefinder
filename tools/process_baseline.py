#!/usr/bin/env python3
"""
process_baseline.py -- Feed baseline CIR captures through CIRProcessor

Reads per-bin magnitude CSV plus the per-frame stats CSV and runs CIRProcessor
on each frame to get leading-edge detection, multipath, NLOS estimates.
"""

import sys
import os
import csv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cir_processing import CIRProcessor, RANGE_PER_SAMPLE_ONEWAY


def load_magnitudes(path):
    frames = []
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            mags = [float(x) for x in row[1:]]
            frames.append(mags)
    return frames


def load_stats(path):
    stats = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats.append(row)
    return stats


def main():
    mag_path = "data/cir_captures/baseline_50ms_64bins_mags.csv"
    stats_path = "data/cir_captures/baseline_50ms_64bins.csv"

    frames = load_magnitudes(mag_path)
    stats = load_stats(stats_path)

    proc = CIRProcessor(noise_threshold_db=6.0)

    print(f"Processing {len(frames)} frames through CIRProcessor\n")
    print(f"{'frame':>5s} {'fp_hw':>5s} {'fp_ref':>7s} {'peak':>5s} {'peak_ref':>8s} "
          f"{'snr':>6s} {'nlos':>5s} {'paths':>5s} {'dist_ref':>8s}")
    print("-" * 65)

    all_results = []
    for i, (mags, st) in enumerate(zip(frames, stats)):
        fp_index = int(st.get('fp_index', 0))

        cir_complex = np.array([m + 0j for m in mags])

        result = proc.process(cir_complex, fp_index=fp_index)
        all_results.append(result)

        print(f"{i:5d} {result.fp_index_hw:5d} {result.fp_index_refined:7.2f} "
              f"{result.peak_index:5d} {result.peak_index_refined:8.2f} "
              f"{result.snr_db:6.1f} {result.nlos_likelihood:5.2f} "
              f"{result.num_paths:5d} {result.distance_refined:8.2f}m")

    # Summary
    print(f"\n=== Summary ===")
    snrs = [r.snr_db for r in all_results]
    nlos_vals = [r.nlos_likelihood for r in all_results]
    n_paths = [r.num_paths for r in all_results]
    peak_indices = [r.peak_index for r in all_results]

    print(f"  SNR: {min(snrs):.1f} to {max(snrs):.1f} dB (mean: {np.mean(snrs):.1f})")
    print(f"  NLOS likelihood: {min(nlos_vals):.2f} to {max(nlos_vals):.2f} (mean: {np.mean(nlos_vals):.2f})")
    print(f"  Paths detected: {min(n_paths)} to {max(n_paths)} (mean: {np.mean(n_paths):.1f})")

    from collections import Counter
    peak_counts = Counter(peak_indices)
    print(f"  Peak bin distribution:")
    for bin_idx, count in peak_counts.most_common():
        print(f"    bin {bin_idx}: {count} frames ({count/len(all_results)*100:.0f}%)")

    # Noise floor consistency
    noise_floors = [r.noise_floor for r in all_results]
    print(f"  Noise floor: {min(noise_floors):.4f} to {max(noise_floors):.4f} "
          f"(std: {np.std(noise_floors):.4f})")

    # Key question: does this look like real CIR data?
    print(f"\n=== Signal Quality Assessment ===")
    mean_snr = np.mean(snrs)
    if mean_snr < 10:
        print(f"  SNR {mean_snr:.1f} dB: BELOW typical UWB signal (20-30 dB)")
        print(f"  This is consistent with noise/artifact, NOT a real UWB frame reception")
    else:
        print(f"  SNR {mean_snr:.1f} dB: within UWB signal range")

    nf_cov = np.std(noise_floors) / np.mean(noise_floors)
    print(f"  Noise floor CoV: {nf_cov:.4f}")
    if nf_cov < 0.05:
        print(f"  Extremely stable noise floor: consistent with CIR RAM artifacts")
        print(f"  Real receiver noise would show more variation (thermal noise is stochastic)")


if __name__ == '__main__':
    main()
