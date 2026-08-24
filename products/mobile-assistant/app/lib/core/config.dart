import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 服务器地址、token 与使用偏好（token 进 Keychain，其余进 SharedPreferences）。
class AppConfig {
  static const _kBaseUrl = 'miru_server_base_url';
  static const _kToken = 'miru_server_token';
  static const _kTtsEnabled = 'miru_tts_enabled';
  static const _kAutoSend = 'miru_auto_send';
  static const _kConversationId = 'miru_last_conversation_id';

  static const defaultBaseUrl = 'http://192.168.31.27:8765';
  static const defaultToken = 'dev-smoke-test-token'; // 与后端 server.token 一致

  static final _secure = const FlutterSecureStorage();

  String baseUrl = defaultBaseUrl; // 例：https://my-pc.tailxxxx.ts.net:8765
  String token = defaultToken;

  /// 语音回复开关：关掉后 Miru 只显示文字，不合成/播放语音
  bool ttsEnabled = true;

  /// 说完自动发送：关掉后语音识别文本会留在输入框，可修改后再手动发送
  bool autoSend = true;

  /// 最近一次会话 ID：重连/重启时继续同一会话，聊天记录不丢
  String lastConversationId = '';

  /// http://host:port → ws://host:port/ws/session；https → wss
  Uri get wsUri {
    final base = Uri.parse(baseUrl);
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/ws/session',
    );
  }

  /// REST 地址去掉尾部斜杠，避免拼出 //api/health
  String get restBaseUrl {
    var url = baseUrl.trim();
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }

  /// hello 消息体（每次重连时按当前设置构建）
  Map<String, dynamic> get hello => {
        'device': 'iphone',
        'mode': 'voice',
        'persona': 'miru',
        'synth_tts': ttsEnabled,
        'auto_run': autoSend,
        if (lastConversationId.isNotEmpty)
          'conversation_id': lastConversationId,
      };

  static Future<AppConfig> load() async {
    final config = AppConfig();
    final prefs = await SharedPreferences.getInstance();
    config.baseUrl = prefs.getString(_kBaseUrl) ?? defaultBaseUrl;
    config.token = await _secure.read(key: _kToken) ?? defaultToken;
    config.ttsEnabled = prefs.getBool(_kTtsEnabled) ?? true;
    config.autoSend = prefs.getBool(_kAutoSend) ?? true;
    config.lastConversationId = prefs.getString(_kConversationId) ?? '';
    return config;
  }

  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, baseUrl);
    await _secure.write(key: _kToken, value: token);
    await prefs.setBool(_kTtsEnabled, ttsEnabled);
    await prefs.setBool(_kAutoSend, autoSend);
    await prefs.setString(_kConversationId, lastConversationId);
  }
}
