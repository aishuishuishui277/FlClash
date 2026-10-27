package core

import (
	"context"
	"sync"
)

type deferredStartupCheck struct {
	ctx context.Context
	run func()
}

type startupHealthGate struct {
	mu      sync.Mutex
	vpn     bool
	ready   bool
	pending map[any]deferredStartupCheck
}

func (g *startupHealthGate) before(ctx context.Context, key any, run func()) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if ctx.Err() != nil {
		return false
	}
	if !g.vpn || g.ready {
		return true
	}
	if g.pending == nil {
		g.pending = make(map[any]deferredStartupCheck)
	}
	for key, check := range g.pending {
		if check.ctx.Err() != nil {
			delete(g.pending, key)
		}
	}
	g.pending[key] = deferredStartupCheck{ctx, run}
	return false
}

func (g *startupHealthGate) update(vpn, ready bool) []func() {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.vpn = vpn
	g.ready = g.ready || ready
	if g.vpn && !g.ready {
		return nil
	}
	checks := make([]func(), 0, len(g.pending))
	for _, check := range g.pending {
		if check.ctx.Err() == nil {
			checks = append(checks, func() {
				if check.ctx.Err() == nil {
					check.run()
				}
			})
		}
	}
	g.pending = nil
	return checks
}
