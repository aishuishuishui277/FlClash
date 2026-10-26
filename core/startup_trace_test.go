package core

import (
	"strings"
	"testing"
	"time"
)

func TestStartupTraceRedactsPayload(t *testing.T) {
	secret := "password=secret UUID=private-token https://private/sub?token=hidden"
	for _, protocol := range []string{"TCP", "UDP"} {
		name, code := startupLogClass("[" + protocol + "] dial " + secret + " error: handshake timeout")
		if name != "flow_"+strings.ToLower(protocol)+"_error" || code != 2 {
			t.Fatalf("unexpected classification: %q %d", name, code)
		}
		state := &startupTraceState{queue: make(chan string, 1)}
		state.emit(name, code, 0)
		if value := <-state.queue; strings.Contains(value, "secret") || strings.Contains(value, "private") || strings.Contains(value, "token") {
			t.Fatalf("credential leaked: %s", value)
		}
	}
	name, _ := startupLogClass("unrelated log " + secret)
	if name != "" {
		t.Fatal("unrelated logs must not be relayed")
	}
}

func TestStartupTraceDisabledAndBounded(t *testing.T) {
	if startupTrace.Load() != nil {
		t.Fatal("diagnostics must default to disabled")
	}
	traceStartup("ignored", 0, 0)
	state := &startupTraceState{queue: make(chan string, 1)}
	state.emit("first", 0, 0)
	done := make(chan struct{})
	go func() { state.emit("overflow", 0, 0); close(done) }()
	select {
	case <-done:
		if state.dropped.Load() != 1 {
			t.Fatal("dropped diagnostics must be counted")
		}
	case <-time.After(time.Second):
		t.Fatal("diagnostics blocked the caller")
	}
}

func TestStartupTraceSinkLifecycle(t *testing.T) {
	received := make(chan string, 8)
	defer SetStartupDiagnosticSink(nil)
	SetStartupDiagnosticSink(func(value string) { received <- value })
	traceStartup("config_apply_begin", 0, 0)
	select {
	case value := <-received:
		if !strings.Contains(value, `"event":"config_apply_begin"`) {
			t.Fatalf("unexpected event: %s", value)
		}
	case <-time.After(time.Second):
		t.Fatal("enabled trace did not reach sink")
	}
	SetStartupDiagnosticSink(nil)
	if startupTrace.Load() != nil {
		t.Fatal("disabled sink is still installed")
	}
}

func TestStartupTraceClassifiesOnlyErrorTail(t *testing.T) {
	name, code := startupLogClass("[TCP] dial dialer loop error: connection refused")
	if name != "flow_tcp_error" || code != 4 {
		t.Fatal("proxy metadata was interpreted as a dialer-loop error")
	}
}
