#!/usr/bin/env python3
"""
cir_noise_characterize.py -- Characterize DW3000 receiver noise from CIR captures

Analyzes the noise properties of CIR data captured during RXPTO (no signal):
- Noise amplitude distribution (should be Rayleigh for I/Q magnitude)
- Noise power spectral density
- Bin-to-bin correlation (adjacent bins should be independent for white noise)
- Temporal autocorrelation across frames
- Estimation of receiver noise figure from measured noise floor

Physical model:
  CIR magnitude during RXPTO = |correlator_output| where correlator_output is
  the cross-correlation of receiver thermal noise with the preamble template.
  For uncorrelated noise input, the correlator output at each bin is complex
  Gaussian, so the magnitude follows a Rayleigh distribution.

Usage:
  python3 cir_noise_characterize.py data/cir_captures/baseline_50ms_64bins_mags.csv
"""

import sys
import os
import csv
import argparse
import numpy as np
try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPEED_OF_LIGHT = 299792458.0
UWB_BANDWIDTH = 499.2e6
K_BOLTZMANN = 1.38e-23
TEMP_KELVIN = 300


def load_magnitudes(path):
    frames = []
    with open(path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            mags = [float(x) for x in row[1:]]
            frames.append(mags)
    return np.array(frames)


def rayleigh_fit(data):
    flat = data.flatten()
    flat = flat[flat > 0]
    sigma = np.sqrt(np.mean(flat**2) / 2)
    _, p_value = scipy_stats.kstest(flat, 'rayleigh', args=(0, sigma))
    return sigma, p_value


def spatial_correlation(data):
    n_frames, n_bins = data.shape
    correlations = []
    for lag in range(1, min(10, n_bins)):
        corrs = []
        for f in range(n_frames):
            c = np.corrcoef(data[f, :n_bins-lag], data[f, lag:])[0, 1]
            if not np.isnan(c):
                corrs.append(c)
        correlations.append(np.mean(corrs) if corrs else 0)
    return correlations


def temporal_correlation(data):
    n_frames, n_bins = data.shape
    correlations = []
    for lag in range(1, min(10, n_frames)):
        corrs = []
        for b in range(n_bins):
            if np.std(data[:, b]) > 0:
                c = np.corrcoef(data[:n_frames-lag, b], data[lag:, b])[0, 1]
                if not np.isnan(c):
                    corrs.append(c)
        correlations.append(np.mean(corrs) if corrs else 0)
    return correlations


def classify_bins_by_noise(data):
    n_frames, n_bins = data.shape
    results = []

    for b in range(n_bins):
        col = data[:, b]
        if np.all(col == 0):
            results.append({'bin': b, 'class': 'zero', 'mean': 0, 'std': 0, 'cov': 0})
            continue

        mean = np.mean(col)
        std = np.std(col)
        cov = std / mean if mean > 0 else 0

        n_unique = len(np.unique(np.round(col, 6)))

        if n_unique <= 2:
            cls = 'constant'
        elif cov < 0.05:
            cls = 'low_noise'
        elif cov < 0.2:
            cls = 'moderate_noise'
        else:
            cls = 'high_noise'

        results.append({'bin': b, 'class': cls, 'mean': mean, 'std': std,
                        'cov': cov, 'n_unique': n_unique})

    return results


def main():
    parser = argparse.ArgumentParser(description="CIR noise characterization")
    parser.add_argument('input', help='Per-bin magnitudes CSV')
    args = parser.parse_args()

    data = load_magnitudes(args.input)
    n_frames, n_bins = data.shape

    # Remove zero-padding bins
    nonzero_mask = np.any(data > 0, axis=0)
    active_bins = np.sum(nonzero_mask)
    active_data = data[:, nonzero_mask]

    print(f"=== CIR Noise Characterization ===")
    print(f"Frames: {n_frames}, Bins: {n_bins} ({active_bins} active)\n")

    # 1. Overall noise statistics
    all_mags = active_data.flatten()
    print(f"--- Magnitude Distribution ---")
    print(f"  Mean: {np.mean(all_mags):.4f}")
    print(f"  Std:  {np.std(all_mags):.4f}")
    print(f"  Min:  {np.min(all_mags):.4f}")
    print(f"  Max:  {np.max(all_mags):.4f}")
    print(f"  Median: {np.median(all_mags):.4f}")

    # 2. Rayleigh fit test
    if HAS_SCIPY:
        try:
            sigma, p_value = rayleigh_fit(active_data)
            print(f"\n--- Rayleigh Fit ---")
            print(f"  Sigma: {sigma:.4f}")
            print(f"  KS p-value: {p_value:.6f}")
            if p_value > 0.05:
                print(f"  RESULT: Data consistent with Rayleigh (receiver noise)")
            else:
                print(f"  RESULT: Data NOT Rayleigh (structured/artifact content)")
        except Exception as e:
            print(f"\n--- Rayleigh Fit: {e} ---")
    else:
        sigma = np.sqrt(np.mean(all_mags**2) / 2)
        print(f"\n--- Rayleigh Fit (scipy not available, basic estimate) ---")
        print(f"  Sigma: {sigma:.4f}")
        expected_mean = sigma * np.sqrt(np.pi / 2)
        print(f"  Expected Rayleigh mean: {expected_mean:.4f}")
        print(f"  Actual mean: {np.mean(all_mags):.4f}")
        ratio = np.mean(all_mags) / expected_mean if expected_mean > 0 else 0
        print(f"  Ratio: {ratio:.3f} (1.0 = perfect Rayleigh)")

    # 3. Spatial correlation (bin-to-bin)
    print(f"\n--- Spatial Correlation (bin-to-bin) ---")
    spatial = spatial_correlation(active_data)
    for lag, corr in enumerate(spatial, 1):
        sig = " ***" if abs(corr) > 0.2 else ""
        print(f"  Lag {lag}: r={corr:+.4f}{sig}")
    if all(abs(c) < 0.2 for c in spatial[:3]):
        print(f"  RESULT: Bins are approximately independent (white noise)")
    else:
        print(f"  RESULT: Adjacent bins correlated (colored noise or artifacts)")

    # 4. Temporal correlation (frame-to-frame)
    print(f"\n--- Temporal Correlation (frame-to-frame) ---")
    temporal = temporal_correlation(active_data)
    for lag, corr in enumerate(temporal, 1):
        sig = " ***" if abs(corr) > 0.2 else ""
        print(f"  Lag {lag}: r={corr:+.4f}{sig}")
    if all(abs(c) < 0.2 for c in temporal[:3]):
        print(f"  RESULT: Frames are approximately independent (no temporal structure)")
    else:
        print(f"  RESULT: Temporal correlation detected (may indicate systematic pattern)")

    # 5. Per-bin classification
    print(f"\n--- Per-Bin Noise Classification ---")
    classifications = classify_bins_by_noise(data)
    class_counts = {}
    for c in classifications:
        cls = c['class']
        class_counts[cls] = class_counts.get(cls, 0) + 1

    for cls, count in sorted(class_counts.items()):
        print(f"  {cls}: {count} bins")
        examples = [c for c in classifications if c['class'] == cls][:3]
        for ex in examples:
            print(f"    bin {ex['bin']}: mean={ex['mean']:.4f}, std={ex['std']:.4f}, "
                  f"cov={ex['cov']:.3f}")

    # 6. Noise figure estimation
    print(f"\n--- Receiver Noise Estimate ---")
    noise_power_linear = np.mean(all_mags**2)
    thermal_noise_power = K_BOLTZMANN * TEMP_KELVIN * UWB_BANDWIDTH
    print(f"  Measured noise power (CIR units): {noise_power_linear:.6f}")
    print(f"  Thermal noise floor (kTB): {thermal_noise_power:.2e} W")
    print(f"  Note: absolute calibration requires knowledge of CIR-to-power")
    print(f"  conversion factor (accumulator gain, ADC scaling, etc.)")

    # 7. Signal detection threshold
    noise_mean = np.mean(all_mags)
    noise_std = np.std(all_mags)
    thresholds = {
        '3-sigma (99.7%)': noise_mean + 3 * noise_std,
        '5-sigma (99.99994%)': noise_mean + 5 * noise_std,
        'CFAR 10dB': noise_mean * 10**(10/20),
    }
    print(f"\n--- Signal Detection Thresholds ---")
    print(f"  Noise floor: {noise_mean:.4f} +/- {noise_std:.4f}")
    for name, thresh in thresholds.items():
        print(f"  {name}: {thresh:.4f}")
    print(f"\n  A reflector signal above these thresholds is detectable")
    print(f"  in a SINGLE frame (no averaging needed)")


if __name__ == '__main__':
    main()
