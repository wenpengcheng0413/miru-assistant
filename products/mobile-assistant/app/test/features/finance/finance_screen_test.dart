import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/core/config.dart';
import 'package:miru_app/features/finance/finance_api.dart';
import 'package:miru_app/features/finance/finance_screen.dart';

class FakeFinanceApi extends FinanceApi {
  FakeFinanceApi({this.ready = false}) : super(AppConfig());
  final bool ready;

  @override
  Future<Map<String, dynamic>> get(String path, [Map<String, dynamic>? query]) async {
    if (path == 'status') return {'state': ready ? 'ready' : 'unpaired', 'revision': ready ? 1 : 0,
      'synced_at': ready ? '2026-10-13T00:00:00Z' : null, 'transaction_count': ready ? 1 : null};
    if (path == 'catalogs') return {'revision': 1, 'wallets': [], 'categories': []};
    if (path == 'summary') return {'revision': 1, 'start': '2026-10-12', 'end_exclusive': '2026-10-19',
      'policy': '排除转账和待支付', 'currencies': {'CNY': {'income': '1000.00', 'expense': '25.30',
        'balance': '974.70', 'categories': {}, 'days': {}}}};
    return {'revision': 1, 'total': 1, 'next_cursor': null, 'items': [{'id': 'one', 'title': '午饭',
      'local_date': '2026-10-13', 'classification': 'expense', 'category': '餐饮', 'wallet': '现金',
      'note': '工作日午餐', 'currency': 'CNY', 'amount': '-25.30'}]};
  }

  @override
  Future<Map<String, dynamic>> post(String path) async => {'code': 'one-time-test-code'};
}

void main() {
  testWidgets('unsynced ledger offers pairing and never invents zero income', (tester) async {
    await tester.pumpWidget(MaterialApp(home: FinanceScreen(config: AppConfig(), api: FakeFinanceApi())));
    await tester.pumpAndSettle();
    expect(find.text('尚未同步'), findsOneWidget);
    expect(find.text('收入 0'), findsNothing);
    await tester.tap(find.text('连接 Cashew'));
    await tester.pumpAndSettle();
    expect(find.text('one-time-test-code'), findsOneWidget);
  });

  testWidgets('summary shows exact decimal strings and transaction detail remains reachable', (tester) async {
    await tester.pumpWidget(MaterialApp(home: FinanceScreen(config: AppConfig(), api: FakeFinanceApi(ready: true))));
    await tester.pumpAndSettle();
    expect(find.text('收入 1000.00'), findsOneWidget);
    expect(find.text('支出 25.30'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('午饭'), 200, scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('午饭'));
    await tester.pumpAndSettle();
    expect(find.textContaining('工作日午餐'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
