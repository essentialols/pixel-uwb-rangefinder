#!/usr/bin/env python3
"""Create v8c patched dw3000.ko: spinlock-free CIR trampoline.

All v5-v8 approaches failed because:
1. acc_clken and read_cir_data call mutex_lock (sleeping)
2. The RXPTO handler's second spinlock section (0x21090-0x210a8)
   holds a spinlock with IRQs disabled
3. Calling sleeping functions in spinlock context = crash

v8c fix: REMOVE the second spinlock entirely by NOP-ing the BL instructions
and neutralizing their relocations (changing R_AARCH64_CALL26 to R_AARCH64_NONE).
The flag check/clear still works without the spinlock (single-threaded access).

Combined with the trampoline_only layout at 0x215b8 (which passes the vendor
integrity check due to 0xf9402288 at offset 0x215c0), this allows:
- cir_config write to succeed (trampoline_only layout)
- acc_clken/read_cir_data to call mutex_lock safely (no spinlock held)
"""

import struct
import shutil
import sys

def patch(src, dst):
    shutil.copy2(src, dst)

    with open(dst, "r+b") as f:
        # Find .text section offset
        f.seek(40); e_shoff = struct.unpack('<Q', f.read(8))[0]
        f.seek(58); e_shentsize = struct.unpack('<H', f.read(2))[0]
        f.seek(60); e_shnum = struct.unpack('<H', f.read(2))[0]
        f.seek(62); e_shstrndx = struct.unpack('<H', f.read(2))[0]

        sections = []
        for i in range(e_shnum):
            f.seek(e_shoff + i * e_shentsize)
            sh = struct.unpack('<IIQQQQIIqq', f.read(64))
            sections.append(sh)

        shstr = sections[e_shstrndx]
        f.seek(shstr[4]); shstr_data = f.read(shstr[5])
        names = []
        for s in sections:
            end = shstr_data.index(b'\x00', s[0])
            names.append(shstr_data[s[0]:end].decode())

        text_idx = names.index('.text')
        text_off = sections[text_idx][4]

        rela_idx = names.index('.rela.text')
        rela_off = sections[rela_idx][4]
        rela_entsz = sections[rela_idx][9]

        # --- Part 1: Neutralize spinlock relocations ---
        # Change r_type from 283 (R_AARCH64_CALL26) to 0 (R_AARCH64_NONE)
        rela_entries = {
            0x83d70: "spin_lock_irqsave at 0x21090",
            0x83d88: "spin_unlock_irqrestore at 0x210a8",
            0x83da0: "spin_unlock_irqrestore at 0x210c4 (error path)",
        }
        for entry_off, desc in rela_entries.items():
            # r_info is at entry_off + 8, 8 bytes
            # Change lower 32 bits (r_type) from 283 to 0
            f.seek(entry_off + 8)
            r_info = struct.unpack('<Q', f.read(8))[0]
            sym = r_info >> 32
            old_type = r_info & 0xffffffff
            assert old_type == 283, f"Expected type 283 at 0x{entry_off:x}, got {old_type}"
            new_info = (sym << 32) | 0  # R_AARCH64_NONE
            f.seek(entry_off + 8)
            f.write(struct.pack('<Q', new_info))
            print(f"  rela 0x{entry_off:05x}: type 283->0  {desc}")

        # --- Part 2: NOP the BL instructions ---
        nop = 0xd503201f
        bl_nops = [
            (0x21090, 0x94000000, "NOP spin_lock_irqsave"),
            (0x210a8, 0x94000000, "NOP spin_unlock_irqrestore"),
            (0x210c4, 0x94000000, "NOP spin_unlock_irqrestore (error)"),
        ]
        for offset, expected, desc in bl_nops:
            f.seek(offset)
            val = struct.unpack('<I', f.read(4))[0]
            if val != expected:
                print(f"  WARN 0x{offset:05x}: {val:08x} != {expected:08x}")
                return False
            f.seek(offset)
            f.write(struct.pack('<I', nop))
            print(f"  0x{offset:05x}: -> {nop:08x}  {desc}")

        # --- Part 3: RXPTO redirect + trampoline (trampoline_only layout) ---
        patches = [
            (0x210a0, 0x390002bf, 0x14000146, "B trampoline (0x215b8)"),
            (0x215b8, None, 0xd10043ff, "SUB sp, sp, #16"),
            (0x215bc, None, 0xf90003e1, "STR x1, [sp] (save regs)"),
            (0x215c0, None, 0xf9402288, "LDR x8, [x20, #64] (NULL check)"),
            (0x215c4, None, 0xb40000c8, "CBZ x8, +24 (skip -> 0x215dc)"),
            (0x215c8, None, 0xaa1403e0, "MOV x0, x20 (dw base)"),
            (0x215cc, None, 0x52800021, "MOV w1, #1 (enable)"),
            (0x215d0, None, 0x97fff4b5, "BL dw3000_acc_clken"),
            (0x215d4, None, 0xaa1403e0, "MOV x0, x20 (dw base)"),
            (0x215d8, None, 0x97fff4e3, "BL dw3000_read_cir_data"),
            (0x215dc, None, 0xf94003e1, "LDR x1, [sp] (restore regs)"),
            (0x215e0, None, 0x910043ff, "ADD sp, sp, #16"),
            (0x215e4, None, 0x390002bf, "STRB wzr, [x21, #0] (clear flag)"),
            (0x215e8, None, 0x17fffeaf, "B 0x210a4 (-> NOP unlock -> epilogue)"),
        ]
        for offset, expected, replacement, desc in patches:
            f.seek(offset)
            val = struct.unpack('<I', f.read(4))[0]
            if expected is not None and val != expected:
                print(f"  WARN 0x{offset:05x}: {val:08x} != {expected:08x}")
                return False
            f.seek(offset)
            f.write(struct.pack('<I', replacement))
            print(f"  0x{offset:05x}: -> {replacement:08x}  {desc}")

    print(f"\nPatched: {dst}")
    return True

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dw3000_vendor.ko"
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dw3000_cir_v8c.ko"
    if not patch(src, dst):
        sys.exit(1)
