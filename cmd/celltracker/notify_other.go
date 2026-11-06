//go:build !windows && !darwin

package main

import "fmt"

func notifyUser(title, message string) {
	fmt.Printf("%s: %s\n", title, message)
}
