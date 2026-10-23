import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/design/miru_theme.dart';
import 'package:miru_app/features/settings/settings_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    FlutterSecureStorage.setMockInitialValues({});
    MiruThemeController.instance.mode.value = ThemeMode.system;
  });

  Future<void> open(WidgetTester tester, AppConfig config,
      {double scale = 1, Future<void> Function(AppConfig)? save}) async {
    tester.view.physicalSize = const Size(320, 740);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        theme: MiruTheme.dark,
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(scale)),
            child: child!),
        home: Builder(
            builder: (context) => Scaffold(
                body: TextButton(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute<void>(
                            builder: (_) => SettingsScreen(
                                config: config, saveConfig: save))),
                    child: const Text('打开设置'))))));
    await tester.tap(find.text('打开设置'));
    await tester.pumpAndSettle();
  }

  testWidgets('未保存的偏好不会更改共享配置，保存后持久化', (tester) async {
    final config = AppConfig()..token = 'fixture-token';
    await open(tester, config);
    await tester.tap(find.text('语音回复'));
    await tester.pump();
    expect(config.ttsEnabled, isTrue);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(config.ttsEnabled, isTrue);
    await tester.tap(find.text('打开设置'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('语音回复'));
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(config.ttsEnabled, isFalse);
    expect((await SharedPreferences.getInstance()).getBool('miru_tts_enabled'),
        isFalse);
    expect(find.text('打开设置'), findsOneWidget);
  });

  testWidgets('小屏两倍字体，展开连接配置不溢出，令牌保持隐藏', (tester) async {
    await open(tester, AppConfig()..token = 'fixture-token', scale: 2);
    await tester.scrollUntilVisible(find.text('服务连接').hitTestable(), 240);
    await tester.tap(find.text('服务连接'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.widgetWithText(TextField, '访问令牌（Bearer token）').hitTestable(), 220,
        scrollable: find.byType(Scrollable).first);
    expect(
        tester
            .widget<TextField>(
                find.widgetWithText(TextField, '访问令牌（Bearer token）'))
            .obscureText,
        isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('不合法连接地址无法保存，显示可操作错误', (tester) async {
    final config = AppConfig()..token = 'fixture-token';
    await open(tester, config);
    await tester.scrollUntilVisible(find.text('服务连接').hitTestable(), 240);
    await tester.tap(find.text('服务连接'));
    await tester.pumpAndSettle();
    final field = find.widgetWithText(TextField, '开发服务器地址');
    await tester.ensureVisible(field);
    await tester.pumpAndSettle();
    await tester.enterText(field, 'invalid-address');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.text('请填写完整的服务器地址'), findsOneWidget);
    expect(config.baseUrl, AppConfig.defaultDevelopmentBaseUrl);
  });

  testWidgets('安全存储失败可重试，当前地址和偏好不被污染', (tester) async {
    final config = AppConfig()..token = 'fixture-token';
    var reject = true;
    await open(tester, config, save: (draft) async {
      if (reject) throw StateError('storage unavailable');
      await draft.save();
    });
    await tester.tap(find.text('语音回复'));
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.text('保存失败，请重试。当前连接未更改。'), findsOneWidget);
    expect(config.ttsEnabled, isTrue);
    expect(find.text('保存中…'), findsNothing);
    reject = false;
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(config.ttsEnabled, isFalse);
  });
}
