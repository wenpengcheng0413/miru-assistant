import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

typedef JsonHandler = void Function(Map<String, dynamic> event);
typedef AudioHandler = void Function(Uint8List chunk);
typedef SessionHandler = void Function(String sessionId);
typedef DisconnectHandler = void Function(String reason);

/// 把底层 WS/Dart 异常翻译成用户能看懂的人话。
String describeWsError(Object e) {
  if (e is TimeoutException) {
    return '连接超时：电脑端 Miru 后端可能未启动，或防火墙拦截了端口 8765';
  }
  final s = e.toString().toLowerCase();
  if (s.contains('refused') || s.contains('拒绝') || s.contains('connection failed')) {
    return '连接被拒绝：电脑端 Miru 后端未启动，或端口不是 8765';
  }
  if (s.contains('unreachable') || s.contains('network is unreachable')) {
    return '网络不可达：手机与电脑可能不在同一 Wi-Fi，或路由器开启了 AP 隔离';
  }
  return '连接失败：$e';
}

String _closeDescription(int? code, String? reason) {
  if (code == 4401) return '服务器拒绝了 token：请检查设置页的访问令牌';
  if (code == 4400) return '握手格式错误：请更新 App';
  if (reason != null && reason.trim().isNotEmpty) return '连接已断开：${reason.trim()}';
  return '连接已断开';
}

/// WS 客户端：文本帧=JSON 事件，二进制帧=TTS 音频；断线自动重连（由上层触发）。
class WsClient {
  WsClient({required this.url, required this.token, required this.hello});

  Uri url;
  String token;
  Map<String, dynamic> hello; // 可变：切换设置后 updateTarget/reconnect 会带新参数握手

  WebSocketChannel? _channel;
  JsonHandler? onJson;
  AudioHandler? onAudio;
  SessionHandler? onSession;
  DisconnectHandler? onDisconnected;
  VoidCallback? onConnected;

  String? sessionId;
  String? lastError;
  bool _closed = false;
  int _generation = 0;
  bool _connectedAnnounced = false;
  Timer? _heartbeatTimer;
  DateTime? _lastFrameAt;

  /// 修改服务器地址/token/hello 后调用 reconnect() 立即生效
  void updateTarget({
    required Uri url,
    required String token,
    required Map<String, dynamic> hello,
  }) {
    this.url = url;
    this.token = token;
    this.hello = Map<String, dynamic>.of(hello);
  }

  /// 建立连接。重复调用会先关闭旧连接，旧连接的回调不会污染新连接。
  Future<void> connect({Duration timeout = const Duration(seconds: 12)}) async {
    if (_closed) return;

    final generation = ++_generation;
    final old = _channel;
    _channel = null;
    _connectedAnnounced = false;
    _heartbeatTimer?.cancel();
    lastError = null;
    try {
      await old?.sink.close();
    } catch (_) {
      // 旧连接可能已断，忽略
    }

    try {
      final channel = WebSocketChannel.connect(url);
      await channel.ready.timeout(timeout);
      if (_closed || generation != _generation) {
        try {
          await channel.sink.close();
        } catch (_) {}
        return;
      }

      _channel = channel;
      channel.sink.add(jsonEncode({
        'type': 'hello',
        'token': token,
        ...hello,
      }));
      channel.stream.listen(
        (frame) {
          if (!_closed && generation == _generation) _onData(frame);
        },
        onDone: () => _onClose(generation, channel),
        onError: (dynamic error) {
          if (!_closed && generation == _generation) {
            lastError = describeWsError(error);
          }
          _onClose(generation, channel);
        },
        cancelOnError: true,
      );
    } catch (e) {
      if (_closed || generation != _generation) return;
      lastError = describeWsError(e);
      onDisconnected?.call(lastError!);
    }
  }

  /// 带新设置重新握手：立即建立新连接。
  Future<void> reconnect() async {
    if (_closed) return;
    await connect();
  }

  void _onData(dynamic frame) {
    _lastFrameAt = DateTime.now();
    if (frame is List<int>) {
      onAudio?.call(Uint8List.fromList(frame));
      return;
    }
    try {
      final event = jsonDecode(frame as String) as Map<String, dynamic>;
      if (event['type'] == 'hello_ok') {
        final newSession = event['session_id'] as String?;
        if (newSession != null && newSession.isNotEmpty) {
          sessionId = newSession;
          onSession?.call(newSession);
        }
        // 收到 hello_ok 才算真正可用：token 错误时服务器会直接断开
        if (!_connectedAnnounced) {
          _connectedAnnounced = true;
          _startHeartbeat();
          onConnected?.call();
        }
      }
      onJson?.call(event);
    } catch (_) {
      // 忽略无法解析的帧
    }
  }

  void _onClose(int generation, WebSocketChannel channel) {
    if (_closed || generation != _generation) return;
    _heartbeatTimer?.cancel();
    if (identical(_channel, channel)) _channel = null;

    int? code;
    String? reason;
    try {
      code = channel.closeCode;
      reason = channel.closeReason;
    } catch (_) {
      // 个别平台/状态读不到关闭码
    }

    lastError ??= _closeDescription(code, reason);
    final message = lastError ?? _closeDescription(code, reason);
    if (_connectedAnnounced) _connectedAnnounced = false;
    onDisconnected?.call(message);
  }

  /// Detect silently-dead Wi-Fi sockets instead of waiting minutes for TCP.
  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _lastFrameAt = DateTime.now();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (_closed || !_connectedAnnounced) return;
      final last = _lastFrameAt;
      if (last != null &&
          DateTime.now().difference(last) > const Duration(seconds: 55)) {
        lastError = '连接心跳超时，正在自动重连';
        final channel = _channel;
        if (channel != null) unawaited(channel.sink.close());
        return;
      }
      sendJson({'type': 'ping'});
    });
  }

  void sendJson(Map<String, dynamic> payload) {
    try {
      _channel?.sink.add(jsonEncode(payload));
    } catch (_) {
      // 连接刚好断开时丢弃
    }
  }

  /// 录音协议闸门：通知后端"开始录音"，之后才接收音频帧
  void sendAudioStart() {
    try {
      _channel?.sink.add(jsonEncode({'type': 'audio_start'}));
    } catch (_) {}
  }

  void sendAudio(Uint8List chunk) {
    try {
      _channel?.sink.add(chunk);
    } catch (_) {}
  }

  bool get isConnected =>
      !_closed && _channel != null && _connectedAnnounced;

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    ++_generation;
    _heartbeatTimer?.cancel();
    final channel = _channel;
    _channel = null;
    try {
      await channel?.sink.close();
    } catch (_) {}
  }
}
