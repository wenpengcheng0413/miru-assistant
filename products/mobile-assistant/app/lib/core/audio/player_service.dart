import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';

/// 句级音频播放队列：
/// - 后端每句先发 sentence 事件、紧跟一个或多个音频二进制帧
/// - feedAudio 收集音频，finishSentence 在下一个事件到来时把当前句入队播放
/// - 服务端预取下一句 → 队列里永远有存货 → 句间无停顿
class PlayerService {
  final AudioPlayer _player = AudioPlayer();
  final List<Uint8List> _queue = [];
  final BytesBuilder _current = BytesBuilder();
  bool _playing = false;

  /// 显式音频上下文：忽略 iOS 侧边静音拨片。
  /// 否则录音插件留下的 playAndRecord 会话会让 TTS 播放被静音键静音。
  final AudioContext _ttsContext = AudioContextConfig(
    respectSilence: false,
    stayAwake: false,
  ).build();

  PlayerService() {
    _player.onPlayerComplete.listen((_) {
      _playing = false;
      _pump();
    });
  }

  void feedAudio(Uint8List chunk) => _current.add(chunk);

  /// 收到下一个 JSON 事件时调用：缓冲的音频构成完整一句
  void finishSentence() {
    final bytes = _current.takeBytes();
    if (bytes.isEmpty) return;
    _queue.add(bytes);
    _pump();
  }

  Future<void> _pump() async {
    if (_playing || _queue.isEmpty) return;
    _playing = true;
    final bytes = _queue.removeAt(0);
    await _player.play(BytesSource(bytes), ctx: _ttsContext);
  }

  /// 打断：清空队列与缓冲，立即停止出声
  Future<void> interrupt() async {
    _queue.clear();
    _current.clear();
    await _player.stop();
    _playing = false;
  }

  bool get isPlaying => _playing || _queue.isNotEmpty;

  Future<void> dispose() async => _player.dispose();
}
