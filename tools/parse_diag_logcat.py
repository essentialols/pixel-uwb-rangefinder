#!/usr/bin/env python3
"""Parse UWB diagnostic data from logcat output into CSV.

Extracts:
- Ranging reports: sequence, session_id, rssi, status, elapsed_nanos, raw_ntf_data
- Diagnostic packets: session_token, sequence_number, frame_reports with rssi/aoa/cir
"""

import re
import sys
import csv
import json
from pathlib import Path


def parse_ranging_report(line):
    """Extract fields from a RangingReport logcat line."""
    m = re.search(r'SeqCounter = (\d+)', line)
    seq = int(m.group(1)) if m else None

    m = re.search(r'SessionId = (\d+)', line)
    session = int(m.group(1)) if m else None

    m = re.search(r'RSSI = (-?\d+)', line)
    rssi = int(m.group(1)) if m else None

    m = re.search(r'RangingStatus = (\d+)', line)
    status = int(m.group(1)) if m else None

    m = re.search(r'Distance = (\d+)', line)
    distance = int(m.group(1)) if m else None

    m = re.search(r'CurrRangingInterval = (\d+)', line)
    interval = int(m.group(1)) if m else None

    m = re.search(r'RawNotificationData = \[([^\]]+)\]', line)
    raw = m.group(1) if m else ''

    m = re.search(r'elapsed real time nanos: (\d+)', line)
    elapsed = int(m.group(1)) if m else None

    return {
        'type': 'ranging',
        'seq': seq,
        'session': session,
        'rssi': rssi,
        'status': status,
        'distance': distance,
        'interval': interval,
        'elapsed_nanos': elapsed,
        'raw_ntf': raw,
    }


def parse_diagnostic_packet(line):
    """Extract fields from a ParsedDiagnosticNtfPacket logcat line."""
    m = re.search(r'session_token: (\d+)', line)
    session = int(m.group(1)) if m else None

    m = re.search(r'sequence_number: (\d+)', line)
    seq = int(m.group(1)) if m else None

    frames = []
    for fm in re.finditer(r'FrameReport \{([^}]+)\}', line):
        frame_str = fm.group(1)
        frame = {}
        for k in ['uwb_msg_id', 'action', 'antenna_set']:
            km = re.search(rf'{k}: (\d+)', frame_str)
            frame[k] = int(km.group(1)) if km else None

        rm = re.search(r'rssi: \[([^\]]*)\]', frame_str)
        frame['rssi'] = rm.group(1) if rm else ''

        am = re.search(r'aoa: \[([^\]]*)\]', frame_str)
        frame['aoa'] = am.group(1) if am else ''

        cm = re.search(r'cir: \[([^\]]*)\]', frame_str)
        frame['cir'] = cm.group(1) if cm else ''

        frames.append(frame)

    return {
        'type': 'diagnostic',
        'session': session,
        'seq': seq,
        'frame_count': len(frames),
        'frames': frames,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <raw_logcat.txt> [output_dir]")
        sys.exit(1)

    infile = Path(sys.argv[1])
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else infile.parent

    ranging_rows = []
    diag_rows = []

    with open(infile) as f:
        for line in f:
            if 'onRangeDataNotificationReceived' in line or 'SeqCounter' in line:
                r = parse_ranging_report(line)
                if r['seq'] is not None:
                    ranging_rows.append(r)

            if 'ParsedDiagnosticNtfPacket' in line:
                d = parse_diagnostic_packet(line)
                if d['seq'] is not None:
                    diag_rows.append(d)

    ranging_csv = outdir / 'ranging_data.csv'
    with open(ranging_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'seq', 'session', 'rssi', 'status', 'distance',
            'interval', 'elapsed_nanos', 'raw_ntf',
        ])
        w.writeheader()
        for r in ranging_rows:
            row = {k: r[k] for k in w.fieldnames}
            w.writerow(row)

    diag_csv = outdir / 'diagnostic_data.csv'
    with open(diag_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'seq', 'session', 'frame_count',
            'frame0_msg_id', 'frame0_rssi', 'frame0_cir',
            'frame1_msg_id', 'frame1_rssi', 'frame1_cir',
            'frame2_msg_id', 'frame2_rssi', 'frame2_cir',
        ])
        w.writeheader()
        for d in diag_rows:
            row = {'seq': d['seq'], 'session': d['session'],
                   'frame_count': d['frame_count']}
            for i, fr in enumerate(d['frames'][:3]):
                row[f'frame{i}_msg_id'] = fr.get('uwb_msg_id')
                row[f'frame{i}_rssi'] = fr.get('rssi')
                row[f'frame{i}_cir'] = fr.get('cir')
            w.writerow(row)

    print(f"Ranging reports: {len(ranging_rows)} -> {ranging_csv}")
    print(f"Diagnostic packets: {len(diag_rows)} -> {diag_csv}")

    if ranging_rows:
        rssi_vals = [r['rssi'] for r in ranging_rows if r['rssi'] is not None and r['rssi'] != -128]
        if rssi_vals:
            print(f"RSSI: min={min(rssi_vals)}, max={max(rssi_vals)}, mean={sum(rssi_vals)/len(rssi_vals):.1f}")
        else:
            print("RSSI: all -128 (no responder)")


if __name__ == '__main__':
    main()
