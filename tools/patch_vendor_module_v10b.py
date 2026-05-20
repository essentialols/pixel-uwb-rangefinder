#!/usr/bin/env python3
"""Create v10b patched dw3000.ko: CIA bypass with skip to acc_clken.

The vendor RXPTO handler already calls read_frame_cir_data (before spinlock).
The CIA check at 0x1e494 returns -ENODATA when CIA hasn't run (RXPTO).

v10 just NOPed the check, but that let code fall through to dw3000_read_ciaregs
which reads invalid CIA registers and crashes.

v10b: keep the TBNZ (normal CIA path unchanged), but change the error
fall-through to JUMP to the acc_clken+read_cir_data code at 0x1e594,
skipping CIA-dependent reads (ciaregs, fp_power, cir_acc).

Binary layout:
    0x1e494: TBNZ w8, #4, 0x1e4a0  (CIA set -> normal path, KEEP)
    0x1e498: B 0x1e594              (CIA not set -> skip to acc_clken, NEW)
    0x1e49c: NOP                    (unreachable padding)

Flow without CIA (RXPTO):
    TBNZ falls through -> B 0x1e594 -> mutex_lock(acc) -> spi_sync(enable)
    -> mutex_unlock(acc) -> read_cir_data -> acc_clken(false) -> complete()
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    # B from 0x1e498 to 0x1e594: offset = (0x1e594 - 0x1e498)/4 = 63
    b_acc_clken = 0x14000000 | 63  # 0x1400003f

    patches = [
        # Keep TBNZ at 0x1e494 (normal CIA path unchanged)
        # Change error path to jump to acc_clken inlined code
        (0x1e498, 0x12800797, b_acc_clken, "B 0x1e594 (skip CIA reads, go to acc_clken)"),
        (0x1e49c, 0x1400009f, 0xd503201f, "NOP (unreachable)"),
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v10b.ko"
    if not patch(src, dst):
        sys.exit(1)
