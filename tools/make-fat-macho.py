#!/usr/bin/env python3
"""Combine two thin macOS Mach-O binaries into one universal (fat) binary.

Go can cross-compile darwin/amd64 and darwin/arm64 without cgo. macOS' lipo is
not available on Windows, so this small writer builds the same FAT_MAGIC
container that lipo would produce.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

FAT_MAGIC = 0xCAFEBABE
CPU_TYPE_X86_64 = 0x01000007
CPU_SUBTYPE_X86_64_ALL = 3
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64_ALL = 0
ALIGN = 1 << 14


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def check_macho(path: Path) -> None:
    magic = path.read_bytes()[:4]
    if magic != b"\xcf\xfa\xed\xfe":
        raise SystemExit(f"{path} is not a little-endian 64-bit Mach-O file (magic={magic.hex()})")


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: make-fat-macho.py <x86_64> <arm64> <output>", file=sys.stderr)
        return 2
    x86 = Path(sys.argv[1])
    arm = Path(sys.argv[2])
    output = Path(sys.argv[3])
    check_macho(x86)
    check_macho(arm)

    x86_data = x86.read_bytes()
    arm_data = arm.read_bytes()
    header_size = 8 + 2 * 20
    x86_offset = align(header_size, ALIGN)
    arm_offset = align(x86_offset + len(x86_data), ALIGN)
    total = arm_offset + len(arm_data)

    with output.open("wb") as handle:
        handle.write(struct.pack(">II", FAT_MAGIC, 2))
        handle.write(struct.pack(">IIIII", CPU_TYPE_X86_64, CPU_SUBTYPE_X86_64_ALL,
                                 x86_offset, len(x86_data), 14))
        handle.write(struct.pack(">IIIII", CPU_TYPE_ARM64, CPU_SUBTYPE_ARM64_ALL,
                                 arm_offset, len(arm_data), 14))
        handle.write(b"\x00" * (x86_offset - header_size))
        handle.write(x86_data)
        handle.write(b"\x00" * (arm_offset - x86_offset - len(x86_data)))
        handle.write(arm_data)

    if output.stat().st_size != total:
        raise SystemExit("unexpected output size")
    print(f"wrote {output} ({total} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
