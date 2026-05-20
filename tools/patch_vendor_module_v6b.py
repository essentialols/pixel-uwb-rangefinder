#!/usr/bin/env python3
"""Create v6b patched dw3000.ko: CIR read on RXPTO, spinlock-safe, correct dw pointer.

Fixes TWO bugs from v5b/v5c/v6:
1. SPINLOCK: Trampoline jumped to epilogue at 0x210ac, skipping
   _raw_spin_unlock_irqrestore at 0x210a8. Now returns to 0x210a4
   which does spin_unlock before epilogue.
2. WRONG REGISTER: x19 = dw + 0x2B08 (rx sub-struct), NOT the dw base.
   x20 = dw struct base (original x0 argument). All acc_clken/read_cir_data
   calls and cir_data loads must use x20.

RXPTO handler register map:
  x20 = dw struct base (SET at 0x2100c: MOV x20, x0)
  x19 = dw + 0x2B08 (SET at 0x21010: ADD x19, x0, x8 where x8=0x2B08)
  x21 = x19 (SET at 0x2101c: MOV x21, x19) -- used for flag byte

dw3000 struct offsets:
  +64 (0x40): cir_data pointer (confirmed from read_frame_cir_data: LDR x20, [x0, #64])
  +0x2B08: rx sub-struct containing spinlock and flag byte

Trampoline flow (at 0x215b8, dead testmode code space):
  1. Save x1 (IRQ flags needed by spin_unlock_irqrestore)
  2. Load cir_data from correct offset: [x20, #64] (NOT [x19, #64])
  3. If non-NULL: call acc_clken(x20) then read_cir_data(x20)
  4. Restore x1
  5. Execute displaced STRB wzr, [x21, #0]
  6. Branch to 0x210a4 -> spin_unlock_irqrestore -> epilogue -> RET
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. NOP the CIA flag check in read_frame_cir_data
        (0x253b8, 0x36200168, 0xd503201f, "NOP CIA check (TBZ)"),

        # 2. Redirect RXPTO handler to trampoline
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),

        # 3. Trampoline: spinlock-safe, correct dw pointer (x20)
        #    0x215b8: save IRQ flags
        (0x215b8, None, 0xd10043ff, "SUB sp, sp, #16"),
        (0x215bc, None, 0xf90003e1, "STR x1, [sp] (save IRQ flags)"),
        #    0x215c0: check cir_data via x20 (dw struct base)
        (0x215c0, None, 0xf9402288, "LDR x8, [x20, #64] (dw->cir_data)"),
        (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip if NULL -> 0x215dc)"),
        #    0x215c8: enable accumulator clock
        (0x215c8, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
        #    0x215d4: read CIR data
        (0x215d4, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215d8, None, 0x97fff4e3, "BL dw3000_read_cir_data"),
        #    0x215dc: restore and return to spin_unlock path
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v6b.ko"
    if not patch(src, dst):
        sys.exit(1)
