import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PATCH = '3f9524a193106949a17c6940b9766a6ee4af5d62'
CORE = '8380d0e7462f061a964323e9bf3129a236fcc5d5'
FORBIDDEN = re.compile(
    r'com[./]google[./]firebase[./](?:analytics|crashlytics)(?:[./:]|\b)'
    r'|com[./]google[./]android[./]gms[./](?:measurement|internal[./]measurement)(?:[./:]|\b)'
    r'|firebase-(?:analytics|crashlytics)|play-services-measurement'
    r'|FirebaseInitProvider|libcrashlytics', re.IGNORECASE
)


def run(*args):
    command = [str(arg) for arg in args]
    if os.name == 'nt' and Path(command[0]).suffix in ('.bat', '.cmd'):
        command = ['cmd', '/c', *command]
    return subprocess.check_output(command, cwd=ROOT, text=True, encoding='utf-8')


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source():
    subprocess.run(['git', 'merge-base', '--is-ancestor', PATCH, 'HEAD'], cwd=ROOT, check=True)
    require(run('git', '-C', 'core/Clash.Meta', 'rev-parse', 'HEAD').strip() == CORE, 'Core pin changed')
    protected = ['core', 'plugins', 'services', 'lib', 'android', 'windows', 'pubspec.yaml', 'pubspec.lock', 'build_config.yaml', 'setup.dart']
    require(not run('git', 'diff', PATCH, '--', *protected).strip(), 'Runtime source differs from approved patch')
    hooks = (ROOT / 'pubspec.yaml').read_text(encoding='utf-8')
    require(hooks.count('build_assets: true') == 2 and 'build_assets: false' not in hooks, 'Native hooks disabled')
    print('Approved runtime source, pinned core and both native hooks verified')


def exactly_one(paths, description):
    paths = list(paths)
    require(len(paths) == 1, f'Expected one {description}, found {paths}')
    return paths[0]


def output(platform):
    path = ROOT / 'delivery' / platform
    path.mkdir(parents=True, exist_ok=False)
    return path


