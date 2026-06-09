package main

import (
	"os"
	"strings"
	"testing"
)

func TestMainConfiguresGracefulShutdown(t *testing.T) {
	data, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatal(err)
	}
	source := string(data)
	for _, required := range []string{
		"server.SetGraceful(true)",
		"server.SetGracefulShutdownTimeout(",
	} {
		if !strings.Contains(source, required) {
			t.Fatalf("main.go must configure GoFrame graceful shutdown with %q", required)
		}
	}
}
