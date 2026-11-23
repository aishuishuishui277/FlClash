import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from xml.etree import ElementTree
from zipfile import ZipFile


APK_NAME = 'FlClash-v0.9.4-Personal-R1-arm64.apk'
PACKAGE = 'com.follow.clash.personal.v094'
CERT_SHA256 = 'e361eb84e2b3689d66529dc0622b35814b81b7ace54897da346220db6c4e2d49'
ANDROID = '{http://schemas.android.com/apk/res/android}'
TELEMETRY = re.compile(
    r'firebase[.-](?:analytics|crashlytics|perf|sessions)|play-services-measurement'
    r'|FirebaseInitProvider|libcrashlytics|io[./]sentry|bugsnag|appcenter',
    re.IGNORECASE,
)


def verify(condition, message):
    if not condition:
        raise SystemExit(message)


def capture(tool, *args):
    tool = Path(tool)
    if os.name == 'nt' and not tool.suffix:
        tool = tool.with_suffix('.bat')
    return subprocess.check_output([str(tool), *map(str, args)], text=True)


def main(directory):
    apk = directory / APK_NAME
    evidence = directory / 'evidence'
    sdk = Path(os.environ['ANDROID_HOME'])
    tools = sdk / 'build-tools' / '37.0.0'
    analyzer = shutil.which('apkanalyzer') or sdk / 'cmdline-tools/latest/bin/apkanalyzer'

    signature = capture(tools / 'apksigner', 'verify', '--verbose', '--print-certs', apk)
    (evidence / 'signature.txt').write_text(signature)
    android_15_signature = capture(tools / 'apksigner', 'verify', '--min-sdk-version', '35',
                                   '--max-sdk-version', '35', '--verbose', apk)
    (evidence / 'signature-android-15.txt').write_text(android_15_signature)
    certs = re.findall(r'certificate SHA-256 digest: ([a-fA-F0-9]{64})', signature)
    verify(certs == [CERT_SHA256], 'Unexpected private signing certificate')

    manifest = capture(analyzer, 'manifest', 'print', apk)
    (evidence / 'AndroidManifest.xml').write_text(manifest)
    tree = ElementTree.fromstring(manifest)
    sdk_info = tree.find('uses-sdk')
    verify(tree.get('package') == PACKAGE, 'Unexpected Android package')
    verify(tree.get(ANDROID + 'versionName') == '0.9.4', 'Unexpected Android version')
    verify(sdk_info is not None and int(sdk_info.get(ANDROID + 'minSdkVersion')) <= 35,
           'APK minimum SDK does not support Android 15')
    application = tree.find('application')
    verify(application.get(ANDROID + 'debuggable', 'false') == 'false', 'APK is debuggable')
    permissions = {item.get(ANDROID + 'name') for item in tree.findall('uses-permission')}
    verify({'android.permission.INTERNET', 'android.permission.POST_NOTIFICATIONS',
            'android.permission.ACCESS_NETWORK_STATE', 'android.permission.FOREGROUND_SERVICE'}
           <= permissions, 'Missing network or foreground service permissions')
    verify('android.permission.REQUEST_INSTALL_PACKAGES' not in permissions,
           'Installer permission is present')
    verify(any(service.get(ANDROID + 'permission') == 'android.permission.BIND_VPN_SERVICE'
               and service.find(f"intent-filter/action[@{ANDROID}name='android.net.VpnService']") is not None
               for service in application.findall('service')), 'VPN Service absent')
    verify('com.follow.clash.MainActivity' in manifest and PACKAGE + '.files' in manifest
           and PACKAGE + '.permission.RECEIVE_BROADCASTS' in manifest
           and PACKAGE + '.action.TOGGLE' in manifest, 'Private package components do not agree')
    verify('TransportBackendDiscovery' not in manifest and 'CctBackendFactory' not in manifest,
           'DataTransport upload backend is registered')

    dex = capture(analyzer, 'dex', 'packages', '--defined-only', apk)
    (evidence / 'dex-packages.txt').write_text(dex)
    deps = (evidence / 'runtime-dependencies.txt').read_text()
    verify('com.google.mlkit:barcode-scanning' in deps, 'ML Kit scanner dependency absent')
    for label, value in [('Manifest', manifest), ('DEX', dex), ('runtime dependencies', deps)]:
        verify(not TELEMETRY.search(value), f'Unexpected telemetry SDK in {label}')

    required = {'libapp.so', 'libflutter.so', 'libclash.so', 'librust_api.so', 'libbarhopper_v3.so'}
    with ZipFile(apk) as archive:
        verify(archive.testzip() is None, 'Invalid APK ZIP')
        names = archive.namelist()
        libraries = [n for n in names if n.startswith('lib/') and n.endswith('.so')]
        verify({Path(n).parent.name for n in libraries} == {'arm64-v8a'}, 'Unexpected native ABI')
        verify(required <= {Path(n).name for n in libraries}, 'Missing required native libraries')
        verify(archive.getinfo('lib/arm64-v8a/libclash.so').file_size > 1_000_000,
               'Native Core size is implausible')
        for library in libraries:
            with archive.open(library) as so:
                header = so.read(20)
            verify(header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183,
                   f'Unexpected ELF format in {library}')
        verify('classes.dex' in names and not TELEMETRY.search('\n'.join(names)),
               'DEX missing or unwanted telemetry files present')
        verify(any(n.startswith('assets/mlkit_barcode_models/') and n.endswith('.tflite')
                   for n in names), 'Bundled barcode models absent')
    (evidence / 'native-libraries.txt').write_text('\n'.join(libraries) + '\n')

    with apk.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (directory / 'SHA256SUMS.txt').write_text(f'{digest}  {APK_NAME}\n')
    print(f'Verified {PACKAGE} on SDK 35, ARM64, private signature, VPN and scanner packaged')
    print(f'{digest}  {APK_NAME}')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
