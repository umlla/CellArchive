//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

func notifyUser(title, message string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")
	titlePtr, _ := syscall.UTF16PtrFromString(title)
	messagePtr, _ := syscall.UTF16PtrFromString(message)
	// MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND
	_, _, _ = messageBox.Call(0,
		uintptr(unsafe.Pointer(messagePtr)),
		uintptr(unsafe.Pointer(titlePtr)),
		uintptr(0x00000040|0x00010000))
}
