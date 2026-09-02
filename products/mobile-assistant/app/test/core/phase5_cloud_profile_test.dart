import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/audio/player_service.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/deployment_profile.dart';
import 'package:miru_app/core/system_status.dart';

void main() {
  test('TTS byte source declares the production MP3 MIME type', () {
    expect(ttsAudioMimeType, 'audio/mpeg');
  });

  test('production profiles require HTTPS and disable Bonjour', () {
    final config = AppConfig()
      ..profile = DeploymentProfile.tailnet
      ..baseUrl = 'http://example.invalid';

    expect(config.bonjourEnabled, isFalse);
    expect(config.validateEndpoint(), '生产模式只允许 HTTPS/WSS');

    config.baseUrl = 'https://miru.example.invalid/';
    expect(config.validateEndpoint(), isNull);
    expect(config.restBaseUrl, 'https://miru.example.invalid');
    expect(config.wsUri.toString(), 'wss://miru.example.invalid/ws/session');
  });

  test('development profile keeps explicit LAN discovery boundary', () {
    final config = AppConfig()
      ..profile = DeploymentProfile.development
      ..baseUrl = 'http://127.0.0.1:8765';

    expect(config.bonjourEnabled, isTrue);
    expect(config.validateEndpoint(), isNull);
  });

  test(
    'status parser accepts Phase 1 strings and future structured values',
    () {
      final status = MiruSystemStatus.fromJson({
        'schema_version': 1,
        'generated_at': '2026-08-30T00:00:00+00:00',
        'cloud': {'state': 'ready'},
        'home_node': {'state': 'not_configured'},
        'capabilities': {
          'chat': 'available',
          'wechat': {
            'available': false,
            'location': 'node-home',
            'reason': 'node_offline',
          },
        },
      });

      expect(status.cloudOnline, isTrue);
      expect(status.homeNodeOnline, isFalse);
      expect(status.capabilities['chat']!.available, isTrue);
      expect(status.capabilities['wechat']!.reason, 'node_offline');
    },
  );
}
