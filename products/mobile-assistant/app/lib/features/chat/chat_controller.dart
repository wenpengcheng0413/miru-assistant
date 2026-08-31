import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../../core/audio/player_service.dart';
import '../../core/audio/recorder_service.dart';
import '../../core/config.dart';
import '../../core/server_discovery.dart';
import '../../core/system_status.dart';
import '../../core/ws_client.dart';

enum ChatPhase { idle, listening, thinking, speaking }

class ChatLine {
  ChatLine(
    this.kind,
    this.text, {
    this.id = '',
    this.turnId = '',
    this.stats,
    List<ProcessStep>? steps,
    List<RemoteImage>? images,
  })  : steps = steps ?? <ProcessStep>[],
        images = images ?? <RemoteImage>[];

  final String kind; // user / miru / note
  final String text;
  final String id;
  final String turnId;
  final TurnStats? stats;
  final List<ProcessStep> steps;
  final List<RemoteImage> images;
  bool processExpanded = false;
}

class RemoteImage {
  RemoteImage({
    required this.id,
    required this.downloadPath,
    required this.mediaType,
    required this.sender,
    required this.messageTime,
    required this.expiresAt,
  });

  final String id;
  final String downloadPath;
  final String mediaType;
  final String sender;
  final String messageTime;
  final String expiresAt;

  factory RemoteImage.fromJson(Map<dynamic, dynamic> json) => RemoteImage(
        id: json['id'] as String? ?? '',
        downloadPath: json['download_path'] as String? ?? '',
        mediaType: json['media_type'] as String? ?? 'image/jpeg',
        sender: json['sender'] as String? ?? '',
        messageTime: json['message_time'] as String? ?? '',
        expiresAt: json['expires_at'] as String? ?? '',
      );
}

class ProcessStep {
  ProcessStep({
    required this.seq,
    required this.phase,
    required this.title,
    required this.detail,
    required this.status,
  });

  final int seq;
  final String phase;
  final String title;
  final String detail;
  final String status;

  factory ProcessStep.fromJson(Map<dynamic, dynamic> json) => ProcessStep(
        seq: (json['seq'] as num?)?.toInt() ?? 0,
        phase: json['phase'] as String? ?? 'process',
        title: json['title'] as String? ?? '处理中',
        detail: json['detail'] as String? ?? '',
        status: json['status'] as String? ?? 'done',
      );
}

class TurnStats {
  TurnStats({
    required this.status,
    required this.durationMs,
    required this.promptTokens,
    required this.completionTokens,
    required this.costRmb,
  });

  final String status;
  final int durationMs;
  final int promptTokens;
  final int completionTokens;
  final double costRmb;

  factory TurnStats.fromJson(Map<dynamic, dynamic> json) => TurnStats(
        status: json['status'] as String? ?? 'completed',
        durationMs: (json['duration_ms'] as num?)?.toInt() ?? 0,
        promptTokens: (json['prompt_tokens'] as num?)?.toInt() ?? 0,
        completionTokens: (json['completion_tokens'] as num?)?.toInt() ?? 0,
        costRmb: (json['cost_rmb'] as num?)?.toDouble() ?? 0,
      );

  factory TurnStats.fromTurnEnd(Map<dynamic, dynamic> json) {
    final usage = json['usage'] is Map ? json['usage'] as Map : const {};
    return TurnStats(
      status: 'completed',
      durationMs: (json['duration_ms'] as num?)?.toInt() ?? 0,
      promptTokens: (usage['prompt_tokens'] as num?)?.toInt() ?? 0,
      completionTokens: (usage['completion_tokens'] as num?)?.toInt() ?? 0,
      costRmb: (json['cost_rmb'] as num?)?.toDouble() ?? 0,
    );
  }
}

class ConversationBrief {
  ConversationBrief({
    required this.id,
    required this.title,
    required this.updatedAt,
    required this.messageCount,
  });

  final String id;
  final String title;
  final DateTime? updatedAt;
  final int messageCount;

  String get displayTitle => title.trim().isEmpty ? '新对话' : title.trim();

