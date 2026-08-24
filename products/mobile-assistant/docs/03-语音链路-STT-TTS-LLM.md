# 03 · 语音链路：STT / TTS / DeepSeek 接入（Q4 / Q5 / Q6）

## 1. STT：SenseVoice 本地部署（Q4）

### 1.1 选型结论

| 方案 | 普通话 | 粤语 | 中英混合 | 延迟 | 成本 | Windows |
|------|--------|------|----------|------|------|---------|
| **SenseVoice-Small（sherpa-onnx）✅** | 优 | 优（自动识别） | 优（`language="auto"`） | 10s 音频 CPU 数百 ms | 免费 | 官方支持 x64 |
| faster-whisper small（本机已有） | 良 | 一般 | 一般 | 1-2s（逐帧解码） | 免费 | ✅ 已在用（V2 语音消息转写） |
| 阿里/腾讯/字节云 STT | 优 | 优 | 优 | 网络 300-800ms | ~2 元/小时起，**按量长期付费** | 无部署问题 |

结论：**SenseVoice 为主，faster-whisper 为兜底**（两个都本地，都不花钱）。SenseVoice 一个模型同时覆盖普通话/粤语/中英混合，正是需求里的三项重点。

### 1.2 部署步骤（Windows，已在 backend 骨架中实现）

```powershell
# 1) 安装（后端可选依赖）
pip install sherpa-onnx        # 官方支持 Windows x64
# 2) 下载模型（脚本内置 hf-mirror 国内镜像，避免 HuggingFace 不通）
python products/mobile-assistant/server/scripts/download_sensevoice.py
#    → products/mobile-assistant/server/data/models/sensevoice/{model.onnx, tokens.txt}
#    → products/mobile-assistant/server/data/models/silero_vad.onnx（可选 VAD）
# 3) 配置 products/mobile-assistant/server/config/settings.yaml
#    stt:
#      engine: sensevoice          # whisper | none
#      model_dir: ./data/models/sensevoice
#      language: auto              # auto/zh/yue/en
# 4) 验证
python products/mobile-assistant/server/scripts/download_sensevoice.py --test data/测试.wav   # 应输出带标点的中文文本
```

### 1.3 流式策略（重要认知）

SenseVoice 是**非自回归整句模型**，不是逐帧流式解码器。"流式感"靠工程手段获得：

1. **部分结果**：用户说话期间，每 800ms 对"本次说话起始点以来的累积音频"跑一次识别（音频短，CPU 上每次 100-300ms），结果作为 `stt_partial` 下发 → 手机上"边说边出字"。
2. **断句即终判**：VAD 判停后立即出 `stt_final`，进入 LLM。
3. 若要真·逐字流式，可再加 sherpa-onnx 的 **streaming Paraformer**（zh 流式模型）做中间结果，SenseVoice 做终判——列为后续优化，MVP 不需要。

### 1.4 实现接口（stt/base.py）

```python
class STTEngine(Protocol):
    name: str
    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str: ...
    # 骨架已提供 SenseVoiceSTT(sherpa-onnx) / WhisperSTT(faster-whisper) / NoneSTT(文本模式)
```

## 2. TTS：MiniMax speech-02-turbo 接入（Q5）

### 2.1 选型结论

| 方案 | 自然度 | 情绪/克隆 | 流式 | 价格 | 结论 |
|------|--------|-----------|------|------|------|
| **MiniMax speech-02-turbo** ✅ | 高 | 情绪参数 + 10s 克隆 | ✅ SSE 句级流式 | ≈2 元/万字符 | **主力** |
| 阿里 CosyVoice v3.5-flash | 高 | 5-20s 克隆 | ✅ | **0.8 元/万字符**（更低） | 备选，可无缝切换 |
| edge-tts（微软 Edge 音色） | 中上 | 无克隆 | ✅ 句级 | 免费 | **兜底**（断网/欠费时保出声） |
| 本地 CosyVoice2 部署 | 高 | 克隆 | ✅ | 免费但吃 GPU（≥6GB） | 看显卡情况，不急 |

选择 MiniMax 的理由：低延迟产品线（turbo）、中文自然、音色克隆只需 10 秒录音、API 稳定多年。**TTS 层做成 Provider 接口，MiniMax 与 CosyVoice 只是两个实现**——价格或体验不合适时改一行配置切换。

### 2.2 接入细节（tts/minimax_tts.py 已实现）

```http
POST {minimax.base_url}/v1/t2a_v2          # 默认 https://api.minimaxi.com（可换国际域名/百炼渠道）
Authorization: Bearer $MINIMAX_API_KEY
{
  "model": "speech-02-turbo",
  "text": "今天群里没有特别重要的消息。",
  "stream": true,
  "stream_options": {"exclude_aggregated_audio": true},   # 只要分块，不要末尾重复的整段
  "audio_setting": {
    "format": "mp3",          # 手机端 MVP 用 mp3；低延迟优化可换 pcm+sample_rate 24000
    "sample_rate": 32000,
    "bitrate": 128000,
    "channel": 1,
    "voice_id": "Calm_Woman"  # 预设音色 或 克隆后的 voice_id
  },
  "voice_setting": {"speed": 1.0, "emotion": "neutral"}
}
```

