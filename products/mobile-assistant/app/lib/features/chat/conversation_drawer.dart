import 'dart:async';

import 'package:flutter/material.dart';
import '../../core/design/miru_widgets.dart';

import 'chat_controller.dart';
import '../finance/finance_screen.dart';

class ConversationDrawer extends StatefulWidget {
  const ConversationDrawer(
      {super.key,
      required this.controller,
      this.embedded = false,
      this.onSettings});

  final ChatController controller;
  final bool embedded;
  final VoidCallback? onSettings;

  @override
  State<ConversationDrawer> createState() => _ConversationDrawerState();
}

class _ConversationDrawerState extends State<ConversationDrawer> {
  final _search = TextEditingController();
  Timer? _debounce;

  ChatController get c => widget.controller;

  @override
  void initState() {
    super.initState();
    _search.text = c.conversationQuery;
    if (c.conversations.isEmpty && c.wsConnected) c.loadConversations();
  }

  @override
  void dispose() {
    _search.dispose();
    _debounce?.cancel();
    super.dispose();
  }

  void _close() {
    if (!widget.embedded) Navigator.of(context).pop();
  }

  void _searchChanged(String value) {
    _debounce?.cancel();
    setState(() {});
    _debounce = Timer(const Duration(milliseconds: 300),
        () => c.loadConversations(query: value));
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final content = SafeArea(
        child: AnimatedBuilder(
            animation: c,
            builder: (context, _) => Column(children: [
                  Padding(
                      padding: const EdgeInsets.fromLTRB(20, 20, 12, 20),
                      child: Row(children: [
                        const MiruBrandMark(size: 36),
                        const SizedBox(width: 12),
                        Expanded(
                            child: Text('你的 Miru',
                                style: Theme.of(context).textTheme.titleLarge)),
                        if (!widget.embedded)
                          IconButton(
                              tooltip: '关闭导航',
                              onPressed: _close,
                              icon: const Icon(Icons.close_rounded)),
                      ])),
                  Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: SizedBox(
                          width: double.infinity,
                          child: FilledButton.icon(
                            onPressed: c.attachmentUploading
                                ? null
                                : () {
                                    _close();
                                    c.createConversation();
                                  },
                            icon: const Icon(Icons.add_rounded),
                            label: const Text('新建对话'),
                          ))),
                  const SizedBox(height: 12),
                  Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: ListTile(
                        leading:
                            const Icon(Icons.account_balance_wallet_outlined),
                        title: const Text('我的账本'),
                        subtitle: const Text('收支与明细'),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                        onTap: () {
                          final navigator = Navigator.of(context);
                          _close();
                          navigator.push(MaterialPageRoute<void>(
                              builder: (_) => FinanceScreen(config: c.config)));
                        },
                      )),
                  Padding(
                      padding: const EdgeInsets.fromLTRB(20, 12, 8, 4),
                      child: Row(children: [
                        Expanded(
                            child: Text('最近对话',
                                style: Theme.of(context)
                                    .textTheme
                                    .labelLarge
                                    ?.copyWith(
                                        color: colors.onSurfaceVariant))),
                        IconButton(
                            tooltip: '刷新',
                            onPressed: c.conversationsLoading
                                ? null
                                : () =>
                                    c.loadConversations(query: _search.text),
                            icon: const Icon(Icons.refresh_rounded, size: 20)),
                      ])),
                  Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: TextField(
                        controller: _search,
                        onChanged: _searchChanged,
                        decoration: InputDecoration(
                          prefixIcon:
                              const Icon(Icons.search_rounded, size: 20),
                          hintText: '搜索聊天记录',
                          isDense: true,
                          suffixIcon: _search.text.isEmpty
                              ? null
                              : IconButton(
                                  tooltip: '清除搜索',
                                  icon:
                                      const Icon(Icons.close_rounded, size: 18),
                                  onPressed: () {
                                    _search.clear();
                                    _searchChanged('');
                                  }),
                        ),
                      )),
                  if (c.conversationsLoading)
                    const Padding(
                        padding:
                            EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        child: LinearProgressIndicator(minHeight: 2)),
                  if (c.conversationsError.isNotEmpty)
                    Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(children: [
                          Text(c.conversationsError,
                              style: TextStyle(color: colors.error)),
                          TextButton(
                              onPressed: () =>
                                  c.loadConversations(query: _search.text),
                              child: const Text('重试')),
                        ])),
                  Expanded(child: _list(context)),
                  const Divider(),
                  ListTile(
                      leading: const Icon(Icons.tune_rounded),
                      title: const Text('设置与偏好'),
                      onTap: widget.onSettings == null
                          ? null
                          : () {
                              _close();
                              widget.onSettings!();
                            }),
                  Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                      child: Row(children: [
                        Icon(
                            c.wsConnected
                                ? Icons.cloud_done_outlined
                                : Icons.cloud_off_outlined,
                            size: 14,
                            color: colors.onSurfaceVariant),
                        const SizedBox(width: 8),
                        Expanded(
                            child: Text(c.wsConnected ? '已连接 · 随时开始' : '连接待恢复',
                                style: Theme.of(context).textTheme.bodySmall)),
                      ])),
                ])));
    return widget.embedded
        ? Material(color: colors.surfaceContainerLow, child: content)
        : Drawer(child: content);
  }

  Widget _list(BuildContext context) {
    if (c.conversationsLoading && c.conversations.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (c.conversations.isEmpty) {
      return Center(
          child: SingleChildScrollView(
              child: MiruEmptyState(
        icon: _search.text.isEmpty
            ? Icons.forum_outlined
            : Icons.search_off_rounded,
        title: _search.text.isEmpty ? '还没有历史对话' : '没有找到相关对话',
        description: _search.text.isEmpty ? '从一个问题开始，之后可以在这里继续。' : '换个关键词试试看。',
      )));
    }
    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      itemCount: c.conversations.length,
      itemBuilder: (context, index) {
        final item = c.conversations[index];
        final selected = item.id == c.config.lastConversationId;
        return ListTile(
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          selected: selected,
          selectedTileColor: Theme.of(context).colorScheme.secondaryContainer,
          leading: const Icon(Icons.chat_bubble_outline),
          title: Text(item.displayTitle,
              maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle:
              Text('${item.messageCount} 条消息${_dateLabel(item.updatedAt)}'),
          onTap: () async {
            if (!c.wsConnected) {
              ScaffoldMessenger.of(context)
                  .showSnackBar(const SnackBar(content: Text('连接恢复后即可打开历史对话')));
              return;
            }
            _close();
            await c.selectConversation(item.id);
          },
          trailing: PopupMenuButton<String>(
            tooltip: '对话操作',
            onSelected: (action) => _act(context, item, action),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'rename', child: Text('重命名')),
              PopupMenuItem(value: 'delete', child: Text('删除')),
            ],
          ),
        );
      },
    );
  }

  String _dateLabel(DateTime? value) {
    if (value == null) return '';
    final local = value.toLocal();
    return ' · ${local.month}/${local.day} ${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _act(
      BuildContext context, ConversationBrief item, String action) async {
    if (action == 'rename') {
      final edit = TextEditingController(text: item.displayTitle);
      final title = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('重命名对话'),
          content: TextField(controller: edit, autofocus: true, maxLength: 120),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(dialogContext, edit.text),
                child: const Text('保存')),
          ],
        ),
      );
      edit.dispose();
      if (title != null) await c.renameConversation(item.id, title);
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删除这段对话？'),
        content: const Text('聊天内容和关联附件将一起删除，无法恢复。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed == true) await c.deleteConversation(item.id);
  }
}
