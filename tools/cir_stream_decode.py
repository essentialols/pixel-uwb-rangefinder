#!/usr/bin/env python3
"""
cir_stream_decode.py -- Decode streaming CIR binary data

Reads binary stream from cir_stream (4-byte length + raw CIR per frame).
Outputs per-frame statistics and optionally saves to CSV.

Usage:
  cat capture.bin | python3 cir_stream_decode.py
  python3 cir_stream_decode.py capture.bin
  python3 cir_stream_decode.py capture.bin --csv output.csv
"""

import sys
import struct
import math
import argparse
import csv


def decode_fixed618(raw_bytes):
    return int.from_bytes(raw_bytes, 'little', signed=True) / (1 << 18)


def decode_frame(data):
    if len(data) < 48:
        return None

    count = struct.unpack_from('<I', data, 0)[0]
    ts = struct.unpack_from('<Q', data, 8)[0]
    fp1 = struct.unpack_from('<I', data, 24)[0]
    fp2 = struct.unpack_from('<I', data, 28)[0]
    fp3 = struct.unpack_from('<I', data, 32)[0]
    fp_idx = struct.unpack_from('<H', data, 40)[0]
    acc = struct.unpack_from('<H', data, 44)[0]

    n_records = (len(data) - 48) // 6
    samples = []
    for i in range(n_records):
        off = 48 + i * 6
        if off + 6 > len(data):
            break
        real = decode_fixed618(data[off:off+3])
        imag = decode_fixed618(data[off+3:off+6])
        mag = math.sqrt(real**2 + imag**2)
        samples.append((real, imag, mag))

    magnitudes = [s[2] for s in samples]
    peak_mag = max(magnitudes) if magnitudes else 0
    peak_idx = magnitudes.index(peak_mag) if magnitudes else 0
    mean_mag = sum(magnitudes) / len(magnitudes) if magnitudes else 0
    rms = math.sqrt(sum(m**2 for m in magnitudes) / len(magnitudes)) if magnitudes else 0

    return {
        'count': count,
        'ts': ts,
        'fp_index': fp_idx,
        'fp_power1': fp1,
        'acc': acc,
        'n_samples': len(samples),
        'peak_mag': peak_mag,
        'peak_idx': peak_idx,
        'mean_mag': mean_mag,
        'rms': rms,
        'snr_db': 20 * math.log10(peak_mag / rms) if rms > 0 else 0,
        'samples': samples,
    }


def main():
    parser = argparse.ArgumentParser(description="Decode CIR stream")
    parser.add_argument('input', nargs='?', help='Binary stream file (default: stdin)')
    parser.add_argument('--csv', type=str, help='Save per-frame stats to CSV')
    parser.add_argument('--full', action='store_true', help='Print all I/Q samples')
    parser.add_argument('--magnitudes', type=str, help='Save per-sample magnitudes CSV')
    args = parser.parse_args()

    if args.input:
        data = open(args.input, 'rb').read()
    else:
        data = sys.stdin.buffer.read()

    frames = []
    pos = 0
    while pos + 4 <= len(data):
        flen = struct.unpack_from('<I', data, pos)[0]
        if flen > 20000 or flen < 48:
            break
        frame_data = data[pos+4:pos+4+flen]
        frames.append(frame_data)
        pos += 4 + flen

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, 'w', newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['frame', 'ts', 'n_samples', 'peak_mag', 'peak_idx',
                           'mean_mag', 'rms', 'snr_db', 'fp_index', 'acc'])

    mag_writer = None
    mag_file = None
    if args.magnitudes:
        mag_file = open(args.magnitudes, 'w', newline='')
        mag_writer = csv.writer(mag_file)

    print(f"{'frame':>5s} {'ts':>16s} {'samples':>7s} {'peak':>8s} {'@idx':>5s} "
          f"{'mean':>8s} {'rms':>8s} {'SNR':>6s}")
    print("-" * 70)

    for i, frame_data in enumerate(frames):
        f = decode_frame(frame_data)
        if not f:
            continue

        print(f"{i:5d} {f['ts']:16d} {f['n_samples']:7d} {f['peak_mag']:8.4f} "
              f"{f['peak_idx']:5d} {f['mean_mag']:8.4f} {f['rms']:8.4f} "
              f"{f['snr_db']:6.1f}")

        if csv_writer:
            csv_writer.writerow([i, f['ts'], f['n_samples'], f['peak_mag'],
                               f['peak_idx'], f['mean_mag'], f['rms'],
                               f['snr_db'], f['fp_index'], f['acc']])

        if mag_writer:
            mags = [s[2] for s in f['samples']]
            if i == 0:
                mag_writer.writerow(['frame'] + [f'bin{j}' for j in range(len(mags))])
            mag_writer.writerow([i] + [f'{m:.6f}' for m in mags])

        if args.full:
            for j, (r, im, m) in enumerate(f['samples'][:20]):
                print(f"    [{j:3d}] real={r:8.4f} imag={im:8.4f} mag={m:8.4f}")
            if len(f['samples']) > 20:
                print(f"    ... {len(f['samples'])-20} more samples")

    print(f"\n=== Summary: {len(frames)} frames ===")
    if frames:
        all_peaks = [decode_frame(f)['peak_mag'] for f in frames if decode_frame(f)]
        all_means = [decode_frame(f)['mean_mag'] for f in frames if decode_frame(f)]
        ts_first = struct.unpack_from('<Q', frames[0], 8)[0]
        ts_last = struct.unpack_from('<Q', frames[-1], 8)[0]
        dt = (ts_last - ts_first) / 1e9 if len(frames) > 1 else 0
        print(f"  Duration: {dt:.1f}s")
        print(f"  Frame rate: {(len(frames)-1)/dt:.1f} fps" if dt > 0 else "")
        print(f"  Peak magnitude: {max(all_peaks):.4f} (frame avg: {sum(all_peaks)/len(all_peaks):.4f})")
        print(f"  Mean magnitude: {sum(all_means)/len(all_means):.4f}")

    if csv_file:
        csv_file.close()
        print(f"  Stats saved to {args.csv}")
    if mag_file:
        mag_file.close()
        print(f"  Magnitudes saved to {args.magnitudes}")


if __name__ == '__main__':
    main()
