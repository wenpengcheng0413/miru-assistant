import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../core/audio/player_service.dart';
import '../../core/audio/recorder_service.dart';
import '../../core/config.dart';
import '../../core/ws_client.dart';

enum ChatPhase { idle, listening, thinking, speaking }

class ChatLine {
  ChatLine(this.kind, this.text);

  final String kind; // user / miru / note
  final String text;
}

/// 对话状态机：
/// idle → listening（按住说话）→ thinking（STT/LLM/工具）→ speaking（播 TTS）→ idle
class ChatController extends ChangeNotifier {
  ChatController({
    required this.config,
    required this.ws,
    required this.recorder,
    required this.player,
  });

  final AppConfig config;
  final WsClient ws;
  final RecorderService recorder;
  final PlayerService player;

  final List<ChatLine> lines = [];
  ChatPhase phase = ChatPhase.idle;
  String partialText = ''; // 识别中的半透明字
  String miruText = ''; // 流式回答字幕
  String toolStatus = ''; // "正在读取群消息…"
  double lastCost = 0;

  /// 最新识别文本（填入输入框供修改）；版本号用于 UI 侧同步
  String pendingInput = '';
  int pendingInputVersion = 0;

  /// WS 是否已连上（聊天页顶部显示离线横幅）
  bool wsConnected = false;

  void init() {
    ws.onJson = _onJson;
    ws.onAudio = player.feedAudio;
    ws.onConnected = () {
      wsConnected = true;
      notifyListeners();
    };
    ws.onDisconnected = () {
      wsConnected = false;
      if (phase != ChatPhase.idle) {
        lines.add(ChatLine('note', '连接断开，正在重连…'));
        phase = ChatPhase.idle;
      }
      notifyListeners();
      _reconnect();
    };
  }

  void _reconnect() {
    Future.delayed(const Duration(seconds: 3), () {
      if (!hasListeners) return;
      ws.connect();
    });
  }

  void _onJson(Map<String, dynamic> e) {
    final type = e['type'] as String? ?? '';
    switch (type) {
      case 'stt_partial':
        partialText = e['text'] as String? ?? '';
        notifyListeners();
      case 'stt_final':
        // 识别完成：文本进输入框（可修改）；只有后端确认收到后才显示为用户消息
        partialText = '';
        pendingInput = e['text'] as String? ?? '';
        pendingInputVersion++;
        notifyListeners();
      case 'user_text':
        _addUserLine(e['text'] as String? ?? '');
        notifyListeners();
      case 'llm_delta':
        miruText += e['text'] as String? ?? '';
        phase = ChatPhase.thinking;
        notifyListeners();
      case 'sentence':
        player.finishSentence(); // 上句音频收齐，入播放队列
        phase = ChatPhase.speaking;
        notifyListeners();
      case 'tool_start':
        toolStatus = '🔧 ${e['name']}…';
        phase = ChatPhase.thinking;
        notifyListeners();
      case 'tool_end':
        toolStatus = '';
        notifyListeners();
      case 'turn_end':
        player.finishSentence(); // 兜底：flush 最后一句
        if (miruText.isNotEmpty) {
          lines.add(ChatLine('miru', miruText));
          miruText = '';
        }
        lastCost = (e['cost_rmb'] as num?)?.toDouble() ?? 0;
        phase = ChatPhase.idle;
        notifyListeners();
      case 'server_note':
        lines.add(ChatLine('note', e['text'] as String? ?? ''));
        notifyListeners();
      case 'error':
        lines.add(ChatLine('note', '⚠️ ${e['message'] ?? e['code']}'));
        phase = ChatPhase.idle;
        notifyListeners();
    }
  }

  void _addUserLine(String text) {
    if (text.isEmpty) return;
    if (lines.isNotEmpty && lines.last.kind == 'user' && lines.last.text == text) {
      return; // 去重（重发同一句时不重复显示）
    }
    lines.add(ChatLine('user', text));
  }

  // ---- 操作 ----

  Future<void> startListening() async {
    if (phase == ChatPhase.listening) return;
    try {
      await recorder.start(onChunk: ws.sendAudio);
    } catch (e) {
      lines.add(ChatLine('note', e.toString()));
      notifyListeners();
      return;
    }
    phase = ChatPhase.listening;
    notifyListeners();
  }

  Future<void> stopListening() async {
    if (phase != ChatPhase.listening) return;
    await recorder.stop();
    ws.sendJson({'type': 'audio_end'});
    // autoSend=false 时后端只回 stt_final，等用户点发送；
    // autoSend=true 时后端直接进管线，这里先进 thinking 等 llm_delta/turn_end
    phase = config.autoSend ? ChatPhase.thinking : ChatPhase.idle;
    notifyListeners();
  }

  Future<void> sendText(String text) async {
    if (text.trim().isEmpty) return;
    _addUserLine(text.trim());
    ws.sendJson({'type': 'text_input', 'text': text.trim()});
    phase = ChatPhase.thinking;
    notifyListeners();
  }

  Future<void> interrupt() async {
    ws.sendJson({'type': 'interrupt'});
    await player.interrupt();
    miruText = '';
    toolStatus = '';
    phase = ChatPhase.idle;
    notifyListeners();
  }

  /// 切换语音回复开关（重连以新参数握手）
  Future<void> toggleTts() async {
    config.ttsEnabled = !config.ttsEnabled;
    await config.save();
    ws.hello = config.hello;
    await ws.reconnect();
    notifyListeners();
  }

  @override
  void dispose() {
    ws.close();
    super.dispose();
  }
}
