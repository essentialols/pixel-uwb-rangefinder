#!/usr/bin/env python3
"""Create v6 patched dw3000.ko: CIR read on RXPTO via trampoline, spinlock-safe.

v5b/v5c crashed because the trampoline at 0x215b8 redirected from 0x210a0
(inside a spin_lock_irqsave section) and jumped to 0x210ac (epilogue),
SKIPPING _raw_spin_unlock_irqrestore at 0x210a8. The permanently-held
spinlock caused hard lockup on next access.

v6 fix: trampoline saves x1 (IRQ flags), does CIR work, restores x1,
executes the displaced STRB wzr instruction, then jumps back to 0x210a4
which does MOV x0, x19 + BL _raw_spin_unlock_irqrestore + epilogue.

Patch summary (15 instructions total):
1. NOP the CIA flag check (TBZ) at file offset 0x253b8
2. Redirect RXPTO spin_unlock-path at 0x210a0 to trampoline
3. Trampoline at 0x215b8 (dead testmode function space):
   - Save x1 (IRQ flags for spin_unlock) on stack
   - Load and NULL-check dw->cir_data (offset 64 in dw3000 struct)
   - If non-NULL: enable accumulator clock, read CIR via SPI
   - Restore x1 from stack
   - Execute displaced STRB wzr, [x21, #0] (clear flag)
   - Branch back to 0x210a4 for spin_unlock_irqrestore + epilogue

RXPTO handler flow with patch:
  0x21090: spin_lock_irqsave(x19)
  0x21094: LDRB w8, [x21]        (read flag)
  0x21098: MOV x1, x0            (save IRQ flags)
  0x2109c: CBZ w8, 0x210c0       (if flag==0, error)
  0x210a0: B 0x215b8             [PATCHED: was STRB wzr, [x21]]
  ---- trampoline ----
  0x215b8: SUB sp, sp, #16       (save space)
  0x215bc: STR x1, [sp]          (save IRQ flags)
  0x215c0: LDR x8, [x19, #64]   (cir_data ptr)
  0x215c4: CBZ x8, +24           (skip if NULL -> 0x215dc)
  0x215c8: MOV x0, x19           (dw ptr)
  0x215cc: MOV w1, #1            (enable)
  0x215d0: BL dw3000_acc_clken   (enable accumulator clock)
  0x215d4: MOV x0, x19           (dw ptr, clobbered by prev call)
  0x215d8: BL dw3000_read_cir_data  (SPI read of accumulator)
  0x215dc: LDR x1, [sp]          (restore IRQ flags)
  0x215e0: ADD sp, sp, #16       (restore stack)
  0x215e4: STRB wzr, [x21, #0]   (displaced: clear flag)
  0x215e8: B 0x210a4             (-> MOV x0,x19 + spin_unlock + epilogue)
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    patches = [
        # 1. NOP the CIA flag check in read_frame_cir_data
        (0x253b8, 0x36200168, 0xd503201f, "NOP CIA check (TBZ)"),

        # 2. Redirect RXPTO handler to trampoline (same site as v5b)
        (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),

        # 3. Trampoline: spinlock-safe CIR read
        (0x215b8, None, 0xd10043ff, "SUB sp, sp, #16"),
        (0x215bc, None, 0xf90003e1, "STR x1, [sp] (save IRQ flags)"),
        (0x215c0, None, 0xf9402268, "LDR x8, [x19, #64] (cir_data)"),
        (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip if NULL)"),
        (0x215c8, None, 0xaa1303e0, "MOV x0, x19 (dw ptr)"),
        (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
        (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
        (0x215d4, None, 0xaa1303e0, "MOV x0, x19 (dw, clobbered)"),
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
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v6.ko"
    if not patch(src, dst):
        sys.exit(1)
