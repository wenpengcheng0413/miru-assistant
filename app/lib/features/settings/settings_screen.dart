import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../../core/config.dart';

/// 设置页：服务器配置 / 连接测试 / 成本 / 记忆（REST 管理面）。
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.config});

  final AppConfig config;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _urlCtrl;
  late final TextEditingController _tokenCtrl;
  bool _saving = false;
  String _testResult = '';

  Dio get _dio => Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 12),
        receiveTimeout: const Duration(seconds: 12),
      ));

  /// 去尾部斜杠：`http://x:8765/` → `http://x:8765`，避免拼出 //api/health
  String get _cleanUrl => _urlCtrl.text.trim().replaceAll(RegExp(r'/+$'), '');

  Map<String, String> get _headers => {
        'Authorization': 'Bearer ${_tokenCtrl.text.trim()}',
      };

  @override
  void initState() {
    super.initState();
    _urlCtrl = TextEditingController(text: widget.config.baseUrl);
    _tokenCtrl = TextEditingController(text: widget.config.token);
  }

  @override
  void dispose() {
    _urlCtrl.dispose();
    _tokenCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _urlCtrl,
            decoration: const InputDecoration(
              labelText: '后端地址',
              hintText: 'http://192.168.1.100:8765 或 https://xxx.ts.net:8765',
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.url,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _tokenCtrl,
            decoration: const InputDecoration(
              labelText: '访问令牌（Bearer token）',
              border: OutlineInputBorder(),
            ),
            obscureText: true,
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: const Icon(Icons.save_outlined),
                  label: const Text('保存'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _testConnection,
                  icon: const Icon(Icons.wifi_tethering),
                  label: const Text('测试连接'),
                ),
              ),
            ],
          ),
          if (_testResult.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_testResult, style: const TextStyle(fontSize: 13)),
            ),
          const Divider(height: 32),
          SwitchListTile(
            title: const Text('语音回复'),
            subtitle: Text(widget.config.ttsEnabled
                ? 'Miru 会用语音回答'
                : '只显示文字，不播放语音'),
            value: widget.config.ttsEnabled,
            onChanged: (v) => setState(() => widget.config.ttsEnabled = v),
          ),
          SwitchListTile(
            title: const Text('说完自动发送'),
            subtitle: Text(widget.config.autoSend
                ? '语音识别后直接发送'
                : '识别文本留在输入框，可修改后再发送'),
            value: widget.config.autoSend,
            onChanged: (v) => setState(() => widget.config.autoSend = v),
          ),
          const Divider(height: 32),
          Text('成本报表（近 7 天）', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          // key 绑定当前地址：保存后自动用新地址重新加载
          _CostPanel(
            key: ValueKey('cost-$_cleanUrl'),
            headers: _headers,
            baseUrl: _cleanUrl,
          ),
          const Divider(height: 32),
          Text('长期记忆（profile）', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          _MemoryPanel(
            key: ValueKey('memory-$_cleanUrl'),
            headers: _headers,
            baseUrl: _cleanUrl,
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    widget.config.baseUrl = _cleanUrl;
    widget.config.token = _tokenCtrl.text.trim();
    await widget.config.save();
    if (mounted) {
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已保存')),
      );
      Navigator.pop(context, true); // 通知聊天页配置已变更（含开关）
    }
  }

  Future<void> _testConnection() async {
    setState(() => _testResult = '测试中…');
    try {
      final resp = await _dio.get(
        '$_cleanUrl/api/health',
        options: Options(headers: _headers),
      );
      setState(() => _testResult = '✅ 连接成功：${resp.data}');
    } catch (e) {
      setState(() => _testResult = '❌ ${friendlyNetError(e)}');
    }
  }
}

/// 把 Dio 网络异常翻译成用户能照着做的人话
String friendlyNetError(Object e) {
  if (e is DioException) {
    final cause = e.error;
    if (e.type == DioExceptionType.connectionTimeout) {
      return '连接超时：手机与电脑可能不在同一 Wi-Fi，或电脑防火墙拦截了端口 8765';
    }
    if (e.type == DioExceptionType.receiveTimeout) {
      return '响应超时：服务器收到了请求但没有回应，后端可能卡住了';
    }
    if (cause is SocketException) {
      final code = cause.osError?.errorCode ?? -1;
      if (code == 51 || cause.message.toLowerCase().contains('unreachable')) {
        return '连不上局域网：① 手机与电脑连同一个 Wi-Fi ② iOS 已允许本地网络权限'
            '（设置→隐私与安全性→本地网络，打开 LiveContainer / Miru）'
            ' ③ 电脑防火墙放行 8765 端口';
      }
      if (code == 61 || cause.message.toLowerCase().contains('refused')) {
        return '连接被拒绝：后端没启动，或端口不是 8765';
      }
    }
  }
  return e.toString();
}

/// 成本面板：/api/cost/report
class _CostPanel extends StatefulWidget {
  const _CostPanel({super.key, required this.headers, required this.baseUrl});

  final Map<String, String> headers;
  final String baseUrl;

  @override
  State<_CostPanel> createState() => _CostPanelState();
}

class _CostPanelState extends State<_CostPanel> {
  String _text = '加载中…';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final dio = Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 8),
        receiveTimeout: const Duration(seconds: 12),
      ));
      final resp = await dio.get(
        '${widget.baseUrl}/api/cost/report?days=7',
        options: Options(headers: widget.headers),
      );
      final data = resp.data as Map<String, dynamic>;
      final by = (data['by_provider'] as Map?) ?? {};
      setState(() {
        _text = '近 7 天合计 ¥${data['total_rmb']} · '
            '${by.entries.map((e) => '${e.key}: ¥${e.value}').join('，')}';
      });
    } catch (e) {
      setState(() => _text = '加载失败：${friendlyNetError(e)}');
    }
  }

  void _reload() {
    setState(() => _text = '加载中…');
    _load();
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_text, style: const TextStyle(fontSize: 13)),
          TextButton(onPressed: _reload, child: const Text('重新加载')),
        ],
      );
}

/// 记忆面板：/api/memory?scope=profile
class _MemoryPanel extends StatefulWidget {
  const _MemoryPanel({super.key, required this.headers, required this.baseUrl});

  final Map<String, String> headers;
  final String baseUrl;

  @override
  State<_MemoryPanel> createState() => _MemoryPanelState();
}

class _MemoryPanelState extends State<_MemoryPanel> {
  String _text = '加载中…';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final dio = Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 8),
        receiveTimeout: const Duration(seconds: 12),
      ));
      final resp = await dio.get(
        '${widget.baseUrl}/api/memory?scope=profile',
        options: Options(headers: widget.headers),
      );
      final entries = (resp.data['entries'] as List?) ?? [];
      setState(() {
        _text = entries.isEmpty
            ? '（空）'
            : entries.map((e) => '${e['key']} = ${e['value']}').join('\n');
      });
    } catch (e) {
      setState(() => _text = '加载失败：${friendlyNetError(e)}');
    }
  }

  void _reload() {
    setState(() => _text = '加载中…');
    _load();
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_text, style: const TextStyle(fontSize: 13)),
          TextButton(onPressed: _reload, child: const Text('重新加载')),
        ],
      );
}
