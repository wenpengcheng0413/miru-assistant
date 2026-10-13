import 'package:dio/dio.dart';

import '../../core/config.dart';

class FinanceApi {
  FinanceApi(AppConfig config)
      : _dio = Dio(BaseOptions(
          baseUrl: config.restBaseUrl,
          headers: {'Authorization': 'Bearer ${config.token}'},
          connectTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 30),
          followRedirects: false,
        ));

  final Dio _dio;

  Future<Map<String, dynamic>> get(String path,
      [Map<String, dynamic>? query]) async {
    final response = await _dio.get<Map<String, dynamic>>('/api/finance/$path',
        queryParameters: query);
    return response.data!;
  }

  Future<Map<String, dynamic>> post(String path) async {
    final response = await _dio.post<Map<String, dynamic>>('/api/finance/$path');
    return response.data!;
  }

  void close() => _dio.close(force: true);

  static String error(Object error) {
    if (error is DioException) {
      final body = error.response?.data;
      final detail = body is Map ? body['detail'] : null;
      final code = detail is Map ? detail['code'] : null;
      if (code == 'snapshot_changed') return '账本已更新，请刷新后继续查看';
      if (code == 'not_synced') return '尚未收到 Cashew 账本，请先在 Cashew 同步';
      if (code == 'reconciliation_changed') return '待核对账本已变化，请刷新后重试';
      if (error.response?.statusCode == 401) return '连接凭据无效，请检查米汝设置';
      if (error.response?.statusCode == 404) return '服务器尚未提供此账本接口，请更新米汝后端';
    }
    return '账本加载失败，请检查连接后重试';
  }
}
