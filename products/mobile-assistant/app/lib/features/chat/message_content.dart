import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

/// Text stays selectable; code blocks scroll independently of the conversation.
class MessageContent extends StatelessWidget {
  const MessageContent({super.key, required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    // Plain text avoids reparsing/selection overhead for the common short reply.
    if (!RegExp(r'[#*`\[\]>_|\n]').hasMatch(text)) {
      return SelectableText(text, style: theme.textTheme.bodyLarge);
    }
    return MarkdownBody(
      data: text,
      selectable: true,
      shrinkWrap: true,
      softLineBreak: true,
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: theme.textTheme.bodyLarge,
        h1: theme.textTheme.headlineMedium,
        h2: theme.textTheme.titleLarge,
        h3: theme.textTheme.titleMedium,
        blockSpacing: 14,
        code: TextStyle(
            fontFamily: 'monospace',
            fontSize: 13,
            height: 1.6,
            color: colors.onSurface,
            backgroundColor: colors.surfaceContainerLow),
        codeblockPadding: const EdgeInsets.all(16),
        codeblockDecoration: BoxDecoration(
            color: colors.surfaceContainerLow,
            borderRadius: BorderRadius.circular(12)),
        blockquoteDecoration: BoxDecoration(
            color: colors.surfaceContainerLow,
            border: Border(left: BorderSide(color: colors.primary, width: 3))),
        tableCellsPadding: const EdgeInsets.all(8),
      ),
      // Generated image URLs are displayed as links rather than fetched eagerly.
      // The app's authenticated image attachments retain their dedicated viewer.
      imageBuilder: (uri, title, alt) => TextButton.icon(
        icon: const Icon(Icons.image_outlined),
        label: Text(alt?.isNotEmpty == true ? alt! : '图片链接'),
        onPressed: () => _showLink(context, uri.toString()),
      ),
      onTapLink: (label, href, title) {
        if (href != null) _showLink(context, href);
      },
    );
  }

  Future<void> _showLink(BuildContext context, String href) => showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('链接'),
          content: SelectableText(href),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('关闭')),
            FilledButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: href));
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context)
                      .showSnackBar(const SnackBar(content: Text('链接已复制')));
                },
                icon: const Icon(Icons.copy_outlined),
                label: const Text('复制链接')),
          ],
        ),
      );
}
