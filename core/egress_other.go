//go:build !windows

package core

import "github.com/metacubex/mihomo/config"

func prepareWindowsEgress(cfg *config.Config) *config.Config { return cfg }

func finishWindowsEgress(*config.Config) {}
