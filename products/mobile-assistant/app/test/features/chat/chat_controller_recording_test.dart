import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/audio/player_service.dart';
import 'package:miru_app/core/audio/recorder_service.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/server_discovery.dart';
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
    await tester.pump(const Duration(seconds: 65));

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
    expect(controller.recordRemaining, 60);
    now = now.add(const Duration(seconds: 65));
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

  testWidgets('附件会随语音结束消息一起发送并在服务端确认后移除', (tester) async {
    final recorder = _DelayedRecorder()..completeStart();
    final ws = _FakeWsClient();
    final controller = _controller(recorder, ws: ws)..init();
    controller.pendingAttachments.add(PendingAttachment(
      id: 'attachment-1',
      filename: 'budget.xlsx',
      kind: 'spreadsheet',
      sizeBytes: 123,
    ));

    await controller.startListening();
    await controller.stopListening();

    expect(ws.jsonMessages.last, {
      'type': 'audio_end',
      'attachment_ids': ['attachment-1'],
    });
    expect(controller.pendingAttachments, hasLength(1));

    ws.onJson?.call({'type': 'user_text', 'text': '分析这个月的支出'});
    expect(controller.pendingAttachments, isEmpty);
    controller.dispose();
  });

  testWidgets('只有附件没有具体要求时不会自动补写提示词或发送', (tester) async {
    final recorder = _DelayedRecorder()..completeStart();
    final ws = _FakeWsClient();
    final controller = _controller(recorder, ws: ws);
    controller.pendingAttachments.add(PendingAttachment(
      id: 'attachment-1',
      filename: 'budget.xlsx',
      kind: 'spreadsheet',
      sizeBytes: 123,
    ));

    expect(await controller.sendText(''), isFalse);
    expect(ws.jsonMessages, isEmpty);
    expect(controller.pendingAttachments, hasLength(1));
    expect(controller.lines.last.text, contains('请先输入或说出'));

    expect(await controller.sendText('按月份分析收支'), isTrue);
    expect(ws.jsonMessages.last, {
      'type': 'text_input',
      'text': '按月份分析收支',
      'attachment_ids': ['attachment-1'],
    });
    expect(controller.pendingAttachments, isEmpty);
    controller.dispose();
  });
}

ChatController _controller(
  RecorderService recorder, {
  DateTime Function()? now,
  WsClient? ws,
}) {
  final config = AppConfig();
  final client = ws ?? WsClient(
    url: config.wsUri,
    token: config.token,
    hello: config.hello,
  );
  return ChatController(
    config: config,
    ws: client,
    recorder: recorder,
    player: _FakePlayer(),
    discovery: ServerDiscovery(),
    now: now,
  )..wsConnected = true;
}

class _FakeWsClient extends WsClient {
  _FakeWsClient()
      : super(
          url: Uri.parse('ws://127.0.0.1:8765/ws/session'),
          token: 'test',
          hello: const {},
        );

  final List<Map<String, dynamic>> jsonMessages = [];

  @override
  void sendJson(Map<String, dynamic> payload) {
    jsonMessages.add(Map<String, dynamic>.of(payload));
  }

  @override
  void sendAudioStart() {}

  @override
  void sendAudio(Uint8List chunk) {}

  @override
  Future<void> close() async {}
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
