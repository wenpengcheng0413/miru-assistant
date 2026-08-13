import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:web_socket_channel/web_socket_channel.dart';

typedef JsonHandler = void Function(Map<String, dynamic> event);
typedef AudioHandler = void Function(Uint8List chunk);

/// WS 客户端：文本帧=JSON 事件，二进制帧=TTS 音频；断线自动重连（由上层触发）。
class WsClient {
  WsClient({required this.url, required this.token, required this.hello});

  final Uri url;
  final String token;
  Map<String, dynamic> hello; // 可变：切换设置后 reconnect() 会带新参数重新握手

  WebSocketChannel? _channel;
  JsonHandler? onJson;
  AudioHandler? onAudio;
  VoidCallback? onDisconnected;
  VoidCallback? onConnected;

  String? sessionId;
  bool _closed = false;

  Future<void> connect() async {
    if (_closed) return;
    try {
      _channel = WebSocketChannel.connect(url);
      await _channel!.ready;
    } catch (_) {
      onDisconnected?.call(); // 由上层决定重试
      return;
    }
    _channel!.sink.add(jsonEncode({
      'type': 'hello',
      'token': token,
      ...hello,
    }));
    _channel!.stream.listen(
      _onData,
      onDone: _onClose,
      onError: (_) => _onClose(),
      cancelOnError: true,
    );
    onConnected?.call();
  }

  /// 带新设置重新握手：断开当前连接（onDone 会触发上层的自动重连）
  Future<void> reconnect() async {
    await _channel?.sink.close();
  }

  void _onData(dynamic frame) {
    if (frame is List<int>) {
      onAudio?.call(Uint8List.fromList(frame));
      return;
    }
    try {
      final event = jsonDecode(frame as String) as Map<String, dynamic>;
      if (event['type'] == 'hello_ok') {
        sessionId = event['session_id'] as String?;
      }
      onJson?.call(event);
    } catch (_) {
      // 忽略无法解析的帧
    }
  }

  void _onClose() {
    if (_closed) return;
    onDisconnected?.call();
  }

  void sendJson(Map<String, dynamic> payload) {
    _channel?.sink.add(jsonEncode(payload));
  }

  void sendAudio(Uint8List chunk) {
    _channel?.sink.add(chunk);
  }

  Future<void> close() async {
    _closed = true;
    await _channel?.sink.close();
  }
}
