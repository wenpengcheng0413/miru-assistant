import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/config.dart';
import 'finance_api.dart';

class FinanceScreen extends StatefulWidget {
  const FinanceScreen({super.key, required this.config, this.api});
  final AppConfig config;
  final FinanceApi? api;

  @override
  State<FinanceScreen> createState() => _FinanceScreenState();
}

class _FinanceScreenState extends State<FinanceScreen> with WidgetsBindingObserver {
  late final FinanceApi _api;
  final _search = TextEditingController();
  Map<String, dynamic>? _status, _summary, _catalogs;
  List<dynamic> _items = [];
  String? _cursor, _wallet, _category, _classification;
  DateTimeRange? _range;
  String _error = '';
  bool _loading = true, _more = false, _action = false;
  int _generation = 0, _total = 0;
  Timer? _refreshTimer;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? FinanceApi(widget.config);
    WidgetsBinding.instance.addObserver(this);
    _refreshTimer = Timer.periodic(const Duration(seconds: 10), (_) => _checkForUpdates());
    _reload();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _refreshTimer?.cancel();
    _api.close();
    _search.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _checkForUpdates();
  }

  Future<void> _checkForUpdates() async {
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    if (!mounted || _checking || _loading || _more || _action ||
        (lifecycle != null && lifecycle != AppLifecycleState.resumed) ||
        ModalRoute.of(context)?.isCurrent == false) return;
    _checking = true;
    final generation = _generation;
    try {
      final status = await _api.get('status');
      if (!mounted || generation != _generation) return;
      if (_error.isNotEmpty || status['revision'] != _status?['revision'] ||
          status['paired'] != _status?['paired'] ||
          (status['reconciliation'] as Map?)?['snapshot_id'] !=
              (_status?['reconciliation'] as Map?)?['snapshot_id']) {
        await _reload();
      }
    } catch (_) {
      // Preserve the last successful view during a temporary connection loss.
      // Its timestamp remains visible; the next foreground check retries.
    } finally {
      _checking = false;
    }
  }

  String _date(DateTime date) => '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

  Map<String, dynamic> get _filters => {
        if (_range != null) 'start': _date(_range!.start),
        if (_range != null) 'end': _date(_range!.end.add(const Duration(days: 1))),
        if (_wallet != null) 'wallet_id': _wallet,
        if (_category != null) 'category_id': _category,
      };

  Future<void> _reload() async {
    final generation = ++_generation;
    setState(() { _loading = true; _more = false; _error = ''; _summary = null; _items = []; _cursor = null; });
    try {
      final status = await _api.get('status');
      Map<String, dynamic>? summary, catalogs, entries;
      if ((status['revision'] as int? ?? 0) > 0) {
        final responses = await Future.wait([
          _api.get('summary', _filters),
          _api.get('catalogs'),
          _api.get('transactions', {..._filters, 'query': _search.text.trim(),
            if (_classification != null) 'classification': _classification}),
        ]);
        summary = responses[0]; catalogs = responses[1]; entries = responses[2];
        // Never present totals and rows from different snapshots as one view.
        if (summary['revision'] != entries['revision'] || catalogs['revision'] != entries['revision'] || status['revision'] != entries['revision']) {
          throw StateError('snapshot_changed');
        }
      }
      if (!mounted || generation != _generation) return;
      setState(() {
        _status = status; _summary = summary; _catalogs = catalogs;
        _items = entries?['items'] as List? ?? [];
        _cursor = entries?['next_cursor'] as String?;
        _total = entries?['total'] as int? ?? 0;
      });
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted && generation == _generation) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    final generation = _generation;
    final cursor = _cursor;
    if (cursor == null || _more) return;
    setState(() => _more = true);
    try {
      final result = await _api.get('transactions', {..._filters, 'query': _search.text.trim(),
        if (_classification != null) 'classification': _classification, 'cursor': cursor});
      if (!mounted || generation != _generation) return;
      setState(() { _items.addAll(result['items'] as List); _cursor = result['next_cursor'] as String?; });
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted && generation == _generation) setState(() => _more = false);
    }
  }

  Future<void> _pair() async {
    setState(() => _action = true);
    try {
      final result = await _api.post('pairing');
      if (!mounted) return;
      await showDialog<void>(context: context, builder: (context) => AlertDialog(
        title: const Text('连接 Cashew'),
        content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('在新版 Cashew 的设置 → 米汝同步中填写以下地址和配对码。配对码 10 分钟内有效，只能使用一次。'),
          const SizedBox(height: 16), const Text('服务器地址'), SelectableText(widget.config.restBaseUrl),
          const SizedBox(height: 16), const Text('配对码'), SelectableText(result['code'] as String),
          const SizedBox(height: 12), const Text('重新配对后，旧设备的上传权限失效。已同步账本保留。'),
        ])),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('完成'))],
      ));
      if (mounted) await _reload();
    } catch (e) {
      if (mounted) setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted) setState(() => _action = false);
    }
  }

  Future<void> _confirmAction(String title, String message, String path) async {
    final accepted = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: Text(title), content: Text(message), actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('确认')),
      ],
    ));
    if (accepted != true || !mounted) return;
    setState(() => _action = true);
    try {
      await _api.post(path);
      if (mounted) await _reload();
    } catch (e) {
      if (mounted) setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted) setState(() => _action = false);
    }
  }

  Future<void> _pickDates() async {
    final picked = await showDateRangePicker(context: context, firstDate: DateTime(1900),
      lastDate: DateTime(2100), initialDateRange: _range);
    if (picked != null && mounted) { setState(() => _range = picked); await _reload(); }
  }

  static const _labels = {'income': '收入', 'expense': '支出', 'pending': '待支付',
    'skipped': '已跳过', 'transfer': '转账', 'adjustment': '余额调整', 'loan': '借贷'};

  void _details(Map<String, dynamic> e) {
    showDialog<void>(context: context, builder: (context) => AlertDialog(
      title: Text(e['title'] as String? ?? '账单详情'),
      content: SingleChildScrollView(child: SelectableText([
        '${e['currency']} ${e['amount']}', '${e['local_date']} · ${_labels[e['classification']] ?? ''}',
        '账户：${e['wallet']}', '分类：${e['category']}${e['subcategory'] == null ? '' : ' / ${e['subcategory']}'}',
        '备注：${e['note']}', '账单 ID：${e['id']}',
      ].join('\n\n'))),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('关闭'))],
    ));
  }

  Widget _select(String label, String? value, List<DropdownMenuItem<String>> items, ValueChanged<String?> changed) {
    return SizedBox(width: 170, child: DropdownButtonFormField<String>(
      key: ValueKey('$label:$value'), initialValue: value, isExpanded: true, decoration: InputDecoration(labelText: label),
      items: [const DropdownMenuItem<String>(value: null, child: Text('全部')), ...items],
      onChanged: _loading ? null : changed,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final pending = _status?['reconciliation'] as Map?;
    return Scaffold(
      appBar: AppBar(title: const Text('我的账本'), actions: [
        IconButton(tooltip: '刷新账本', onPressed: _loading ? null : _reload, icon: const Icon(Icons.refresh)),
        PopupMenuButton<String>(enabled: !_action, onSelected: (value) {
          if (value == 'pair') _pair();
          if (value == 'revoke') _confirmAction('断开 Cashew', '停止接收该设备的上传，保留已同步的账本。', 'revoke');
        }, itemBuilder: (_) => const [PopupMenuItem(value: 'pair', child: Text('连接 Cashew')),
          PopupMenuItem(value: 'revoke', child: Text('撤销上传权限'))]),
      ]),
      body: RefreshIndicator(onRefresh: _reload, child: ListView(padding: const EdgeInsets.all(16), children: [
        if (_loading) const LinearProgressIndicator(),
        if (_error.isNotEmpty) Card(child: Padding(padding: const EdgeInsets.all(16), child: Text(_error))),
        if (_status != null) Text(_status!['synced_at'] == null ? '尚未同步' :
          '数据更新于 ${DateTime.tryParse(_status!['synced_at'] as String)?.toLocal().toString().split('.').first ?? _status!['synced_at']} · ${_status!['transaction_count']} 笔'),
        const Text('Cashew 联网并在前台时自动上传；切回这里会检查更新，账本打开时每 10 秒检查一次。'),
        if (_status?['paired'] == false) const Text('上传权限已撤销，目前显示上一次同步的数据。'),
        if (pending != null) Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('需要核对：当前 ${_status?['transaction_count']} 笔，新账本 ${pending['transaction_count']} 笔。可能来自删除或恢复备份。'),
          TextButton(onPressed: _action ? null : () => _confirmAction('采用新账本',
            '将当前云端账本替换为 Cashew 提交的 ${pending['transaction_count']} 笔记录。请先核对手机账本。',
            'reconciliation/${Uri.encodeComponent(pending['snapshot_id'] as String)}/approve'), child: const Text('核对并采用')),
        ]))),
        if (!_loading && _status != null && _summary == null && _error.isEmpty) ...[
          const SizedBox(height: 48), const Icon(Icons.account_balance_wallet_outlined, size: 56),
          const Padding(padding: EdgeInsets.all(20), child: Text('连接 Cashew 后，这里会显示你的收支和每笔账单。', textAlign: TextAlign.center)),
          FilledButton(onPressed: _action ? null : _pair, child: const Text('连接 Cashew')),
        ],
        if (_summary != null) ...[
          const SizedBox(height: 20), Text(_range == null ? '本周实际收支' : '所选日期实际收支', style: Theme.of(context).textTheme.titleLarge),
          Text('${_summary!['start']} 至 ${_summary!['end_exclusive']}（结束日期不含）'),
          ...(_summary!['currencies'] as Map).entries.map((currency) => _summaryCard(currency.key.toString(), Map<String, dynamic>.from(currency.value as Map))),
          if ((_summary!['currencies'] as Map).isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('此区间没有符合实际收支口径的记录')),
          Text(_summary!['policy'] as String, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 24), Text('账单明细 · $_total 笔', style: Theme.of(context).textTheme.titleLarge),
          const Text('默认查看全部历史，包含转账、待支付和借贷。'),
          TextField(controller: _search, onSubmitted: (_) => _reload(), decoration: InputDecoration(
            hintText: '搜索标题、备注、分类', suffixIcon: IconButton(onPressed: _reload, icon: const Icon(Icons.search)))),
          Wrap(spacing: 12, children: [
            TextButton.icon(onPressed: _pickDates, icon: const Icon(Icons.date_range), label: Text(_range == null ? '选择日期' : '${_date(_range!.start)} — ${_date(_range!.end)}')),
            if (_range != null) TextButton(onPressed: () { setState(() => _range = null); _reload(); }, child: const Text('全部日期')),
            _select('账户', _wallet, (_catalogs?['wallets'] as List? ?? []).map((e) => DropdownMenuItem<String>(value: e['id'] as String, child: Text(e['name'] as String))).toList(), (v) { setState(() => _wallet = v); _reload(); }),
            _select('分类', _category, (_catalogs?['categories'] as List? ?? []).map((e) => DropdownMenuItem<String>(value: e['id'] as String, child: Text(e['name'] as String))).toList(), (v) { setState(() => _category = v); _reload(); }),
            _select('状态', _classification, _labels.entries.map((e) => DropdownMenuItem<String>(value: e.key, child: Text(e.value))).toList(), (v) { setState(() => _classification = v); _reload(); }),
          ]),
          const SizedBox(height: 16),
          ..._items.map((item) { final e = Map<String, dynamic>.from(item as Map); return ListTile(
            contentPadding: EdgeInsets.zero, title: Text(e['title'] as String),
            subtitle: Text('${e['local_date']} · ${e['category']} · ${_labels[e['classification']]}\n${e['wallet']}'),
            trailing: Text('${e['currency']} ${e['amount']}'), onTap: () => _details(e)); }),
          if (_cursor != null) TextButton(onPressed: _more || _loading ? null : _loadMore, child: Text(_more ? '加载中…' : '加载更多')),
          if (_items.isEmpty && !_loading) const Padding(padding: EdgeInsets.all(24), child: Text('没有符合筛选条件的账单')),
        ],
      ])),
    );
  }

  Widget _summaryCard(String currency, Map<String, dynamic> data) {
    final categories = (data['categories'] as Map).values.map((e) => Map<String, dynamic>.from(e as Map)).toList()
      ..sort((a, b) => (double.tryParse(b['amount'].toString()) ?? 0).compareTo(double.tryParse(a['amount'].toString()) ?? 0));
    final days = (data['days'] as Map).entries.toList()..sort((a, b) => a.key.toString().compareTo(b.key.toString()));
    return Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(currency, style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 8), Wrap(spacing: 20, runSpacing: 8, children: [
        Text('收入 ${data['income']}'), Text('支出 ${data['expense']}'), Text('结余 ${data['balance']}'),
      ]),
      if (categories.isNotEmpty) const Padding(padding: EdgeInsets.only(top: 12), child: Text('分类支出')),
      ...categories.map((e) => Text('${e['name']}  ${e['amount']}')),
      if (days.isNotEmpty) const Padding(padding: EdgeInsets.only(top: 12), child: Text('每日收支')),
      ...days.map((e) => Text('${e.key}   收入 ${e.value['income']}   支出 ${e.value['expense']}')),
    ])));
  }
}
