import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/audio/player_service.dart';
import 'package:miru_app/core/audio/recorder_service.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/ws_client.dart';
import 'package:miru_app/features/chat/chat_controller.dart';

void main() {
  testWidgets('松手早于录音启动完成时不会留下超时定时器', (tester) async {
    final recorder = _DelayedRecorder();
    final controller = _controller(recorder);

    final start = controller.startListening();
    expect(controller.phase, ChatPhase.listening);

    await controller.stopListening();
    recorder.completeStart();
    await start;
    await tester.pump(const Duration(seconds: 35));

    expect(
      controller.lines.where((line) => line.text == '录音超时，已自动停止'),
      isEmpty,
    );
    expect(recorder.stopCalls, 2);
    controller.dispose();
  });

  testWidgets('真正超时时只提示一次', (tester) async {
    final recorder = _DelayedRecorder()..completeStart();
    var now = DateTime(2026, 8, 23);
    final controller = _controller(recorder, now: () => now);

    await controller.startListening();
    now = now.add(const Duration(seconds: 35));
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();

    expect(
      controller.lines
          .where((line) => line.text == '录音超时，已自动停止')
          .length,
      1,
    );
    expect(controller.phase, ChatPhase.thinking);
    await tester.pump(const Duration(seconds: 10));
    expect(
      controller.lines
          .where((line) => line.text == '录音超时，已自动停止')
          .length,
      1,
    );
    controller.dispose();
  });
}

ChatController _controller(
  RecorderService recorder, {
  DateTime Function()? now,
}) {
  final config = AppConfig();
  final ws = WsClient(
    url: config.wsUri,
    token: config.token,
    hello: config.hello,
  );
  return ChatController(
    config: config,
    ws: ws,
    recorder: recorder,
    player: _FakePlayer(),
    now: now,
  )..wsConnected = true;
}

class _DelayedRecorder implements RecorderService {
  final Completer<void> _started = Completer<void>();
  bool _isRecording = false;
  int stopCalls = 0;

  void completeStart() {
    if (!_started.isCompleted) _started.complete();
  }

  @override
  bool get isRecording => _isRecording;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<void> start({required void Function(Uint8List) onChunk}) async {
    await _started.future;
    _isRecording = true;
  }

  @override
  Future<void> stop() async {
    stopCalls++;
    _isRecording = false;
  }

  @override
  Future<void> dispose() async {}
}

class _FakePlayer implements PlayerService {
  @override
  void feedAudio(Uint8List chunk) {}

  @override
  void finishSentence() {}

  @override
  Future<void> interrupt() async {}

  @override
  bool get isPlaying => false;

  @override
  Future<void> dispose() async {}
}
