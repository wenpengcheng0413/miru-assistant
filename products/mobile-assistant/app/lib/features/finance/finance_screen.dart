import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/config.dart';
import '../../core/design/miru_theme.dart';
import '../../core/design/miru_widgets.dart';
import 'finance_api.dart';

class FinanceScreen extends StatefulWidget {
  const FinanceScreen({super.key, required this.config, this.api});
  final AppConfig config;
  final FinanceApi? api;

  @override
  State<FinanceScreen> createState() => _FinanceScreenState();
}

class _FinanceScreenState extends State<FinanceScreen>
    with WidgetsBindingObserver {
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
    _refreshTimer =
        Timer.periodic(const Duration(seconds: 3), (_) => _checkForUpdates());
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
    if (!mounted ||
        _checking ||
        _loading ||
        _more ||
        _action ||
        (lifecycle != null && lifecycle != AppLifecycleState.resumed) ||
        ModalRoute.of(context)?.isCurrent == false) return;
    _checking = true;
    final generation = _generation;
    try {
      final status = await _api.get('status');
      if (!mounted || generation != _generation) return;
      if (_error.isNotEmpty ||
          status['revision'] != _status?['revision'] ||
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

  String _date(DateTime date) =>
      '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

  Map<String, dynamic> get _filters => {
        if (_range != null) 'start': _date(_range!.start),
        if (_range != null)
          'end': _date(_range!.end.add(const Duration(days: 1))),
        if (_wallet != null) 'wallet_id': _wallet,
        if (_category != null) 'category_id': _category,
      };

  Future<void> _reload() async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _more = false;
      _error = '';
      _summary = null;
      _items = [];
      _cursor = null;
    });
    try {
      final status = await _api.get('status');
      Map<String, dynamic>? summary, catalogs, entries;
      if ((status['revision'] as int? ?? 0) > 0) {
        final responses = await Future.wait([
          _api.get('summary', _filters),
          _api.get('catalogs'),
          _api.get('transactions', {
            ..._filters,
            'query': _search.text.trim(),
            if (_classification != null) 'classification': _classification
          }),
        ]);
        summary = responses[0];
        catalogs = responses[1];
        entries = responses[2];
        // Never present totals and rows from different snapshots as one view.
        if (summary['revision'] != entries['revision'] ||
            catalogs['revision'] != entries['revision'] ||
            status['revision'] != entries['revision']) {
          throw StateError('snapshot_changed');
        }
      }
      if (!mounted || generation != _generation) return;
      setState(() {
        _status = status;
        _summary = summary;
        _catalogs = catalogs;
        _items = entries?['items'] as List? ?? [];
        _cursor = entries?['next_cursor'] as String?;
        _total = entries?['total'] as int? ?? 0;
      });
    } catch (e) {
      if (mounted && generation == _generation)
        setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted && generation == _generation)
        setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    final generation = _generation;
    final cursor = _cursor;
    if (cursor == null || _more) return;
    setState(() => _more = true);
    try {
      final result = await _api.get('transactions', {
        ..._filters,
        'query': _search.text.trim(),
        if (_classification != null) 'classification': _classification,
        'cursor': cursor
      });
      if (!mounted || generation != _generation) return;
      setState(() {
        _items.addAll(result['items'] as List);
        _cursor = result['next_cursor'] as String?;
      });
    } catch (e) {
      if (mounted && generation == _generation)
        setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted && generation == _generation) setState(() => _more = false);
    }
  }

  Future<void> _pair() async {
    setState(() => _action = true);
    try {
      final result = await _api.post('pairing');
      if (!mounted) return;
      await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
                title: const Text('连接 Cashew'),
                content: SingleChildScrollView(
                    child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                      const Text(
                          '在新版 Cashew 的设置 → 米汝同步中填写以下地址和配对码。配对码 10 分钟内有效，只能使用一次。'),
                      const SizedBox(height: 16),
                      const Text('服务器地址'),
                      SelectableText(widget.config.restBaseUrl),
                      const SizedBox(height: 16),
                      const Text('配对码'),
                      SelectableText(result['code'] as String),
                      const SizedBox(height: 12),
                      const Text('重新配对后，旧设备的上传权限失效。已同步账本保留。'),
                    ])),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('完成'))
                ],
              ));
      if (mounted) await _reload();
    } catch (e) {
      if (mounted) setState(() => _error = FinanceApi.error(e));
    } finally {
      if (mounted) setState(() => _action = false);
    }
  }

  Future<void> _confirmAction(String title, String message, String path) async {
    final accepted = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text(title),
              content: Text(message),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('确认')),
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
    final picked = await showDateRangePicker(
        context: context,
        firstDate: DateTime(1900),
        lastDate: DateTime(2100),
        initialDateRange: _range);
    if (picked != null && mounted) {
      setState(() => _range = picked);
      await _reload();
    }
  }

  static const _labels = {
    'income': '收入',
    'expense': '支出',
    'pending': '待支付',
    'skipped': '已跳过',
    'transfer': '转账',
    'adjustment': '余额调整',
    'loan': '借贷'
  };

  void _details(Map<String, dynamic> e) {
    showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text(e['title'] as String? ?? '账单详情'),
              content: SingleChildScrollView(
                  child: SelectableText([
                '${e['currency']} ${e['amount']}',
                '${e['local_date']} · ${_labels[e['classification']] ?? ''}',
                '账户：${e['wallet']}',
                '分类：${e['category']}${e['subcategory'] == null ? '' : ' / ${e['subcategory']}'}',
                '备注：${e['note']}',
                '账单 ID：${e['id']}',
              ].join('\n\n'))),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('关闭'))
              ],
            ));
  }

  Widget _select(String label, String? value,
      List<DropdownMenuItem<String>> items, ValueChanged<String?> changed) {
    return DropdownButtonFormField<String>(
      key: ValueKey('$label:$value'),
      initialValue: value,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      items: [
        const DropdownMenuItem<String>(value: null, child: Text('全部')),
        ...items
      ],
      onChanged: _loading ? null : changed,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('我的账本'), actions: [
        IconButton(
            tooltip: '刷新账本',
            onPressed: _loading ? null : _reload,
            icon: const Icon(Icons.refresh)),
        PopupMenuButton<String>(
            tooltip: '账本连接',
            enabled: !_action,
            onSelected: (value) {
              if (value == 'pair') _pair();
              if (value == 'revoke')
                _confirmAction('断开 Cashew', '停止接收该设备的上传，保留已同步的账本。', 'revoke');
            },
            itemBuilder: (_) => const [
                  PopupMenuItem(value: 'pair', child: Text('连接 Cashew')),
                  PopupMenuItem(value: 'revoke', child: Text('撤销上传权限'))
                ]),
      ]),
      body: MiruPageBody(
          child: RefreshIndicator(
              onRefresh: _reload,
              child: ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(MiruSpacing.page),
                itemCount: _items.length + 2,
                itemBuilder: (context, index) {
                  if (index == 0) return _header(context);
                  if (index <= _items.length)
                    return _transactionCard(
                        Map<String, dynamic>.from(_items[index - 1] as Map));
                  return Padding(
                      padding:
                          const EdgeInsets.symmetric(vertical: MiruSpacing.lg),
                      child: Column(children: [
                        if (_cursor != null)
                          OutlinedButton.icon(
                              onPressed: _more || _loading ? null : _loadMore,
                              icon: const Icon(Icons.expand_more),
                              label: Text(_more ? '加载中…' : '加载更多')),
                        if (_summary != null && _items.isEmpty && !_loading)
                          const MiruEmptyState(
                              icon: Icons.search_off,
                              title: '没有符合筛选条件的账单',
                              description: '试试更换关键词、日期或分类。'),
                      ]));
                },
              ))),
    );
  }

  Widget _header(BuildContext context) {
    final pending = _status?['reconciliation'] as Map?;
    final colors = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('收支，清晰在眼前', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: 8),
      const Text('来自 Cashew 的账本，随时查看与核对。'),
      const SizedBox(height: MiruSpacing.lg),
      if (_loading)
        const Padding(
            padding: EdgeInsets.only(bottom: 16),
            child: LinearProgressIndicator()),
      if (_error.isNotEmpty)
        Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Card(
              color: colors.errorContainer,
              child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_error,
                            style: TextStyle(color: colors.onErrorContainer)),
                        TextButton.icon(
                            onPressed: _loading ? null : _reload,
                            icon: const Icon(Icons.refresh),
                            label: const Text('重试')),
                      ])),
            )),
      if (_status != null)
        Card(
            child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.sync_outlined, color: colors.primary),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                            Text(
                                _status!['synced_at'] == null
                                    ? '尚未同步'
                                    : '数据更新于 ${DateTime.tryParse(_status!['synced_at'] as String)?.toLocal().toString().split('.').first ?? _status!['synced_at']}',
                                style: Theme.of(context).textTheme.labelLarge),
                            if (_status!['transaction_count'] != null)
                              Text('${_status!['transaction_count']} 笔账单',
                                  style: Theme.of(context).textTheme.bodySmall),
                            const SizedBox(height: 4),
                            Text('Cashew 联网并在前台时会自动上传。打开账本后自动检查更新，也可以下拉刷新。',
                                style: Theme.of(context).textTheme.bodySmall),
                            if (_status?['paired'] == false &&
                                (_status?['revision'] as int? ?? 0) > 0)
                              const Padding(
                                  padding: EdgeInsets.only(top: 8),
                                  child: Text('上传权限已撤销，目前显示上一次同步的数据。')),
                          ])),
                    ]))),
      if (pending != null)
        Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Card(
              color: colors.tertiaryContainer,
              child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('有一份账本需要你核对',
                            style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        Text(
                            '当前 ${_status?['transaction_count']} 笔，新账本 ${pending['transaction_count']} 笔。可能来自删除或恢复备份。'),
                        const SizedBox(height: 8),
                        TextButton(
                            onPressed: _action
                                ? null
                                : () => _confirmAction(
                                    '采用新账本',
                                    '将当前云端账本替换为 Cashew 提交的 ${pending['transaction_count']} 笔记录。请先核对手机账本。',
                                    'reconciliation/${Uri.encodeComponent(pending['snapshot_id'] as String)}/approve'),
                            child: const Text('核对并采用')),
                      ])),
            )),
      if (!_loading && _status != null && _summary == null && _error.isEmpty)
        MiruEmptyState(
            icon: Icons.account_balance_wallet_outlined,
            title: '把账本连接起来',
            description: '连接 Cashew 后，这里会显示你的收支和每笔账单。',
            action: FilledButton.icon(
                onPressed: _action ? null : _pair,
                icon: const Icon(Icons.link),
                label: const Text('连接 Cashew'))),
      if (_summary != null) ...[
        const SizedBox(height: MiruSpacing.lg),
        Text(_range == null ? '本周实际收支' : '所选日期实际收支',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text('${_summary!['start']} 至 ${_summary!['end_exclusive']}（结束日期不含）',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        ...(_summary!['currencies'] as Map).entries.map((currency) =>
            _summaryCard(currency.key.toString(),
                Map<String, dynamic>.from(currency.value as Map))),
        if ((_summary!['currencies'] as Map).isEmpty)
          const Padding(
              padding: EdgeInsets.all(16), child: Text('此区间没有符合实际收支口径的记录')),
        const SizedBox(height: 8),
        Text(_summary!['policy'] as String,
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: MiruSpacing.xl),
        Text('账单明细 · $_total 笔', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text('默认查看全部历史，包含转账、待支付和借贷。',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        TextField(
            controller: _search,
            onSubmitted: (_) => _reload(),
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
                hintText: '搜索标题、备注、分类',
                suffixIcon: IconButton(
                    tooltip: '搜索账单',
                    onPressed: _loading ? null : _reload,
                    icon: const Icon(Icons.search)))),
        const SizedBox(height: 12),
        Card(
            child: ExpansionTile(
          leading: const Icon(Icons.tune),
          title: const Text('筛选账单'),
          subtitle: Text([
            if (_range != null) '日期',
            if (_wallet != null) '账户',
            if (_category != null) '分类',
            if (_classification != null) '状态'
          ].isEmpty
              ? '日期、账户、分类与状态'
              : '已选择 ${[
                  if (_range != null) '日期',
                  if (_wallet != null) '账户',
                  if (_category != null) '分类',
                  if (_classification != null) '状态'
                ].join(' · ')}'),
          childrenPadding: const EdgeInsets.all(16),
          children: [
            Wrap(spacing: 8, runSpacing: 8, children: [
              OutlinedButton.icon(
                  onPressed: _loading ? null : _pickDates,
                  icon: const Icon(Icons.date_range),
                  label: Text(_range == null
                      ? '选择日期'
                      : '${_date(_range!.start)} — ${_date(_range!.end)}')),
              if (_range != null)
                TextButton(
                    onPressed: () {
                      setState(() => _range = null);
                      _reload();
                    },
                    child: const Text('全部日期')),
            ]),
            const SizedBox(height: 12),
            LayoutBuilder(builder: (context, constraints) {
              final width = constraints.maxWidth < 500
                  ? constraints.maxWidth
                  : (constraints.maxWidth - 12) / 2;
              return Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(
                    width: width,
                    child: _select(
                        '账户',
                        _wallet,
                        (_catalogs?['wallets'] as List? ?? [])
                            .map((e) => DropdownMenuItem<String>(
                                value: e['id'] as String,
                                child: Text(e['name'] as String,
                                    overflow: TextOverflow.ellipsis)))
                            .toList(), (v) {
                      setState(() => _wallet = v);
                      _reload();
                    })),
                SizedBox(
                    width: width,
                    child: _select(
                        '分类',
                        _category,
                        (_catalogs?['categories'] as List? ?? [])
                            .map((e) => DropdownMenuItem<String>(
                                value: e['id'] as String,
                                child: Text(e['name'] as String,
                                    overflow: TextOverflow.ellipsis)))
                            .toList(), (v) {
                      setState(() => _category = v);
                      _reload();
                    })),
                SizedBox(
                    width: width,
                    child: _select(
                        '状态',
                        _classification,
                        _labels.entries
                            .map((e) => DropdownMenuItem<String>(
                                value: e.key, child: Text(e.value)))
                            .toList(), (v) {
                      setState(() => _classification = v);
                      _reload();
                    })),
              ]);
            }),
          ],
        )),
        const SizedBox(height: 16),
      ],
    ]);
  }

  Widget _transactionCard(Map<String, dynamic> entry) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Card(
            child: InkWell(
          borderRadius: BorderRadius.circular(MiruSpacing.radius),
          onTap: () => _details(entry),
          child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                              child: Text(entry['title'] as String,
                                  style:
                                      Theme.of(context).textTheme.titleMedium)),
                          const SizedBox(width: 8),
                          const Icon(Icons.chevron_right, size: 20),
                        ]),
                    const SizedBox(height: 6),
                    Text('${entry['currency']} ${entry['amount']}',
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            color: entry['classification'] == 'income'
                                ? colors.primary
                                : colors.onSurface)),
                    const SizedBox(height: 6),
                    Text(
                        '${entry['local_date']} · ${entry['category']} · ${_labels[entry['classification']] ?? entry['classification']}',
                        style: Theme.of(context).textTheme.bodySmall),
                    Text('${entry['wallet']}',
                        style: Theme.of(context).textTheme.bodySmall),
                  ])),
        )));
  }

  Widget _summaryCard(String currency, Map<String, dynamic> data) {
    final categories = (data['categories'] as Map)
        .values
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList()
      ..sort((a, b) => (double.tryParse(b['amount'].toString()) ?? 0)
          .compareTo(double.tryParse(a['amount'].toString()) ?? 0));
    final days = (data['days'] as Map).entries.toList()
      ..sort((a, b) => a.key.toString().compareTo(b.key.toString()));
    return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Card(
            child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(currency,
                          style: Theme.of(context).textTheme.labelLarge),
                      const SizedBox(height: 16),
                      Text('结余 ${data['balance']}',
                          style: Theme.of(context).textTheme.headlineMedium),
                      const SizedBox(height: 12),
                      Wrap(spacing: 24, runSpacing: 8, children: [
                        Text('收入 ${data['income']}',
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.primary)),
                        Text('支出 ${data['expense']}'),
                      ]),
                      if (categories.isNotEmpty || days.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        ExpansionTile(
                            tilePadding: EdgeInsets.zero,
                            title: const Text('查看收支分布'),
                            children: [
                              if (categories.isNotEmpty)
                                Align(
                                    alignment: Alignment.centerLeft,
                                    child: Text('分类支出',
                                        style: Theme.of(context)
                                            .textTheme
                                            .labelLarge)),
                              ...categories.map((e) => Padding(
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 6),
                                  child: Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Expanded(child: Text('${e['name']}')),
                                        const SizedBox(width: 12),
                                        Flexible(child: Text('${e['amount']}')),
                                      ]))),
                              if (days.isNotEmpty)
                                Padding(
                                    padding: const EdgeInsets.only(
                                        top: 16, bottom: 8),
                                    child: Align(
                                        alignment: Alignment.centerLeft,
                                        child: Text('每日收支',
                                            style: Theme.of(context)
                                                .textTheme
                                                .labelLarge))),
                              ...days.map((e) => Padding(
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 6),
                                  child: Align(
                                      alignment: Alignment.centerLeft,
                                      child: Text(
                                          '${e.key}   收入 ${e.value['income']}   支出 ${e.value['expense']}')))),
                            ]),
                      ],
                    ]))));
  }
}
