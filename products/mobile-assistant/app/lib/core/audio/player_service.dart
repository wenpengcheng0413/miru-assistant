import 'dart:async';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';

/// 句级音频播放队列：
/// - 后端每句先发 sentence 事件、紧跟一个或多个音频二进制帧
/// - feedAudio 收集音频，finishSentence 在下一个事件到来时把当前句入队播放
/// - 服务端预取下一句 → 队列里永远有存货 → 句间无停顿
class PlayerService {
  late final AudioPlayer _player;
  late final Future<void> _audioContextReady;
  final List<Uint8List> _queue = [];
  final BytesBuilder _current = BytesBuilder();
  bool _playing = false;

  /// 显式音频上下文：忽略 iOS 侧边静音拨片。
  /// 否则录音插件留下的 playAndRecord 会话会让 TTS 播放被静音键静音。
  final AudioContext _ttsContext = AudioContext(
    iOS: AudioContextIOS(
      // 录音插件会把 App 的共享 AVAudioSession 切到录音模式。
      // TTS 开始前明确切回 output-only playback，声音才会走媒体扬声器，
      // 同时不受 iPhone 侧边静音拨片影响。
      category: AVAudioSessionCategory.playback,
    ),
    android: const AudioContextAndroid(
      contentType: AndroidContentType.speech,
      usageType: AndroidUsageType.assistant,
      audioFocus: AndroidAudioFocus.gainTransient,
    ),
  );

  PlayerService() {
    // iOS 的 Audio Context 是整个 App 共享的，先注册全局播放配置；
    // 每句播放前仍会再次应用，覆盖刚结束的麦克风录音配置。
    _audioContextReady = AudioPlayer.global.setAudioContext(_ttsContext);
    _player = AudioPlayer();
    _player.onPlayerComplete.listen((_) {
      _playing = false;
      unawaited(_pump());
    });
  }

  void feedAudio(Uint8List chunk) => _current.add(chunk);

  /// 收到下一个 JSON 事件时调用：缓冲的音频构成完整一句
  void finishSentence() {
    final bytes = _current.takeBytes();
    if (bytes.isEmpty) return;
    _queue.add(bytes);
    unawaited(_pump());
  }

  Future<void> _pump() async {
    if (_playing || _queue.isEmpty) return;
    _playing = true;
    final bytes = _queue.removeAt(0);
    try {
      await _audioContextReady;
      await AudioPlayer.global.setAudioContext(_ttsContext);
      // iOS 版 audioplayers 会把 BytesSource 写入无扩展名临时文件。
      // 必须携带 MIME 类型，否则 AVPlayer 可能无法判断这是 MP3。
      await _player.play(
        BytesSource(bytes, mimeType: ttsAudioMimeType),
        ctx: _ttsContext,
        volume: 1.0,
      );
    } catch (error) {
      // iOS/Darwin 播放器若拒绝短 MP3，不能让队列永久卡在 _playing=true。
      // 仅记录异常类型，音频内容与服务端文本都不进入设备日志。
      debugPrint('TTS playback failed: ${error.runtimeType}');
      _playing = false;
      unawaited(_pump());
    }
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

/// 当前生产 TTS（Edge）固定输出 MP3。保留为公开常量，便于静态测试防回归。
const String ttsAudioMimeType = 'audio/mpeg';
