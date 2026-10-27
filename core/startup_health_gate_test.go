package core

import (
	"context"
	"sync"
	"sync/atomic"
	"testing"
)

func TestStartupHealthWaitsWithoutBlockingAndDeduplicates(t *testing.T) {
	g := startupHealthGate{vpn: true}
	var runs int
	for range 10 {
		if g.before(context.Background(), "provider", func() { runs++ }) {
			t.Fatal("automatic pre-VPN probe permitted")
		}
	}
	if runs != 0 {
		t.Fatal("a deferred probe ran before TUN readiness")
	}
	checks := g.update(true, true)
	if len(checks) != 1 {
		t.Fatalf("expected one resumed provider, got %d", len(checks))
	}
	checks[0]()
	if runs != 1 || !g.before(context.Background(), "provider", func() {}) {
		t.Fatal("ready VPN did not restore normal checks")
	}
	if len(g.update(true, true)) != 0 {
		t.Fatal("duplicate readiness scheduled another probe")
	}
	if !g.before(context.Background(), "provider", func() {}) {
		t.Fatal("the first-start gate rearmed")
	}
}

func TestStartupHealthProxyModeAndCancellation(t *testing.T) {
	g := startupHealthGate{vpn: true}
	ctx, cancel := context.WithCancel(context.Background())
	g.before(ctx, "removed", func() { t.Fatal("cancelled provider resumed") })
	cancel()
	checks := g.update(false, false)
	if len(checks) != 0 || !g.before(context.Background(), "proxy", func() {}) {
		t.Fatal("non-VPN proxy mode was blocked")
	}
	if g.before(ctx, "removed", func() {}) {
		t.Fatal("cancelled provider admitted")
	}
	g.update(true, false)
	var runs int
	g.before(context.Background(), "valid", func() { runs++ })
	for _, run := range g.update(false, false) {
		run()
	}
	if runs != 1 {
		t.Fatal("switching out of VPN mode lost a deferred check")
	}
}

func TestStartupHealthConcurrentReadinessDoesNotLoseChecks(t *testing.T) {
	g := startupHealthGate{vpn: true}
	var wg sync.WaitGroup
	var runs atomic.Int32
	for i := range 100 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			run := func() { runs.Add(1) }
			if g.before(context.Background(), i, run) {
				run()
			}
		}()
	}
	for _, run := range g.update(true, true) {
		run()
	}
	wg.Wait()
	if runs.Load() != 100 {
		t.Fatalf("lost or duplicated checks: %d", runs.Load())
	}
}
