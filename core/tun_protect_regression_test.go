package core

import (
	"bytes"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func protectDeclarations(t *testing.T, source []byte, names ...string) string {
	t.Helper()
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "production.go", source, 0)
	if err != nil {
		t.Fatal(err)
	}
	wanted := make(map[string]bool)
	for _, name := range names {
		wanted[name] = true
	}
	var out bytes.Buffer
	for _, decl := range file.Decls {
		var name string
		switch node := decl.(type) {
		case *ast.FuncDecl:
			name = node.Name.Name
		case *ast.GenDecl:
			if len(node.Specs) == 1 {
				if spec, ok := node.Specs[0].(*ast.TypeSpec); ok {
					name = spec.Name.Name
				}
			}
		}
		if wanted[name] {
			if err := format.Node(&out, fset, decl); err != nil {
				t.Fatal(err)
			}
			out.WriteString("\n\n")
			delete(wanted, name)
		}
	}
	if len(wanted) != 0 {
		t.Fatalf("missing Android production declarations: %v", wanted)
	}
	return out.String()
}

func TestAndroidProtectWindowAgainstDiagnosticBaseline(t *testing.T) {
	baseline, err := exec.Command("git", "show", "611de39561ee19bb3c5aa9b8b5bf4284a083c485:core/lib.go").Output()
	if err != nil {
		t.Fatal(err)
	}
	current, err := os.ReadFile("lib.go")
	if err != nil {
		t.Fatal(err)
	}
	trace, err := os.ReadFile("startup_trace.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, sample := range []struct {
		name string
		data []byte
	}{
		{"baseline", baseline},
		{"R1", current},
	} {
		dir := t.TempDir()
		production := "package core\nimport (\"sync\"; \"github.com/metacubex/mihomo/listener/sing_tun\")\n" +
			protectDeclarations(t, sample.data, "TunCallbacks", "TunHandler", "handleProtect") +
			protectDeclarations(t, trace, "boolTrace")
		implementation := filepath.Join(dir, "protect.go")
		tests := filepath.Join(dir, "protect_test.go")
		if err := os.WriteFile(implementation, []byte(production), 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(tests, []byte(protectWindowCases), 0600); err != nil {
			t.Fatal(err)
		}
		output, err := exec.Command("go", "test", "-count=1", implementation, tests).CombinedOutput()
		if sample.name == "baseline" {
			if err == nil || !strings.Contains(string(output), "protect skipped while listener is pending") {
				t.Fatalf("baseline did not reproduce the protection window: %v\n%s", err, output)
			}
			t.Log("baseline: expected failure reproduced while listener is pending")
		} else if err != nil {
			t.Fatalf("R1 Android handler regression failed: %v\n%s", err, output)
		} else {
			t.Logf("R1: four handler cases passed: %s", output)
		}
	}
}

const protectWindowCases = `package core
import (
    "testing"
    "github.com/metacubex/mihomo/listener/sing_tun"
)
type protectCall struct { calls int; result bool }
func (p *protectCall) Protect(int) bool { p.calls++; return p.result }
func (*protectCall) ResolveUid(int, string, string) int { return -1 }
func (*protectCall) ResolvePackage(int) string { return "" }
type traceRecord struct { name string; code int64 }
var records []traceRecord
func traceStartupSocket(name string, code, value int64) { records = append(records, traceRecord{name, code}) }
func TestProtectWhileListenerPending(t *testing.T) {
    records = nil
    callback := &protectCall{result: true}
    handler := &TunHandler{callbacks: callback}
    handler.handleProtect(42)
    if callback.calls != 1 { t.Fatal("protect skipped while listener is pending") }
    if len(records) != 2 || records[0].name != "protect_before_tun_ready" || records[1].code != 1 { t.Fatalf("unexpected trace: %v", records) }
}
func TestNoRegisteredCallback(t *testing.T) {
    records = nil
    handler := &TunHandler{}
    handler.handleProtect(43)
    if len(records) != 1 || records[0].name != "protect_skipped" { t.Fatalf("unexpected trace: %v", records) }
}
func TestProtectionFailureRemainsVisible(t *testing.T) {
    records = nil
    callback := &protectCall{result: false}
    handler := &TunHandler{callbacks: callback}
    handler.handleProtect(44)
    if callback.calls != 1 || len(records) != 2 || records[1].name != "protect_result" || records[1].code != 0 { t.Fatalf("failure hidden: %v", records) }
}
func TestProtectionAfterListenerReady(t *testing.T) {
    records = nil
    callback := &protectCall{result: true}
    handler := &TunHandler{callbacks: callback, listener: &sing_tun.Listener{}}
    handler.handleProtect(45)
    if callback.calls != 1 || len(records) != 1 || records[0].name != "protect_result" || records[0].code != 1 { t.Fatalf("ready path changed: %v", records) }
}
`
