#!/usr/bin/env python3
"""Create v5b patched dw3000.ko: CIR read on RXPTO via trampoline in dead testmode code.

Patch summary (10 instructions total):
1. NOP the CIA flag check (TBZ) at file offset 0x253b8
2. Redirect RXPTO epilogue at 0x210a0 to trampoline
3. Trampoline at 0x215b8 (dead testmode function space):
   - Load and NULL-check dw->cir_data (offset 64 in dw3000 struct)
   - If non-NULL: enable accumulator clock, read CIR via SPI
   - Branch back to original register-restore epilogue at 0x210ac

Key offsets (vendor dw3000.ko, 644344 bytes):
- dw3000_isr_handle_rxto_event: file 0x20ff4 (RXPTO handler)
- dw3000_read_frame_cir_data: file 0x25388 (CIA check at 0x253b8)
- dw3000_acc_clken: file 0x1e8a4 (.text+0xdea8)
- dw3000_read_cir_data: file 0x1e964 (.text+0xdf68)
- dw3000_testmode_*: file 0x215b8 (.text+0x10bbc, 844 bytes dead code)
- dw->cir_data offset: 64 bytes (0x40) from struct base
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        (0x253b8, 0x36200168, 0xd503201f, "NOP CIA check"),
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline"),
        (0x215b8, None, 0xf9402268, "LDR x8, [x19, #64] (cir_data)"),
        (0x215bc, None, 0xb40000a8, "CBZ x8, +20 (skip if NULL)"),
        (0x215c0, None, 0xaa1303e0, "MOV x0, x19 (dw ptr)"),
        (0x215c4, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215c8, None, 0x97fff4b7, "BL dw3000_acc_clken"),
        (0x215cc, None, 0xaa1303e0, "MOV x0, x19 (dw, clobbered)"),
        (0x215d0, None, 0x97fff4e5, "BL dw3000_read_cir_data"),
        (0x215d4, None, 0x17fffeb6, "B epilogue (0x210ac)"),
    ]

    with open(dst, "r+b") as f:
        for offset, expected, replacement, desc in patches:
            f.seek(offset)
            val = struct.unpack("<I", f.read(4))[0]
            if expected is not None and val != expected:
                print(f"  WARN 0x{offset:05x}: {val:08x} != {expected:08x}")
                return False
            f.seek(offset)
            f.write(struct.pack("<I", replacement))
            print(f"  0x{offset:05x}: -> {replacement:08x}  {desc}")

    print(f"\nPatched: {dst}")
    return True

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dw3000_vendor.ko"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v5b.ko"
    if not patch(src, dst):
        sys.exit(1)
