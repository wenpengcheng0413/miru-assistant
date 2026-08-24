import 'package:flutter/material.dart';

import 'chat_controller.dart';

class ConversationDrawer extends StatefulWidget {
  const ConversationDrawer({super.key, required this.controller});

  final ChatController controller;

  @override
  State<ConversationDrawer> createState() => _ConversationDrawerState();
}

class _ConversationDrawerState extends State<ConversationDrawer> {
  final _search = TextEditingController();

  ChatController get c => widget.controller;

  @override
  void initState() {
    super.initState();
    if (c.conversations.isEmpty) c.loadConversations();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: SafeArea(
        child: AnimatedBuilder(
          animation: c,
          builder: (context, _) => Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text('聊天记录', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                    ),
                    IconButton(
                      tooltip: '刷新',
                      onPressed: c.conversationsLoading ? null : c.loadConversations,
                      icon: const Icon(Icons.refresh),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: FilledButton.icon(
                  onPressed: c.conversationsLoading
                      ? null
                      : () async {
                          Navigator.of(context).pop();
                          await c.createConversation();
                        },
                  icon: const Icon(Icons.add),
                  label: const Text('新建对话'),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                child: TextField(
                  controller: _search,
                  onChanged: (value) => c.loadConversations(query: value),
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search),
                    hintText: '搜索聊天记录',
                    isDense: true,
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              if (c.conversationsError.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(c.conversationsError),
                ),
              Expanded(child: _list(context)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _list(BuildContext context) {
    if (c.conversationsLoading && c.conversations.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (c.conversations.isEmpty) {
      return const Center(child: Text('还没有历史对话'));
    }
    return ListView.builder(
      itemCount: c.conversations.length,
      itemBuilder: (context, index) {
        final item = c.conversations[index];
        final selected = item.id == c.config.lastConversationId;
        return ListTile(
          selected: selected,
          selectedTileColor: Theme.of(context).colorScheme.secondaryContainer,
          leading: const Icon(Icons.chat_bubble_outline),
          title: Text(item.displayTitle, maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: Text('${item.messageCount} 条消息${_dateLabel(item.updatedAt)}'),
          onTap: () async {
            Navigator.of(context).pop();
            await c.selectConversation(item.id);
          },
          trailing: PopupMenuButton<String>(
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

  Future<void> _act(BuildContext context, ConversationBrief item, String action) async {
    if (action == 'rename') {
      final edit = TextEditingController(text: item.displayTitle);
      final title = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('重命名对话'),
          content: TextField(controller: edit, autofocus: true, maxLength: 120),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(dialogContext, edit.text), child: const Text('保存')),
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
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('删除')),
        ],
      ),
    );
    if (confirmed == true) await c.deleteConversation(item.id);
  }
}
