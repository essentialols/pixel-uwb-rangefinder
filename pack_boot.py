#!/usr/bin/env python3
"""
pack_boot.py -- Create a bootable boot.img from a kernel Image

Creates a boot v4 image for Pixel 7 Pro (GKI) from:
  - A kernel Image (built from source, uncompressed ARM64)
  - The original boot.img (for header and AVB blocks)

The script:
  1. Reads the original boot.img header and AVB footer
  2. LZ4-compresses the new kernel (matching original format)
  3. Packs everything into a new boot.img preserving AVB blocks

Usage:
  python3 pack_boot.py --kernel /path/to/Image --orig /path/to/boot_orig.img --output /path/to/boot.img

Requirements: lz4 CLI tool (apt install lz4)
"""

import struct
import sys
import argparse
import os
import subprocess
import tempfile


def pack_boot_image(kernel_path, orig_boot_path, output_path):
    """Create a new boot.img with custom kernel, preserving AVB."""

    # Read original boot image
    with open(orig_boot_path, 'rb') as f:
        orig = f.read()

    # Parse header
    magic = orig[:8]
    assert magic == b'ANDROID!', f"Not a boot image (magic={magic})"
    header_version = struct.unpack_from('<I', orig, 40)[0]
    orig_kernel_size = struct.unpack_from('<I', orig, 8)[0]
    ramdisk_size = struct.unpack_from('<I', orig, 16)[0]

    PAGE_SIZE = 4096
    orig_kernel_pages = (orig_kernel_size + PAGE_SIZE - 1) // PAGE_SIZE
    orig_kernel_end = PAGE_SIZE + orig_kernel_pages * PAGE_SIZE

    print(f"Original boot image:")
    print(f"  Header version: {header_version}")
    print(f"  Kernel size: {orig_kernel_size} ({orig_kernel_size/1024/1024:.1f} MB)")
    print(f"  Kernel area ends at: 0x{orig_kernel_end:x}")
    print(f"  Ramdisk size: {ramdisk_size}")

    # Check if original kernel is LZ4 compressed
    orig_kernel_magic = orig[PAGE_SIZE:PAGE_SIZE+4]
    is_lz4 = orig_kernel_magic == b'\x02\x21\x4c\x18'
    print(f"  Kernel compression: {'LZ4' if is_lz4 else 'unknown/none'}")

    # Check AVB blocks after kernel
    after_kernel = orig[orig_kernel_end:orig_kernel_end+4]
    has_avb = after_kernel == b'AVB0'
    has_footer = orig[-64:-60] == b'AVBf'
    print(f"  AVB vbmeta block: {'yes' if has_avb else 'no'}")
    print(f"  AVB footer: {'yes' if has_footer else 'no'}")

    # Read and compress new kernel
    with open(kernel_path, 'rb') as f:
        kernel_raw = f.read()
    print(f"\nNew kernel (raw): {len(kernel_raw)} bytes ({len(kernel_raw)/1024/1024:.1f} MB)")

    # LZ4 compress using legacy format (kernel-compatible)
    with tempfile.NamedTemporaryFile(suffix='.img', delete=False) as tmp_in:
        tmp_in.write(kernel_raw)
        tmp_in_path = tmp_in.name
    tmp_out_path = tmp_in_path + '.lz4'

    try:
        result = subprocess.run(
            ['lz4', '-l', '-12', tmp_in_path, tmp_out_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"LZ4 compression failed: {result.stderr}")
            sys.exit(1)

        with open(tmp_out_path, 'rb') as f:
            kernel_compressed = f.read()
    finally:
        os.unlink(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.unlink(tmp_out_path)

    print(f"New kernel (LZ4): {len(kernel_compressed)} bytes ({len(kernel_compressed)/1024/1024:.1f} MB)")

    # Verify it fits in the original kernel area
    kernel_area_size = orig_kernel_end - PAGE_SIZE
    if len(kernel_compressed) > kernel_area_size:
        print(f"ERROR: Compressed kernel ({len(kernel_compressed)}) doesn't fit "
              f"in original kernel area ({kernel_area_size})")
        sys.exit(1)

    # Build new image
    # 1. Header (updated kernel size)
    header = bytearray(orig[:PAGE_SIZE])
    struct.pack_into('<I', header, 8, len(kernel_compressed))

    # 2. Kernel (LZ4 compressed, padded to fill original kernel area)
    kernel_padded = kernel_compressed + b'\x00' * (kernel_area_size - len(kernel_compressed))

    # 3. Everything after kernel (AVB blocks, footer, padding)
    after_kernel_data = orig[orig_kernel_end:]

    new_boot = bytes(header) + kernel_padded + after_kernel_data
    assert len(new_boot) == len(orig), f"Size mismatch: {len(new_boot)} vs {len(orig)}"

    with open(output_path, 'wb') as f:
        f.write(new_boot)

    # Verify
    print(f"\nOutput: {output_path} ({len(new_boot)} bytes)")
    verify_ks = struct.unpack_from('<I', new_boot, 8)[0]
    verify_lz4 = new_boot[PAGE_SIZE:PAGE_SIZE+4] == b'\x02\x21\x4c\x18'
    verify_avb = new_boot[orig_kernel_end:orig_kernel_end+4] == b'AVB0' if has_avb else True
    verify_footer = new_boot[-64:-60] == b'AVBf' if has_footer else True

    print(f"Verification:")
    print(f"  Kernel size: {verify_ks} (was {orig_kernel_size})")
    print(f"  LZ4 magic: {'OK' if verify_lz4 else 'FAIL'}")
    print(f"  AVB block: {'OK' if verify_avb else 'FAIL'}")
    print(f"  AVB footer: {'OK' if verify_footer else 'FAIL'}")

    if not all([verify_lz4, verify_avb, verify_footer]):
        print("\nWARNING: Verification failed!")
        sys.exit(1)
    print("\nAll checks passed.")


def main():
    parser = argparse.ArgumentParser(description='Pack GKI boot.img with custom kernel')
    parser.add_argument('--kernel', required=True, help='Path to kernel Image (uncompressed)')
    parser.add_argument('--orig', required=True, help='Path to original boot.img')
    parser.add_argument('--output', required=True, help='Output boot.img path')
    args = parser.parse_args()

    pack_boot_image(args.kernel, args.orig, args.output)


if __name__ == '__main__':
    main()
