import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = '7fd417fb9a9a277c6a9339a8ac87f907df7c25f7'
CORE = 'c5062921054902b25215a6a933e72ccd714c9bfa'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()


def require(value, message):
    if not value:
        raise SystemExit(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source():
    allowed = {
        '.github/workflows/build.yaml', '.github/workflows/experiment-tun-recovery.yml',
        'lib/common/task.dart', 'core/experiment_interface_test.go',
        'core/config.go', 'core/lifecycle.go', 'core/egress_windows.go',
        'core/egress_windows_test.go', 'core/egress_other.go',
        'test/common/task_windows_interface_experiment_test.dart', 'tool/verify_tun_experiment.py',
        *[f'tool/tun-recovery/{name}' for name in ['Measure-Startup.ps1', 'Start-Automatic.cmd', 'Start-WLAN.cmd', 'ACCEPTANCE.txt']],
    }
    changed = set(git('diff', '--name-only', BASE, 'HEAD').splitlines())
    require(changed <= allowed, f'Unexpected changes: {changed - allowed}')
    require(git('-C', 'core/Clash.Meta', 'rev-parse', 'HEAD') == CORE, 'Core pin changed')
    core_changes = set(git('-C', 'core/Clash.Meta', 'diff', '--name-only').splitlines())
    require(core_changes <= {'component/ca/ca-certificates.crt'}, 'Tracked core code changed')
    if core_changes:
        require(sha((ROOT / 'core/Clash.Meta/component/ca/ca-certificates.crt').read_bytes()) == 'a41b5d356aea97a529fe27e0f7316d2f9d946d75927476cf9cf1b90637d00505', 'CA bundle differs from the official v0.9.2 build')
    pubspec = (ROOT / 'pubspec.yaml').read_text(encoding='utf-8')
    require(pubspec.count('build_assets: true') == 2 and 'build_assets: false' not in pubspec, 'Native hooks disabled')
    require(not git('diff', BASE, 'HEAD', '--', 'pubspec.yaml', 'pubspec.lock', 'build_config.yaml', 'setup.dart', 'android', 'plugins', 'services', 'windows', 'lib/models', 'lib/core'), 'Protected code or versions changed')
    print('Official v0.9.2 pins, protected code and native hooks preserved')


def pe(data, name):
    require(data[:2] == b'MZ', f'Invalid PE file: {name}')
    offset = struct.unpack_from('<I', data, 60)[0]
    require(data[offset:offset + 4] == b'PE\0\0', f'Invalid PE header: {name}')
    expected = [0x14c, 0x8664] if Path(name).name == 'EnableLoopback.exe' else [0x8664]
    require(struct.unpack_from('<H', data, offset + 4)[0] in expected, f'Wrong PE architecture: {name}')


def package():
    source()
    bundle = ROOT / 'build/windows/x64/runner/Release'
    for name in ['FlClash.exe', 'FlClashCore.exe', 'FlClashHelperService.exe', 'manifest.json', 'flutter_windows.dll', 'data/app.so', 'data/icudtl.dat']:
        require((bundle / name).is_file() and (bundle / name).stat().st_size > 0, f'Missing release file: {name}')
    require((bundle / 'data/flutter_assets').is_dir(), 'Flutter assets missing')
    require(list(bundle.rglob('*rust_api*.dll')), 'Native Rust library missing')
    require(list(bundle.glob('vcruntime*.dll')) and list(bundle.glob('msvcp*.dll')), 'MSVC runtime missing')
    for file in [*bundle.rglob('*.exe'), *bundle.rglob('*.dll')]:
        pe(file.read_bytes(), str(file))
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest['coreSha256'] == sha((bundle / 'FlClashCore.exe').read_bytes()), 'Core integrity hash mismatch')
    archives = list((ROOT / 'dist').rglob('*.zip'))
    require(len(archives) == 1, f'Expected one native package: {archives}')
    target = ROOT / 'delivery/tun-experiment'
    target.mkdir(parents=True, exist_ok=False)
    archive = target / 'FlClash-v0.9.2-experiment-tun-recovery-windows-x64.zip'
    shutil.copy2(archives[0], archive)
    with zipfile.ZipFile(archive) as z:
        entries = {name.replace('\\', '/').lstrip('./'): name for name in z.namelist() if not name.endswith('/')}
        for file in bundle.rglob('*'):
            if not file.is_file():
                continue
            relative = file.relative_to(bundle).as_posix()
            matches = [key for key in entries if key == relative or key.endswith('/' + relative)]
            require(len(matches) == 1 and sha(z.read(entries[matches[0]])) == sha(file.read_bytes()), f'Portable content mismatch: {relative}')
        app_entry = next(key for key in entries if key == 'FlClash.exe' or key.endswith('/FlClash.exe'))
        prefix = app_entry[:-len('FlClash.exe')]
    with zipfile.ZipFile(archive, 'a', compression=zipfile.ZIP_DEFLATED) as z:
        for file in (ROOT / 'tool/tun-recovery').iterdir():
            z.write(file, prefix + file.name)
        require(z.testzip() is None, 'ZIP integrity failure')
    report = {
        'commit': git('rev-parse', 'HEAD'), 'base': BASE, 'core': CORE,
        'runtime_change': 'Windows automatic egress bootstrap before early outbound sessions; released after TUN setup; explicit interface retained',
        'package_validation': 'complete x64 release files, native assets, portable equality and core hash passed',
        'network_fix_confirmed': False,
        'device_network_tests': 'not performed; user A/B and NIC packet evidence required',
    }
    (target / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (target / 'SHA256SUMS.txt').write_text(''.join(f'{sha(file.read_bytes())}  {file.name}\n' for file in sorted(target.iterdir()) if file.is_file()), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print((target / 'SHA256SUMS.txt').read_text(encoding='utf-8'))


if __name__ == '__main__':
    {'source': source, 'package': package}[sys.argv[1]]()
