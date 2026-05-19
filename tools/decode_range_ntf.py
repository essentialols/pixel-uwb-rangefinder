#!/usr/bin/env python3
"""
decode_range_ntf.py -- Decode UCI RANGE_DATA_NTF raw notification data

Parses the raw_ntf_data bytes from Android UWB ranging reports.
This is the UCI (UWB Command Interface) notification payload.

UCI RANGE_DATA_NTF format (UCI Spec v1.1, section 8.3):
  Bytes 0-3:   Sequence number (uint32 LE)
  Byte  4:     Session ID (uint32 LE, actually only byte 4 used)
  Bytes 5-7:   Reserved
  Byte  8:     RCR Indication (Range Control Result)
  Byte  9:     Current Ranging Interval (uint8)
  Bytes 10-11: Reserved
  Byte  12:    Ranging Measurement Type
  Byte  13:    Reserved
  Byte  14:    MAC Addressing Mode Indicator
  Bytes 15+:   Per-measurement data
"""

import sys
import struct
import re


def decode_ntf(raw_bytes):
    """Decode a UCI RANGE_DATA_NTF raw notification."""
    if len(raw_bytes) < 16:
        print(f"  Too short ({len(raw_bytes)} bytes)")
        return

    seq = struct.unpack_from('<I', raw_bytes, 0)[0]
    session_id = struct.unpack_from('<I', raw_bytes, 4)[0]
    rcr = raw_bytes[8]
    current_interval = raw_bytes[9]
    meas_type = raw_bytes[12]
    num_measurements = raw_bytes[13] if len(raw_bytes) > 13 else 0

    print(f"  Sequence: {seq}")
    print(f"  Session ID: {session_id}")
    print(f"  RCR Indication: 0x{rcr:02X}")
    print(f"  Current Interval: {current_interval}")
    print(f"  Measurement Type: {meas_type}")
    print(f"  Num Measurements: {num_measurements}")

    # Byte 24+: measurement data (varies by type)
    if len(raw_bytes) > 24:
        print(f"  Measurement data ({len(raw_bytes)-24} bytes):")
        for i in range(24, len(raw_bytes), 16):
            chunk = raw_bytes[i:min(i+16, len(raw_bytes))]
            hex_str = ' '.join(f'{b:02X}' for b in chunk)
            print(f"    [{i:3d}] {hex_str}")

    # Full hex dump
    print(f"  Full hex ({len(raw_bytes)} bytes):")
    for i in range(0, len(raw_bytes), 16):
        chunk = raw_bytes[i:min(i+16, len(raw_bytes))]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"    {i:04X}: {hex_str:<48s} {ascii_str}")


def parse_java_array(s):
    """Parse Java signed byte array string like '[0, -56, 0, 127, ...]'"""
    s = s.strip('[]')
    vals = [int(x.strip()) for x in s.split(',') if x.strip()]
    # Java bytes are signed, convert to unsigned
    return bytes(v & 0xFF for v in vals)


def main():
    if len(sys.argv) > 1:
        text = open(sys.argv[1]).read()
    else:
        text = sys.stdin.read()

    # Find all raw_ntf_data arrays
    pattern = r'raw_ntf_data=\[([^\]]+)\]'
    matches = re.findall(pattern, text)

    if not matches:
        print("No raw_ntf_data found in input")
        return

    print(f"Found {len(matches)} raw notifications\n")

    for i, match in enumerate(matches):
        data = parse_java_array(match)
        print(f"--- Notification {i} ({len(data)} bytes) ---")
        decode_ntf(data)
        print()

    # Check for incrementing sequence numbers
    if len(matches) >= 2:
        seqs = []
        for m in matches:
            data = parse_java_array(m)
            if len(data) >= 4:
                seqs.append(struct.unpack_from('<I', data, 0)[0])
        if seqs:
            intervals = [seqs[i+1] - seqs[i] for i in range(len(seqs)-1)]
            print(f"--- Sequence Analysis ---")
            print(f"  Range: {seqs[0]} to {seqs[-1]}")
            print(f"  Count: {len(seqs)}")
            if intervals:
                print(f"  Intervals: {set(intervals)}")


if __name__ == '__main__':
    main()
