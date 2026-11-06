//go:build darwin

package main

import (
	"fmt"
	"os/exec"
	"strings"
)

func notifyUser(title, message string) {
	script := fmt.Sprintf(`display dialog "%s" with title "%s" buttons {"OK"} default button "OK"`,
		escapeAppleScript(message), escapeAppleScript(title))
	_ = exec.Command("osascript", "-e", script).Run()
}

func escapeAppleScript(value string) string {
	value = strings.ReplaceAll(value, `\`, `\\`)
	value = strings.ReplaceAll(value, `"`, `\"`)
	value = strings.ReplaceAll(value, "\n", `\n`)
	return value
}
