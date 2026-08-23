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
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final AppConfig config;
  final WsClient ws;
  final RecorderService recorder;
  final PlayerService player;
  final DateTime Function() _now;

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
  int _recordingGeneration = 0;
  bool _disposed = false;
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
      if (phase == ChatPhase.listening) {
        _invalidateRecording();
        unawaited(recorder.stop()); // 断线立刻停录音，防止麦克风泄漏
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
    final generation = ++_recordingGeneration;
    // 先亮红灯再启动：UI 反馈即时；启动失败（如权限被拒）回退到 idle
    phase = ChatPhase.listening;
    recordRemaining = 30;
    notifyListeners();
    ws.sendAudioStart();
    try {
      await recorder.start(onChunk: ws.sendAudio);
    } catch (e) {
      // 录音启动期间可能已经松手/断线；旧会话不得覆盖新状态。
      if (generation != _recordingGeneration || _disposed) return;
      _invalidateRecording();
      phase = ChatPhase.idle;
      lines.add(ChatLine('note', e.toString()));
      notifyListeners();
      return;
    }

    // 用户可能在 startStream 完成前已经松手。这时不能再启动超时定时器，
    // 并且要再停一次刚刚才真正启动的底层录音。
    if (generation != _recordingGeneration ||
        phase != ChatPhase.listening ||
        _disposed) {
      await recorder.stop();
      return;
    }
    _startRecordTicker(generation);
  }

  /// 每秒刷新剩余时间；剩 10 秒时重震提醒；到 0 自动停
  void _startRecordTicker(int generation) {
    _listenTimer?.cancel();
    _recordStartedAt = _now();
    var warned = false;
    _listenTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      // 过期的录音定时器必须自行熔断，不能循环追加超时提示。
      if (generation != _recordingGeneration ||
          phase != ChatPhase.listening ||
          _disposed) {
        timer.cancel();
        if (identical(_listenTimer, timer)) _listenTimer = null;
        return;
      }

      final startedAt = _recordStartedAt;
      if (startedAt == null) {
        timer.cancel();
        if (identical(_listenTimer, timer)) _listenTimer = null;
        return;
      }
      final elapsed = _now().difference(startedAt).inSeconds;
      final remaining = 30 - elapsed;
      recordRemaining = remaining > 0 ? remaining : 0;
      if (remaining == 10 && !warned) {
        warned = true;
        HapticFeedback.heavyImpact();
      }
      if (remaining <= 0) {
        timer.cancel();
        if (identical(_listenTimer, timer)) _listenTimer = null;
        unawaited(_stopListening(timedOut: true));
        return;
      }
      notifyListeners();
    });
  }

  Future<void> stopListening() => _stopListening();

  Future<void> _stopListening({bool timedOut = false}) async {
    if (phase != ChatPhase.listening) return;
    _invalidateRecording();

    // 先同步切换状态和关闭后端音频闸门，使重复 stop 立即幂等。
    phase = config.autoSend ? ChatPhase.thinking : ChatPhase.idle;
    if (timedOut) {
      lines.add(ChatLine('note', '录音超时，已自动停止'));
    }
    ws.sendJson({'type': 'audio_end'});
    notifyListeners();
    await recorder.stop();
  }

  void _invalidateRecording() {
    ++_recordingGeneration;
    _listenTimer?.cancel();
    _listenTimer = null;
    _recordStartedAt = null;
    recordRemaining = 0;
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
    _disposed = true;
    _invalidateRecording();
    ws.close();
    super.dispose();
  }
}
