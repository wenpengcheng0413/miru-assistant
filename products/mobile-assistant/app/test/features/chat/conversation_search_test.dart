import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/server_discovery.dart';
import 'package:miru_app/features/chat/chat_controller.dart';
import '../../support/chat_fakes.dart';

void main() {
  test('较慢的旧搜索不能覆盖新搜索，销毁后的响应不通知页面', () async {
    await HttpOverrides.runWithHttpOverrides(() async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final oldReceived = Completer<void>(), releaseOld = Completer<void>();
      final lastReceived = Completer<void>(), releaseLast = Completer<void>();
      server.listen((request) async {
        final query = request.uri.queryParameters['q'] ?? '';
        if (query == 'old') {
          oldReceived.complete();
          await releaseOld.future;
        }
        if (query == 'disposed') {
          lastReceived.complete();
          await releaseLast.future;
        }
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode([
          {'id': query, 'title': query, 'message_count': 1}
        ]));
        await request.response.close();
      });
      final c = ChatController(
          config: AppConfig()..baseUrl = 'http://127.0.0.1:${server.port}',
          ws: TestWsClient(),
          recorder: TestRecorder(),
          player: TestPlayer(),
          discovery: ServerDiscovery());
      try {
        final first = c.loadConversations(query: 'old');
        await oldReceived.future;
        await c.loadConversations(query: 'new');
        releaseOld.complete();
        await first;
        expect(c.conversations.single.id, 'new');
        expect(c.conversationQuery, 'new');
        final last = c.loadConversations(query: 'disposed');
        await lastReceived.future;
        c.dispose();
        releaseLast.complete();
        await last;
      } finally {
        await server.close(force: true);
      }
    }, _LoopbackHttpOverrides());
  });
}

class _LoopbackHttpOverrides extends HttpOverrides {}
