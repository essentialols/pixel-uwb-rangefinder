#!/usr/bin/env python3
"""Create v10 patched dw3000.ko: CIA bypass in read_frame_cir_data.

BREAKTHROUGH: The vendor module already has CIR-on-RXPTO code at
dw3000_isr_handle_rxto_event line 7718:
    if (dw->cir_data && swait_active(&dw->cir_data->complete.wait)) {
        cir_rc = dw3000_read_frame_cir_data(dw, &info, pkt_ts);
    }

This runs BEFORE the spinlock section, so mutex_lock in read_frame_cir_data
is safe. The only blocker: the CIA flag check at the start of
read_frame_cir_data returns -ENODATA when CIA hasn't run (RXPTO events).

Fix: NOP the CIA check (3 instructions at 0x1e494-0x1e49c).

The CIA check pattern:
    0x1e490: LDRB w8, [x24, #0]      # load dw->rx.flags
    0x1e494: TBNZ w8, #4, 0x1e4a0    # if CIA flag set, continue
    0x1e498: MOV w23, #-61           # rc = -ENODATA
    0x1e49c: B 0x1e718               # goto error exit

NOP the branch + error path: always fall through to the CIR read code.

Usage: write cir_config (with 5s delay after insmod), start a cir_data
reader (cat/dd), start a FiRa session. RXPTO fires, detects the waiter,
reads CIR, signals completion, reader gets data.
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # NOP the CIA check: TBNZ + error setup + branch
        (0x1e494, 0x37200068, 0xd503201f, "NOP TBNZ w8, #4 (CIA check)"),
        (0x1e498, 0x12800797, 0xd503201f, "NOP MOV w23, #-ENODATA"),
        (0x1e49c, 0x1400009f, 0xd503201f, "NOP B error_exit"),
    ]

    with open(dst, "r+b") as f:
        for offset, expected, replacement, desc in patches:
            f.seek(offset)
            val = struct.unpack("<I", f.read(4))[0]
            if val != expected:
                print(f"  WARN 0x{offset:05x}: found {val:08x}, expected {expected:08x}")
                return False
            f.seek(offset)
            f.write(struct.pack("<I", replacement))
            print(f"  0x{offset:05x}: {expected:08x} -> {replacement:08x}  {desc}")

    print(f"\nPatched: {dst}")
    return True

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dw3000_vendor.ko"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v10.ko"
    if not patch(src, dst):
        sys.exit(1)
