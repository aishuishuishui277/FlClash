package core

import (
	"encoding/json"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/metacubex/mihomo/common/observable"
	"github.com/metacubex/mihomo/log"
)

type startupTraceState struct {
	send    func(string)
	queue   chan string
	done    chan struct{}
	stopped atomic.Bool
	sockets atomic.Uint32
	dropped atomic.Uint64
	logs    observable.Subscription[log.Event]
}

var startupTrace atomic.Pointer[startupTraceState]
var startupTraceMu sync.Mutex

func boolTrace(value bool) int64 {
	if value {
		return 1
	}
	return 0
}

func traceProtocol(network string) int64 {
	if strings.HasPrefix(network, "tcp") {
		return 1
	}
	if strings.HasPrefix(network, "udp") {
		return 2
	}
	return 0
}

func SetStartupDiagnosticSink(send func(string)) {
	startupTraceMu.Lock()
	defer startupTraceMu.Unlock()
	if old := startupTrace.Swap(nil); old != nil {
		old.stopped.Store(true)
		log.UnSubscribe(old.logs)
		close(old.done)
	}
	if send == nil {
		return
	}
	state := &startupTraceState{send: send, queue: make(chan string, 128), done: make(chan struct{}), logs: log.Subscribe()}
	startupTrace.Store(state)
	safeGo("startupTraceSend", func() {
		for {
			select {
			case value := <-state.queue:
				state.send(value)
				if dropped := state.dropped.Swap(0); dropped > 0 {
					data, _ := json.Marshal(map[string]any{"event": "trace_dropped", "time_ms": time.Now().UnixMilli(), "value": dropped})
					state.send(string(data))
				}
			case <-state.done:
				return
			}
		}
	})
	safeGo("startupTraceLog", func() {
		for event := range state.logs {
			if !state.stopped.Load() {
				name, code := startupLogClass(event.Payload)
				if name != "" {
					state.emit(name, code, 0)
				}
			}
		}
	})
}

func (state *startupTraceState) emit(event string, code, value int64) {
	data, _ := json.Marshal(struct {
		Time  int64  `json:"time_ms"`
		Event string `json:"event"`
		Code  int64  `json:"code"`
		Value int64  `json:"value"`
	}{time.Now().UnixMilli(), event, code, value})
	select {
	case state.queue <- string(data):
	default:
		state.dropped.Add(1)
	}
}

func traceStartup(event string, code, value int64) {
	if state := startupTrace.Load(); state != nil {
		state.emit(event, code, value)
	}
}

func traceStartupSocket(event string, code, value int64) {
	if state := startupTrace.Load(); state != nil {
		count := state.sockets.Add(1)
		if count <= 512 {
			state.emit(event, code, value)
		} else if count == 513 {
			state.emit("socket_trace_limit", 0, 512)
		}
	}
}

func startupErrorClass(message string) int64 {
	text := strings.ToLower(message)
	switch {
	case strings.Contains(text, "dialer loop"), strings.Contains(text, "loopback connection"):
		return 1
	case strings.Contains(text, "timeout"), strings.Contains(text, "timed out"), strings.Contains(text, "deadline"):
		return 2
	case strings.Contains(text, "network is unreachable"), strings.Contains(text, "no route"):
		return 3
	case strings.Contains(text, "refused"):
		return 4
	case strings.Contains(text, "tls"), strings.Contains(text, "handshake"), strings.Contains(text, "certificate"):
		return 5
	case strings.Contains(text, "eof"):
		return 6
	case strings.Contains(text, "dns"), strings.Contains(text, "no such host"):
		return 7
	default:
		return 8
	}
}

func startupLogClass(message string) (string, int64) {
	if strings.HasPrefix(message, "Mixed(http+socks) proxy listening at: ") {
		return "mixed_listener_ready", 0
	}
	protocol := ""
	if strings.HasPrefix(message, "[TCP]") {
		protocol = "tcp"
	} else if strings.HasPrefix(message, "[UDP]") {
		protocol = "udp"
	}
	if protocol != "" {
		if strings.Contains(message, " error:") {
			return "flow_" + protocol + "_error", startupErrorClass(message[strings.LastIndex(message, " error:")+7:])
		}
		if strings.Contains(message, " using ") {
			return "flow_" + protocol + "_connected", 0
		}
	}
	if strings.HasPrefix(message, "[DNS] resolve ") {
		return "dns_query", 0
	}
	if strings.HasPrefix(message, "[DNS] cache hit ") {
		return "dns_cache_hit", 0
	}
	if strings.HasPrefix(message, "[DNS] ") && strings.Contains(message, " --> ") && strings.Contains(message, " from ") {
		return "dns_answer", 0
	}
	return "", 0
}
