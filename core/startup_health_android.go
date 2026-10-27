package core

import (
	"context"
	"sync/atomic"

	"github.com/metacubex/mihomo/adapter/provider"
	"github.com/metacubex/sing-quic/hysteria2"
)

var androidStartupHealth = startupHealthGate{vpn: true}
var startupTunReady atomic.Bool

func init() {
	provider.StartupAutoHealthCheckGate = func(ctx context.Context, key any, run func()) bool {
		allowed := androidStartupHealth.before(ctx, key, run)
		traceStartup("auto_healthcheck_gate", boolTrace(allowed), boolTrace(startupTunReady.Load()))
		return allowed
	}
	hysteria2.ClientLifecycleHook = func(event string, client, session uint64, err error) {
		traceStartup("hy2_"+event, int64(client), int64(session))
		traceStartup("hy2_"+event+"_vpn", boolTrace(startupTunReady.Load()), int64(session))
		if err != nil {
			traceStartup("hy2_"+event+"_error", startupErrorClass(err.Error()), int64(session))
		}
	}
}

func resumeStartupHealth(checks []func()) {
	for _, check := range checks {
		safeGo("startupHealthCheck", check)
	}
	traceStartup("auto_healthcheck_resumed", 0, int64(len(checks)))
}

func SetStartupVPNMode(enabled bool) {
	defer recoverExport("setStartupVPNMode")
	traceStartup("startup_vpn_mode", boolTrace(enabled), 0)
	resumeStartupHealth(androidStartupHealth.update(enabled, false))
}

func markStartupTunReady() {
	startupTunReady.Store(true)
	traceStartup("startup_tun_ready", 1, 0)
	resumeStartupHealth(androidStartupHealth.update(true, true))
}
