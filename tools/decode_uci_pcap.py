#!/usr/bin/env python3
"""
decode_uci_pcap.py -- Decode UCI packets from PCAPNG captures

Reads the uwb_uci.pcapng file captured by Android UWB stack and decodes
UCI (UWB Command Interface) packets.

UCI packet header (4 bytes):
  Byte 0: MT (bits 7-5) | PBF (bit 4) | GID (bits 3-0)
  Byte 1: OID (bits 5-0)
  Byte 2-3: Payload length (LE)

MT (Message Type):
  1 = Command, 2 = Response, 3 = Notification

GID (Group ID):
  0x00 = Core
  0x01 = Session Config
  0x02 = Session Control
  0x03 = Android vendor
  0x09-0x0F = Vendor-specific
  0x0D = RF Test

Usage:
  python3 tools/decode_uci_pcap.py data/uwb_uci.pcapng
"""

import struct
import sys
from datetime import datetime

# UCI Message Types
MT_NAMES = {1: "CMD", 2: "RSP", 3: "NTF", 4: "DATA"}

# UCI Group IDs
GID_NAMES = {
    0x00: "Core",
    0x01: "SessionCfg",
    0x02: "SessionCtrl",
    0x03: "Android",
    0x0C: "AndroidExt",
    0x0D: "RfTest",
    0x0E: "Vendor_E",
    0x0F: "Vendor_F",
}

# UCI OIDs per GID
OID_NAMES = {
    (0x00, 0x00): "DEVICE_RESET",
    (0x00, 0x01): "DEVICE_STATUS_NTF",
    (0x00, 0x02): "GET_DEVICE_INFO",
    (0x00, 0x03): "GET_CAPS_INFO",
    (0x00, 0x04): "SET_CONFIG",
    (0x00, 0x05): "GET_CONFIG",
    (0x00, 0x08): "QUERY_TIMESTAMP",
    (0x01, 0x00): "SESSION_INIT",
    (0x01, 0x01): "SESSION_DEINIT",
    (0x01, 0x02): "SESSION_STATUS_NTF",
    (0x01, 0x03): "SESSION_SET_APP_CONFIG",
    (0x01, 0x04): "SESSION_GET_APP_CONFIG",
    (0x01, 0x05): "SESSION_GET_COUNT",
    (0x01, 0x06): "SESSION_GET_STATE",
    (0x02, 0x00): "RANGE_START",
    (0x02, 0x01): "RANGE_STOP",
    (0x02, 0x02): "RANGE_GET_RANGING_COUNT",
    (0x03, 0x00): "ANDROID_GET_POWER_STATS",
    (0x03, 0x01): "ANDROID_SET_COUNTRY_CODE",
    (0x03, 0x02): "ANDROID_RANGE_DIAGNOSTICS_NTF",
    (0x03, 0x03): "ANDROID_SET_RADAR_CONFIG",
    (0x03, 0x04): "ANDROID_GET_RADAR_CONFIG",
    (0x0C, 0x00): "VENDOR_C_CMD0",
    (0x0C, 0x01): "VENDOR_C_SET_COUNTRY",
    (0x0C, 0x02): "VENDOR_C_DIAGNOSTICS_NTF",
    (0x0D, 0x00): "TEST_CONFIG_SET",
    (0x0D, 0x01): "TEST_CONFIG_GET",
    (0x0D, 0x02): "TEST_PERIODIC_TX",
    (0x0D, 0x03): "TEST_PER_RX",
    (0x0D, 0x04): "TEST_RX",
    (0x0D, 0x05): "TEST_LOOPBACK",
    (0x0D, 0x06): "TEST_STOP",
    (0x0D, 0x07): "TEST_SS_TWR",
}

# Session status codes
SESSION_STATE = {
    0: "INIT", 1: "DEINIT", 2: "ACTIVE", 3: "IDLE",
}

# UCI status codes
STATUS_CODES = {
    0x00: "OK", 0x01: "REJECTED", 0x02: "FAILED",
    0x03: "SYNTAX_ERROR", 0x04: "INVALID_PARAM",
    0x05: "INVALID_RANGE", 0x06: "INVALID_MSG_SIZE",
    0x0B: "SESSION_NOT_EXIST", 0x0C: "SESSION_DUPLICATE",
    0x0D: "SESSION_ACTIVE", 0x0E: "MAX_SESSIONS_EXCEEDED",
    0x0F: "SESSION_NOT_CONFIGURED",
}