def finish(path, report):
    report['commit'] = run('git', 'rev-parse', 'HEAD').strip()
    report['approved_patch'] = PATCH
    report['core_commit'] = CORE
    report['device_network_tests'] = 'not performed'
    report['ml_kit_metrics'] = 'retained on Android as approved'
    (path / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    files = sorted(file for file in path.iterdir() if file.is_file())
    (path / 'SHA256SUMS.txt').write_text(''.join(f'{digest(file.read_bytes())}  {file.name}\n' for file in files), encoding='utf-8')
    print((path / 'validation.json').read_text(encoding='utf-8'))
    print((path / 'SHA256SUMS.txt').read_text(encoding='utf-8'))


def android():
    apk = exactly_one((ROOT / 'dist').rglob('*.apk'), 'ARM64 release APK')
    analyzer = shutil.which('apkanalyzer')
    signer = shutil.which('apksigner')
    require(analyzer and signer, 'Android SDK inspection tools missing')
    signature = run(signer, 'verify', '--verbose', '--print-certs', apk)
    manifest = run(analyzer, 'manifest', 'print', apk)
    dex = run(analyzer, 'dex', 'packages', '--defined-only', apk)
    dependencies = (ROOT / 'android-runtime-dependencies.txt').read_text(encoding='utf-8')
    require('FAILED' not in dependencies and 'BUILD SUCCESSFUL' in dependencies, 'Dependency resolution incomplete')
    for label, content in [('DEX', dex), ('Manifest', manifest), ('dependencies', dependencies)]:
        require(not FORBIDDEN.search(content), f'Forbidden telemetry in {label}: {FORBIDDEN.search(content)}')
    tree = ET.fromstring(manifest)
    ns = '{http://schemas.android.com/apk/res/android}'
    package = tree.attrib['package']
    require(package in ['com.follow.clash', 'com.follow.clash.dev'], 'Unexpected application ID')
    sdk = tree.find('uses-sdk')
    require(sdk is not None and int(sdk.attrib[ns + 'minSdkVersion']) <= 35, 'APK cannot support Android 15')
    require(tree.find('application').attrib.get(ns + 'debuggable', 'false') != 'true', 'APK is not release mode')
    services = tree.findall('.//service')
    require(any(service.attrib.get(ns + 'permission') == 'android.permission.BIND_VPN_SERVICE' for service in services), 'VPN service missing')
    require('android.permission.INTERNET' in manifest, 'Internet permission missing')
    with zipfile.ZipFile(apk) as archive:
        require(archive.testzip() is None, 'APK ZIP integrity failure')
        names = archive.namelist()
        libs = [name for name in names if name.startswith('lib/') and name.endswith('.so')]
        require({name.split('/')[1] for name in libs} == {'arm64-v8a'}, 'APK is not ARM64-only')
        for required in ['libflutter.so', 'libapp.so', 'libgojni.so', 'librust_api.so']:
            require(any(Path(name).name == required for name in libs), f'Missing {required}')
        for name in libs:
            header = archive.read(name)[:20]
            require(header[:4] == b'\x7fELF' and header[4] == 2 and struct.unpack_from('<H', header, 18)[0] == 183, f'Not AArch64 ELF: {name}')
        require(not FORBIDDEN.search('\n'.join(names)), 'Telemetry native files present')
        require(any(name.startswith('classes') and name.endswith('.dex') for name in names), 'DEX missing')
    require('barcode-scanning' in dependencies and 'com.google.mlkit' in dependencies, 'ML Kit scanner dependency missing')
    test_signed = 'CN=Android Debug' in signature
    require(not test_signed or package.endswith('.dev'), 'Debug signature must use .dev package')
    path = output('android')
    name = 'FlClash-personal-stable-android-arm64' + ('-test-signed' if test_signed else '') + '.apk'
    shutil.copy2(apk, path / name)
    for name, content in [('signature.txt', signature), ('manifest.xml', manifest), ('dex-packages.txt', dex), ('runtime-dependencies.txt', dependencies)]:
        (path / name).write_text(content, encoding='utf-8')
    finish(path, {'platform': 'android-arm64', 'package': package, 'test_signed': test_signed, 'native_libraries': libs, 'firebase_analytics_crashlytics': 'absent in resolved dependency graph, defined DEX packages, Manifest and native names'})


def pe(data, name, machine=0x8664):
    require(data[:2] == b'MZ' and len(data) > 64, f'Invalid PE file: {name}')
    offset = struct.unpack_from('<I', data, 60)[0]
    require(data[offset:offset + 4] == b'PE\0\0', f'Invalid PE signature: {name}')
    actual = struct.unpack_from('<H', data, offset + 4)[0]
    require(actual in [0x14c, 0x8664] if machine is None else actual == machine, f'Unexpected PE architecture: {name}')


def windows():
    bundle = ROOT / 'build/windows/x64/runner/Release'
    required = ['FlClash.exe', 'FlClashCore.exe', 'FlClashHelperService.exe', 'manifest.json', 'flutter_windows.dll', 'data/icudtl.dat', 'data/app.so']
    for name in required:
        require((bundle / name).is_file() and (bundle / name).stat().st_size > 0, f'Missing release file: {name}')
    require((bundle / 'data/flutter_assets').is_dir(), 'Flutter assets missing')
    native = list(bundle.rglob('*rust_api*.dll'))
    require(native, 'Rust native library missing')
    require(list(bundle.glob('vcruntime*.dll')) and list(bundle.glob('msvcp*.dll')), 'Bundled MSVC runtime missing')
    binaries = list(bundle.rglob('*.exe')) + list(bundle.rglob('*.dll'))
    for file in binaries:
        pe(file.read_bytes(), str(file), None if file.name == 'EnableLoopback.exe' else 0x8664)
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest['coreSha256'] == digest((bundle / 'FlClashCore.exe').read_bytes()), 'Core integrity manifest mismatch')
    require(not FORBIDDEN.search('\n'.join(str(file) for file in bundle.rglob('*'))), 'Telemetry library found')
    installer = exactly_one((ROOT / 'dist').rglob('*.exe'), 'Windows installer')
    pe(installer.read_bytes(), str(installer), None)
    portable = exactly_one((ROOT / 'dist').rglob('*.zip'), 'complete portable ZIP')
    with zipfile.ZipFile(portable) as archive:
        require(archive.testzip() is None, 'Portable ZIP integrity failure')
        entries = {name.replace('\\', '/').lstrip('./'): name for name in archive.namelist() if not name.endswith('/')}
        for file in bundle.rglob('*'):
            if not file.is_file():
                continue
            relative = file.relative_to(bundle).as_posix()
            matches = [key for key in entries if key == relative or key.endswith('/' + relative)]
            require(len(matches) == 1 and digest(archive.read(entries[matches[0]])) == digest(file.read_bytes()), f'Portable file missing or different: {relative}')
    path = output('windows')
    shutil.copy2(installer, path / 'FlClash-personal-stable-windows-x64-setup.exe')
    shutil.copy2(portable, path / 'FlClash-personal-stable-windows-x64-portable.zip')
    finish(path, {'platform': 'windows-x64', 'release_files': sorted(str(file.relative_to(bundle)) for file in bundle.rglob('*') if file.is_file()), 'pe_architecture': 'AMD64', 'portable_matches_release': True, 'core_integrity_manifest': 'passed', 'installer_signature': 'not asserted; personal unsigned build', 'firebase_analytics_crashlytics': 'Android-only dependencies; approved Windows source unchanged, no telemetry library filenames in release bundle'})


if __name__ == '__main__':
    os.chdir(ROOT)
    {'source': source, 'android': android, 'windows': windows}[sys.argv[1]]()
