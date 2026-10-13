import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:miru_app/features/finance/finance_api.dart';

void main() {
  test('finance errors distinguish no data, changed snapshot and expired credentials', () {
    DioException failure(int status, String code) => DioException(
      requestOptions: RequestOptions(path: '/api/finance/status'),
      response: Response(requestOptions: RequestOptions(), statusCode: status, data: {'detail': {'code': code}}),
    );
    expect(FinanceApi.error(failure(409, 'not_synced')), contains('尚未收到'));
    expect(FinanceApi.error(failure(409, 'snapshot_changed')), contains('刷新'));
    expect(FinanceApi.error(failure(401, 'invalid_token')), contains('凭据无效'));
    expect(FinanceApi.error(failure(500, 'secret-server-error')), isNot(contains('secret-server-error')));
  });
}
