import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

/// 16kHz PCM16 单声道流式录音，音频分块直发 WS（后端做 VAD 断句）。
class RecorderService {
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _sub;

  bool get isRecording => _sub != null;

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<void> start({required void Function(Uint8List) onChunk}) async {
    if (!await hasPermission()) {
      throw Exception('没有麦克风权限（设置 → 隐私 → 麦克风）');
    }
    final stream = await _recorder.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
      autoGain: true,
      echoCancel: true,
      noiseSuppress: true,
    ));
    _sub = stream.listen(onChunk);
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    try {
      await _recorder.stop();
    } catch (_) {
      // 未在录音时调用 stop 可能抛错，忽略
    }
  }

  Future<void> dispose() async {
    await stop();
    await _recorder.dispose();
  }
}
