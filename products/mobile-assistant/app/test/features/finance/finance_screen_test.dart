import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/features/finance/finance_api.dart';
import 'package:miru_app/features/finance/finance_screen.dart';

class FakeFinanceApi extends FinanceApi {
  FakeFinanceApi({this.ready = false}) : super(AppConfig());
  final bool ready;
  int revision = 1;
  int summaryReads = 0;
  String expense = '25.30';

  @override
  Future<Map<String, dynamic>> get(String path,
      [Map<String, dynamic>? query]) async {
    if (path == 'status')
      return {
        'state': ready ? 'ready' : 'unpaired',
        'revision': ready ? revision : 0,
        'synced_at': ready ? '2026-10-13T00:00:00Z' : null,
        'transaction_count': ready ? 1 : null
      };
    if (path == 'catalogs')
      return {'revision': revision, 'wallets': [], 'categories': []};
    if (path == 'summary') {
      summaryReads++;
      return {
        'revision': revision,
        'start': '2026-10-12',
        'end_exclusive': '2026-10-19',
        'policy': '排除转账和待支付',
        'currencies': {
          'CNY': {
            'income': '1000.00',
            'expense': expense,
            'balance': '974.70',
            'categories': {},
            'days': {}
          }
        }
      };
    }
    return {
      'revision': revision,
      'total': 1,
      'next_cursor': null,
      'items': [
        {
          'id': 'one',
          'title': '午饭',
          'local_date': '2026-10-13',
          'classification': 'expense',
          'category': '餐饮',
          'wallet': '现金',
          'note': '工作日午餐',
          'currency': 'CNY',
          'amount': '-25.30'
        }
      ]
    };
  }

  @override
  Future<Map<String, dynamic>> post(String path) async =>
      {'code': 'one-time-test-code'};
}

void main() {
  testWidgets('unsynced ledger offers pairing and never invents zero income',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: FinanceScreen(config: AppConfig(), api: FakeFinanceApi())));
    await tester.pumpAndSettle();
    expect(find.text('尚未同步'), findsOneWidget);
    expect(find.text('收入 0'), findsNothing);
    await tester.tap(find.text('连接 Cashew'));
    await tester.pumpAndSettle();
    expect(find.text('one-time-test-code'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'summary shows exact decimal strings and transaction detail remains reachable',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: FinanceScreen(
            config: AppConfig(), api: FakeFinanceApi(ready: true))));
    await tester.pumpAndSettle();
    expect(find.text('收入 1000.00'), findsOneWidget);
    expect(find.text('支出 25.30'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('午饭').hitTestable(), 200,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('午饭'));
    await tester.pumpAndSettle();
    expect(find.textContaining('工作日午餐'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'foreground checks new snapshots and resumes without resetting unchanged views',
      (tester) async {
    final api = FakeFinanceApi(ready: true);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(
        MaterialApp(home: FinanceScreen(config: AppConfig(), api: api)));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(seconds: 10));
    await tester.pumpAndSettle();
    expect(api.summaryReads, 1);
    api.revision++;
    api.expense = '30.00';
    await tester.pump(const Duration(seconds: 10));
    await tester.pumpAndSettle();
    expect(find.text('支出 30.00'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    api.revision++;
    api.expense = '45.00';
    await tester.pump(const Duration(seconds: 20));
    expect(api.summaryReads, 2);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('支出 45.00'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
