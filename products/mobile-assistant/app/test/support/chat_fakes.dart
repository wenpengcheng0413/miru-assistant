import 'dart:typed_data';
import 'package:miru_app/core/audio/player_service.dart';
import 'package:miru_app/core/audio/recorder_service.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/server_discovery.dart';
import 'package:miru_app/core/ws_client.dart';
import 'package:miru_app/features/chat/chat_controller.dart';

class TestWsClient extends WsClient {
  TestWsClient()
      : super(
            url: Uri.parse('ws://localhost/ws/session'), token: '', hello: {});
  final sent = <Map<String, dynamic>>[];
  @override
  void sendJson(Map<String, dynamic> payload) => sent.add(Map.of(payload));
  @override
  Future<void> connect(
      {Duration timeout = const Duration(seconds: 12)}) async {}
  @override
  Future<void> reconnect() async {}
  @override
  Future<void> close() async {}
}

class TestPlayer implements PlayerService {
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

class TestRecorder implements RecorderService {
  @override
  bool isRecording = false;
  @override
  Future<bool> hasPermission() async => true;
  @override
  Future<void> start({required void Function(Uint8List) onChunk}) async {
    isRecording = true;
  }

  @override
  Future<void> stop() async {
    isRecording = false;
  }

  @override
  Future<void> dispose() async {}
}

class TestChatController extends ChatController {
  TestChatController({AppConfig? appConfig, TestWsClient? client})
      : super(
          config: appConfig ?? AppConfig(),
          ws: client ?? TestWsClient(),
          recorder: TestRecorder(),
          player: TestPlayer(),
          discovery: ServerDiscovery(),
        ) {
    wsConnected = true;
  }
  @override
  Future<void> loadConversations({String? query}) async {}
  void update() => notifyListeners();
}
