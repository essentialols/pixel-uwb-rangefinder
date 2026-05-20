#!/usr/bin/env python3
"""Create v8 patched dw3000.ko: CIR read on RXPTO, post-spinlock trampoline.

Root cause of all v5-v7 crashes: acc_clken calls mutex_lock (sleeping lock)
while the RXPTO handler holds a spinlock with interrupts disabled. This is
"scheduling while atomic" and crashes Linux.

v8 fix: redirect at 0x210ac (AFTER spin_unlock at 0x210a8), so the trampoline
runs with no locks held and interrupts enabled. The trampoline does CIR work,
then executes the displaced epilogue (register restores + AUTIASP + RET).

Note: 0x210ac is reached by ALL paths through the RXPTO handler (both the
normal flag-set path and the B.EQ early exit), so CIR work runs on every
RXPTO event. The dw+64 NULL check gates whether acc_clken/read_cir_data
are actually called.

Trampoline layout at 0x215b8 (dead testmode code, 844 bytes available):
  0x215b8: LDR x8, [x20, #64]       check dw+64 (config struct)
  0x215bc: CBZ x8, skip              skip CIR if NULL
  0x215c0: MOV x0, x20               dw base ptr for acc_clken
  0x215c4: MOV w1, #1                enable accumulator clock
  0x215c8: NOP                       padding (preserve safe byte value)
  0x215cc: BL dw3000_acc_clken       NOW SAFE: no spinlock held
  0x215d0: MOV x0, x20               dw base ptr for read_cir_data
  0x215d4: BL dw3000_read_cir_data   SPI read of CIR accumulator
  skip:
  0x215d8: LDP x20, x19, [sp, #32]  displaced epilogue instr 1
  0x215dc: LDR x21, [sp, #16]       displaced epilogue instr 2
  0x215e0: LDP x29, x30, [sp], #48  displaced epilogue instr 3
  0x215e4: AUTIASP                   displaced epilogue instr 4
  0x215e8: RET                       displaced epilogue instr 5
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. Redirect epilogue to trampoline (AFTER spin_unlock)
        (0x210ac, 0xa9424ff4, 0x14000143, "B trampoline (0x215b8)"),

        # 2. Trampoline: CIR work + displaced epilogue
        (0x215b8, None, 0xf9402288, "LDR x8, [x20, #64] (dw config check)"),
        (0x215bc, None, 0xb40000e8, "CBZ x8, +28 (skip CIR -> 0x215d8)"),
        (0x215c0, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215c4, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215c8, None, 0xd503201f, "NOP (alignment)"),
        (0x215cc, None, 0x97fff4b6, "BL dw3000_acc_clken"),
        (0x215d0, None, 0xaa1403e0, "MOV x0, x20 (dw base ptr)"),
        (0x215d4, None, 0x97fff4e4, "BL dw3000_read_cir_data"),
        # Displaced epilogue (executed always, CIR or not)
        (0x215d8, None, 0xa9424ff4, "LDP x20, x19, [sp, #32]"),
        (0x215dc, None, 0xf9400bf5, "LDR x21, [sp, #16]"),
        (0x215e0, None, 0xa8c37bfd, "LDP x29, x30, [sp], #48"),
        (0x215e4, None, 0xd50323bf, "AUTIASP"),
        (0x215e8, None, 0xd65f03c0, "RET"),
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v8.ko"
    if not patch(src, dst):
        sys.exit(1)
