import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = '7fd417fb9a9a277c6a9339a8ac87f907df7c25f7'
CORE = 'c5062921054902b25215a6a933e72ccd714c9bfa'
REMOVAL = 'bc72bba981bdb8ec7c235d955eda124cd6c123a3'
R3 = 'e4c8af2d821e4b054ecb51dd7694497e6563a8b5'
IDENTITY = json.loads((ROOT / 'tool/android-personal-signing.json').read_text())
FORBIDDEN = re.compile(
    r'com[./]google[./]firebase[./](?:analytics|crashlytics)(?:[./:]|\b)'
    r'|com[./]google[./]android[./]gms[./](?:measurement|internal[./]measurement)(?:[./:]|\b)'
    r'|firebase-(?:analytics|crashlytics)|play-services-measurement'
    r'|FirebaseInitProvider|libcrashlytics', re.IGNORECASE,
)


def run(*args):
    return subprocess.check_output([str(a) for a in args], cwd=ROOT, text=True, encoding='utf-8')


def require(value, message):
    if not value:
        raise SystemExit(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def special_use(value):
    if 'specialUse' in value.split('|'):
        return True
    try:
        return bool(int(value, 0) & 0x40000000)
    except ValueError:
        return False


def certificate_digests(signature):
    return {value.lower() for value in re.findall(r'certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\b', signature)}


def source():
    final_files = {'.github/workflows/build.yaml', '.github/workflows/android-personal-0.9.2.yml',
                   'android/common/src/main/java/com/follow/clash/common/StartupTrace.kt',
                   'pubspec.yaml', 'tool/verify_android_personal.py', 'tool/android-startup/README.md'}
    final_changes = set(run('git', 'diff', '--name-only', R3, 'HEAD').splitlines())
    require(final_changes <= final_files, f'Changes exceed diagnostics-off release: {final_changes - final_files}')
    trace_file = 'android/common/src/main/java/com/follow/clash/common/StartupTrace.kt'
    expected_trace = run('git', 'show', f'{R3}:{trace_file}').replace(
        'get() = runCatching { Log.isLoggable(TAG, Log.DEBUG) }.getOrDefault(false)', 'get() = false')
    require((ROOT / trace_file).read_text(encoding='utf-8') == expected_trace, 'Startup diagnostics not forcibly disabled')
    allowed = {'.github/workflows/build.yaml', '.github/workflows/android-personal-0.9.2.yml',
               'android/app/build.gradle.kts', 'tool/verify_android_personal.py', 'tool/android-personal-signing.json',
               'android/app/src/main/kotlin/com/follow/clash/ServiceController.kt',
               'android/app/src/main/kotlin/com/follow/clash/plugins/ServicePlugin.kt',
               'android/common/src/main/java/com/follow/clash/common/StartupTrace.kt',
               'android/core/src/main/java/com/follow/clash/core/Core.kt',
               'android/service/src/main/java/com/follow/clash/service/NetworkObserver.kt',
               'android/service/src/main/java/com/follow/clash/service/VpnService.kt',
               'core/config.go', 'core/connection.go', 'core/delay.go', 'core/hooks.go', 'core/lib.go',
               'core/lifecycle.go', 'core/mobile/mobile.go', 'core/startup_trace.go', 'core/startup_trace_test.go',
               'core/startup_epoch_android.go', 'tool/android-startup/r3_sources.py',
               'tool/android-startup/Measure-AndroidStartup.ps1', 'tool/android-startup/README.md', 'pubspec.yaml'}
    changed = set(run('git', 'diff', '--name-only', BASE, 'HEAD').splitlines())
    allowed.update('tool/android-startup/r3/' + name for name in ['sources.json', 'client.patch',
                   'flclash_startup_epoch.patch', 'flclash_startup_epoch_test.patch'])
    require(changed <= allowed, f'Unexpected changes: {changed - allowed}')
    subprocess.run(['git', 'merge-base', '--is-ancestor', REMOVAL, 'HEAD'], cwd=ROOT, check=True)
    original = run('git', 'show', f'{BASE}:android/app/build.gradle.kts')
    expected = original.replace('signingConfig = signingConfigs.getByName("release")',
                                'signingConfig = signingConfigs.getByName("release")\n                applicationIdSuffix = ".personal"')
    require((ROOT / 'android/app/build.gradle.kts').read_text() == expected, 'Android changes exceed the approved package suffix')
    require(run('git', '-C', 'core/Clash.Meta', 'rev-parse', 'HEAD').strip() == CORE, 'mihomo pin changed')
    subprocess.run([sys.executable, str(ROOT / 'tool/android-startup/r3_sources.py'), 'verify'], check=True)
    require(not (ROOT / 'core/startup_health_android.go').exists(), 'R2 behavior returned')
    require('protect_before_tun_ready' not in (ROOT / 'core/lib.go').read_text(encoding='utf-8'), 'R1 behavior returned')
    changes = set(run('git', '-C', 'core/Clash.Meta', 'diff', '--name-only').splitlines())
    require(changes <= {'component/ca/ca-certificates.crt'}, 'Tracked mihomo source modified')
    if changes:
        require(digest((ROOT / 'core/Clash.Meta/component/ca/ca-certificates.crt').read_bytes()) ==
                'a41b5d356aea97a529fe27e0f7316d2f9d946d75927476cf9cf1b90637d00505', 'CA bundle differs from upstream')
    pubspec = (ROOT / 'pubspec.yaml').read_text()
    require(pubspec == run('git', 'show', f'{BASE}:pubspec.yaml').replace(
        'version: 0.9.2+2026102401', 'version: 0.9.2+2026102801'), 'Changes exceed build-number metadata')
    require(pubspec.count('build_assets: true') == 2 and 'build_assets: false' not in pubspec, 'Native hooks disabled')
    require(not (ROOT / 'android/app/google-services.json').exists(), 'Firebase config returned')
    for file in (ROOT / 'android').rglob('*'):
        if file.suffix in ['.kts', '.toml'] and 'build' not in file.parts:
            content = file.read_text()
            require(not FORBIDDEN.search(content) and 'com.google.gms.google-services' not in content, f'Firebase build dependency in {file}')
    print('Diagnostics forced off; accepted R3 Go sources, patches, pins and native hooks unchanged')


def apk_file():
    files = list((ROOT / 'dist').rglob('*.apk'))
    require(len(files) == 1, f'Expected one ARM64 release APK: {files}')
    return files[0]


def finish(folder, report):
    report.update(commit=run('git', 'rev-parse', 'HEAD').strip(), base=BASE, core_commit=CORE,
                  runtime_base=R3, startup_diagnostics='forced off; DEBUG log property cannot enable startup capture',
                  r3_device_acceptance='user accepted three cold starts within 15s and Google Play; one captured run VPN-to-proxy-HTTPS 2.856s',
                  user_confirmed_regressions=['Hy2 OFBS and server-side port hopping evidence', 'Wi-Fi/mobile switching',
                                              'VPN off/on', 'background/screen-off recovery'],
                  unreported_regressions=['Reality real HTTPS', 'ML Kit scan', 'explicit HTTP proxy', 'battery/high-frequency redial'],
                  final_apk_device_tests='not yet performed on this diagnostics-off APK',
                  purpose='private Android release retaining accepted R3 behavior; no additional network changes')
    (folder / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (folder / 'SHA256SUMS.txt').write_text(''.join(f'{digest(f.read_bytes())}  {f.name}\n'
        for f in sorted(folder.iterdir()) if f.is_file() and f.name != 'SHA256SUMS.txt'), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print((folder / 'SHA256SUMS.txt').read_text())


def candidate():
    apk = apk_file()
    with zipfile.ZipFile(apk) as z:
        require(z.testzip() is None, 'APK ZIP corruption')
    folder = ROOT / 'delivery/android-candidate'
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copy2(apk, folder / 'FlClash-v0.9.2-personal-arm64-candidate.apk')
    finish(folder, {'acceptance': 'candidate only; final binary and JVM acceptance pending'})


def android():
    source()
    apk = apk_file()
    analyzer, signer = shutil.which('apkanalyzer'), shutil.which('apksigner')
    require(analyzer and signer, 'Android SDK inspection tools missing')
    signature = run(signer, 'verify', '--verbose', '--print-certs', apk)
    run(signer, 'verify', '--verbose', '--min-sdk-version', '35', apk)
    require(certificate_digests(signature) == {IDENTITY['certificate_sha256']}, 'Unexpected signing certificate')
    require('CN=Android Debug' not in signature, 'Ephemeral debug signature is not accepted')
    manifest = run(analyzer, 'manifest', 'print', apk)
    dex = run(analyzer, 'dex', 'packages', '--defined-only', apk)
    deps = (ROOT / 'android-runtime-dependencies.txt').read_text()
    require('FAILED' not in deps and 'BUILD SUCCESSFUL' in deps, 'Dependency resolution incomplete')
    for label, content in [('DEX', dex), ('Manifest', manifest), ('runtime graph', deps)]:
        require(not FORBIDDEN.search(content), f'Firebase analytics/crash reporting found in {label}')
    tree = ET.fromstring(manifest)
    ns = '{http://schemas.android.com/apk/res/android}'
    require(tree.attrib['package'] == IDENTITY['package'], 'Incorrect private package ID')
    sdk = tree.find('uses-sdk')
    require(sdk is not None and int(sdk.attrib[ns + 'minSdkVersion']) <= 35, 'APK excludes Android 15')
    require(tree.find('application').attrib.get(ns + 'debuggable', 'false') != 'true', 'Not a release APK')
    require(any(s.attrib.get(ns + 'permission') == 'android.permission.BIND_VPN_SERVICE' and
                special_use(s.attrib.get(ns + 'foregroundServiceType', '')) for s in tree.findall('.//service')), 'VPN foreground service missing')
    for permission in ['INTERNET', 'CAMERA', 'FOREGROUND_SERVICE_SPECIAL_USE', 'POST_NOTIFICATIONS']:
        require('android.permission.' + permission in manifest, f'Missing {permission}')
    with zipfile.ZipFile(apk) as z:
        require(z.testzip() is None, 'APK ZIP corruption')
        names = z.namelist()
        libs = [n for n in names if n.startswith('lib/') and n.endswith('.so')]
        require({n.split('/')[1] for n in libs} == {'arm64-v8a'}, 'APK is not ARM64-only')
        for name in ['libflutter.so', 'libapp.so', 'libclash.so', 'librust_api.so', 'libbarhopper_v3.so']:
            require('lib/arm64-v8a/' + name in libs, f'Missing {name}')
        require(z.getinfo('lib/arm64-v8a/libclash.so').file_size > 1_000_000, 'Empty or placeholder core')
        alignment = {}
        for name in libs:
            data = z.read(name)
            require(data[:4] == b'\x7fELF' and data[4] == 2 and struct.unpack_from('<H', data, 18)[0] == 183, f'Invalid AArch64 ELF: {name}')
            offset, size, count = struct.unpack_from('<Q', data, 32)[0], struct.unpack_from('<H', data, 54)[0], struct.unpack_from('<H', data, 56)[0]
            alignment[name] = sorted({struct.unpack_from('<Q', data, offset + i * size + 48)[0] for i in range(count)
                                      if struct.unpack_from('<I', data, offset + i * size)[0] == 1})
        require(not FORBIDDEN.search('\n'.join(names)), 'Telemetry native files found')
        require(any(n.startswith('classes') and n.endswith('.dex') for n in names), 'DEX missing')
        require(any(n.startswith('assets/mlkit_barcode_models/') and n.endswith('.tflite') for n in names), 'Bundled scanner models missing')
    require('barcode-scanning' in deps and 'com.google.mlkit' in deps, 'ML Kit scanner removed')
    totals = dict(tests=0, failures=0, errors=0, skipped=0)
    results = list((ROOT / 'build').glob('**/test-results/testDebugUnitTest/TEST-*.xml'))
    require(results, 'JVM test reports missing')
    for file in results:
        suite = ET.parse(file).getroot()
        for key in totals:
            totals[key] += int(suite.attrib.get(key, 0))
    require(totals['tests'] > 0 and totals['failures'] == totals['errors'] == 0, f'JVM tests failed: {totals}')
    folder = ROOT / 'delivery/android'
    folder.mkdir(parents=True, exist_ok=False)
    require(int(tree.attrib[ns + 'versionCode']) > 2026104703, 'Version code does not permit upgrade from R3')
    shutil.copy2(apk, folder / 'FlClash-v0.9.2-personal-android-arm64-release.apk')
    for file in (ROOT / 'tool/android-startup').iterdir():
        if file.name == 'README.md':
            shutil.copy2(file, folder / file.name)
    shutil.copy2(ROOT / 'r3-source-provenance.json', folder)
    shutil.copy2(ROOT / 'r3-epoch-tests.txt', folder)
    for name, content in [('signature.txt', signature), ('manifest.xml', manifest), ('dex-packages.txt', dex), ('runtime-dependencies.txt', deps)]:
        (folder / name).write_text(content, encoding='utf-8')
    finish(folder, {'package': IDENTITY['package'], 'version_name': tree.attrib.get(ns + 'versionName'),
                    'version_code': tree.attrib.get(ns + 'versionCode'), 'min_sdk': sdk.attrib.get(ns + 'minSdkVersion'),
                    'target_sdk': sdk.attrib.get(ns + 'targetSdkVersion'), 'certificate_sha256': IDENTITY['certificate_sha256'],
                    'test_signed': False, 'native_libraries': libs, 'elf_load_alignment': alignment, 'jvm_tests': totals,
                    'firebase_analytics_crashlytics': 'absent from runtime graph, Manifest, defined DEX and native names',
                    'ml_kit': 'barcode native library and bundled models retained; metrics/DataTransport exception remains'})


if __name__ == '__main__':
    {'source': source, 'candidate': candidate, 'android': android}[sys.argv[1]]()
