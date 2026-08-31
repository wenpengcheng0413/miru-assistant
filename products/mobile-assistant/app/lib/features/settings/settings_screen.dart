import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../core/config.dart';
import '../../core/deployment_profile.dart';
import '../../core/server_discovery.dart';
import '../../core/system_status.dart';

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
  late DeploymentProfile _profile;
  bool _saving = false;
  bool _discovering = false;
  bool _syncingWechat = false;
  String _testResult = '';
  String _wechatStatus = '';

  Dio get _dio => Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 12),
          receiveTimeout: const Duration(seconds: 12),
        ),
      );

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
    _profile = widget.config.profile;
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
          DropdownButtonFormField<DeploymentProfile>(
            initialValue: _profile,
            decoration: const InputDecoration(
              labelText: '连接模式',
              border: OutlineInputBorder(),
            ),
            items: DeploymentProfile.values
                .map(
                  (item) =>
                      DropdownMenuItem(value: item, child: Text(item.label)),
                )
                .toList(),
            onChanged: (value) {
              if (value == null) return;
              setState(() {
                _profile = value;
                _testResult = '';
                _wechatStatus = '';
              });
            },
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _urlCtrl,
            decoration: InputDecoration(
              labelText: _profile.isCloud ? 'Cloud 地址（HTTPS）' : '开发服务器地址',
              hintText: _profile.isCloud
                  ? 'https://设备名.tailnet.ts.net'
                  : 'http://127.0.0.1:8765',
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
          const SizedBox(height: 4),
          if (_profile.allowsBonjour)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: _discovering ? null : _discoverComputer,
                icon: _discovering
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.radar),
                label: Text(_discovering ? '正在查找电脑…' : '自动查找开发电脑'),
              ),
            ),
          if (_testResult.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_testResult, style: const TextStyle(fontSize: 13)),
            ),
          if (_wechatStatus.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(_wechatStatus, style: const TextStyle(fontSize: 12)),
            if (_profile.allowsBonjour)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: _syncingWechat ? null : _syncWechat,
                  icon: _syncingWechat
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.sync),
                  label: Text(_syncingWechat ? '正在同步微信数据…' : '同步微信数据'),
                ),
              ),
          ],
          const Divider(height: 32),
          SwitchListTile(
            title: const Text('语音回复'),
            subtitle: Text(
              widget.config.ttsEnabled ? 'Miru 会用语音回答' : '只显示文字，不播放语音',
            ),
            value: widget.config.ttsEnabled,
            onChanged: (v) => setState(() => widget.config.ttsEnabled = v),
          ),
          SwitchListTile(
            title: const Text('说完自动发送'),
            subtitle: Text(
              widget.config.autoSend ? '语音识别后直接发送' : '识别文本留在输入框，可修改后再发送',
            ),
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
    final error = _validateInput();
    if (error != null) {
      setState(() => _testResult = '❌ $error');
      return;
    }
    setState(() => _saving = true);
    widget.config.profile = _profile;
    widget.config.baseUrl = _cleanUrl;
    widget.config.token = _tokenCtrl.text.trim();
    await widget.config.save();
    if (mounted) {
      setState(() => _saving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('已保存')));
      Navigator.pop(context, true); // 通知聊天页配置已变更（含开关）
    }
  }

  Future<void> _testConnection() async {
    final cleanUrl = _cleanUrl;
    final validationError = _validateInput();
    if (validationError != null) {
      setState(() => _testResult = '❌ $validationError');
      return;
    }

    setState(() => _testResult = '测试中…');
    try {
      final resp = await _dio.get(
        '$cleanUrl/api/status',
        options: Options(headers: _headers),
      );
      // REST 通了还要验证 WS 握手（聊天功能走 WS），防止只通一半
      await _probeWs(cleanUrl);
      final status = MiruSystemStatus.fromJson(resp.data as Map);
      setState(() {
        _testResult = _profile.isCloud
            ? '✅ 连接成功（HTTPS REST + WSS）'
            : '✅ 连接成功（REST + WebSocket）';
        _wechatStatus = _formatSystemStatus(status);
      });
    } catch (e) {
      setState(() => _testResult = '❌ ${friendlyNetError(e)}');
    }
  }

  Future<void> _discoverComputer() async {
    if (!_profile.allowsBonjour) {
      setState(() => _testResult = '❌ 生产模式已禁用局域网自动发现');
      return;
    }
    setState(() {
      _discovering = true;
      _testResult = '正在局域网中查找 Miru…';
    });
    final found = await ServerDiscovery().findServer();
    if (!mounted) return;
    if (found == null) {
      setState(() {
        _discovering = false;
        _testResult = '❌ 没有发现电脑：请确认电脑端 Miru 已启动，且 iOS 已允许“本地网络”权限';
      });
      return;
    }
    _urlCtrl.text = found.toString().replaceAll(RegExp(r'/+$'), '');
    setState(() {
      _discovering = false;
      _testResult = '已找到 ${found.host}:${found.port}，正在验证连接…';
    });
    await _testConnection();
  }

  String? _validateInput() {
    if (_tokenCtrl.text.trim().isEmpty) return '访问令牌不能为空';
    final uri = Uri.tryParse(_cleanUrl);
    if (_cleanUrl.isEmpty || uri == null || uri.host.isEmpty) {
      return '请填写完整的服务器地址';
    }
    if (uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment) {
      return '服务器地址不能包含账号、查询参数或片段';
    }
    if (_profile.isCloud && uri.scheme != 'https') {
      return '生产模式只允许 HTTPS/WSS';
    }
    if (!_profile.isCloud && uri.scheme != 'http' && uri.scheme != 'https') {
      return '服务器地址必须以 http:// 或 https:// 开头';
    }
    return null;
  }

  String _formatSystemStatus(MiruSystemStatus status) {
    final unavailable = status.capabilities.entries
        .where((entry) => !entry.value.available)
        .map((entry) => entry.key)
        .take(4)
        .join('、');
    return '${status.cloudLabel} · ${status.homeNodeLabel}'
        '${unavailable.isEmpty ? '' : '\n暂不可用：$unavailable'}';
  }

  String _formatWechatStatus(Map<String, dynamic> health) {
    final wx = Map<String, dynamic>.from((health['wechat'] as Map?) ?? {});
    if (wx.isEmpty) return '微信状态：服务端未返回诊断信息';
    final error = wx['error'] as String? ?? '';
    if (error.isNotEmpty) {
      return '微信状态：异常（${wx['error_code'] ?? 'reader_error'}）\n$error';
    }
    final source = wx['source'] == 'snapshot' ? '离线快照' : '实时数据库';
    final stale = (wx['snapshot'] as Map?)?['stale'] == true ? '，快照已过期' : '';
    return '微信状态：${wx['contacts_db_readable'] == true ? '联系人可读' : '联系人不可读'}'
        ' · 消息分片 ${wx['message_shards'] ?? 0}/6'
        ' · 密钥 ${wx['keys_file'] == true ? '已找到' : '缺失'}'
        ' · 来源 $source$stale\n构建 ${health['build_id'] ?? wx['build_id'] ?? 'dev'}';
  }

  Future<void> _syncWechat() async {
    final cleanUrl = _cleanUrl;
    setState(() => _syncingWechat = true);
    try {
      await _dio.post(
        '$cleanUrl/api/wechat/sync',
        options: Options(headers: _headers),
      );
      final resp = await _dio.get(
        '$cleanUrl/api/health',
        options: Options(headers: _headers),
      );
      if (!mounted) return;
      setState(() {
        _wechatStatus = _formatWechatStatus(
          Map<String, dynamic>.from(resp.data as Map),
        );
        _testResult = '✅ 微信离线快照同步完成';
      });
    } catch (e) {
      if (mounted)
        setState(() => _testResult = '❌ 微信同步失败：${friendlyNetError(e)}');
    } finally {
      if (mounted) setState(() => _syncingWechat = false);
    }
  }

  /// 探测 /ws/session：完成 hello 握手收到 hello_ok 才算真的能用。
  Future<void> _probeWs(String cleanUrl) async {
    final base = Uri.parse(cleanUrl);
    final wsUri = base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/ws/session',
    );
    final channel = WebSocketChannel.connect(wsUri);
    try {
      await channel.ready.timeout(const Duration(seconds: 8));
      final helloOk = channel.stream.firstWhere((frame) {
        if (frame is! String) return false;
        try {
          final event = jsonDecode(frame) as Map<String, dynamic>;
          return event['type'] == 'hello_ok';
        } catch (_) {
          return false;
        }
      }).timeout(const Duration(seconds: 8));
      channel.sink.add(
        jsonEncode({
          'type': 'hello',
          'token': _tokenCtrl.text.trim(),
          'device': 'iphone',
          'mode': 'text',
        }),
      );
      await helloOk;
    } finally {
      try {
        await channel.sink.close();
      } catch (_) {}
    }
  }
}

