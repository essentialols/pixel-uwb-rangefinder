#!/usr/bin/env python3
"""
decode_cir.py -- Decode CIR data from DW3000 debugfs cir_data

The debugfs cir_data file outputs dw3000_cir_data starting from the 'count' field:
  count:     u32 (4 bytes)
  filter:    u32 (4 bytes)
  ts:        u64 (8 bytes)
  utime:     u64 (8 bytes)
  fp_power1: u32 (4 bytes)
  fp_power2: u32 (4 bytes)
  fp_power3: u32 (4 bytes)
  offset:    s32 (4 bytes)
  fp_index:  u16 (2 bytes)
  pdoa:      u16 (2 bytes)
  acc:       u16 (2 bytes)
  type:      u8  (1 byte)
  dummy:     u8  (1 byte)
  data[]:    N * 6 bytes (real[3] + imag[3], format 6.18 fixed-point)

Total header: 48 bytes. Each record: 6 bytes.

Usage:
  cir_reader 10 | decode_cir.py    # live from device
  decode_cir.py capture.bin        # from saved file
  decode_cir.py --hex "14000000 00000000 ..."  # from hex string
"""

import sys
import struct
import math
import argparse

def decode_fixed618(raw_bytes):
    return int.from_bytes(raw_bytes, 'little', signed=True) / (1 << 18)

def decode_cir(data):
    if len(data) < 48:
        print(f"Error: need at least 48 bytes header, got {len(data)}")
        return

    count = struct.unpack_from('<I', data, 0)[0]
    filt = struct.unpack_from('<I', data, 4)[0]
    ts = struct.unpack_from('<Q', data, 8)[0]
    utime = struct.unpack_from('<Q', data, 16)[0]
    fp1 = struct.unpack_from('<I', data, 24)[0]
    fp2 = struct.unpack_from('<I', data, 28)[0]
    fp3 = struct.unpack_from('<I', data, 32)[0]
    offset = struct.unpack_from('<i', data, 36)[0]
    fp_idx = struct.unpack_from('<H', data, 40)[0]
    pdoa = struct.unpack_from('<H', data, 42)[0]
    acc = struct.unpack_from('<H', data, 44)[0]
    cir_type = data[46]
    dummy = data[47]

    print(f"=== CIR Header ({len(data)} bytes total) ===")
    print(f"  count:     {count}")
    print(f"  filter:    0x{filt:08x}")
    print(f"  ts:        {ts}")
    print(f"  utime:     {utime}")
    print(f"  fp_power1: 0x{fp1:08x}")
    print(f"  fp_power2: 0x{fp2:08x}")
    print(f"  fp_power3: 0x{fp3:08x}")
    print(f"  offset:    {offset}")
    print(f"  fp_index:  {fp_idx}")
    print(f"  pdoa:      {pdoa} (raw)")
    print(f"  acc:       {acc}")
    print(f"  type:      {cir_type}")

    n_records = (len(data) - 48) // 6
    print(f"\n=== CIR I/Q Records ({n_records} samples) ===")
    print(f"{'idx':>4s} {'real':>10s} {'imag':>10s} {'mag':>10s} {'phase':>8s}")
    print("-" * 48)

    magnitudes = []
    for i in range(n_records):
        off = 48 + i * 6
        if off + 6 > len(data):
            break
        real = decode_fixed618(data[off:off+3])
        imag = decode_fixed618(data[off+3:off+6])
        mag = math.sqrt(real**2 + imag**2)
        phase = math.atan2(imag, real) * 180 / math.pi
        magnitudes.append(mag)
        print(f"{i:4d} {real:10.4f} {imag:10.4f} {mag:10.4f} {phase:8.1f}")

    if magnitudes:
        peak = max(magnitudes)
        peak_idx = magnitudes.index(peak)
        mean = sum(magnitudes) / len(magnitudes)
        print(f"\n=== Statistics ===")
        print(f"  Peak magnitude: {peak:.4f} at index {peak_idx}")
        print(f"  Mean magnitude: {mean:.4f}")
        print(f"  Peak/Mean ratio: {peak/mean:.1f}x" if mean > 0 else "")
        print(f"  Samples: {len(magnitudes)}")


def main():
    parser = argparse.ArgumentParser(description="Decode DW3000 CIR data")
    parser.add_argument('input', nargs='?', help='Binary CIR file')
    parser.add_argument('--hex', type=str, help='Hex string of CIR data')
    args = parser.parse_args()

    if args.hex:
        hex_str = args.hex.replace(' ', '').replace('\n', '')
        data = bytes.fromhex(hex_str)
    elif args.input:
        with open(args.input, 'rb') as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()

    decode_cir(data)


if __name__ == '__main__':
    main()
