import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/design/miru_theme.dart';
import 'package:miru_app/features/chat/chat_controller.dart';
import 'package:miru_app/features/chat/chat_screen.dart';
import 'package:miru_app/features/chat/message_content.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../support/chat_fakes.dart';

void main() {
  Future<void> mount(WidgetTester tester, TestChatController c,
      {Size size = const Size(390, 844),
      double scale = 1,
      bool dark = false,
      double keyboard = 0}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        theme: dark ? MiruTheme.dark : MiruTheme.light,
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
                textScaler: TextScaler.linear(scale),
                viewInsets: EdgeInsets.only(bottom: keyboard),
                disableAnimations: true),
            child: child!),
        home: ChatScreen(controller: c, player: c.player)));
    await tester.pumpAndSettle();
  }

  Future<void> unmount(WidgetTester tester, TestChatController c) async {
    await tester.pumpWidget(const SizedBox());
    c.dispose();
  }

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('中文组词尚未完成时不发送', (tester) async {
    final ws = TestWsClient();
    final c = TestChatController(client: ws);
    await mount(tester, c);
    final field =
        tester.widget<TextField>(find.byKey(const ValueKey('chat-input')));
    field.controller!.value = const TextEditingValue(
        text: '计划', composing: TextRange(start: 0, end: 2));
    await tester.pump();
    await tester.tap(find.byTooltip('发送消息'));
    await tester.pump();
    expect(ws.sent, isEmpty);
    field.controller!.value = const TextEditingValue(text: '计划');
    await tester.pump();
    await tester.tap(find.byTooltip('发送消息'));
    await tester.pump();
    expect(ws.sent, hasLength(1));
    await unmount(tester, c);
  });

  testWidgets('阅读历史时流式增长保留当前可见消息位置', (tester) async {
    final c = TestChatController();
    for (var i = 0; i < 60; i++) {
      c.lines.add(ChatLine('user', '历史消息 $i'));
    }
    await mount(tester, c);
    await tester.drag(find.byKey(const ValueKey('conversation-messages')),
        const Offset(0, 700));
    await tester.pumpAndSettle();
    final visible = find.byType(SelectableText).hitTestable().first;
    final text = tester.widget<SelectableText>(visible).data!;
    final top = tester.getTopLeft(find.text(text)).dy;
    c.phase = ChatPhase.thinking;
    c.miruText = '正在流式生成的较长回答。\n' * 20;
    c.update();
    await tester.pump();
    await tester.pump();
    expect(tester.getTopLeft(find.text(text)).dy, closeTo(top, 1));
    expect(find.byTooltip('回到最新消息'), findsOneWidget);
    await unmount(tester, c);
  });

  testWidgets('空输入禁用发送，换行保留且连续点击只发送一次', (tester) async {
    final ws = TestWsClient();
    final c = TestChatController(client: ws);
    await mount(tester, c);
    final send = find.byTooltip('发送消息');
    expect(
        tester
            .widget<IconButton>(
                find.widgetWithIcon(IconButton, Icons.arrow_upward_rounded))
            .onPressed,
        isNull);
    await tester.enterText(
        find.byKey(const ValueKey('chat-input')), '第一行\n第二行');
    await tester.pump();
    await tester.tap(send);
    await tester.tap(send);
    await tester.pump();
    expect(ws.sent.where((e) => e['type'] == 'text_input'), hasLength(1));
    expect(ws.sent.last['text'], '第一行\n第二行');
    expect(find.text('停止生成'), findsOneWidget);
    await unmount(tester, c);
  });

  testWidgets('离线发送失败保留草稿，工具与错误长文不会溢出', (tester) async {
    final c = TestChatController()..wsConnected = false;
    await mount(tester, c, size: const Size(320, 680), scale: 1.8);
    await tester.enterText(find.byKey(const ValueKey('chat-input')), '离线草稿');
    await tester.pump();
    await tester.tap(find.byTooltip('发送消息'));
    await tester.pump();
    expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('chat-input')))
            .controller!
            .text,
        '离线草稿');
    expect(tester.takeException(), isNull);
    c.phase = ChatPhase.thinking;
    c.toolStatus = '正在处理很长的工具说明' * 8;
    c.update();
    await tester.pump();
    expect(tester.takeException(), isNull);
    await unmount(tester, c);
  });

  testWidgets('停止生成保留已收到的回复', (tester) async {
    final c = TestChatController()
      ..phase = ChatPhase.thinking
      ..miruText = '已经生成的内容';
    await mount(tester, c);
    await tester.tap(find.text('停止生成'));
    await tester.pumpAndSettle();
    expect(c.lines.single.text, '已经生成的内容');
    expect(c.lines.single.stats!.status, 'interrupted');
    expect(c.phase, ChatPhase.idle);
    await unmount(tester, c);
  });

  testWidgets('320宽大字深色键盘布局以及思考面板无溢出', (tester) async {
    final c = TestChatController();
    c.lines.add(ChatLine('miru',
        '## 回复\n\n**重要内容**，可选择与复制。\n\n```dart\nfinal longValue = "${'x' * 100}";\n```'));
    await mount(tester, c,
        size: const Size(320, 740), scale: 2, dark: true, keyboard: 260);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('标准思考'));
    await tester.pumpAndSettle();
    expect(find.text('选择思考方式'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await unmount(tester, c);
  });

  testWidgets('宽屏导航常驻且不会弹出主页路由', (tester) async {
    final c = TestChatController();
    await mount(tester, c, size: const Size(1280, 900));
    expect(find.text('最近对话'), findsOneWidget);
    expect(find.text('设置与偏好'), findsOneWidget);
    await tester.tap(find.text('设置与偏好'));
    await tester.pumpAndSettle();
    expect(find.text('让 Miru 更懂你的习惯'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('最近对话'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await unmount(tester, c);
  });

  testWidgets('Markdown长代码和表格可布局，链接可查看复制', (tester) async {
    tester.view.physicalSize = const Size(320, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        theme: MiruTheme.dark,
        home: Scaffold(
            body: SingleChildScrollView(
                child: Padding(
          padding: const EdgeInsets.all(16),
          child: MessageContent(
              text:
                  '# 标题\n\n[来源](https://example.com)\n\n|项目|状态|\n|---|---|\n|语音|保留|\n\n```dart\nfinal answer = "${List.filled(80, 'x').join()}";\n```'),
        )))));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byType(MessageContent), findsOneWidget);
    String? copied;
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String;
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    await tester.tap(find.text('来源', findRichText: true));
    await tester.pumpAndSettle();
    expect(find.text('https://example.com'), findsOneWidget);
    await tester.tap(find.text('复制链接'));
    await tester.pumpAndSettle();
    expect(copied, 'https://example.com');
    expect(find.text('链接已复制'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('界面外观独立持久化，不改其他配置', () async {
    await MiruThemeController.instance.setMode(ThemeMode.dark);
    MiruThemeController.instance.mode.value = ThemeMode.light;
    await MiruThemeController.instance.load();
    expect(MiruThemeController.instance.mode.value, ThemeMode.dark);
    MiruThemeController.instance.mode.value = ThemeMode.system;
  });
}