def decode_uci_packet(data):
    """Decode a UCI packet and return a description."""
    if len(data) < 4:
        return f"[too short: {len(data)} bytes]"

    byte0 = data[0]
    byte1 = data[1]
    payload_len = struct.unpack_from('<H', data, 2)[0]

    mt = (byte0 >> 5) & 0x07
    pbf = (byte0 >> 4) & 0x01
    gid = byte0 & 0x0F
    oid = byte1 & 0x3F

    mt_name = MT_NAMES.get(mt, f"MT{mt}")
    gid_name = GID_NAMES.get(gid, f"GID{gid:X}")
    oid_name = OID_NAMES.get((gid, oid), f"OID{oid:02X}")

    payload = data[4:4 + payload_len] if len(data) > 4 else b''

    desc = f"{mt_name:>3} {gid_name}/{oid_name}"
    if pbf:
        desc += " [fragmented]"

    # Decode common payloads
    if mt == 2 and len(payload) >= 1:  # Response
        status = payload[0]
        status_name = STATUS_CODES.get(status, f"0x{status:02X}")
        desc += f" status={status_name}"

    if (gid, oid) == (0x01, 0x02) and mt == 3:  # SESSION_STATUS_NTF
        if len(payload) >= 3:
            session_id = struct.unpack_from('<I', payload, 0)[0] if len(payload) >= 4 else payload[0]
            state = payload[2] if len(payload) >= 3 else 0
            state_name = SESSION_STATE.get(state, f"state{state}")
            desc += f" session={session_id} state={state_name}"

    if (gid, oid) in [(0x03, 0x02), (0x0C, 0x02)] and mt == 3:  # DIAGNOSTICS NTF
        desc += f" DIAG({payload_len} bytes)"

    # Show first few payload bytes
    if payload:
        hex_preview = ' '.join(f'{b:02X}' for b in payload[:min(16, len(payload))])
        if len(payload) > 16:
            hex_preview += f" ... ({len(payload)} total)"
        desc += f"\n        payload: [{hex_preview}]"

    return desc


def read_pcapng(filepath):
    """Read PCAPNG file and yield (timestamp, packet_data) tuples."""
    with open(filepath, 'rb') as f:
        data = f.read()

    offset = 0
    ts_resolution = 1e-6  # Default microsecond resolution

    while offset + 12 <= len(data):
        block_type = struct.unpack_from('<I', data, offset)[0]
        block_len = struct.unpack_from('<I', data, offset + 4)[0]

        if block_len < 12 or offset + block_len > len(data):
            break

        if block_type == 0x00000006:  # Enhanced Packet Block
            iface = struct.unpack_from('<I', data, offset + 8)[0]
            ts_high = struct.unpack_from('<I', data, offset + 12)[0]
            ts_low = struct.unpack_from('<I', data, offset + 16)[0]
            cap_len = struct.unpack_from('<I', data, offset + 20)[0]
            pkt_len = struct.unpack_from('<I', data, offset + 24)[0]

            timestamp = (ts_high << 32 | ts_low) * ts_resolution
            pkt_data = data[offset + 28:offset + 28 + cap_len]

            yield timestamp, pkt_data

        offset += block_len


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <pcapng_file>")
        sys.exit(1)

    filepath = sys.argv[1]
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    packets = list(read_pcapng(filepath))
    print(f"=== UCI Packet Capture: {len(packets)} packets ===\n")

    # Statistics
    stats = {'CMD': 0, 'RSP': 0, 'NTF': 0, 'DATA': 0, 'other': 0}
    diag_count = 0

    for i, (ts, pkt) in enumerate(packets):
        if len(pkt) < 4:
            if verbose:
                print(f"[{i:4d}] {ts:12.6f}s  [empty/short packet]")
            continue

        mt = (pkt[0] >> 5) & 0x07
        gid = pkt[0] & 0x0F
        oid = pkt[1] & 0x3F

        mt_name = MT_NAMES.get(mt, f"MT{mt}")
        stats[mt_name] = stats.get(mt_name, 0) + 1

        if (gid, oid) in [(0x03, 0x02), (0x0C, 0x02)] and mt == 3:
            diag_count += 1

        desc = decode_uci_packet(pkt)
        print(f"[{i:4d}] {ts:12.6f}s  {desc}")

    print(f"\n=== Summary ===")
    print(f"Total packets: {len(packets)}")
    for k, v in sorted(stats.items()):
        if v > 0:
            print(f"  {k}: {v}")
    print(f"  Diagnostic NTFs: {diag_count}")


if __name__ == '__main__':
    main()
