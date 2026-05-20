#!/usr/bin/env python3
"""Create v7 patched dw3000.ko: CIR read on RXPTO, spinlock-safe.

Fixes from v6b/v6c/v6d:
- Correct NULL check: uses dw + 11120 (cir struct pointer allocated by
  cir_config), NOT dw + 64 (which is always non-NULL)
- Spinlock-safe: returns to spin_unlock path
- Correct dw pointer: x20 (not x19)
- No CIA NOP: the TBZ at 0x253b8 is in rx_get_measurement, not
  read_frame_cir_data. Our trampoline calls read_cir_data directly.
- No debugfs NOP: causes interaction bug with cir_config write.
  Instead, the cir_data read blocks on wait_for_completion until we
  find a way to signal it.

CIR data flow:
  cir_config write -> dw3000_cir_data_alloc_count -> allocates cir struct at dw+11120
  RXPTO fires -> trampoline -> acc_clken(enable) -> read_cir_data(SPI read)
  -> data in kernel buffer at *(dw+11120)+312

Struct offsets in dw3000_local:
  +64 (0x40): config/measurement sub-struct (always non-NULL after probe)
  +11120 (0x2B70): cir struct pointer (NULL until cir_config written)
  +0x2B08: rx sub-struct (x19 in RXPTO handler, spinlock + flag byte)
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. Redirect RXPTO handler to trampoline
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),

        # 2. Trampoline at 0x215b8
        (0x215b8, None, 0xd10043ff, "SUB sp, sp, #16"),
        (0x215bc, None, 0xf90003e1, "STR x1, [sp] (save IRQ flags)"),
        # NULL check on cir struct (dw + 11120), NOT dw + 64
        (0x215c0, None, 0xf955ba88, "LDR x8, [x20, #11120] (dw->cir_struct)"),
        (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip if NULL -> 0x215dc)"),
        # Enable accumulator clock
        (0x215c8, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
        # Read CIR data via SPI
        (0x215d4, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215d8, None, 0x97fff4e3, "BL dw3000_read_cir_data"),
        # Restore and return to spin_unlock path
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v7.ko"
    if not patch(src, dst):
        sys.exit(1)
