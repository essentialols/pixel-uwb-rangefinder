#!/usr/bin/env python3
"""
cir_phase_analysis.py -- Analyze I/Q phase data from raw CIR captures

Decodes raw hex CIR captures to extract phase information. Phase stability
vs. randomness distinguishes stale RAM artifacts from live correlator output:
- Stale RAM: deterministic phases, exact same values across captures
- Live correlator noise: random phases, uniform distribution [-180, 180]
- Real signal: coherent phases with SNR-dependent jitter

Also compares captures from different sessions/configurations to identify
which bins are actually being updated by the correlator.

Usage:
  python3 cir_phase_analysis.py data/cir_captures/capture_*.txt
"""

import sys
import os
import struct
import math
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def decode_fixed618(raw_bytes):
    return int.from_bytes(raw_bytes, 'little', signed=True) / (1 << 18)


def parse_hex_capture(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    hex_str = ''
    for line in lines:
        if line.startswith('CIR DATA') or line.startswith('Opening') or line.startswith('File') or line.startswith('Timeout'):
            continue
        cleaned = line.strip().replace(' ', '')
        if all(c in '0123456789abcdef' for c in cleaned) and len(cleaned) > 0:
            hex_str += cleaned

    if not hex_str:
        return None

    data = bytes.fromhex(hex_str)
    if len(data) < 48:
        return None

    count = struct.unpack_from('<I', data, 0)[0]
    ts = struct.unpack_from('<Q', data, 8)[0]
    fp_idx = struct.unpack_from('<H', data, 40)[0]
    acc = struct.unpack_from('<H', data, 44)[0]

    n_records = (len(data) - 48) // 6
    samples = []
    for i in range(n_records):
        off = 48 + i * 6
        if off + 6 > len(data):
            break
        real_bytes = data[off:off+3]
        imag_bytes = data[off+3:off+6]
        real = decode_fixed618(real_bytes)
        imag = decode_fixed618(imag_bytes)
        mag = math.sqrt(real**2 + imag**2)
        phase = math.atan2(imag, real) * 180 / math.pi
        raw_real = int.from_bytes(real_bytes, 'little', signed=True)
        raw_imag = int.from_bytes(imag_bytes, 'little', signed=True)
        samples.append({
            'real': real, 'imag': imag, 'mag': mag, 'phase': phase,
            'raw_real': raw_real, 'raw_imag': raw_imag,
            'hex_real': real_bytes.hex(), 'hex_imag': imag_bytes.hex(),
        })

    return {
        'count': count, 'ts': ts, 'fp_index': fp_idx, 'acc': acc,
        'n_samples': len(samples), 'samples': samples,
        'raw_hex': hex_str[:96] + '...',
    }


def analyze_phases(captures):
    if not captures:
        return

    n = len(captures[0]['samples'])

    print(f"\n=== Phase Analysis ({len(captures)} captures, {n} bins) ===\n")

    # Per-bin phase across captures
    print(f"{'bin':>4s} {'mag_mean':>8s} {'phase_mean':>10s} {'phase_std':>9s} "
          f"{'raw_I':>8s} {'raw_Q':>8s} {'identical':>9s}")
    print("-" * 65)

    all_identical = 0
    all_varying = 0

    for b in range(n):
        phases = [c['samples'][b]['phase'] for c in captures]
        mags = [c['samples'][b]['mag'] for c in captures]
        raw_reals = [c['samples'][b]['raw_real'] for c in captures]
        raw_imags = [c['samples'][b]['raw_imag'] for c in captures]

        mean_mag = sum(mags) / len(mags)
        mean_phase = sum(phases) / len(phases)
        phase_std = math.sqrt(sum((p - mean_phase)**2 for p in phases) / len(phases)) if len(phases) > 1 else 0

        identical_iq = all(r == raw_reals[0] for r in raw_reals) and \
                       all(i == raw_imags[0] for i in raw_imags)
        ident_str = "YES" if identical_iq else "no"

        if identical_iq:
            all_identical += 1
        else:
            all_varying += 1

        print(f"{b:4d} {mean_mag:8.4f} {mean_phase:+10.1f} {phase_std:9.1f} "
              f"{raw_reals[0]:8d} {raw_imags[0]:8d} {ident_str:>9s}")

    print(f"\n  Bins with identical I/Q across all captures: {all_identical}/{n}")
    print(f"  Bins with varying I/Q: {all_varying}/{n}")

    if all_identical == n:
        print(f"  CONCLUSION: ALL bins identical -> pure stale RAM, correlator never wrote")
    elif all_identical > n * 0.5:
        print(f"  CONCLUSION: Majority stale RAM, some bins updated by correlator")
    else:
        print(f"  CONCLUSION: Most bins vary -> correlator is writing (may still be noise)")


def compare_captures_detailed(captures):
    if len(captures) < 2:
        return

    print(f"\n=== Capture-to-Capture Raw Byte Comparison ===\n")

    ref = captures[0]
    for i, cap in enumerate(captures[1:], 1):
        diffs = 0
        diff_bins = []
        for b in range(min(len(ref['samples']), len(cap['samples']))):
            if ref['samples'][b]['hex_real'] != cap['samples'][b]['hex_real'] or \
               ref['samples'][b]['hex_imag'] != cap['samples'][b]['hex_imag']:
                diffs += 1
                diff_bins.append(b)

        bins_str = ' (bins: ' + ','.join(map(str, diff_bins[:10])) + ')' if diff_bins else ''
        print(f"  Capture 0 vs {i}: {diffs} bins differ{bins_str}")


def main():
    parser = argparse.ArgumentParser(description="CIR phase analysis")
    parser.add_argument('inputs', nargs='+', help='Capture text files')
    args = parser.parse_args()

    captures = []
    for path in args.inputs:
        cap = parse_hex_capture(path)
        if cap:
            print(f"Loaded {path}: count={cap['count']}, ts={cap['ts']}, "
                  f"samples={cap['n_samples']}, fp_index={cap['fp_index']}")
            captures.append(cap)
        else:
            print(f"Skipped {path}: no valid CIR data")

    if not captures:
        print("No valid captures found")
        return

    analyze_phases(captures)
    compare_captures_detailed(captures)

    # Check if phases are uniformly distributed (would indicate noise)
    if captures:
        all_phases = [s['phase'] for c in captures for s in c['samples']]
        n_bins_hist = 12
        hist = [0] * n_bins_hist
        for p in all_phases:
            bin_idx = int((p + 180) / 360 * n_bins_hist)
            bin_idx = min(bin_idx, n_bins_hist - 1)
            hist[bin_idx] += 1

        print(f"\n=== Phase Distribution (all captures combined) ===")
        total = len(all_phases)
        expected = total / n_bins_hist
        chi2 = sum((h - expected)**2 / expected for h in hist)
        print(f"  Phase histogram ({n_bins_hist} bins, {total} samples):")
        for i, h in enumerate(hist):
            angle = -180 + i * 360 / n_bins_hist
            bar = '#' * int(h / total * 60)
            print(f"    [{angle:+6.0f}deg]: {h:4d} {bar}")
        print(f"  Chi-squared: {chi2:.1f} (uniform: ~{n_bins_hist-1})")
        if chi2 > 30:
            print(f"  RESULT: Non-uniform phase distribution -> NOT pure thermal noise")
        else:
            print(f"  RESULT: Approximately uniform -> consistent with thermal noise")


if __name__ == '__main__':
    main()
