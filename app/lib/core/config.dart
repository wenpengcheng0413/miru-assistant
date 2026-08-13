import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 服务器地址、token 与使用偏好（token 进 Keychain，其余进 SharedPreferences）。
class AppConfig {
  static const _kBaseUrl = 'miru_server_base_url';
  static const _kToken = 'miru_server_token';
  static const _kTtsEnabled = 'miru_tts_enabled';
  static const _kAutoSend = 'miru_auto_send';

  static const defaultBaseUrl = 'http://192.168.1.100:8765';

  static final _secure = const FlutterSecureStorage();

  String baseUrl = defaultBaseUrl; // 例：https://my-pc.tailxxxx.ts.net:8765
  String token = '';

  /// 语音回复开关：关掉后 Miru 只显示文字，不合成/播放语音
  bool ttsEnabled = true;

  /// 说完自动发送：关掉后语音识别文本会留在输入框，可修改后再手动发送
  bool autoSend = true;

  /// http://host:port → ws://host:port/ws/session
  Uri get wsUri => Uri.parse(
        baseUrl.replaceFirst('http', 'ws') + '/ws/session',
      );

  String get restBaseUrl => baseUrl;

  /// hello 消息体（每次重连时按当前设置构建）
  Map<String, dynamic> get hello => {
        'device': 'iphone',
        'mode': 'voice',
        'persona': 'miru',
        'synth_tts': ttsEnabled,
        'auto_run': autoSend,
      };

  static Future<AppConfig> load() async {
    final config = AppConfig();
    final prefs = await SharedPreferences.getInstance();
    config.baseUrl = prefs.getString(_kBaseUrl) ?? defaultBaseUrl;
    config.token = await _secure.read(key: _kToken) ?? '';
    config.ttsEnabled = prefs.getBool(_kTtsEnabled) ?? true;
    config.autoSend = prefs.getBool(_kAutoSend) ?? true;
    return config;
  }

  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, baseUrl);
    await _secure.write(key: _kToken, value: token);
    await prefs.setBool(_kTtsEnabled, ttsEnabled);
    await prefs.setBool(_kAutoSend, autoSend);
  }
}
