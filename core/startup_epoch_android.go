package core

import (
	"sync/atomic"

	"github.com/metacubex/sing-quic/hysteria2"
)

var startupVPNEpoch atomic.Uint64
var startupTunReady atomic.Bool

func init() {
	hysteria2.ClientStartupEpoch = func() uint64 { return startupVPNEpoch.Load() }
	hysteria2.ClientLifecycleHook = func(event string, client, session, epoch uint64, err error) {
		traceStartup("hy2_"+event, int64(client), int64(session))
		traceStartup("hy2_"+event+"_epoch", int64(epoch), int64(session))
		traceStartup("hy2_"+event+"_vpn", boolTrace(startupTunReady.Load()), int64(session))
		if err != nil {
			traceStartup("hy2_"+event+"_error", startupErrorClass(err.Error()), int64(session))
		}
	}
}

func markStartupVPNEpoch() {
	startupTunReady.Store(true)
	traceStartup("startup_tun_ready", 1, 0)
	changed := startupVPNEpoch.CompareAndSwap(0, 1)
	traceStartup("hy2_vpn_epoch", boolTrace(changed), int64(startupVPNEpoch.Load()))
}
