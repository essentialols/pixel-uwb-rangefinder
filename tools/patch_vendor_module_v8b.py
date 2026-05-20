#!/usr/bin/env python3
"""Create v8b patched dw3000.ko: post-spinlock CIR trampoline, byte-aligned.

Same approach as v8 (redirect after spin_unlock at 0x210ac) but with the
trampoline rearranged so that offset 0x215c0 contains 0xf9402288
(LDR x8, [x20, #64]), the only value experimentally confirmed to allow
cir_config writes to succeed.

The mysterious sensitivity to bytes at 0x215c0 is likely a vendor integrity
check. We work around it by placing our NULL-check LDR at that exact offset.
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. Redirect epilogue to trampoline (AFTER spin_unlock)
        (0x210ac, 0xa9424ff4, 0x14000143, "B trampoline (0x215b8)"),

        # 2. Trampoline: NOP padding + CIR work + displaced epilogue
        # Two NOPs to align the LDR at 0x215c0
        (0x215b8, None, 0xd503201f, "NOP (padding)"),
        (0x215bc, None, 0xd503201f, "NOP (padding)"),
        # The critical LDR MUST be at 0x215c0 = 0xf9402288
        (0x215c0, None, 0xf9402288, "LDR x8, [x20, #64] (dw config check)"),
        (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip CIR -> 0x215dc)"),
        (0x215c8, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
        (0x215d4, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215d8, None, 0x97fff4e3, "BL dw3000_read_cir_data"),
        # Displaced epilogue
        (0x215dc, None, 0xa9424ff4, "LDP x20, x19, [sp, #32]"),
        (0x215e0, None, 0xf9400bf5, "LDR x21, [sp, #16]"),
        (0x215e4, None, 0xa8c37bfd, "LDP x29, x30, [sp], #48"),
        (0x215e8, None, 0xd50323bf, "AUTIASP"),
        (0x215ec, None, 0xd65f03c0, "RET"),
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v8b.ko"
    if not patch(src, dst):
        sys.exit(1)
