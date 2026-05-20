#!/usr/bin/env python3
"""Create v6d patched dw3000.ko: full CIR pipeline on RXPTO.

Key fix from v6c: REMOVED the CIA NOP at 0x253b8 which was actually in
rx_get_measurement (NOT read_frame_cir_data as previously believed). That NOP
broke dw3000_cir_data_alloc_count, causing cir_config writes to hang on
mutex_lock.

Since our trampoline calls dw3000_read_cir_data directly (bypassing
read_frame_cir_data), the CIA check bypass is NOT needed.

Patches (14 instructions):
1. Debugfs non-blocking read (0x292a0): NOP wait_for_completion so cir_data
   reads return immediately with latest buffer contents
2. RXPTO trampoline redirect (0x210a0): B to dead code at 0x215b8
3. Trampoline (0x215b8): save IRQ flags, check cir_data via x20,
   call acc_clken + read_cir_data, restore flags, clear flag, return to
   spin_unlock + epilogue
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. NOP wait_for_completion_interruptible in debugfs cir_data handler
        (0x292a0, 0x94000000, 0x52800000, "NOP wait_for_completion (MOV w0, #0)"),

        # 2. Redirect RXPTO handler to trampoline
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),

        # 3. Trampoline at 0x215b8 (dw3000_testmode_continuous_tx_start, dead code)
        (0x215b8, None, 0xd10043ff, "SUB sp, sp, #16"),
        (0x215bc, None, 0xf90003e1, "STR x1, [sp] (save IRQ flags)"),
        (0x215c0, None, 0xf9402288, "LDR x8, [x20, #64] (dw->cir_data)"),
        (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip if NULL -> 0x215dc)"),
        (0x215c8, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
        (0x215d4, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215d8, None, 0x97fff4e3, "BL dw3000_read_cir_data"),
        (0x215dc, None, 0xf94003e1, "LDR x1, [sp] (restore IRQ flags)"),
        (0x215e0, None, 0x910043ff, "ADD sp, sp, #16"),
        (0x215e4, None, 0x390002bf, "STRB wzr, [x21, #0] (clear flag)"),
        (0x215e8, None, 0x17fffeaf, "B 0x210a4 (spin_unlock + epilogue)"),
    ]

    with open(dst, "r+b") as f:
        for offset, expected, replacement, desc in patches:
            f.seek(offset)
            val = struct.unpack("<I", f.read(4))[0]
            if expected is not None and val != expected:
                print(f"  WARN 0x{offset:05x}: found {val:08x}, expected {expected:08x}")
                return False
            f.seek(offset)
            f.write(struct.pack("<I", replacement))
            print(f"  0x{offset:05x}: -> {replacement:08x}  {desc}")

    print(f"\nPatched: {dst}")
    return True

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dw3000_vendor.ko"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v6d.ko"
    if not patch(src, dst):
        sys.exit(1)
