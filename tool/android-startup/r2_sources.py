import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PATCHES = Path(__file__).parent / 'r2'
SOURCES = json.loads((PATCHES / 'sources.json').read_text(encoding='utf-8'))
STATE = Path(os.environ.get('RUNNER_TEMP', ROOT / '.dart_tool')) / 'flclash-r2-sources'
MODULE = 'github.com/metacubex/sing-quic'
VERSION = 'v0.0.0-20260904234848-1c242664697a'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def roots():
    module = json.loads(subprocess.check_output(['go', 'list', '-m', '-json', MODULE], cwd=ROOT / 'core'))
    assert module['Version'] == VERSION and 'Replace' not in module, 'Unexpected sing-quic version'
    cache = Path(subprocess.check_output(['go', 'env', 'GOMODCACHE'], text=True).strip()).resolve()
    directory = Path(module['Dir']).resolve()
    assert directory.is_relative_to(cache), 'Module path outside Go cache'
    return {'mihomo': ROOT / 'core/Clash.Meta', 'sing-quic': directory}


def apply():
    locations = roots()
    assert not STATE.exists(), 'Unrestored R2 source patch state'
    plan = []
    for source in SOURCES:
        path = locations[source['group']] / source['file']
        assert digest(path) == source['before'], f'Unexpected unpatched source: {path}'
        plan.append(dict(source, path=str(path), mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else None,
                         parent_mode=stat.S_IMODE(path.parent.stat().st_mode)))
    STATE.mkdir(parents=True)
    for i, entry in enumerate(plan):
        if entry['before'] is not None:
            (STATE / str(i)).write_bytes(Path(entry['path']).read_bytes())
    (STATE / 'state.json').write_text(json.dumps(plan), encoding='utf-8')
    for entry in plan:
        path = Path(entry['path'])
        path.parent.chmod(entry['parent_mode'] | stat.S_IWUSR)
        if path.exists():
            path.chmod(entry['mode'] | stat.S_IWUSR)
        command = ['git', '-c', 'core.autocrlf=false', 'apply', '--whitespace=nowarn', '--unidiff-zero', str(PATCHES / entry['patch'])]
        subprocess.run(command[:5] + ['--check'] + command[5:], cwd=locations[entry['group']], check=True)
        subprocess.run(command, cwd=locations[entry['group']], check=True)
    verify()


def verify():
    locations = roots()
    for entry in SOURCES:
        assert digest(locations[entry['group']] / entry['file']) == entry['after'], f'R2 patch missing/drifted: {entry["file"]}'
    report = {'sing_quic': VERSION, 'mihomo': 'c5062921054902b25215a6a933e72ccd714c9bfa', 'sources': SOURCES}
    destination = ROOT / 'r2-source-provenance.json'
    destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('R2 exact source patches verified; version pins unchanged')


def restore():
    state = STATE / 'state.json'
    if not state.exists():
        return
    locations = roots()
    plan = json.loads(state.read_text(encoding='utf-8'))
    for i, entry in enumerate(plan):
        path = Path(entry['path'])
        assert path == locations[entry['group']] / entry['file'], 'Invalid restore target'
        if entry['before'] is None:
            if path.exists():
                assert digest(path) == entry['after'], 'Refuse deleting unexpected helper'
                path.unlink()
        else:
            original = STATE / str(i)
            assert digest(original) == entry['before'], 'Corrupt source backup'
            path.write_bytes(original.read_bytes())
            path.chmod(entry['mode'])
        assert digest(path) == entry['before'], 'Source restore failed'
    for entry in plan:
        Path(entry['path']).parent.chmod(entry['parent_mode'])
    print('R2 sources restored before Go module cache save')


if __name__ == '__main__':
    {'apply': apply, 'verify': verify, 'restore': restore}[sys.argv[1]]()
