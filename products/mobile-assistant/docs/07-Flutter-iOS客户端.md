# 07 · Flutter iOS 客户端（Q2）

> 定位：**Miru 的身体**。只做麦克风、播放、UI 与设置，所有业务逻辑在后端。

## 1. 包与架构

```yaml
# pubspec 依赖（全部主流、长期维护；状态管理用内置 ChangeNotifier，零额外依赖）
web_socket_channel    # WS 长连接
record                # 录音（支持 pcm16bits / 16kHz）
audioplayers          # TTS 句级 mp3 播放
dio                   # REST（设置/记忆/成本页）
shared_preferences    # 服务器地址
flutter_secure_storage# token 存 Keychain
```

```
lib/
├── main.dart / app.dart
├── core/
│   ├── config.dart          # 服务器地址/端口/token 读取
│   ├── ws_client.dart       # WS 收发封装：自动重连、心跳、事件流
│   └── audio/
│       ├── recorder_service.dart   # 16kHz PCM16 分帧 → WS 二进制帧
│       └── player_service.dart     # sentence 事件+mp3 队列播放、打断清空
├── features/
│   ├── chat/                # 对话 UI：字幕流、工具状态 chip、按住说话按钮
│   │   ├── chat_screen.dart
│   │   └── chat_controller.dart    # 状态机
│   └── settings/            # 服务器设置 / Persona 编辑 / 记忆管理 / 成本面板
```

## 2. 录音（recorder_service.dart 核心）

```dart
final recorder = AudioRecorder();
await recorder.start(const RecordConfig(
  encoder: AudioEncoder.pcm16bits,
  sampleRate: 16000, numChannels: 1,
  autoGain: true, echoCancel: true, noiseSuppress: true,
), path: ''); // 空 path = 流式

// record 包暴露 onAmplitudeChanged / 数据流；按 100ms 切帧后:
ws.sink.add(Uint8List chunk);   // 二进制帧 → 服务端 VAD 断句
```

要点：**PCM16 16kHz mono = 32KB/s**，局域网完全无压力；手机端不做 VAD（后端统一做，便于调参与换 Silero），"按住说话"松手发 `audio_end`。

## 3. WS 客户端（ws_client.dart 核心）

```dart
final channel = WebSocketChannel.connect(
  Uri.parse('wss://miru-pc.xxx.ts.net:8765/ws/session'),
);
// 首帧握手
channel.sink.add(jsonEncode({'type':'hello', 'token': token,
  'device':'iphone', 'mode':'voice', 'persona':'miru'}));

// 事件流分发（二进制帧=音频，文本帧=JSON 事件）
await for (final frame in channel.stream) {
  if (frame is Uint8List) { playerService.feed(frame); continue; }
  switch (jsonDecode(frame)['type']) {
    case 'stt_partial': …        // 半透明大字显示识别中
    case 'llm_delta':   …        // 字幕流
    case 'tool_start':  …        // "正在读取群消息…"
    case 'sentence':    …        // 预告下一句（可选字幕高亮）
    case 'turn_end':    …        // 显示本轮成本
    case 'server_note': …
  }
}
// 断线重连：指数退避 + 带 conversation_id 重新 hello 续上会话
```

## 4. 播放（player_service.dart）

MVP = **句级 mp3 队列**（服务端每句发 `sentence` 事件 + 紧跟的音频帧）：

```dart
final _queue = <Uint8List>[];
void feed(Uint8List mp3Chunk) { _queue.add(mp3Chunk); _pump(); }

Future<void> _pump() async {
  if (_playing) return; _playing = true;
  while (_queue.isNotEmpty && !_interrupted) {
    final bytes = _queue.removeAt(0);
    await _player.play(BytesSource(bytes));   // audioplayers
  }
  _playing = false;
}
void interrupt() { _interrupted = true; _player.stop(); _queue.clear(); ws.send('interrupt'); }
```

- 服务端预取 1 句 → 播放器队列里永远有存货 → 句间无停顿
- 打断（barge-in）：点击停止按钮 → 清队列 + 发 `interrupt`，后端停 LLM/TTS，等新输入
- 升级位（MVP3）：`format: pcm` + 原生 AVAudioEngine 环形缓冲，句间零间隙；先不做

## 5. 对话状态机（chat_controller）

```
idle ──按住说话──▶ listening ──松手/audio_end──▶ thinking ──首句音频──▶ speaking ──▶ idle
 │                    ▲                              │  ▲（收到 tool_start → thinking）│
 └──interrupt 打断────┴──────────────────────────────┴──┘（speaking 中可打断回 listening）
```

UI 元素：大号按住说话按钮（MVP 主交互）＋ 可选的"自动听"开关（靠后端 VAD）、识别中的半透明字、回答字幕流、工具执行 chip（"正在分析聊天记录…"）、打断按钮、本轮费用角标（用户关心的成本，第一版就显示）。

## 6. 自签部署（SideStore + LiveContainer）实测约束

| 事项 | 结论 |
|------|------|
| 麦克风 | ✅ **普通权限**，自签可用；LiveContainer 下权限在宿主层授予一次即可 |
| 后台/推送 | ❌ 无 APNs、无 App Extensions → 主动提醒只能靠 App 前台 WS 长连接（MVP8 的早报=打开 App 即收到） |
| 7 天签名 | SideStore 设备上 Wi-Fi 刷新；LiveContainer JIT-less 模式需与宿主同证书签名 |
| Info.plist | 必须加 `NSMicrophoneUsageDescription`；局域网 HTTP 调试需 ATS 例外 + `NSLocalNetworkUsageDescription`；Tailscale/frp 阶段走 HTTPS 则无需 ATS 例外 |
| 安全 | 只用官方版 LiveContainer（第三方构建可读钥匙串）；guest App 之间不隔离，别往里装来路不明的 IPA |
| 打包 | 本机（有 Xcode 的 Mac 或云端 Mac）`flutter build ipa --release` → 签名工具注入描述文件 |

## 7. 开发顺序建议

1. 先在本机跑 `server/scripts/ws_chat.py` 终端对话，验证后端全链路（**不需要 iPhone**）
2. `flutter create` 建壳 → 接入 lib/ 代码 → 先用文字输入跑通对话页
3. 接录音 + 播放 → 局域网内全链路语音验证
4. 配 Tailscale + HTTPS → 出门也能用
5. 再迭代 Persona/记忆/成本等设置页
