#!/usr/bin/env python3
"""
capture_uci_diag.py -- Capture UCI diagnostic notifications from Android logcat

Streams logcat, parses ParsedDiagnosticNtfPacket entries, and extracts:
- Frame reports (TX/RX) with antenna sets
- RSSI values
- AoA data
- CIR (Channel Impulse Response) samples
- Segment metrics

Usage:
  # Live capture from device via H1:
  ssh h1 "adb logcat" | python3 tools/capture_uci_diag.py

  # From saved logcat file:
  python3 tools/capture_uci_diag.py saved_logcat.txt

  # With JSON output:
  ssh h1 "adb logcat" | python3 tools/capture_uci_diag.py --json

  # Save CIR data to CSV:
  ssh h1 "adb logcat" | python3 tools/capture_uci_diag.py --csv cir_data.csv
"""

import sys
import re
import json
import csv
import argparse
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class FrameReport:
    uwb_msg_id: int  # 0=RCPU, 1=RIM, 2=RFM, 3=RCM
    action: int  # 0=RX, 1=TX
    antenna_set: int
    rssi: list = field(default_factory=list)
    aoa: list = field(default_factory=list)
    cir: list = field(default_factory=list)
    segment_metrics: dict = field(default_factory=dict)

    @property
    def msg_name(self) -> str:
        names = {0: "RCPU", 1: "RIM", 2: "RFM", 3: "RCM"}
        return names.get(self.uwb_msg_id, f"MSG{self.uwb_msg_id}")

    @property
    def action_name(self) -> str:
        return "RX" if self.action == 0 else "TX"


@dataclass
class DiagnosticPacket:
    timestamp: str
    session_token: int
    sequence_number: int
    frame_reports: list = field(default_factory=list)


def parse_frame_report(text: str) -> FrameReport:
    """Parse a FrameReport from its string representation."""
    report = FrameReport(uwb_msg_id=0, action=0, antenna_set=0)

    m = re.search(r'uwb_msg_id:\s*(\d+)', text)
    if m:
        report.uwb_msg_id = int(m.group(1))

    m = re.search(r'action:\s*(\d+)', text)
    if m:
        report.action = int(m.group(1))

    m = re.search(r'antenna_set:\s*(\d+)', text)
    if m:
        report.antenna_set = int(m.group(1))

    # Parse RSSI array
    m = re.search(r'rssi:\s*\[([^\]]*)\]', text)
    if m and m.group(1).strip():
        try:
            report.rssi = [int(x.strip()) for x in m.group(1).split(',') if x.strip()]
        except ValueError:
            pass

    # Parse AoA array
    m = re.search(r'aoa:\s*\[([^\]]*)\]', text)
    if m and m.group(1).strip():
        report.aoa = m.group(1).strip()

    # Parse CIR array
    m = re.search(r'cir:\s*\[([^\]]*)\]', text)
    if m and m.group(1).strip():
        report.cir = m.group(1).strip()

    return report


def parse_diagnostic_line(line: str) -> Optional[DiagnosticPacket]:
    """Parse a logcat line containing a ParsedDiagnosticNtfPacket."""
    m = re.search(r'Received diagnostic packet:\s*Ok\(ParsedDiagnosticNtfPacket\s*\{(.+)\}\)', line)
    if not m:
        return None

    content = m.group(1)

    # Extract timestamp from logcat line
    ts_match = re.match(r'^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})', line)
    timestamp = ts_match.group(1) if ts_match else ""

    packet = DiagnosticPacket(timestamp=timestamp, session_token=0, sequence_number=0)

    # Parse top-level fields
    st = re.search(r'session_token:\s*(\d+)', content)
    if st:
        packet.session_token = int(st.group(1))

    sn = re.search(r'sequence_number:\s*(\d+)', content)
    if sn:
        packet.sequence_number = int(sn.group(1))

    # Parse frame reports
    # Find all FrameReport blocks
    fr_pattern = r'FrameReport\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}'
    for fr_match in re.finditer(fr_pattern, content):
        report = parse_frame_report(fr_match.group(1))
        packet.frame_reports.append(report)

    return packet


def print_packet(packet: DiagnosticPacket, verbose: bool = False):
    """Print a diagnostic packet in human-readable format."""
    print(f"[{packet.timestamp}] seq={packet.sequence_number} session={packet.session_token}")
    for fr in packet.frame_reports:
        rssi_str = f" RSSI={fr.rssi}" if fr.rssi else ""
        cir_str = f" CIR={fr.cir}" if fr.cir else ""
        aoa_str = f" AoA={fr.aoa}" if fr.aoa else ""
        print(f"  {fr.msg_name} {fr.action_name} ant={fr.antenna_set}{rssi_str}{aoa_str}{cir_str}")
        if verbose and fr.segment_metrics:
            print(f"    segments: {fr.segment_metrics}")


def main():
    parser = argparse.ArgumentParser(description="Capture UCI diagnostic notifications")
    parser.add_argument('input', nargs='?', help='Logcat file (default: stdin)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--csv', type=str, help='Save CIR data to CSV file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--summary', action='store_true', help='Print summary at end')
    args = parser.parse_args()

    if args.input:
        source = open(args.input)
    else:
        source = sys.stdin

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, 'w', newline='')
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['timestamp', 'session', 'sequence', 'msg_id', 'msg_name',
                           'action', 'antenna_set', 'rssi', 'has_cir', 'has_aoa'])

    packets = []
    rx_count = 0
    tx_count = 0
    cir_count = 0

    try:
        for line in source:
            line = line.rstrip()
            if 'diagnostic packet' not in line:
                continue

            packet = parse_diagnostic_line(line)
            if not packet:
                continue

            packets.append(packet)

            if args.json:
                out = asdict(packet)
                print(json.dumps(out))
            else:
                print_packet(packet, args.verbose)

            for fr in packet.frame_reports:
                if fr.action == 0:
                    rx_count += 1
                else:
                    tx_count += 1
                if fr.cir:
                    cir_count += 1

                if csv_writer:
                    csv_writer.writerow([
                        packet.timestamp,
                        packet.session_token,
                        packet.sequence_number,
                        fr.uwb_msg_id,
                        fr.msg_name,
                        fr.action_name,
                        fr.antenna_set,
                        fr.rssi[0] if fr.rssi else '',
                        bool(fr.cir),
                        bool(fr.aoa),
                    ])

            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        if csv_file:
            csv_file.close()

    if args.summary or (source != sys.stdin and not args.json):
        print(f"\n--- Summary ---")
        print(f"Total packets: {len(packets)}")
        print(f"TX reports: {tx_count}")
        print(f"RX reports: {rx_count}")
        print(f"Reports with CIR: {cir_count}")
        if packets:
            print(f"Sequence range: {packets[0].sequence_number} - {packets[-1].sequence_number}")


if __name__ == '__main__':
    main()
