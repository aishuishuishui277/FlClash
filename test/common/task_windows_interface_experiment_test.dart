import 'dart:io';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

Future<YamlMap> _profile({bool safeMode = false}) async {
  final result = await makeRealProfileTask(
    MakeRealProfileState(
      profilesPath: '/profiles',
      profileId: 1,
      rawConfig: {
        'interface-name': 'profile-interface',
        'tun': {
          'auto-detect-interface': true,
          'mtu': 1400,
          'strict-route': true,
          'route-exclude-address': ['203.0.113.0/24'],
        },
        'dns': {
          'enable': true,
          'nameserver': ['https://1.1.1.1/dns-query'],
        },
      },
      realPatchConfig: const PatchClashConfig(
        interfaceNameMode: InterfaceNameMode.clear,
        tun: Tun(enable: true, stack: TunStack.mixed),
      ),
      appendSystemDns: false,
      proxyGroups: const [],
      rules: const [],
      addedRules: const [],
      defaultUA: 'FlClash-Test',
      safeMode: safeMode,
    ),
  );
  return loadYaml(result.yaml) as YamlMap;
}

void main() {
  test('process interface experiment survives profile generation without '
      'changing TUN or DNS', () async {
    final configured = Platform.isWindows
        ? Platform.environment['FLCLASH_TUN_INTERFACE']?.trim()
        : null;
    final profile = await _profile();
    expect(
      profile['interface-name'],
      configured?.isNotEmpty == true ? configured : '',
    );
    final tun = profile['tun'] as YamlMap;
    expect(tun['auto-detect-interface'], true);
    expect(tun['auto-route'], true);
    expect(tun['stack'], 'mixed');
    expect(tun['mtu'], 1400);
    expect(tun['strict-route'], true);
    expect(tun['route-exclude-address'], ['203.0.113.0/24']);
    expect(tun['dns-hijack'], defaultDnsHijack);
    expect((profile['dns'] as YamlMap)['nameserver'], [
      'https://1.1.1.1/dns-query',
    ]);
  });

  test('safe mode does not bind the experimental physical interface', () async {
    final profile = await _profile(safeMode: true);
    expect(profile['interface-name'], '');
  });
}