  factory ConversationBrief.fromJson(Map<dynamic, dynamic> json) {
    return ConversationBrief(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      updatedAt: DateTime.tryParse(json['updated_at'] as String? ?? ''),
      messageCount: (json['message_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class PendingAttachment {
  PendingAttachment({
    required this.id,
    required this.filename,
    required this.kind,
    required this.sizeBytes,
  });

  final String id;
  final String filename;
  final String kind;
  final int sizeBytes;

  factory PendingAttachment.fromJson(Map<dynamic, dynamic> json) =>
      PendingAttachment(
        id: json['id'] as String? ?? '',
        filename: json['filename'] as String? ?? '附件',
        kind: json['kind'] as String? ?? 'document',
        sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
      );
}

/// 对话状态机：
/// idle → listening（按住说话）→ thinking（STT/LLM/工具）→ speaking（播 TTS）→ idle
class ChatController extends ChangeNotifier {
  static const int recordingLimitSeconds = 60;

  ChatController({
    required this.config,
    required this.ws,
    required this.recorder,
    required this.player,
    required this.discovery,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final AppConfig config;
  final WsClient ws;
  final RecorderService recorder;
  final PlayerService player;
  final ServerDiscovery discovery;
  final DateTime Function() _now;

  final List<ChatLine> lines = [];
  ChatPhase phase = ChatPhase.idle;
  String partialText = ''; // 识别中的半透明字
  String miruText = ''; // 流式回答字幕
  String toolStatus = ''; // "正在读取群消息…"
  String progressStatus = '';
  String activeTurnId = '';
  final List<ProcessStep> activeProcessSteps = <ProcessStep>[];
  bool activeProcessExpanded = true;
  TurnStats? activeTurnStats;
  double lastCost = 0;
  final List<ConversationBrief> conversations = [];
  final List<PendingAttachment> pendingAttachments = [];
  final Set<String> _voiceAttachmentIdsInFlight = <String>{};
  bool attachmentUploading = false;
  bool conversationsLoading = false;
  String conversationsError = '';

  /// 最新识别文本（填入输入框供修改）；版本号用于 UI 侧同步
  String pendingInput = '';
  int pendingInputVersion = 0;

  /// WS 是否已连上（聊天页顶部显示离线横幅）
  bool wsConnected = false;

  /// 离线横幅显示的最近一次错误/状态
  String wsStatus = '正在连接…';

  MiruSystemStatus? systemStatus;
  DateTime? systemStatusReceivedAt;

  bool get systemStatusStale =>
      systemStatusReceivedAt == null ||
      _now().difference(systemStatusReceivedAt!) > const Duration(minutes: 2);

  Timer? _listenTimer; // 录音兜底：手势丢失时最多录 60 秒
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  bool _historyLoaded = false;
  bool _everConnected = false;
  bool _discoveryActive = false;
  bool _disposed = false;
  int _recordingGeneration = 0;
  DateTime? _recordStartedAt;

  /// 录音剩余秒数：最后 10 秒在按键上倒计时显示
  int recordRemaining = 0;

  void init() {
    ws.onJson = _onJson;
    ws.onAudio = player.feedAudio;
    ws.onSession = _onSession;
    ws.onConnected = () {
      _reconnectTimer?.cancel();
      _reconnectAttempts = 0;
      wsConnected = true;
      wsStatus = config.requiresHttps ? 'Cloud 已连接' : '已连接';
      final reconnected = _everConnected;
      _everConnected = true;
      if (reconnected) {
        lines.add(ChatLine('note', '已重新连接，正在同步任务状态'));
      }
      notifyListeners();
      _loadHistory();
      loadConversations();
    };
    ws.onDisconnected = (reason) {
      final wasConnected = wsConnected;
      wsConnected = false;
      wsStatus = reason.trim().isEmpty ? '连接已断开' : reason.trim();
      if (phase == ChatPhase.listening) {
        _invalidateRecording();
        unawaited(recorder.stop()); // 断线立刻停录音，防止麦克风泄漏
        lines.add(ChatLine('note', '连接断开，录音已停止'));
      } else if (wasConnected && phase != ChatPhase.idle) {
        lines.add(ChatLine('note', '连接断开，正在重连…'));
      }
      if (phase != ChatPhase.idle) phase = ChatPhase.idle;
      notifyListeners();
      _recoverOrReconnect(reason);
    };
  }

  /// 指数退避重连：3s / 6s / 12s / 24s，之后每 30s 一次。
  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    final attempt = _reconnectAttempts;
    final seconds = attempt <= 0
        ? 3
        : (attempt <= 2 ? 3 * (1 << attempt) : (attempt == 3 ? 24 : 30));
    _reconnectTimer = Timer(Duration(seconds: seconds), () {
      if (_disposed) return;
      _reconnectAttempts++;
      ws.connect();
    });
  }

  /// On the first failure (and periodically afterwards), discover the PC by
  /// Bonjour. This recovers automatically when DHCP changes the computer IP.
  Future<void> _recoverOrReconnect(String reason) async {
    if (_disposed) return;
    final lower = reason.toLowerCase();
    if (lower.contains('token') || lower.contains('握手格式')) {
      // Repeating an authentication failure only drains battery; settings are
      // required to fix it.
      return;
    }
    final shouldDiscover = config.bonjourEnabled &&
        !_discoveryActive &&
        (_reconnectAttempts == 0 || _reconnectAttempts % 5 == 0);
    if (!shouldDiscover) {
      _scheduleReconnect();
      return;
    }

    _discoveryActive = true;
    wsStatus = '正在局域网中自动查找电脑…';
    notifyListeners();
    try {
      final found = await discovery.findServer();
      if (_disposed) return;
      if (found != null) {
        final newUrl = found.toString().replaceAll(RegExp(r'/+$'), '');
        if (config.baseUrl != newUrl) {
          config.baseUrl = newUrl;
          await config.save();
        }
        ws.updateTarget(
          url: config.wsUri,
          token: config.token,
          hello: config.hello,
        );
        wsStatus = '已自动找到电脑：${found.host}:${found.port}';
        notifyListeners();
        // Avoid immediately launching a second discovery if this address is
        // reachable but the token is rejected.
        _reconnectAttempts = 1;
        _discoveryActive = false;
        await ws.connect();
        return;
      }
      wsStatus = '$reason；未发现电脑，将继续重连';
      notifyListeners();
    } finally {
      _discoveryActive = false;
    }
    _scheduleReconnect();
  }

  /// iOS can suspend timers and sockets in the background. Recheck as soon as
  /// the app returns to the foreground instead of waiting for backoff.
  void onAppResumed() {
    if (_disposed) return;
    if (wsConnected) {
      ws.sendJson({'type': 'ping'});
      return;
    }
    if (_discoveryActive) return;
    _reconnectTimer?.cancel();
    wsStatus = '正在恢复连接…';
    notifyListeners();
    ws.connect();
  }

  void _onSession(String id) {
    if (id.isEmpty || config.lastConversationId == id) return;
    config.lastConversationId = id;
    config.save(); // 异步落盘，不阻塞会话
  }

  /// 连接成功后把最近一次会话的历史消息拉回来。
  /// 只在本次 App 生命周期内加载一次；重连不重复加载（内存里已有）。
  Future<void> _loadHistory() async {
    if (_historyLoaded) return;
    _historyLoaded = true;
    final conversationId = ws.sessionId;
    if (conversationId == null || conversationId.isEmpty) return;

    try {
      final dio = Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 6),
          receiveTimeout: const Duration(seconds: 10),
        ),
      );
      final resp = await dio.get(
        '${config.restBaseUrl}/api/conversations/$conversationId/messages?limit=100',
        options: Options(headers: {'Authorization': 'Bearer ${config.token}'}),
      );
      final rows = (resp.data as List?) ?? const [];
      final history = <ChatLine>[];
      for (final row in rows) {
        if (row is! Map) continue;
        final role = row['role'] as String? ?? '';
        final content = (row['content'] as String?)?.trim() ?? '';
        if (content.isEmpty) continue;
        final turnId = row['turn_id'] as String? ?? '';
        final trace = row['trace'] is Map ? row['trace'] as Map : null;
        final traceSteps = trace?['steps'] is List
            ? (trace!['steps'] as List)
                .whereType<Map>()
                .map(ProcessStep.fromJson)
                .toList()
            : <ProcessStep>[];
        final stats = trace == null ? null : TurnStats.fromJson(trace);
        if (role == 'user') {
          history.add(ChatLine('user', content, turnId: turnId));
          // 后台任务尚未完成时，用户消息携带的 trace 是唯一可恢复的运行状态。
          if (trace != null &&
              trace['status'] == 'running' &&
              turnId.isNotEmpty &&
              activeTurnId.isEmpty) {
            activeTurnId = turnId;
            activeProcessSteps
              ..clear()
              ..addAll(traceSteps);
            activeProcessExpanded = true;
            phase = ChatPhase.thinking;
            progressStatus = '正在继续后台任务…';
          }
        } else if (role == 'assistant') {
          history.add(
            ChatLine(
              'miru',
              content,
              id: '${row['id'] ?? ''}',
              turnId: turnId,
              stats: stats,
              steps: traceSteps,
            ),
          );
        }
      }
      try {
        final mediaResponse = await dio.get(
          '${config.restBaseUrl}/api/conversations/$conversationId/node-media',
          options:
              Options(headers: {'Authorization': 'Bearer ${config.token}'}),
        );
        final mediaRows =
            (mediaResponse.data as Map?)?['items'] as List? ?? const [];
        final images = mediaRows
            .whereType<Map>()
            .map(RemoteImage.fromJson)
            .where((item) => item.id.isNotEmpty && item.downloadPath.isNotEmpty)
            .toList();
        if (images.isNotEmpty) {
          history.add(ChatLine('media', '微信原图（24 小时有效）', images: images));
        }
      } catch (_) {
        // 短期媒体恢复失败不影响文字历史。
      }
      if (history.isEmpty) return;

      // 如果加载期间用户已经说话，保留这些新行并去重，避免历史消息被插到最下面
      final live = lines.toList();
      lines.clear();
      for (final h in history) {
        final duplicate = live.any((l) => l.kind == h.kind && l.text == h.text);
        if (!duplicate) lines.add(h);
      }
      lines.addAll(live);
      notifyListeners();
    } catch (_) {
      // 历史记录加载失败不影响当前会话
    }
  }

  Dio _api() => Dio(
        BaseOptions(
          connectTimeout: const Duration(seconds: 6),
          receiveTimeout: const Duration(seconds: 12),
          headers: {'Authorization': 'Bearer ${config.token}'},
        ),
      );

  Future<void> loadConversations({String query = ''}) async {
    if (conversationsLoading) return;
    conversationsLoading = true;
    conversationsError = '';
    notifyListeners();
    try {
      final response = await _api().get(
        '${config.restBaseUrl}/api/conversations',
        queryParameters: {
          'limit': 100,
          if (query.trim().isNotEmpty) 'q': query.trim(),
        },
      );
      final rows = (response.data as List?) ?? const [];
      conversations
        ..clear()
        ..addAll(
          rows
              .whereType<Map>()
              .map(ConversationBrief.fromJson)
              .where((c) => c.id.isNotEmpty),
        );
    } catch (_) {
      conversationsError = '会话列表暂时无法加载';
    } finally {
      conversationsLoading = false;
      notifyListeners();
    }
  }

  Future<void> createConversation() async {
    if (!wsConnected) {
      lines.add(ChatLine('note', '未连接服务器，暂时无法新建会话'));
      notifyListeners();
      return;
    }
    try {
      final response = await _api().post(
        '${config.restBaseUrl}/api/conversations',
        data: {'persona': 'miru'},
      );
      final id = (response.data as Map?)?['id'] as String? ?? '';
      if (id.isEmpty) throw StateError('服务器没有返回会话 ID');
      await selectConversation(id);
    } catch (_) {
      lines.add(ChatLine('note', '新建会话失败，请稍后重试'));
      notifyListeners();
    }
  }

  Future<void> selectConversation(String conversationId) async {
    if (conversationId.isEmpty || conversationId == config.lastConversationId)
      return;
    if (!wsConnected) return;
    if (phase == ChatPhase.listening ||
        phase == ChatPhase.thinking ||
        phase == ChatPhase.speaking) {
      await interrupt();
    }
    config.lastConversationId = conversationId;
    await config.save();
    _historyLoaded = false;
    lines.clear();
    partialText = '';
    miruText = '';
    toolStatus = '';
    progressStatus = '';
    _resetActiveTurn();
    ws.updateTarget(
      url: config.wsUri,
      token: config.token,
      hello: config.hello,
    );
    wsStatus = '正在打开历史会话…';
    notifyListeners();
    await ws.reconnect();
  }

  Future<void> renameConversation(String conversationId, String title) async {
    final value = title.trim();
    if (value.isEmpty) return;
    try {
      await _api().patch(
        '${config.restBaseUrl}/api/conversations/$conversationId',
        data: {'title': value},
      );
      await loadConversations();
    } catch (_) {
      lines.add(ChatLine('note', '重命名失败，请稍后重试'));
      notifyListeners();
    }
  }

  Future<void> deleteConversation(String conversationId) async {
    try {
      await _api().delete(
        '${config.restBaseUrl}/api/conversations/$conversationId',
      );
      if (conversationId == config.lastConversationId) {
        config.lastConversationId = '';
        await config.save();
        _historyLoaded = false;
        lines.clear();
        await createConversation();
      }
      await loadConversations();
    } catch (_) {
      lines.add(ChatLine('note', '删除会话失败，请稍后重试'));
      notifyListeners();
    }
  }

  Future<String?> _ensureConversationForAttachment() async {
    if (config.lastConversationId.isNotEmpty) return config.lastConversationId;
    if (!wsConnected) return null;
    try {
      final response = await _api().post(
        '${config.restBaseUrl}/api/conversations',
        data: {'persona': 'miru'},
      );
      final id = (response.data as Map?)?['id'] as String? ?? '';
      if (id.isEmpty) return null;
      config.lastConversationId = id;
      await config.save();
      _historyLoaded = false;
      ws.updateTarget(
        url: config.wsUri,
        token: config.token,
        hello: config.hello,
      );
      await ws.reconnect();
      return id;
    } catch (_) {
      return null;
    }
  }

  Future<void> uploadAttachment(String localPath, {String? filename}) async {
    if (attachmentUploading) return;
    final file = File(localPath);
    if (!await file.exists()) {
      lines.add(ChatLine('note', '找不到所选文件，请重新选择'));
      notifyListeners();
      return;
    }
    attachmentUploading = true;
    notifyListeners();
    try {
      final conversationId = await _ensureConversationForAttachment();
      if (conversationId == null) throw StateError('未连接服务器');
      final response = await _api().post(
        '${config.restBaseUrl}/api/conversations/$conversationId/attachments',
        data: FormData.fromMap({
          'file': await MultipartFile.fromFile(
            localPath,
            filename: filename ?? file.uri.pathSegments.last,
          ),
        }),
      );
      final item = PendingAttachment.fromJson(response.data as Map);
      if (item.id.isEmpty) throw StateError('上传结果无效');
      pendingAttachments.add(item);
    } on DioException catch (e) {
      final message = e.response?.data is Map
          ? (e.response?.data['detail'] as String?)
          : null;
      lines.add(ChatLine('note', '附件上传失败：${message ?? '请检查网络或文件格式'}'));
    } catch (_) {
      lines.add(ChatLine('note', '附件上传失败，请稍后重试'));
    } finally {
      attachmentUploading = false;
      notifyListeners();
    }
  }

  void removePendingAttachment(String id) {
    pendingAttachments.removeWhere((item) => item.id == id);
    _voiceAttachmentIdsInFlight.remove(id);
    notifyListeners();
  }

  void _onJson(Map<String, dynamic> e) {
    final type = e['type'] as String? ?? '';
    switch (type) {
      case 'system_status':
        final payload = e['status'] is Map ? e['status'] as Map : e;
        systemStatus = MiruSystemStatus.fromJson(payload);
        systemStatusReceivedAt = _now();
        notifyListeners();
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
        // 语音任务只有在服务端确认进入管线后才移除附件；识别失败时附件仍留在输入区，
        // 用户可以直接重试，不需要重新上传。
        if (_voiceAttachmentIdsInFlight.isNotEmpty) {
          pendingAttachments.removeWhere(
            (item) => _voiceAttachmentIdsInFlight.contains(item.id),
          );
          _voiceAttachmentIdsInFlight.clear();
        }
        final serverTurnId = e['turn_id'] as String? ?? '';
        _addUserLine(e['text'] as String? ?? '', turnId: serverTurnId);
        if (serverTurnId.isNotEmpty) activeTurnId = serverTurnId;
        progressStatus = '正在处理…';
        // 消息已进聊天记录：清掉预填文本（语音自动发送后输入框不留残留）
        if (pendingInput.isNotEmpty) {
          pendingInput = '';
          pendingInputVersion++;
        }
        notifyListeners();
      case 'llm_delta':
        miruText += e['text'] as String? ?? '';
        progressStatus = '正在生成回复…';
        phase = ChatPhase.thinking;
        notifyListeners();
      case 'progress':
        progressStatus = e['text'] as String? ?? '正在处理…';
        phase = ChatPhase.thinking;
        notifyListeners();
      case 'process_step':
        final turnId = e['turn_id'] as String? ?? '';
        if (turnId.isNotEmpty && turnId != activeTurnId) {
          activeTurnId = turnId;
          activeProcessSteps.clear();
          activeProcessExpanded = true;
        }
        final step = ProcessStep.fromJson(e);
        final index = activeProcessSteps.indexWhere(
          (item) => item.seq == step.seq,
        );
        if (index >= 0) {
          activeProcessSteps[index] = step;
        } else {
          activeProcessSteps.add(step);
        }
        phase = ChatPhase.thinking;
        progressStatus = step.title;
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
        final toolError = e['error'] as String? ?? '';
        if (toolError.isNotEmpty) {
          progressStatus = '工具失败：$toolError';
        }
        notifyListeners();
      case 'node_media':
        final items = (e['items'] as List? ?? const [])
            .whereType<Map>()
            .map(RemoteImage.fromJson)
            .where((item) => item.id.isNotEmpty && item.downloadPath.isNotEmpty)
            .toList();
        if (items.isNotEmpty) {
          lines.add(ChatLine('media', '微信原图（24 小时有效）', images: items));
        }
        notifyListeners();
      case 'turn_end':
        player.finishSentence(); // 兜底：flush 最后一句
        final stats = TurnStats.fromTurnEnd(e);
        if (miruText.isNotEmpty) {
          final completed = ChatLine(
            'miru',
            miruText,
            turnId: e['turn_id'] as String? ?? activeTurnId,
            stats: stats,
            steps: List<ProcessStep>.from(activeProcessSteps),
          );
          lines.add(completed);
          miruText = '';
        }
        lastCost = (e['cost_rmb'] as num?)?.toDouble() ?? 0;
        phase = ChatPhase.idle;
        progressStatus = '';
        activeTurnStats = stats;
        _resetActiveTurn(keepStats: true);
        notifyListeners();
        loadConversations();
      case 'server_note':
        lines.add(ChatLine('note', e['text'] as String? ?? ''));
        notifyListeners();
      case 'error':
        if (miruText.isNotEmpty) {
          lines.add(
            ChatLine(
              'miru',
              miruText,
              turnId: activeTurnId,
              stats: TurnStats(
                status: 'failed',
                durationMs: 0,
                promptTokens: 0,
                completionTokens: 0,
                costRmb: 0,
              ),
              steps: List<ProcessStep>.from(activeProcessSteps),
            ),
          );
          miruText = '';
        }
        lines.add(ChatLine('note', '⚠️ ${e['message'] ?? e['code']}'));
        phase = ChatPhase.idle;
        progressStatus = '';
        _resetActiveTurn();
        notifyListeners();
    }
  }

  void _addUserLine(String text, {String turnId = ''}) {
    if (text.isEmpty) return;
    if (lines.isNotEmpty &&
        lines.last.kind == 'user' &&
        lines.last.text == text) {
      return; // 去重（重发同一句时不重复显示）
    }
    lines.add(ChatLine('user', text, turnId: turnId));
  }

  void toggleActiveProcessExpanded() {
    activeProcessExpanded = !activeProcessExpanded;
    notifyListeners();
  }

  void _resetActiveTurn({bool keepStats = false}) {
    activeTurnId = '';
    activeProcessSteps.clear();
    activeProcessExpanded = true;
    if (!keepStats) activeTurnStats = null;
  }

  // ---- 操作 ----

  Future<void> startListening() async {
    if (phase == ChatPhase.listening) return;
    if (!wsConnected) {
      lines.add(ChatLine('note', '未连接服务器，请先在设置页测试连接'));
      notifyListeners();
      return;
    }
    final generation = ++_recordingGeneration;
    // 先亮红灯再启动：UI 反馈即时；启动失败（如权限被拒）回退到 idle
    phase = ChatPhase.listening;
    recordRemaining = recordingLimitSeconds;
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
      // 定时器属于具体的一次录音。即使外部停止与异步启动交错，
      // 过期定时器也必须自行熔断，绝不允许循环追加超时提示。
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
      final remaining = recordingLimitSeconds - elapsed;
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
    // 也避免底层 recorder.stop() 尚未完成时被定时器再次命中。
    phase = config.autoSend ? ChatPhase.thinking : ChatPhase.idle;
    if (timedOut) {
      lines.add(ChatLine('note', '录音超时，已自动停止'));
    }
    final attachmentIds = config.autoSend
        ? pendingAttachments.map((item) => item.id).toList()
        : const <String>[];
    if (attachmentIds.isNotEmpty) {
      _voiceAttachmentIdsInFlight.addAll(attachmentIds);
    }
    ws.sendJson({
      'type': 'audio_end',
      if (attachmentIds.isNotEmpty) 'attachment_ids': attachmentIds,
    });
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

  Future<bool> sendText(String text) async {
    final value = text.trim();
    if (value.isEmpty) {
      if (pendingAttachments.isNotEmpty) {
        lines.add(ChatLine('note', '请先输入或说出你希望如何处理附件，再一起发送'));
        notifyListeners();
      }
      return false;
    }
    if (!wsConnected) {
      lines.add(ChatLine('note', '未连接服务器，请先在设置页测试连接'));
      notifyListeners();
      return false;
    }
    _addUserLine(value);
    final attachmentIds = pendingAttachments.map((item) => item.id).toList();
    pendingAttachments.clear();
    _voiceAttachmentIdsInFlight.removeAll(attachmentIds);
    ws.sendJson({
      'type': 'text_input',
      'text': value,
      if (attachmentIds.isNotEmpty) 'attachment_ids': attachmentIds,
    });
    phase = ChatPhase.thinking;
    notifyListeners();
    return true;
  }

  Future<void> interrupt() async {
    ws.sendJson({'type': 'interrupt'});
    await player.interrupt();
    miruText = '';
    toolStatus = '';
    progressStatus = '';
    _resetActiveTurn();
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

  /// 设置页保存后调用：让新的地址/token/开关立即生效并马上重连。
  Future<void> applyServerSettings() async {
    ws.updateTarget(
      url: config.wsUri,
      token: config.token,
      hello: config.hello,
    );
    _reconnectTimer?.cancel();
    _reconnectAttempts = 0;
    wsStatus = '正在按新设置连接…';
    notifyListeners();
    await ws.reconnect();
  }

  @override
  void dispose() {
    _disposed = true;
    _invalidateRecording();
    _reconnectTimer?.cancel();
    ws.close();
    super.dispose();
  }
}