响应是 SSE 行：`data: {"data":{"audio":"<hex 音频块>","status":1},...}` —— 逐行 `bytes.fromhex()` 得到 mp3 分块，直接二进制帧推给手机；最后一个块 `status: 2` 携带 `extra_info`（audio_length / audio_sample_rate）。**注意**：MiniMax 需要 `GroupId`（控制台可查），配在 `MINIMAX_GROUP_ID`。

### 2.3 手机端播放策略（详见 07 文档）

- MVP：**句级 mp3**——每个 `sentence` 事件后跟整句音频（1-4s），手机用 audioplayers 的 `BytesSource` 排队播放，配合服务端预取 1 句，听感连续。
- 优化：改 `format: pcm` + 24kHz，手机端接 AVAudioEngine 环形缓冲，句间零间隙（方法通道调原生代码，MVP3 再做）。

### 2.4 成本估算

按每天 100 轮语音、平均回复 150 字算：150×100×30 = 45 万字符/月 ≈ **9 元/月**（MiniMax）或 3.6 元（CosyVoice）。克隆音色一次性 9.9 元。可控。

## 3. DeepSeek API 接入（Q6）

### 3.1 连接参数

```
base_url : https://api.deepseek.com        （OpenAI 兼容，直接用 openai SDK）
model    : deepseek-v4-flash              （自动指向 0731 版本）
auth     : Bearer $MIRU_DEEPSEEK_API_KEY
上下文   : 1M token 窗口 / 输出上限 384K → 个人助手场景无压力
```

### 3.2 三个必做配置（语音场景）

```python
client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=messages,
    tools=tool_schemas,                       # Q9 工具
    stream=True,                              # SSE 流式
    stream_options={"include_usage": True},   # 拿到真实 token 数做成本入账
    extra_body={"thinking": {"enabled": False}},  # ★ 语音必须关思考模式
    temperature=0.7,
    max_tokens=2048,                          # 语音回复短，硬顶住防跑题烧钱
)
# 兼容处理：若 API 报 thinking 参数错误（老版本网关），去掉 extra_body 重试一次
```

- **thinking 关闭是硬要求**：默认开启时模型先输出内部推理（按输出 token 计费），TTFT 多几秒且费用翻倍——语音助手的回答不需要长链推理；未来遇到"真的难的问题"可临时开 thinking 或换 pro。
- **流式 + 工具调用的拼接**：`delta.tool_calls` 按 `index` 归并、`function.arguments` 分片拼接（骨架 `core/llm.py` 已实现，这是最容易写错的点）；`finish_reason == "tool_calls"` 表示需要执行工具后继续。

### 3.3 成本结构（影响架构的两个数字）

| 项目 | 单价 | 说明 |
|------|------|------|
| 输入（缓存未命中） | 1 元/M | 首次出现的上下文 |
| **输入（缓存命中）** | **0.02 元/M** | 50 倍价差！→ system prompt 前缀必须稳定（见下） |
| 输出 | 2 元/M | 含 reasoning（我们已关） |
| 高峰时段 | ×2 | 工作日 9-12 / 14-18（北京）；夜间与周末便宜 |

**省钱的系统级动作**：
1. **稳定前缀**：system prompt 顺序固定为 `[persona 核心] → [memory] → [工具使用规则] → [当前时间]`。persona/memory 不变则整段命中缓存；变了也只失效变更点之后的部分。
2. **多轮对话天然吃缓存**：历史消息每次都重复发送，第二次起全部按 0.02 元/M 计——所以多轮上下文放心带，但**单轮超长上下文要摘要化**（记忆系统负责，见 05 文档）。
3. 批量任务（群日报）安排到非高峰时段跑。

### 3.4 接入路径复用

日报项目的 `products/daily-report/src/miru/llm/client.py` 已封装同款 base_url/model/`thinking: disabled` 降级逻辑；手机后端另写流式版（`server/miru_server/core/llm.py`），因为流式工具循环与一次性 JSON 分析是两套调用形态。

## 4. 参考资料（2026-08 调研）

- DeepSeek 模型与价格：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing/>；V4 Flash 上线与参数：<https://apidog.com/blog/deepseek-v4-flash-api/>；峰谷计价与涨价公告：<https://news.sohu.com/a/1059490756_313745>、<https://www.c114.net.cn/industry/108389.html>
- MiniMax TTS 流式与参数：<https://platform.minimaxi.com/docs/guides/pricing-speech>、<https://help.aliyun.com/zh/model-studio/minimax-synchronous-speech-synthesis-api>、<https://help.aliyun.com/zh/model-studio/speech-02-turbo>
- CosyVoice：<https://help.aliyun.com/zh/model-studio/cosyvoice-v3.5-flash.md>
- SenseVoice / sherpa-onnx：<https://github.com/FunAudioLLM/SenseVoice>、<https://github.com/k2-fsa/sherpa-onnx>（模型 `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`，`yue`=粤语）
- DeepSeek 流式工具调用分片拼接：<https://github.com/mystous/vllm_hybrid/blob/1ff658a67eea5ef8c42fdf92c3507c0b5025cf96/vllm/tool_parsers/deepseekv31_tool_parser.py>、<https://bumo.cc/blog/llm-api-streaming-output-function-calling-openai-compatible-guide>
- Tailscale HTTPS 证书：<https://tailscale.com/kb/1153/enabling-https>
