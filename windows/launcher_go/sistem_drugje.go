//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
)

// Zaganjalnik tece samo na Windows. Ta datoteka obstaja, da se njegova pravila (razlicice, razpakirava, ciscenje)
// preizkusijo tudi drugje (go test na Linuxu in na strezniku za preverjanje).
func showMessage(title, text string, style uint) int {
	fmt.Fprintln(os.Stderr, title+": "+text)
	return 0
}

func brezOkna(cmd *exec.Cmd) {}
