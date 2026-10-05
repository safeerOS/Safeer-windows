//go:build windows

package main

import (
	"os/exec"
	"syscall"
	"unsafe"
)

// showMessage pokaze okno s sporocilom (MessageBoxW) in vrne izbrani gumb.
func showMessage(title, text string, style uint) int {
	user32 := syscall.NewLazyDLL("user32.dll")
	proc := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	r, _, _ := proc.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), uintptr(style))
	return int(r)
}

// brezOkna: podproces se zazene brez okna ukazne vrstice (CREATE_NO_WINDOW).
func brezOkna(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
}
