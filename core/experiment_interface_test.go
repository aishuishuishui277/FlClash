package core

import (
	"testing"

	"github.com/metacubex/mihomo/config"
)

func TestWindowsOutboundInterfaceExperiment(t *testing.T) {
	cfg, err := config.Parse([]byte(`
mixed-port: 7890
interface-name: WLAN
rules: ["MATCH,DIRECT"]
tun:
  enable: true
  device: FlClash
  stack: mixed
  auto-route: true
  auto-detect-interface: true
  dns-hijack: [any:53]
  route-exclude-address: [203.0.113.0/24]
`))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.General.Interface != "WLAN" || !cfg.General.Tun.AutoDetectInterface || !cfg.General.Tun.AutoRoute {
		t.Fatalf("interface binding or TUN routing changed: interface=%q tun=%+v", cfg.General.Interface, cfg.General.Tun)
	}
}
