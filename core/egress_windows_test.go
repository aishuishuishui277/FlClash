package core

import (
	"net/netip"
	"reflect"
	"testing"

	"github.com/metacubex/mihomo/component/dialer"
	"github.com/metacubex/mihomo/config"
)

func TestWindowsEgressBootstrap(t *testing.T) {
	originalDetect := detectWindowsEgress
	originalInterface := dialer.DefaultInterface.Load()
	originalFinder := dialer.DefaultInterfaceFinder.Load()
	t.Cleanup(func() {
		detectWindowsEgress = originalDetect
		dialer.DefaultInterface.Store(originalInterface)
		dialer.DefaultInterfaceFinder.Store(originalFinder)
		windowsBootstrapInterface = ""
	})
	for _, name := range []string{"Wi-Fi", "Ethernet 2"} {
		t.Run(name, func(t *testing.T) {
			cfg, err := config.Parse([]byte("tun:\n  enable: true\n  auto-route: true\n  auto-detect-interface: true\n  device: FlClash\n"))
			if err != nil {
				t.Fatal(err)
			}
			dialer.DefaultInterfaceFinder.Store(nil)
			detectWindowsEgress = func() string { return name }
			prepared := prepareWindowsEgress(cfg)
			if prepared.General.Interface != name || cfg.General.Interface != "" {
				t.Fatalf("bootstrap must bind a copy, not persist the detected name: %q / %q", prepared.General.Interface, cfg.General.Interface)
			}
			if !prepared.General.Tun.AutoDetectInterface || !prepared.General.Tun.AutoRoute || !reflect.DeepEqual(prepared.General.Tun, cfg.General.Tun) {
				t.Fatal("TUN configuration changed")
			}
			dialer.DefaultInterface.Store(prepared.General.Interface)
			finder := &egressTestFinder{name: "new-network"}
			dialer.DefaultInterfaceFinder.Store(finder)
			finishWindowsEgress(cfg)
			if dialer.DefaultInterface.Load() != "" || dialer.DefaultInterfaceFinder.Load() != finder {
				t.Fatal("automatic detection was not restored")
			}
			if got := dialer.DefaultInterfaceFinder.Load().FindInterfaceName(netip.IPv4Unspecified()); got != "new-network" {
				t.Fatalf("network changes must remain dynamic: %q", got)
			}
		})
	}
	for _, tc := range []struct {
		name string
		yaml string
	}{
		{"explicit", "interface-name: custom-exit\ntun: {enable: true, auto-route: true, auto-detect-interface: true}"},
		{"disabled", "tun: {enable: false}"},
		{"manual-detection", "tun: {enable: true, auto-detect-interface: false}"},
		{"manual-routing", "tun: {enable: true, auto-route: false}"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := config.Parse([]byte(tc.yaml))
			if err != nil {
				t.Fatal(err)
			}
			dialer.DefaultInterfaceFinder.Store(nil)
			detectWindowsEgress = func() string { t.Fatal("unexpected automatic lookup"); return "" }
			if prepareWindowsEgress(cfg) != cfg {
				t.Fatal("explicit/disabled configuration changed")
			}
		})
	}
	t.Run("active-detector", func(t *testing.T) {
		cfg := config.DefaultRawConfig()
		cfg.Tun.Enable = true
		parsed, err := config.ParseRawConfig(cfg)
		if err != nil {
			t.Fatal(err)
		}
		dialer.DefaultInterfaceFinder.Store(&egressTestFinder{name: "active-network"})
		detectWindowsEgress = func() string { t.Fatal("active detector must be reused"); return "" }
		if prepareWindowsEgress(parsed) != parsed {
			t.Fatal("active detector was replaced")
		}
	})
	for _, name := range []string{"", "FlClash", "<invalid>", "<nil>"} {
		t.Run("reject-"+name, func(t *testing.T) {
			cfg, err := config.Parse([]byte("tun: {enable: true, device: FlClash, auto-route: true, auto-detect-interface: true}"))
			if err != nil {
				t.Fatal(err)
			}
			dialer.DefaultInterfaceFinder.Store(nil)
			detectWindowsEgress = func() string { return name }
			if prepareWindowsEgress(cfg) != cfg || windowsBootstrapInterface != "" {
				t.Fatal("invalid or self-TUN interface was accepted")
			}
		})
	}
}

type egressTestFinder struct{ name string }

func (f *egressTestFinder) FindInterfaceName(netip.Addr) string { return f.name }
