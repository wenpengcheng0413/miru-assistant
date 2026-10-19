import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/audio/player_service.dart';
import 'package:miru_app/core/audio/recorder_service.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/server_discovery.dart';
import 'package:miru_app/core/ws_client.dart';
import 'package:miru_app/features/chat/chat_controller.dart';
import 'package:miru_app/features/chat/chat_screen.dart';

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
      controller.lines.where((line) => line.text == '录音超时，已自动停止').length,
      1,
    );
    expect(controller.phase, ChatPhase.thinking);
    await tester.pump(const Duration(seconds: 10));
    expect(
      controller.lines.where((line) => line.text == '录音超时，已自动停止').length,
      1,
    );
    controller.dispose();
  });

  testWidgets('取消录音时不发送 audio_end 且清空识别草稿', (tester) async {
    final recorder = _DelayedRecorder()..completeStart();
    final ws = _FakeWsClient();
    final controller = _controller(recorder, ws: ws);

    await controller.startListening();
    controller.partialText = '尚未完成的识别';
    controller.pendingInput = '旧草稿';
    final previousVersion = controller.pendingInputVersion;
    await controller.cancelListening();

    expect(controller.phase, ChatPhase.idle);
    expect(controller.partialText, isEmpty);
    expect(controller.pendingInput, isEmpty);
    expect(controller.pendingInputVersion, previousVersion + 1);
    expect(ws.jsonMessages, [
      {'type': 'audio_start', 'thinking_level': 'low'},
      {'type': 'audio_cancel'},
    ]);
    expect(recorder.stopCalls, 1);
    controller.dispose();
  });

  testWidgets('按住说话上滑后松手会取消而不是发送', (tester) async {
    final recorder = _DelayedRecorder()..completeStart();
    final ws = _FakeWsClient();
    final player = _FakePlayer();
    final controller = _controller(recorder, ws: ws);
    await tester.pumpWidget(
      MaterialApp(home: ChatScreen(controller: controller, player: player)),
    );

    final gesture = await tester.startGesture(
      tester.getCenter(find.text('按住说话')),
    );
    await tester.pump();
    expect(find.text('上滑取消 · 松开发送'), findsOneWidget);

    await gesture.moveBy(const Offset(0, -70));
    await tester.pump();
    expect(find.text('松开取消 · 下滑继续'), findsOneWidget);

    await gesture.up();
    await tester.pump();
    expect(ws.jsonMessages, [
      {'type': 'audio_start', 'thinking_level': 'low'},
      {'type': 'audio_cancel'},
    ]);
    expect(controller.phase, ChatPhase.idle);

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
      'thinking_level': 'low',
      'attachment_ids': ['attachment-1'],
    });
    expect(controller.pendingAttachments, isEmpty);
    controller.dispose();
  });

  testWidgets('历史会话从最新消息打开，向下按钮回到末尾', (tester) async {
    final controller = _controller(_DelayedRecorder(), ws: _FakeWsClient());
    for (var i = 0; i < 80; i++) { controller.lines.add(ChatLine('user', '消息 $i')); }
    await tester.pumpWidget(MaterialApp(home: ChatScreen(controller: controller, player: _FakePlayer())));
    await tester.pump();
    expect(find.text('消息 79'), findsOneWidget);
    final list = find.byType(ListView).first;
    await tester.drag(list, const Offset(0, 600));
    await tester.pumpAndSettle();
    expect(find.byTooltip('回到最新消息'), findsOneWidget);
    await tester.tap(find.byTooltip('回到最新消息'));
    await tester.pumpAndSettle();
    expect(find.text('消息 79'), findsOneWidget);
    controller.dispose();
  });

  testWidgets('后台再打开空闲会话回到新对话，草稿附件不丢失', (tester) async {
    final ws = _FakeWsClient();
    final controller = _controller(_DelayedRecorder(), ws: ws);
    controller.config.lastConversationId = 'old';
    controller.lines.add(ChatLine('user', '旧消息'));
    controller.onAppBackgrounded();
    controller.onAppResumed();
    await tester.pump();
    expect(controller.lines, isEmpty);
    expect(ws.hello.containsKey('conversation_id'), isFalse);
    controller.lines.add(ChatLine('user', '新的消息'));
    controller.pendingInput = '未发送的草稿';
    controller.onAppBackgrounded();
    controller.onAppResumed();
    await tester.pump();
    expect(controller.lines, hasLength(1));
    expect(controller.pendingInput, '未发送的草稿');
    controller.dispose();
  });

  testWidgets('高思考等级随文字和语音发送', (tester) async {
    final ws = _FakeWsClient();
    final controller = _controller(_DelayedRecorder()..completeStart(), ws: ws);
    controller.config.thinkingLevel = 'high';
    await controller.sendText('分析最近花销');
    expect(ws.jsonMessages.last['thinking_level'], 'high');
    controller.phase = ChatPhase.idle;
    await controller.startListening();
    expect(ws.jsonMessages.last, {'type': 'audio_start', 'thinking_level': 'high'});
    await controller.cancelListening();
    controller.dispose();
  });
}

ChatController _controller(
  RecorderService recorder, {
  DateTime Function()? now,
  WsClient? ws,
}) {
  final config = AppConfig();
  final client = ws ??
      WsClient(
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
  @override
  Future<void> connect({Duration timeout = const Duration(seconds: 12)}) async {}
  @override
  Future<void> reconnect() async {}
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
