// Package web contains the pre-built Vue frontend embedded into the Go binary.
package web

import "embed"

// Assets is the production frontend build. It is generated from frontend/dist
// by build.ps1 and committed so a Go build never needs Node.js.
//
//go:embed all:dist
var Assets embed.FS