/// 把 Dio / WS / Socket 异常翻译成用户能照着做的人话。
String friendlyNetError(Object e) {
  if (e is DioException) {
    final cause = e.error;
    if (e.type == DioExceptionType.connectionTimeout) {
      return '连接超时：请检查手机网络、Tailscale 与 Cloud 服务状态';
    }
    if (e.type == DioExceptionType.receiveTimeout) {
      return '响应超时：服务器收到了请求但没有回应，后端可能卡住了';
    }
    if (e.type == DioExceptionType.badResponse) {
      final status = e.response?.statusCode ?? 0;
      if (status == 401 || status == 403) {
        return '服务器拒绝了访问令牌（HTTP $status）：请重新输入 App Token';
      }
      return 'Cloud 返回错误（HTTP $status）';
    }
    if (cause is SocketException) {
      final code = cause.osError?.errorCode ?? -1;
      if (code == 51 || cause.message.toLowerCase().contains('unreachable')) {
        return '网络不可达：请检查手机网络与 Tailscale 连接';
      }
      if (code == 61 || cause.message.toLowerCase().contains('refused')) {
        return '连接被拒绝：Cloud 服务暂不可达';
      }
      return '网络错误：${cause.message}';
    }
  }
  if (e is StateError) {
    return 'WebSocket 握手失败：token 可能不对，或后端版本不匹配';
  }
  final text = e.toString();
  if (text.toLowerCase().contains('timed out') ||
      text.toLowerCase().contains('timeout')) {
    return '连接超时：请检查手机网络、Tailscale 与 Cloud 服务状态';
  }
  if (text.toLowerCase().contains('connection refused') ||
      text.toLowerCase().contains('拒绝')) {
    return '连接被拒绝：Cloud 服务暂不可达';
  }
  return text;
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
      final dio = Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 12),
        ),
      );
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

