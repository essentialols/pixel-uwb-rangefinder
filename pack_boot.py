#!/usr/bin/env python3
"""
pack_boot.py -- Create a bootable boot.img from a kernel Image

Creates a boot v4 image for Pixel 7 Pro (GKI) from:
  - A kernel Image (built from source)
  - The original boot.img (for header parameters)

Usage:
  python3 pack_boot.py --kernel /tmp/android14-kernel/arch/arm64/boot/Image \
                       --orig /tmp/boot_orig.img \
                       --output /tmp/boot_custom.img

The boot v4 format:
  - Header (4096 bytes): magic, kernel_size, ramdisk_size, etc.
  - Kernel: the actual Image, page-aligned
  - Ramdisk: empty for GKI (ramdisk is in vendor_boot)

This script copies the original header (preserving all device-specific
parameters) and replaces just the kernel payload.
"""

import struct
import sys
import argparse
import os


def read_boot_v4_header(data):
    """Parse boot image v4 header."""
    magic = data[0:8]
    assert magic == b'ANDROID!', f"Not a boot image (magic={magic})"

    kernel_size = struct.unpack_from('<I', data, 8)[0]
    ramdisk_size = struct.unpack_from('<I', data, 16)[0]
    os_version = struct.unpack_from('<I', data, 28)[0]
    header_size = struct.unpack_from('<I', data, 32)[0]
    header_version = struct.unpack_from('<I', data, 40)[0]

    # v4 specific
    signature_size = 0
    if header_version >= 4:
        signature_size = struct.unpack_from('<I', data, 44)[0]

    return {
        'kernel_size': kernel_size,
        'ramdisk_size': ramdisk_size,
        'os_version': os_version,
        'header_size': header_size,
        'header_version': header_version,
        'signature_size': signature_size,
    }


def page_align(size, page_size=4096):
    """Align size to page boundary."""
    return (size + page_size - 1) & ~(page_size - 1)


def pack_boot_image(kernel_path, orig_boot_path, output_path):
    """Create a new boot.img with custom kernel."""

    # Read original boot image
    with open(orig_boot_path, 'rb') as f:
        orig_data = f.read()

    header = read_boot_v4_header(orig_data)
    print(f"Original boot image:")
    print(f"  Header version: {header['header_version']}")
    print(f"  Kernel size: {header['kernel_size']}")
    print(f"  Ramdisk size: {header['ramdisk_size']}")
    print(f"  Signature size: {header['signature_size']}")

    # Read new kernel
    with open(kernel_path, 'rb') as f:
        kernel_data = f.read()
    print(f"\nNew kernel: {len(kernel_data)} bytes ({len(kernel_data)/1024/1024:.1f} MB)")

    # Build new boot image
    # Start with original header
    header_page_size = 4096
    new_boot = bytearray(orig_data[:header_page_size])

    # Update kernel size in header
    struct.pack_into('<I', new_boot, 8, len(kernel_data))

    # Kernel payload (page-aligned)
    kernel_padded = kernel_data + b'\x00' * (page_align(len(kernel_data)) - len(kernel_data))
    new_boot += kernel_padded

    # Ramdisk (empty for GKI boot v4 - ramdisk is in vendor_boot)
    if header['ramdisk_size'] > 0:
        ramdisk_offset = header_page_size + page_align(header['kernel_size'])
        ramdisk_data = orig_data[ramdisk_offset:ramdisk_offset + header['ramdisk_size']]
        ramdisk_padded = ramdisk_data + b'\x00' * (page_align(len(ramdisk_data)) - len(ramdisk_data))
        new_boot += ramdisk_padded

    # Pad to original size (or minimum boot partition size)
    target_size = max(len(orig_data), len(new_boot))
    if len(new_boot) < target_size:
        new_boot += b'\x00' * (target_size - len(new_boot))

    # Write output
    with open(output_path, 'wb') as f:
        f.write(new_boot)

    print(f"\nNew boot image: {len(new_boot)} bytes ({len(new_boot)/1024/1024:.1f} MB)")
    print(f"Written to: {output_path}")

    # Verify
    new_header = read_boot_v4_header(bytes(new_boot))
    print(f"\nVerification:")
    print(f"  Kernel size: {new_header['kernel_size']} (was {header['kernel_size']})")
    print(f"  Ramdisk size: {new_header['ramdisk_size']}")


def main():
    parser = argparse.ArgumentParser(description='Pack GKI boot.img with custom kernel')
    parser.add_argument('--kernel', required=True, help='Path to kernel Image')
    parser.add_argument('--orig', required=True, help='Path to original boot.img')
    parser.add_argument('--output', required=True, help='Output boot.img path')
    args = parser.parse_args()

    pack_boot_image(args.kernel, args.orig, args.output)


if __name__ == '__main__':
    main()
