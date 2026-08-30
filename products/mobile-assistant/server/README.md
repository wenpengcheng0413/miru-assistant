# Miru Server —— 语音 AI 工作台后端

设计文档：[docs/](../docs/README.md)（架构 / 流式管线 / STT / TTS / Tool / Memory / Persona / 成本 / 安全 / 路线图）

## 功能

- `WebSocket /ws/session`：语音/文字会话（协议见 `../docs/02-流式管线与通信协议.md` §3）
  - 上行 PCM16/16kHz 音频帧 + JSON 控制消息；下行 JSON 事件 + TTS 音频帧
  - VAD 断句 → 本地 STT（SenseVoice）→ DeepSeek V4 Flash 流式（函数调用工具循环）→ 句级 TTS（MiniMax，edge-tts 兜底）
  - 打断（interrupt）、多轮上下文、会话落库、每轮成本入账
- `REST /api/*`：会话 / 记忆 / Persona / 成本报表与预算 / 调试端点（见 `../docs/06-数据库与API设计.md` §2）
- 记忆系统：画像/偏好/项目/知识 + 对话后自动提取（可关，可一键清空）
- 成本账本：pricing.yaml 价格表、高峰 ×2、预算提醒/硬顶
- 微信工具（可选）：复用现有 `miru` 包（离线读库/统计/搜索），隐私分档 aggregates/samples/raw

## 快速开始

```powershell
cd products/mobile-assistant/server

# 1. 依赖（新环境建议每个项目使用独立 .venv）
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -e .

# 2. 配置
copy config\settings.example.yaml config\settings.yaml
copy config\persona.example.yaml config\persona\miru.yaml
#    编辑 settings.yaml：至少设置 llm.api_key（或环境变量 MIRU_DEEPSEEK_API_KEY）
#    （.env.example 里的环境变量会自动通过 ${VAR} 被 settings.yaml 引用）

# Cloud profile（Linux/云端；不导入微信/Windows 运行时、不加载本地 STT）
$env:MIRU_PROFILE = "cloud"

# 3. 启动
.\.venv\Scripts\python -m miru_server            # http://127.0.0.1:8765

# 家庭电脑一次性安装（管理员 PowerShell）：开机启动、异常重启、局域网防火墙
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1

# 4. 终端文字对话（验证全链路，不需要 iPhone）
.\.venv\Scripts\python scripts\ws_chat.py --token <你的token>

# 5. （可选）本地 STT
.\.venv\Scripts\python -m pip install sherpa-onnx numpy
.\.venv\Scripts\python scripts\download_sensevoice.py

# 6. （可选）PC 麦克风全链路语音调试
.\.venv\Scripts\python -m pip install sounddevice
.\.venv\Scripts\python scripts\voice_chat.py --token <你的token>

# 7. （可选）启用微信查询工具时，安装日报项目的分析包
.\.venv\Scripts\python -m pip install -e ..\..\daily-report
```

## 测试

```powershell
cd products/mobile-assistant/server
.\.venv\Scripts\python -m pytest
```

全部离线（FakeLLM 脚本化验证工具循环/落库/成本），无需 API key。

## 配置要点

| 项 | 说明 |
|----|------|
| `MIRU_SERVER_TOKEN` | cloud profile 必须设置；缺失时拒绝启动。development 可临时生成（不写入日志） |
| `server.host` | 默认 127.0.0.1；手机连局域网用 0.0.0.0；**永远不要裸奔公网**（用 Tailscale/frp，见 `../docs/01-总体架构与选型.md` §6） |
| `server.advertise_lan` | 默认开启 `_miru._tcp` Bonjour 广播，手机可自动发现 DHCP 变化后的电脑地址 |
| `stt.engine: none` | 没下载模型也能跑（纯文本模式）；`sensevoice` 需先跑下载脚本 |
| `tts.provider: none` | 不出声但文字照常；`minimax` 需 MINIMAX_API_KEY + MINIMAX_GROUP_ID |
| `tools.enabled` | 工具白名单；微信工具默认关闭（需本机安装现有 miru 包） |

### MiniMax 接入注记

MiniMax 官方要求 GroupId（控制台 API 页面可查），本实现的 Authorization 头为
`Bearer <api_key>?GroupId=<group_id>`。若你的账户/渠道（国际站、阿里云百炼）
格式不同，改 `miru_server/tts/minimax_tts.py` 的 `_headers()` 即可（约 5 行）。
百炼渠道也可直接换成 DashScope 的 CosyVoice 实现（接口同 `tts/base.py`）。

## 目录

```
miru_server/
├── api/       ws.py（会话入口） rest.py（管理接口） deps.py（鉴权）
├── core/      pipeline.py（主循环） llm.py（DeepSeek 流式） splitter.py events.py
├── stt/       sensevoice.py whisper_stt.py vad.py（能量法）
├── tts/       minimax_tts.py edge_tts.py queue.py（句队列+预取）
├── tools/     registry.py + builtin/{system,memory,api_cost,wechat}.py
├── memory/    store.py extractor.py
├── persona/   builder.py
├── cost/      tracker.py pricing.py
├── db/        models.py database.py
├── config.py  services.py  main.py
scripts/       ws_chat.py voice_chat.py download_sensevoice.py
tests/         pytest（离线）
config/        settings.example.yaml persona.example.yaml pricing.yaml
```
