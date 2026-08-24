# Miru Mobile Assistant

当前主力产品：以 Flutter 手机端作为入口，由 Windows 上的 Python 服务完成语音识别、LLM 工具调用、记忆、成本记录和语音合成。

```text
app/ ── WebSocket / REST ──> server/
                                 │
                                 └─ 可选导入 ../../daily-report/src/miru
                                    （仅微信查询工具）
```

## 目录职责

- `app/`：Flutter 客户端，负责录音、播放、聊天界面、服务发现和连接设置。
- `server/`：FastAPI 后端，负责 STT → LLM/Tool → TTS 流式管线、Memory、Persona 和成本账本。
- `docs/`：协议、数据库、语音链路、安全和路线图等设计文档。

## 快速入口

- 客户端装配与构建：[app/README.md](app/README.md)
- 后端安装、配置和启动：[server/README.md](server/README.md)
- 工程设计文档：[docs/README.md](docs/README.md)

后端数据库、模型、日志和调试产物统一放在 `server/data/`，真实配置放在 `server/config/`；这些本机数据不会提交到 Git。
