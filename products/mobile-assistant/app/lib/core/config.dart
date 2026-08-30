import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'deployment_profile.dart';

/// 服务器地址、token 与使用偏好（token 进 Keychain，其余进 SharedPreferences）。
class AppConfig {
  static const _kBaseUrl = 'miru_server_base_url';
  static const _kToken = 'miru_server_token';
  static const _kTtsEnabled = 'miru_tts_enabled';
  static const _kAutoSend = 'miru_auto_send';
  static const _kConversationId = 'miru_last_conversation_id';
  static const _kDeploymentProfile = 'miru_deployment_profile';
  static const _kDeviceId = 'miru_device_id';

  static const buildProfile = String.fromEnvironment(
    'MIRU_DEPLOYMENT_PROFILE',
    defaultValue: 'development',
  );
  static const buildBaseUrl = String.fromEnvironment('MIRU_BASE_URL');
  static const defaultDevelopmentBaseUrl = 'http://127.0.0.1:8765';

  static final _secure = const FlutterSecureStorage();

  DeploymentProfile profile = parseDeploymentProfile(buildProfile);
  String baseUrl = buildBaseUrl.isNotEmpty
      ? buildBaseUrl
      : (parseDeploymentProfile(buildProfile).isCloud
            ? ''
            : defaultDevelopmentBaseUrl);
  String token = '';
  String deviceId = '';

  bool get bonjourEnabled => profile.allowsBonjour;
  bool get requiresHttps => profile.isCloud;

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
      query: null,
      fragment: null,
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
    if (deviceId.isNotEmpty) 'device_id': deviceId,
    if (lastConversationId.isNotEmpty) 'conversation_id': lastConversationId,
  };

  static Future<AppConfig> load() async {
    final config = AppConfig();
    final prefs = await SharedPreferences.getInstance();
    config.baseUrl = prefs.getString(_kBaseUrl) ?? config.baseUrl;
    final savedProfile = prefs.getString(_kDeploymentProfile);
    config.profile = savedProfile == null
        ? _inferProfile(config.baseUrl, fallback: config.profile)
        : parseDeploymentProfile(savedProfile);
    config.token = await _secure.read(key: _kToken) ?? '';
    config.deviceId = await _secure.read(key: _kDeviceId) ?? _newDeviceId();
    await _secure.write(key: _kDeviceId, value: config.deviceId);
    config.ttsEnabled = prefs.getBool(_kTtsEnabled) ?? true;
    config.autoSend = prefs.getBool(_kAutoSend) ?? true;
    config.lastConversationId = prefs.getString(_kConversationId) ?? '';
    return config;
  }

  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, baseUrl);
    await prefs.setString(_kDeploymentProfile, profile.value);
    await _secure.write(key: _kToken, value: token);
    await prefs.setBool(_kTtsEnabled, ttsEnabled);
    await prefs.setBool(_kAutoSend, autoSend);
    await prefs.setString(_kConversationId, lastConversationId);
  }

  String? validateEndpoint() {
    final uri = Uri.tryParse(restBaseUrl);
    if (restBaseUrl.isEmpty || uri == null || uri.host.isEmpty) {
      return '请填写完整的服务器地址';
    }
    if (uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment) {
      return '服务器地址不能包含账号、查询参数或片段';
    }
    if (requiresHttps && uri.scheme != 'https') {
      return '生产模式只允许 HTTPS/WSS';
    }
    if (!requiresHttps && uri.scheme != 'http' && uri.scheme != 'https') {
      return '服务器地址必须以 http:// 或 https:// 开头';
    }
    return null;
  }

  static DeploymentProfile _inferProfile(
    String baseUrl, {
    required DeploymentProfile fallback,
  }) {
    final uri = Uri.tryParse(baseUrl);
    if (uri?.scheme == 'https') {
      return uri!.host.endsWith('.ts.net')
          ? DeploymentProfile.tailnet
          : DeploymentProfile.public;
    }
    return fallback;
  }

  static String _newDeviceId() {
    final bytes = List<int>.generate(18, (_) => Random.secure().nextInt(256));
    return 'ios-${base64UrlEncode(bytes).replaceAll('=', '')}';
  }
}
