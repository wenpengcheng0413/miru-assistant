import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

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

  Timer? _listenTimer; // 录音兜底：手势丢失时最多录 30 秒
  DateTime? _recordStartedAt;

  /// 录音剩余秒数：最后 10 秒在按键上倒计时显示
  int recordRemaining = 0;

  void init() {
    ws.onJson = _onJson;
    ws.onAudio = player.feedAudio;
    ws.onConnected = () {
      wsConnected = true;
      notifyListeners();
    };
    ws.onDisconnected = () {
      wsConnected = false;
      _listenTimer?.cancel();
      if (phase == ChatPhase.listening) {
        recorder.stop(); // 断线立刻停录音，防止麦克风泄漏
        lines.add(ChatLine('note', '连接断开，录音已停止'));
      } else if (phase != ChatPhase.idle) {
        lines.add(ChatLine('note', '连接断开，正在重连…'));
      }
      if (phase != ChatPhase.idle) phase = ChatPhase.idle;
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
        // 识别完成：autoSend=false 时文本进输入框供修改；
        // autoSend=true 直接由后端管线处理，不占输入框
        partialText = '';
        if (!config.autoSend) {
          pendingInput = e['text'] as String? ?? '';
          pendingInputVersion++;
        }
        notifyListeners();
      case 'user_text':
        _addUserLine(e['text'] as String? ?? '');
        // 消息已进聊天记录：清掉预填文本（语音自动发送后输入框不留残留）
        if (pendingInput.isNotEmpty) {
          pendingInput = '';
          pendingInputVersion++;
        }
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
    // 先亮红灯再启动：UI 反馈即时；启动失败（如权限被拒）回退到 idle
    phase = ChatPhase.listening;
    recordRemaining = 30;
    notifyListeners();
    ws.sendAudioStart();
    try {
      await recorder.start(onChunk: ws.sendAudio);
    } catch (e) {
      phase = ChatPhase.idle;
      recordRemaining = 0;
      lines.add(ChatLine('note', e.toString()));
      notifyListeners();
      return;
    }
    _startRecordTicker();
  }

  /// 每秒刷新剩余时间；剩 10 秒时重震提醒；到 0 自动停
  void _startRecordTicker() {
    _listenTimer?.cancel();
    _recordStartedAt = DateTime.now();
    var warned = false;
    _listenTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      final elapsed = DateTime.now().difference(_recordStartedAt!).inSeconds;
      final remaining = 30 - elapsed;
      recordRemaining = remaining > 0 ? remaining : 0;
      if (remaining == 10 && !warned) {
        warned = true;
        HapticFeedback.heavyImpact();
      }
      if (remaining <= 0) {
        stopListening();
        lines.add(ChatLine('note', '录音超时，已自动停止'));
      }
      notifyListeners();
    });
  }

  Future<void> stopListening() async {
    if (phase != ChatPhase.listening) return;
    _listenTimer?.cancel();
    recordRemaining = 0;
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
    _listenTimer?.cancel();
    ws.close();
    super.dispose();
  }
}
