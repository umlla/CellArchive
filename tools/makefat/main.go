// Command makefat combines two thin macOS Mach-O binaries into a universal
// (FAT_MAGIC) binary. It is the Windows-friendly equivalent of macOS lipo.
package main

import (
	"encoding/binary"
	"fmt"
	"os"
)

const (
	fatMagic      = 0xcafebabe
	cpuTypeX8664  = 0x01000007
	cpuSubtypeX86 = 3
	cpuTypeARM64  = 0x0100000c
	cpuSubtypeARM = 0
	align         = 1 << 14
)

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: makefat <x86_64> <arm64> <output>")
		os.Exit(2)
	}
	x86, err := os.ReadFile(os.Args[1])
	if err != nil {
		fail(err)
	}
	arm, err := os.ReadFile(os.Args[2])
	if err != nil {
		fail(err)
	}
	check(x86, os.Args[1])
	check(arm, os.Args[2])

	headerSize := 8 + 2*20
	x86Offset := alignUp(headerSize)
	armOffset := alignUp(x86Offset + len(x86))
	total := armOffset + len(arm)
	out := make([]byte, total)

	binary.BigEndian.PutUint32(out[0:], fatMagic)
	binary.BigEndian.PutUint32(out[4:], 2)
	writeArch(out[8:], cpuTypeX8664, cpuSubtypeX86, x86Offset, len(x86))
	writeArch(out[28:], cpuTypeARM64, cpuSubtypeARM, armOffset, len(arm))
	copy(out[x86Offset:], x86)
	copy(out[armOffset:], arm)

	if err := os.WriteFile(os.Args[3], out, 0o755); err != nil {
		fail(err)
	}
	fmt.Printf("wrote %s (%d bytes)\n", os.Args[3], len(out))
}

func writeArch(buf []byte, cpuType, cpuSubtype uint32, offset, size int) {
	binary.BigEndian.PutUint32(buf[0:], cpuType)
	binary.BigEndian.PutUint32(buf[4:], cpuSubtype)
	binary.BigEndian.PutUint32(buf[8:], uint32(offset))
	binary.BigEndian.PutUint32(buf[12:], uint32(size))
	binary.BigEndian.PutUint32(buf[16:], 14)
}

func check(data []byte, name string) {
	if len(data) < 4 || string(data[:4]) != "\xcf\xfa\xed\xfe" {
		fail(fmt.Errorf("%s is not a little-endian 64-bit Mach-O file", name))
	}
}

func alignUp(value int) int {
	return (value + align - 1) / align * align
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
