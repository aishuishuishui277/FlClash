package core

import (
	"github.com/metacubex/mihomo/component/dialer"
	"github.com/metacubex/mihomo/config"
	"github.com/metacubex/mihomo/listener/sing_tun"
	"github.com/metacubex/mihomo/log"
	tun "github.com/metacubex/sing-tun"
)

var (
	windowsBootstrapInterface string
	detectWindowsEgress       = windowsDefaultEgress
)

func windowsDefaultEgress() string {
	network, err := tun.NewNetworkUpdateMonitor(log.SingLogger)
	if err != nil {
		return ""
	}
	defer network.Close()
	monitor, err := tun.NewDefaultInterfaceMonitor(network, log.SingLogger, tun.DefaultInterfaceMonitorOptions{
		InterfaceFinder: sing_tun.DefaultInterfaceFinder,
	})
	if err != nil {
		return ""
	}
	defer monitor.Close()
	if err := monitor.Start(); err != nil {
		return ""
	}
	if selected := monitor.DefaultInterface(); selected != nil {
		return selected.Name
	}
	return ""
}

func prepareWindowsEgress(cfg *config.Config) *config.Config {
	windowsBootstrapInterface = ""
	general := cfg.General
	if general.Interface != "" || !general.Tun.Enable || !general.Tun.AutoRoute || !general.Tun.AutoDetectInterface || dialer.DefaultInterfaceFinder.Load() != nil {
		return cfg
	}
	name := detectWindowsEgress()
	if name == "" || name == general.Tun.Device || name == "<invalid>" || name == "<nil>" {
		return cfg
	}
	// Provider/DNS traffic can create a UDP session before TUN installs its finder.
	prepared := *cfg
	bound := *general
	bound.Interface = name
	prepared.General = &bound
	windowsBootstrapInterface = name
	log.Infoln("[Windows egress] bootstrap interface => %s", name)
	return &prepared
}

func finishWindowsEgress(cfg *config.Config) {
	if cfg == nil || windowsBootstrapInterface == "" {
		return
	}
	dialer.DefaultInterface.CompareAndSwap(windowsBootstrapInterface, cfg.General.Interface)
	windowsBootstrapInterface = ""
	log.Infoln("[Windows egress] bootstrap released; configured interface=%q, TUN detector ready=%t", cfg.General.Interface, dialer.DefaultInterfaceFinder.Load() != nil)
}
