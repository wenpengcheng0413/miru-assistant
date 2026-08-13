import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/audio/player_service.dart';
import '../../core/config.dart';
import 'chat_controller.dart';
import '../settings/settings_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.controller, required this.player});

  final ChatController controller;
  final PlayerService player;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  final TextEditingController _textCtrl = TextEditingController();
  bool _holding = false;
  int _syncedInputVersion = -1;

  ChatController get c => widget.controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _textCtrl.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 切到后台时若还在录音，立刻停止——否则麦克风一直开着，
    // 环境噪声会被 STT 幻觉成句号/英文单词自动发出去
    if (state != AppLifecycleState.resumed &&
        c.phase == ChatPhase.listening) {
      _holding = false;
      c.stopListening();
    }
  }

  /// 语音识别文本 → 预填输入框（可修改后发送）
  void _syncPendingInput() {
    if (c.pendingInputVersion == _syncedInputVersion) return;
    _syncedInputVersion = c.pendingInputVersion;
    if (c.pendingInput.isNotEmpty) {
      _textCtrl.text = c.pendingInput;
      _textCtrl.selection =
          TextSelection.collapsed(offset: _textCtrl.text.length);
    }
  }

  Future<void> _send() async {
    final text = _textCtrl.text.trim();
    if (text.isEmpty) return;
    _textCtrl.clear();
    await c.sendText(text);
  }

  /// 手指抬起/被系统取消：结束录音（幂等，重复调用无害）
  void _finishHold() {
    if (!_holding) return;
    _holding = false;
    HapticFeedback.lightImpact();
    c.stopListening();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Miru'),
        actions: [
          if (c.lastCost > 0)
            Center(
              child: Text(
                '本轮 ¥${c.lastCost.toStringAsFixed(3)}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          // 语音回复快捷开关
          IconButton(
            tooltip: c.config.ttsEnabled ? '关闭语音回复' : '开启语音回复',
            icon: Icon(c.config.ttsEnabled
                ? Icons.volume_up_outlined
                : Icons.volume_off_outlined),
            onPressed: c.toggleTts,
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => _openSettings(context),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: AnimatedBuilder(
        animation: c,
        builder: (context, _) {
          _syncPendingInput();
          return Column(
            children: [
              if (!c.wsConnected) _offlineBanner(context),
              Expanded(
                // 点聊天区域收键盘；拖动列表滚动也收键盘
                child: GestureDetector(
                  behavior: HitTestBehavior.translucent,
                  onTap: () => FocusScope.of(context).unfocus(),
                  child: ListView.builder(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                    itemCount: c.lines.length + 1,
                    itemBuilder: (context, i) {
                      if (i == c.lines.length) return _liveArea();
                      final line = c.lines[i];
                      return Align(
                        alignment: line.kind == 'user'
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 8),
                          decoration: BoxDecoration(
                            color: line.kind == 'user'
                                ? Theme.of(context).colorScheme.primaryContainer
                                : line.kind == 'note'
                                    ? Theme.of(context)
                                        .colorScheme
                                        .surfaceContainerHighest
                                    : Theme.of(context)
                                        .colorScheme
                                        .surfaceContainerHigh,
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Text(line.text,
                              style: const TextStyle(fontSize: 15)),
                        ),
                      );
                    },
                  ),
                ),
              ),
              _bottomBar(context),
            ],
          );
        },
      ),
    );
  }

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
                  '未连接服务器（每 3 秒自动重连）· 点此检查设置',
                  style: TextStyle(fontSize: 13, color: scheme.onErrorContainer),
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
      parts.add(Text(
        c.partialText,
        style: TextStyle(
          fontSize: 15,
          color: Theme.of(context).colorScheme.onSurface.withOpacity(0.45),
        ),
      ));
    }
    if (c.miruText.isNotEmpty) {
      parts.add(Text(c.miruText, style: const TextStyle(fontSize: 15)));
    }
    if (c.toolStatus.isNotEmpty) {
      parts.add(Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Row(
          children: [
            const SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 8),
            Text(c.toolStatus, style: const TextStyle(fontSize: 13)),
          ],
        ),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: parts);
  }

  Widget _bottomBar(BuildContext context) {
    final thinking = c.phase == ChatPhase.thinking;
    final speaking = c.phase == ChatPhase.speaking;
    final listening = c.phase == ChatPhase.listening;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 输入行：识别文本可编辑，可打字发送
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _textCtrl,
                    minLines: 1,
                    maxLines: 3,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _send(),
                    decoration: InputDecoration(
                      hintText: '说话或输入…',
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 10),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(22),
                      ),
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.send),
                  onPressed: (thinking || listening) ? null : _send,
                ),
              ],
            ),
            const SizedBox(height: 6),
            // 按住说话 + 打断
            Row(
              children: [
                if (thinking || speaking)
                  IconButton.filledTonal(
                    icon: const Icon(Icons.stop),
                    onPressed: c.interrupt,
                  ),
                Expanded(
                  // 原始指针事件（不用 GestureDetector 长按）：
                  // 按下立即开录、抬起/取消立即停止，状态和真实录音严格同步
                  child: Listener(
                    behavior: HitTestBehavior.opaque,
                    onPointerDown: (_) {
                      _holding = true;
                      HapticFeedback.mediumImpact();
                      c.startListening();
                    },
                    onPointerUp: (_) => _finishHold(),
                    onPointerCancel: (_) => _finishHold(),
                    child: Container(
                      height: 48,
                      decoration: BoxDecoration(
                        color: listening
                            ? Theme.of(context).colorScheme.errorContainer
                            : Theme.of(context).colorScheme.primary,
                        borderRadius: BorderRadius.circular(24),
                      ),
                      child: Center(
                        child: Text(
                          listening
                              ? (c.recordRemaining > 0 && c.recordRemaining <= 10
                                  ? '松开结束 · 还剩 ${c.recordRemaining}s'
                                  : '松开结束 · 录音中')
                              : '按住说话',
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openSettings(BuildContext context) async {
    final changed = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => SettingsScreen(config: c.config)),
    );
    if (changed == true) {
      // 配置变了：带新参数重新握手
      c.ws.hello = c.config.hello;
      c.ws.reconnect();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('配置已保存，正在重新连接…')),
        );
      }
    }
  }
}
