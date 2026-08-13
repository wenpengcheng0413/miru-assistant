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
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 8),
      ));

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
          _CostPanel(headers: _headers, baseUrl: _urlCtrl.text.trim()),
          const Divider(height: 32),
          Text('长期记忆（profile）', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          _MemoryPanel(headers: _headers, baseUrl: _urlCtrl.text.trim()),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    widget.config.baseUrl = _urlCtrl.text.trim();
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
        '${_urlCtrl.text.trim()}/api/health',
        options: Options(headers: _headers),
      );
      setState(() => _testResult = '✅ 连接成功：${resp.data}');
    } catch (e) {
      setState(() => _testResult = '❌ 连接失败：$e');
    }
  }
}

/// 成本面板：/api/cost/report
class _CostPanel extends StatefulWidget {
  const _CostPanel({required this.headers, required this.baseUrl});

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
      final dio = Dio();
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
      setState(() => _text = '加载失败：$e');
    }
  }

  @override
  Widget build(BuildContext context) => Text(_text, style: const TextStyle(fontSize: 13));
}

/// 记忆面板：/api/memory?scope=profile
class _MemoryPanel extends StatefulWidget {
  const _MemoryPanel({required this.headers, required this.baseUrl});

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
      final dio = Dio();
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
      setState(() => _text = '加载失败：$e');
    }
  }

  @override
  Widget build(BuildContext context) => Text(_text, style: const TextStyle(fontSize: 13));
}
