import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/audio/player_service.dart';
import '../../core/design/miru_theme.dart';
import '../../core/design/miru_widgets.dart';
import 'chat_controller.dart';
import 'conversation_drawer.dart';
import 'message_content.dart';
import '../finance/finance_screen.dart';
import '../settings/settings_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.controller, required this.player});

  final ChatController controller;
  final PlayerService player;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  static const double _voiceCancelDistance = 56;

  final TextEditingController _textCtrl = TextEditingController();
  final ImagePicker _imagePicker = ImagePicker();
  final ScrollController _scroll = ScrollController();
  final FocusNode _inputFocus = FocusNode();
  bool _sending = false;
  bool _awayFromLatest = false;
  int _conversationVersion = -1;
  bool _holding = false;
  bool _cancelingVoice = false;
  Offset? _voicePointerStart;
  int _syncedInputVersion = -1;

  ChatController get c => widget.controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _textCtrl.dispose();
    _inputFocus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 切到后台时若还在录音，立刻停止——否则麦克风一直开着，
    // 环境噪声会被 STT 幻觉成句号/英文单词自动发出去
    if (state != AppLifecycleState.resumed && c.phase == ChatPhase.listening) {
      _holding = false;
      _cancelingVoice = false;
      _voicePointerStart = null;
      c.cancelListening();
    }
    if (state == AppLifecycleState.resumed) c.onAppResumed();
  }

  void _onScroll() {
    final away = _scroll.hasClients && _scroll.offset > 120;
    if (away != _awayFromLatest && mounted)
      setState(() => _awayFromLatest = away);
  }

  void _scrollToLatest() {
    if (_scroll.hasClients) {
      if (MediaQuery.disableAnimationsOf(context)) {
        _scroll.jumpTo(0);
      } else {
        _scroll.animateTo(0,
            duration: MiruMotion.duration(context), curve: Curves.easeOut);
      }
    }
  }

  /// 语音识别文本 → 预填输入框（可修改后发送）；预填被清空时同步清空输入框
  void _syncPendingInput() {
    if (c.pendingInputVersion == _syncedInputVersion) return;
    _syncedInputVersion = c.pendingInputVersion;
    if (c.pendingInput.isNotEmpty) {
      _textCtrl.text = c.pendingInput;
      _textCtrl.selection = TextSelection.collapsed(
        offset: _textCtrl.text.length,
      );
    } else {
      _textCtrl.clear();
    }
  }

  Future<void> _send() async {
    if (!_textCtrl.value.composing.isCollapsed) return;
    if (_sending || c.phase != ChatPhase.idle || c.attachmentUploading) return;
    final text = _textCtrl.text.trim();
    if (text.isEmpty) return;
    _sending = true;
    try {
      if (await c.sendText(text)) {
        if (mounted && _textCtrl.text.trim() == text) _textCtrl.clear();
        if (mounted) _scrollToLatest();
      }
    } finally {
      _sending = false;
    }
  }

  Future<void> _openRemoteImage(RemoteImage item) async {
    final url = '${c.config.restBaseUrl}${item.downloadPath}';
    await showDialog<void>(
      context: context,
      useSafeArea: false,
      builder: (context) => Dialog.fullscreen(
        child: Scaffold(
          appBar: AppBar(
            title: const Text('微信原图'),
            leading: IconButton(
              tooltip: '关闭',
              icon: const Icon(Icons.close),
              onPressed: () => Navigator.pop(context),
            ),
          ),
          backgroundColor: Colors.black,
          body: Center(
            child: InteractiveViewer(
              minScale: 0.8,
              maxScale: 6,
              child: Image.network(
                url,
                headers: {'Authorization': 'Bearer ${c.config.token}'},
                fit: BoxFit.contain,
                loadingBuilder: (context, child, progress) => progress == null
                    ? child
                    : const CircularProgressIndicator(),
                errorBuilder: (context, error, stackTrace) => const Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    '原图已过期或暂时无法加载，请重新向 Miru 请求这张图片。',
                    style: TextStyle(color: Colors.white),
                    textAlign: TextAlign.center,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _pickImage(ImageSource source) async {
    try {
      final image =
          await _imagePicker.pickImage(source: source, imageQuality: 100);
      if (image != null && mounted) {
        await c.uploadAttachment(image.path, filename: image.name);
      }
    } catch (_) {
      _pickerError('暂时无法打开照片，请检查相机或相册权限。');
    }
  }

  Future<void> _pickFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const [
          'jpg',
          'jpeg',
          'png',
          'gif',
          'webp',
          'pdf',
          'docx',
          'xlsx',
          'xls',
          'csv',
          'pptx',
          'txt',
          'md',
        ],
      );
      final file = (result != null && result.files.isNotEmpty)
          ? result.files.first
          : null;
      if (file?.path != null && mounted) {
        await c.uploadAttachment(file!.path!, filename: file.name);
      }
    } catch (_) {
      _pickerError('暂时无法选择文件，请重试。');
    }
  }

  void _pickerError(String message) {
    if (mounted)
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
  }

  /// 手指抬起：上滑超过阈值则放弃，否则结束并提交录音。
  void _finishHold() {
    if (!_holding) return;
    final shouldCancel = _cancelingVoice;
    _holding = false;
    _cancelingVoice = false;
    _voicePointerStart = null;
    HapticFeedback.lightImpact();
    if (shouldCancel) {
      c.cancelListening();
    } else {
      c.stopListening();
    }
  }

  /// 系统抢占手势时必须放弃录音，不能把不完整语音误提交。
  void _cancelHold() {
    if (!_holding) return;
    _holding = false;
    _cancelingVoice = false;
    _voicePointerStart = null;
    c.cancelListening();
  }

  void _updateVoiceDrag(PointerMoveEvent event) {
    if (!_holding || _voicePointerStart == null) return;
    final next =
        event.position.dy <= _voicePointerStart!.dy - _voiceCancelDistance;
    if (next == _cancelingVoice) return;
    setState(() => _cancelingVoice = next);
    if (next) HapticFeedback.selectionClick();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: c,
      builder: (context, _) {
        _syncPendingInput();
        if (_conversationVersion != c.conversationVersion) {
          _conversationVersion = c.conversationVersion;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && _scroll.hasClients) _scroll.jumpTo(0);
          });
        }
        return LayoutBuilder(builder: (context, constraints) {
          final wide = constraints.maxWidth >= MiruSpacing.wideBreakpoint;
          final page = Scaffold(
            drawer: wide
                ? null
                : ConversationDrawer(
                    controller: c, onSettings: () => _openSettings(context)),
            appBar: AppBar(
              leading: wide
                  ? null
                  : Builder(
                      builder: (context) => IconButton(
                            tooltip: '打开导航',
                            onPressed: () => Scaffold.of(context).openDrawer(),
                            icon: const Icon(Icons.menu_rounded),
                          )),
              title: Row(mainAxisSize: MainAxisSize.min, children: [
                const MiruBrandMark(size: 30),
                const SizedBox(width: 10),
                const Flexible(
                    child: Text('Miru', overflow: TextOverflow.ellipsis)),
              ]),
              actions: [
                IconButton(
                  tooltip: c.config.ttsEnabled ? '关闭语音回复' : '开启语音回复',
                  icon: Icon(c.config.ttsEnabled
                      ? Icons.volume_up_outlined
                      : Icons.volume_off_outlined),
                  onPressed: c.phase == ChatPhase.idle ? c.toggleTts : null,
                ),
                IconButton(
                    tooltip: '新对话',
                    onPressed:
                        c.attachmentUploading ? null : c.createConversation,
                    icon: const Icon(Icons.edit_square)),
                IconButton(
                    tooltip: '设置',
                    icon: const Icon(Icons.tune_rounded),
                    onPressed: () => _openSettings(context)),
                const SizedBox(width: 4),
              ],
            ),
            body: SafeArea(
                top: false,
                bottom: false,
                child: Column(children: [
                  if (!c.wsConnected) _offlineBanner(context),
                  if (c.wsConnected && c.systemStatus != null)
                    _systemStatusBanner(context),
                  if (c.historyLoading)
                    const LinearProgressIndicator(
                        minHeight: 2, semanticsLabel: '正在加载对话'),
                  if (c.historyError.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      child: Row(children: [
                        Expanded(
                            child: Text(c.historyError,
                                style: Theme.of(context).textTheme.bodySmall)),
                        TextButton(
                            onPressed: c.retryHistory, child: const Text('重试'))
                      ]),
                    ),
                  Expanded(child: LayoutBuilder(builder: (context, bounds) {
                    final gutter =
                        ((bounds.maxWidth - MiruSpacing.contentWidth) / 2)
                            .clamp(16.0, double.infinity);
                    return Stack(children: [
                      Positioned.fill(
                          child: GestureDetector(
                        behavior: HitTestBehavior.translucent,
                        onTap: () => FocusScope.of(context).unfocus(),
                        child: ListView.builder(
                          key: const ValueKey('conversation-messages'),
                          controller: _scroll,
                          reverse: true,
                          keyboardDismissBehavior:
                              ScrollViewKeyboardDismissBehavior.onDrag,
                          padding: EdgeInsets.fromLTRB(gutter, 16, gutter, 20),
                          itemCount: c.lines.length + 1,
                          itemBuilder: (context, i) => i == 0
                              ? _liveArea()
                              : _messageBubble(c.lines[c.lines.length - i]),
                        ),
                      )),
                      if (c.lines.isEmpty &&
                          c.miruText.isEmpty &&
                          c.phase == ChatPhase.idle &&
                          !c.historyLoading)
                        Positioned.fill(child: _welcome()),
                      if (_awayFromLatest)
                        Positioned(
                            right: gutter,
                            bottom: 12,
                            child: FloatingActionButton.small(
                              heroTag: 'latest-message',
                              tooltip: '回到最新消息',
                              onPressed: _scrollToLatest,
                              child: const Icon(Icons.arrow_downward),
                            )),
                    ]);
                  })),
                  MiruPageBody(child: _bottomBar(context)),
                ])),
          );
          if (!wide) return page;
          return Row(children: [
            SizedBox(
                width: 288,
                child: ConversationDrawer(
                    controller: c,
                    embedded: true,
                    onSettings: () => _openSettings(context))),
            const VerticalDivider(width: 1),
            Expanded(child: page),
          ]);
        });
      },
    );
  }

  Widget _welcome() {
    final theme = Theme.of(context);
    return LayoutBuilder(
        builder: (context, bounds) => SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                    minHeight:
                        (bounds.maxHeight - 48).clamp(0.0, double.infinity)),
                child: Center(
                    child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 440),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const MiruBrandMark(size: 56),
                            const SizedBox(height: 24),
                            Text('把想法说给 Miru',
                                style: theme.textTheme.headlineLarge),
                            const SizedBox(height: 10),
                            Text('一起理清思路，也照顾好日常。',
                                style: theme.textTheme.bodyLarge?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant)),
                            const SizedBox(height: 28),
                            _starter(Icons.lightbulb_outline_rounded, '一起想一想',
                                '帮我梳理一下这个想法：'),
                            const SizedBox(height: 10),
                            _starter(Icons.description_outlined, '读懂一份资料',
                                '请帮我总结这份资料的重点：'),
                            const SizedBox(height: 10),
                            Card(
                                child: ListTile(
                              leading: Icon(
                                  Icons.account_balance_wallet_outlined,
                                  color: theme.colorScheme.primary),
                              title: const Text('看看我的账本'),
                              trailing: const Icon(Icons.arrow_forward_rounded,
                                  size: 18),
                              onTap: () => Navigator.push(
                                  context,
                                  MaterialPageRoute<void>(
                                      builder: (_) =>
                                          FinanceScreen(config: c.config))),
                            )),
                            const SizedBox(height: 20),
                            Text('输入文字，或按住下方按钮说话',
                                style: theme.textTheme.bodySmall),
                          ],
                        ))),
              ),
            ));
  }

  Widget _starter(IconData icon, String title, String prompt) => Card(
        child: ListTile(
          leading: Icon(icon, color: Theme.of(context).colorScheme.primary),
          title: Text(title),
          trailing: const Icon(Icons.north_west_rounded, size: 18),
          onTap: () {
            _textCtrl.text = prompt;
            _textCtrl.selection =
                TextSelection.collapsed(offset: prompt.length);
            _inputFocus.requestFocus();
          },
        ),
      );

  /// 未连接服务器时的顶部横幅：点按直接进设置
  Widget _offlineBanner(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.errorContainer,
      child: InkWell(
        onTap: () => _openSettings(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Icon(Icons.cloud_off, size: 16, color: scheme.onErrorContainer),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '未连接 · ${c.wsStatus.trim().isEmpty ? '自动重连中' : c.wsStatus.trim()} · 点此检查设置',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    color: scheme.onErrorContainer,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 识别中的半透明字 + 流式回答字幕 + 工具状态
  Widget _liveArea() {
    final parts = <Widget>[];
    if (c.partialText.isNotEmpty) {
      parts.add(
        Text(
          c.partialText,
          style: TextStyle(
            fontSize: 15,
            color: Theme.of(
              context,
            ).colorScheme.onSurface.withValues(alpha: 0.45),
          ),
        ),
      );
    }
    if (c.miruText.isNotEmpty) {
      parts.add(MessageContent(text: c.miruText));
    }
    if (c.toolStatus.isNotEmpty) {
      parts.add(
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            children: [
              const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              const SizedBox(width: 8),
              Expanded(
                  child: Text(c.toolStatus,
                      style: Theme.of(context).textTheme.bodySmall)),
            ],
          ),
        ),
      );
    }
    if (c.activeProcessSteps.isNotEmpty) {
      parts.add(
        _processPanel(
          c.activeProcessSteps,
          expanded: c.activeProcessExpanded,
          onToggle: c.toggleActiveProcessExpanded,
        ),
      );
    }
    if (c.phase == ChatPhase.thinking &&
        c.miruText.isEmpty &&
        c.toolStatus.isEmpty) {
      parts.add(
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            children: [
              const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              const SizedBox(width: 8),
              Expanded(
                  child: Text(
                c.progressStatus.isEmpty ? '正在处理…' : c.progressStatus,
                style: TextStyle(
                  fontSize: 13,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              )),
            ],
          ),
        ),
      );
    }
    if (parts.isEmpty) return const SizedBox.shrink();
    return Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(children: [
                  const MiruBrandMark(size: 24),
                  const SizedBox(width: 8),
                  Text('Miru', style: Theme.of(context).textTheme.labelLarge)
                ])),
            ...parts,
          ],
        ));
  }

  Widget _systemStatusBanner(BuildContext context) {
    final status = c.systemStatus!;
    final scheme = Theme.of(context).colorScheme;
    final stale = c.systemStatusStale;
    return Material(
      color: stale ? scheme.tertiaryContainer : scheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
        child: Row(
          children: [
            Icon(
              status.cloudOnline ? Icons.cloud_done_outlined : Icons.cloud_off,
              size: 16,
              color: status.cloudOnline ? scheme.primary : scheme.error,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                '${status.cloudOnline ? '云端已连接' : '云端暂不可用'} · ${status.homeNodeOnline ? '家庭节点在线' : '家庭节点未连接'}'
                '${stale ? ' · 状态待刷新' : ''}'
                '${c.lastCost > 0 ? ' · 本轮 ¥${c.lastCost.toStringAsFixed(3)}' : ''}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messageBubble(ChatLine line) {
    final scheme = Theme.of(context).colorScheme;
    final isUser = line.kind == 'user';
    final isNote = line.kind == 'note';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: FractionallySizedBox(
          widthFactor: isUser ? .9 : 1,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 10),
            padding: EdgeInsets.all(isUser || isNote ? 16 : 4),
            decoration: BoxDecoration(
              color: isUser
                  ? scheme.primaryContainer
                  : isNote
                      ? scheme.surfaceContainerHighest
                      : Colors.transparent,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (!isNote)
                  Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(children: [
                        if (!isUser) ...[
                          const MiruBrandMark(size: 24),
                          const SizedBox(width: 8)
                        ],
                        Text(isUser ? '你' : 'Miru',
                            style: Theme.of(context)
                                .textTheme
                                .labelMedium
                                ?.copyWith(color: scheme.onSurfaceVariant)),
                      ])),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: line.text.isEmpty
                          ? const SizedBox.shrink()
                          : isUser || isNote
                              ? SelectableText(line.text,
                                  style: Theme.of(context).textTheme.bodyLarge)
                              : MessageContent(text: line.text),
                    ),
                  ],
                ),
                if (line.images.isNotEmpty)
                  ...line.images.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(top: 8, right: 6),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          GestureDetector(
                            onTap: () => _openRemoteImage(item),
                            child: Stack(
                              alignment: Alignment.bottomRight,
                              children: [
                                ClipRRect(
                                  borderRadius: BorderRadius.circular(10),
                                  child: Image.network(
                                    '${c.config.restBaseUrl}${item.downloadPath}',
                                    headers: {
                                      'Authorization':
                                          'Bearer ${c.config.token}',
                                    },
                                    fit: BoxFit.contain,
                                    loadingBuilder:
                                        (context, child, progress) =>
                                            progress == null
                                                ? child
                                                : const SizedBox(
                                                    height: 120,
                                                    child: Center(
                                                      child:
                                                          CircularProgressIndicator(),
                                                    ),
                                                  ),
                                    errorBuilder:
                                        (context, error, stackTrace) =>
                                            const SizedBox(
                                      height: 90,
                                      child: Center(
                                        child: Text('原图已过期或暂时无法加载'),
                                      ),
                                    ),
                                  ),
                                ),
                                const Padding(
                                  padding: EdgeInsets.all(8),
                                  child: CircleAvatar(
                                    radius: 16,
                                    child: Icon(Icons.open_in_full, size: 17),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          if (item.sender.isNotEmpty ||
                              item.messageTime.isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(
                                [item.sender, item.messageTime]
                                    .where((value) => value.isNotEmpty)
                                    .join(' · '),
                                style: TextStyle(
                                  fontSize: 11,
                                  color: scheme.onSurfaceVariant,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                if (line.kind == 'miru' && line.steps.isNotEmpty)
                  _processPanel(
                    line.steps,
                    expanded: line.processExpanded,
                    onToggle: () {
                      line.processExpanded = !line.processExpanded;
                      setState(() {});
                    },
                  ),
                if (line.kind == 'miru' && line.stats != null)
                  _completionMeta(line.stats!),
                if (isUser || line.kind == 'miru')
                  Align(
                      alignment: Alignment.centerLeft,
                      child: IconButton(
                        tooltip: '复制',
                        iconSize: 18,
                        icon: const Icon(Icons.copy_outlined),
                        onPressed: () => _copyText(line.text),
                      )),
              ],
            ),
          )),
    );
  }

  Widget _completionMeta(TurnStats stats) {
    final completed = stats.status == 'completed';
    final seconds = stats.durationMs <= 0 ? 0 : stats.durationMs / 1000;
    final parts = <String>[
      completed
          ? '已完成'
          : stats.status == 'interrupted'
              ? '已停止'
              : '本轮未完成',
      if (stats.durationMs > 0) '${seconds.toStringAsFixed(1)} 秒',
      if (stats.completionTokens > 0) '生成 ${stats.completionTokens} tokens',
      if (stats.costRmb > 0) '¥${stats.costRmb.toStringAsFixed(3)}',
    ];
    return Padding(
      padding: const EdgeInsets.only(top: 6, right: 4),
      child: Row(
        children: [
          Icon(
            completed ? Icons.check_circle_outline : Icons.error_outline,
            size: 14,
            color: completed
                ? Theme.of(context).colorScheme.primary
                : Theme.of(context).colorScheme.error,
          ),
          const SizedBox(width: 5),
          Expanded(
            child: Text(
              parts.join(' · '),
              style: TextStyle(
                fontSize: 11,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _processPanel(
    List<ProcessStep> steps, {
    required bool expanded,
    required VoidCallback onToggle,
  }) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 8, right: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: onToggle,
            borderRadius: BorderRadius.circular(6),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    expanded
                        ? Icons.keyboard_arrow_down
                        : Icons.keyboard_arrow_right,
                    size: 18,
                  ),
                  Flexible(
                      child: Text(
                    '处理过程（${steps.length} 个步骤）',
                    style: TextStyle(
                      fontSize: 12,
                      color: scheme.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
                    ),
                  )),
                  IconButton(
                    tooltip: '复制处理过程',
                    visualDensity: VisualDensity.compact,
                    iconSize: 16,
                    icon: const Icon(Icons.copy_outlined),
                    onPressed: () => _copyText(_processText(steps)),
                  ),
                ],
              ),
            ),
          ),
          if (expanded)
            ...steps.map(
              (step) => Padding(
                padding: const EdgeInsets.only(left: 8, top: 3),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      step.status == 'error'
                          ? Icons.error_outline
                          : step.status == 'running'
                              ? Icons.more_horiz
                              : Icons.check,
                      size: 14,
                      color: step.status == 'error'
                          ? scheme.error
                          : scheme.primary,
                    ),
                    const SizedBox(width: 5),
                    Expanded(
                      child: SelectableText(
                        step.detail.isEmpty
                            ? step.title
                            : '${step.title}：${step.detail}',
                        style: TextStyle(
                          fontSize: 12,
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '复制步骤',
                      visualDensity: VisualDensity.compact,
                      iconSize: 16,
                      icon: const Icon(Icons.copy_outlined),
                      onPressed: () => _copyText(
                        step.detail.isEmpty
                            ? step.title
                            : '${step.title}：${step.detail}',
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  void _copyText(String text) {
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('已复制'),
        duration: Duration(milliseconds: 900),
      ),
    );
  }

  String _processText(List<ProcessStep> steps) => steps
      .map(
        (step) =>
            step.detail.isEmpty ? step.title : '${step.title}：${step.detail}',
      )
      .join('\n');

  Widget _bottomBar(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final busy = c.phase == ChatPhase.thinking || c.phase == ChatPhase.speaking;
    final listening = c.phase == ChatPhase.listening;
    return SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (c.pendingAttachments.isNotEmpty || c.attachmentUploading)
              SizedBox(
                height: 52,
                child: ListView(scrollDirection: Axis.horizontal, children: [
                  ...c.pendingAttachments.map((item) => Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: InputChip(
                          avatar: Icon(
                              item.kind == 'image'
                                  ? Icons.image_outlined
                                  : Icons.attach_file,
                              size: 18),
                          label: ConstrainedBox(
                              constraints: const BoxConstraints(maxWidth: 160),
                              child: Text(item.filename,
                                  overflow: TextOverflow.ellipsis)),
                          onDeleted: listening
                              ? null
                              : () => c.removePendingAttachment(item.id),
                        ),
                      )),
                  if (c.attachmentUploading)
                    const Chip(
                        label: Text('上传中…'),
                        avatar: SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2))),
                ]),
              ),
            DecoratedBox(
              decoration: BoxDecoration(
                  color: colors.surfaceContainerLowest,
                  border: Border.all(
                      color:
                          listening ? colors.primary : colors.outlineVariant),
                  borderRadius: BorderRadius.circular(24)),
              child: Padding(
                  padding: const EdgeInsets.fromLTRB(6, 6, 6, 4),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    CallbackShortcuts(
                      bindings: {
                        const SingleActivator(LogicalKeyboardKey.enter,
                            control: true): _send,
                        const SingleActivator(LogicalKeyboardKey.enter,
                            meta: true): _send
                      },
                      child: TextField(
                        key: const ValueKey('chat-input'),
                        controller: _textCtrl,
                        focusNode: _inputFocus,
                        minLines: 1,
                        maxLines: 5,
                        textInputAction: TextInputAction.newline,
                        keyboardType: TextInputType.multiline,
                        decoration: const InputDecoration(
                            hintText: '想聊些什么？',
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            filled: false,
                            contentPadding:
                                EdgeInsets.fromLTRB(12, 10, 12, 10)),
                      ),
                    ),
                    Row(children: [
                      PopupMenuButton<String>(
                        tooltip: '添加图片或文件',
                        enabled: c.wsConnected &&
                            !busy &&
                            !listening &&
                            !c.attachmentUploading,
                        icon: const Icon(Icons.add_rounded),
                        onSelected: (value) {
                          if (value == 'camera') {
                            _pickImage(ImageSource.camera);
                          } else if (value == 'photos') {
                            _pickImage(ImageSource.gallery);
                          } else {
                            _pickFile();
                          }
                        },
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'camera', child: Text('拍照')),
                          PopupMenuItem(value: 'photos', child: Text('从相册选择')),
                          PopupMenuItem(value: 'files', child: Text('选择文件或表格')),
                        ],
                      ),
                      Expanded(
                          child: Align(
                              alignment: Alignment.centerLeft,
                              child: TextButton(
                                onPressed:
                                    busy || listening ? null : _chooseThinking,
                                style: TextButton.styleFrom(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 10)),
                                child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Flexible(
                                          child: Text(
                                              c.config.thinkingLevel == 'high'
                                                  ? '深入思考'
                                                  : '标准思考',
                                              overflow: TextOverflow.ellipsis)),
                                      const SizedBox(width: 2),
                                      const Icon(Icons.expand_more_rounded,
                                          size: 18),
                                    ]),
                              ))),
                      ValueListenableBuilder<TextEditingValue>(
                          valueListenable: _textCtrl,
                          builder: (context, value, _) => IconButton.filled(
                                tooltip: '发送消息',
                                onPressed: value.text.trim().isEmpty ||
                                        busy ||
                                        listening ||
                                        c.attachmentUploading ||
                                        c.historyLoading
                                    ? null
                                    : _send,
                                icon: const Icon(Icons.arrow_upward_rounded,
                                    size: 22),
                              )),
                    ]),
                  ])),
            ),
            const SizedBox(height: 8),
            if (busy)
              SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: c.interrupt,
                    icon: const Icon(Icons.stop_circle_outlined, size: 20),
                    label:
                        Text(c.phase == ChatPhase.speaking ? '停止语音' : '停止生成'),
                  ))
            else
              Semantics(
                button: true,
                label: listening ? '结束录音' : '语音输入',
                hint: '按住说话，上滑取消。使用屏幕阅读器时双击开始或结束。',
                onTap: !c.wsConnected || busy || c.attachmentUploading
                    ? null
                    : () {
                        if (listening) {
                          c.stopListening();
                        } else {
                          c.startListening();
                        }
                      },
                child: Listener(
                  behavior: HitTestBehavior.opaque,
                  onPointerDown: (event) {
                    if (!c.wsConnected ||
                        busy ||
                        c.attachmentUploading ||
                        c.historyLoading ||
                        _holding) return;
                    _holding = true;
                    _cancelingVoice = false;
                    _voicePointerStart = event.position;
                    HapticFeedback.mediumImpact();
                    c.startListening();
                  },
                  onPointerMove: _updateVoiceDrag,
                  onPointerUp: (_) => _finishHold(),
                  onPointerCancel: (_) => _cancelHold(),
                  child: AnimatedContainer(
                    duration: MiruMotion.duration(context),
                    constraints: const BoxConstraints(minHeight: 48),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 10),
                    decoration: BoxDecoration(
                        color: _cancelingVoice
                            ? colors.errorContainer
                            : listening
                                ? colors.primaryContainer
                                : colors.surfaceContainerLow,
                        borderRadius: BorderRadius.circular(16)),
                    child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                              listening
                                  ? Icons.graphic_eq_rounded
                                  : Icons.mic_none_rounded,
                              size: 20,
                              color: _cancelingVoice
                                  ? colors.onErrorContainer
                                  : colors.primary),
                          const SizedBox(width: 8),
                          Flexible(
                              child: Text(
                            listening
                                ? (_cancelingVoice
                                    ? '松开取消 · 下滑继续'
                                    : (c.recordRemaining > 0 &&
                                            c.recordRemaining <= 10
                                        ? '上滑取消 · 还剩 ${c.recordRemaining}s'
                                        : '上滑取消 · 松开发送'))
                                : '按住说话',
                            textAlign: TextAlign.center,
                            style: Theme.of(context)
                                .textTheme
                                .labelLarge
                                ?.copyWith(
                                    color: _cancelingVoice
                                        ? colors.onErrorContainer
                                        : c.wsConnected && !busy
                                            ? colors.primary
                                            : colors.onSurfaceVariant),
                          )),
                        ]),
                  ),
                ),
              ),
          ]),
        ));
  }

  Future<void> _chooseThinking() async {
    await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (context) => SafeArea(
                child: SingleChildScrollView(
                    child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
              child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text('选择思考方式',
                            style: Theme.of(context).textTheme.titleLarge)),
                    for (final level in ['low', 'high'])
                      ListTile(
                        leading: Icon(level == 'low'
                            ? Icons.bolt_outlined
                            : Icons.auto_awesome_outlined),
                        title: Text(level == 'low' ? '标准思考' : '深入思考'),
                        subtitle: Text(level == 'low'
                            ? '适合日常问题，回应更轻快'
                            : '适合复杂分析，可能需要更长时间与更多费用'),
                        trailing: c.config.thinkingLevel == level
                            ? const Icon(Icons.check_rounded)
                            : null,
                        onTap: () {
                          c.setThinkingLevel(level);
                          Navigator.pop(context);
                        },
                      ),
                  ]),
            ))));
  }

  Future<void> _openSettings(BuildContext context) async {
    final changed = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => SettingsScreen(config: c.config)),
    );
    if (changed == true) {
      // 配置变了：让 controller 更新 WS 目标并立即重连。
      // 注意不能只调 c.ws.reconnect()：ws.url 是旧地址构造的，改了设置也不会生效。
      c.applyServerSettings();
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('配置已保存，正在重新连接…')));
      }
    }
  }
}