/// 记忆面板：管理画像、偏好、项目和知识四类长期记忆。
class _MemoryPanel extends StatefulWidget {
  const _MemoryPanel({super.key, required this.headers, required this.baseUrl});

  final Map<String, String> headers;
  final String baseUrl;

  @override
  State<_MemoryPanel> createState() => _MemoryPanelState();
}

class _MemoryPanelState extends State<_MemoryPanel> {
  static const _scopeLabels = <String, String>{
    'profile': '个人画像',
    'preferences': '偏好',
    'projects': '项目',
    'knowledge': '知识',
  };

  String _scope = 'profile';
  List<_MemoryEntry> _entries = const [];
  bool _loading = true;
  String _error = '';

  Dio get _api => Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 12),
          headers: widget.headers,
        ),
      );

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final resp = await _api.get(
        '${widget.baseUrl}/api/memory',
        queryParameters: {'scope': _scope},
      );
      final rows = (resp.data['entries'] as List?) ?? const [];
      if (!mounted) return;
      setState(() {
        _entries = rows
            .whereType<Map>()
            .map((row) => _MemoryEntry.fromJson(_scope, row))
            .toList();
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '加载失败：${friendlyNetError(e)}';
      });
    }
  }

  String _entryUrl(_MemoryEntry entry) =>
      '${widget.baseUrl}/api/memory/${entry.scope}/${Uri.encodeComponent(entry.key)}';

  Future<void> _edit(_MemoryEntry entry) async {
    final value = TextEditingController(text: entry.value);
    final notes = TextEditingController(text: entry.notes);
    final save = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('修改${_scopeLabels[entry.scope]}记忆'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(entry.title, style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 12),
              TextField(
                controller: value,
                autofocus: true,
                minLines: 2,
                maxLines: 8,
                decoration: InputDecoration(
                  labelText: entry.scope == 'projects' ? '项目状态' : '记忆内容',
                  border: const OutlineInputBorder(),
                ),
              ),
              if (entry.scope == 'projects') ...[
                const SizedBox(height: 12),
                TextField(
                  controller: notes,
                  minLines: 2,
                  maxLines: 6,
                  decoration: const InputDecoration(
                    labelText: '项目备注',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (save != true || value.text.trim().isEmpty) return;
    try {
      await _api.put(
        _entryUrl(entry),
        data: {
          'value': value.text.trim(),
          if (entry.scope == 'projects') 'notes': notes.text.trim(),
        },
      );
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('保存失败：${friendlyNetError(e)}')),
      );
    } finally {
      value.dispose();
      notes.dispose();
    }
  }

  Future<void> _delete(_MemoryEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除长期记忆？'),
        content: Text('将删除“${entry.title}”。此操作不会删除聊天记录。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton.tonal(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _api.delete(_entryUrl(entry));
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('删除失败：${friendlyNetError(e)}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _scope,
                  decoration: const InputDecoration(
                    labelText: '记忆分类',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                  items: _scopeLabels.entries
                      .map(
                        (item) => DropdownMenuItem(
                          value: item.key,
                          child: Text(item.value),
                        ),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value == null || value == _scope) return;
                    _scope = value;
                    _load();
                  },
                ),
              ),
              IconButton(
                tooltip: '重新加载',
                onPressed: _loading ? null : _load,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (_loading)
            const Center(child: CircularProgressIndicator())
          else if (_error.isNotEmpty)
            Text(_error,
                style: TextStyle(color: Theme.of(context).colorScheme.error))
          else if (_entries.isEmpty)
            const Text('（空）')
          else
            ..._entries.map(
              (entry) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  title: Text(entry.title),
                  subtitle: Text(
                    [entry.value, if (entry.notes.isNotEmpty) entry.notes]
                        .join('\n'),
                    maxLines: 5,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: Wrap(
                    spacing: 0,
                    children: [
                      IconButton(
                        tooltip: '修改',
                        onPressed: () => _edit(entry),
                        icon: const Icon(Icons.edit_outlined),
                      ),
                      IconButton(
                        tooltip: '删除',
                        onPressed: () => _delete(entry),
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      );
}

class _MemoryEntry {
  const _MemoryEntry({
    required this.scope,
    required this.key,
    required this.title,
    required this.value,
    required this.notes,
  });

  final String scope;
  final String key;
  final String title;
  final String value;
  final String notes;

  factory _MemoryEntry.fromJson(String scope, Map<dynamic, dynamic> json) {
    if (scope == 'projects') {
      final name = json['name'] as String? ?? '';
      return _MemoryEntry(
        scope: scope,
        key: name,
        title: name,
        value: json['status'] as String? ?? '',
        notes: json['notes'] as String? ?? '',
      );
    }
    if (scope == 'knowledge') {
      final id = '${json['id'] ?? ''}';
      return _MemoryEntry(
        scope: scope,
        key: id,
        title: '知识 #$id',
        value: json['content'] as String? ?? '',
        notes: '',
      );
    }
    final key = json['key'] as String? ?? '';
    return _MemoryEntry(
      scope: scope,
      key: key,
      title: key,
      value: json['value'] as String? ?? '',
      notes: '',
    );
  }
}
