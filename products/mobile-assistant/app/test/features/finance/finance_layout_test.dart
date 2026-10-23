import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/core/design/miru_theme.dart';
import 'package:miru_app/features/finance/finance_screen.dart';
import 'finance_screen_test.dart' show FakeFinanceApi;

void main() {
  testWidgets('账本小屏两倍字，筛选、滚动与详情可用', (tester) async {
    tester.view.physicalSize = const Size(320, 740);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        theme: MiruTheme.dark,
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(2)),
            child: child!),
        home: FinanceScreen(
            config: AppConfig(), api: FakeFinanceApi(ready: true))));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(find.text('筛选账单').hitTestable(), 240,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('筛选账单'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(find.text('午饭').hitTestable(), 240,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('午饭'));
    await tester.pumpAndSettle();
    expect(find.textContaining('工作日午餐'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
