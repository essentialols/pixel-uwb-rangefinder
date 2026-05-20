#!/usr/bin/env python3
"""Create v6c patched dw3000.ko: full CIR pipeline on RXPTO.

Combines three fixes:
1. CIA NOP (0x253b8): bypass CIA flag check so CIR read works on RXPTO
2. Spinlock-safe trampoline (0x210a0 + 0x215b8): correct dw pointer (x20),
   saves/restores IRQ flags, returns to spin_unlock path
3. Debugfs non-blocking (0x292a0): NOP wait_for_completion so cir_data
   reads return immediately with latest buffer contents

Previous bugs fixed:
- v5b: spinlock deadlock (skipped spin_unlock_irqrestore)
- v5b: wrong register (x19 = dw+0x2B08, not dw base)
- v6b: working trampoline but debugfs blocked on completion signal

Data flow:
  RXPTO fires -> trampoline -> acc_clken(enable) -> read_cir_data(SPI read)
  -> data stored in kernel buffer -> debugfs reader copies to userspace
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. NOP the CIA flag check in read_frame_cir_data
        (0x253b8, 0x36200168, 0xd503201f, "NOP CIA check (TBZ)"),

        # 2. NOP wait_for_completion_interruptible in debugfs cir_data handler
        #    Original: BL wait_for_completion_interruptible (returns 0 on success)
        #    Replace: MOV w0, #0 (pretend immediate success)
        (0x292a0, 0x94000000, 0x52800000, "NOP wait_for_completion (MOV w0, #0)"),

        # 3. Redirect RXPTO handler to trampoline
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),

        # 4. Trampoline at 0x215b8 (dead testmode code, 844 bytes available)
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v6c.ko"
    if not patch(src, dst):
        sys.exit(1)
