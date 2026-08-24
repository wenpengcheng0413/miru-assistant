# Miru 语音 AI 工作台 —— 工程设计文档

> 面向可落地的工程方案，配套代码在同一产品目录的 `server/`（包名 `miru_server`）。
> 本文档回答需求书中的 24 个问题，速查表见下。

## 24 问速查

| # | 问题 | 答案位置 |
|---|------|----------|
| 1 | 整体技术栈 | [01-总体架构与选型](01-总体架构与选型.md) §2 |
| 2 | Flutter iOS 客户端架构 | [07-Flutter-iOS客户端](07-Flutter-iOS客户端.md) |
| 3 | FastAPI Backend 架构 | [01-总体架构与选型](01-总体架构与选型.md) §4 |
| 4 | STT 选择与部署 | [03-语音链路-STT-TTS-LLM](03-语音链路-STT-TTS-LLM.md) §1 |
| 5 | TTS 选择与接入 | [03-语音链路-STT-TTS-LLM](03-语音链路-STT-TTS-LLM.md) §2 |
| 6 | DeepSeek API 接入 | [03-语音链路-STT-TTS-LLM](03-语音链路-STT-TTS-LLM.md) §3 |
| 7 | 流式 STT/LLM/TTS 实现 | [02-流式管线与通信协议](02-流式管线与通信协议.md) |
| 8 | WebSocket 与 HTTP 分工 | [01-总体架构与选型](01-总体架构与选型.md) §5 |
| 9 | Tool/Skill 插件架构 | [04-Tool与Skill系统](04-Tool与Skill系统.md) §1-3 |
| 10 | Memory 系统 | [05-Memory与Persona](05-Memory与Persona.md) §1 |
| 11 | Persona 系统 | [05-Memory与Persona](05-Memory与Persona.md) §2 |
| 12 | 微信分析模块接入 | [04-Tool与Skill系统](04-Tool与Skill系统.md) §4 |
| 13 | 图片/语音模块接入 | [04-Tool与Skill系统](04-Tool与Skill系统.md) §5 |
| 14 | API Cost Tracking | [08-成本控制与安全风险](08-成本控制与安全风险.md) §1 |
| 15 | iPhone↔Windows 安全通信 | [01-总体架构与选型](01-总体架构与选型.md) §6 |
| 16 | 迁移云服务器 | [09-MVP路线图与云迁移](09-MVP路线图与云迁移.md) §3 |
| 17 | 项目目录结构 | [01-总体架构与选型](01-总体架构与选型.md) §7 |
| 18 | 数据库设计 | [06-数据库与API设计](06-数据库与API设计.md) §1 |
| 19 | API 接口设计 | [06-数据库与API设计](06-数据库与API设计.md) §2 |
| 20 | MVP1 具体功能 | [09-MVP路线图与云迁移](09-MVP路线图与云迁移.md) §1 |
| 21 | 后续扩展路径 | [09-MVP路线图与云迁移](09-MVP路线图与云迁移.md) §2 |
| 22 | 本地 vs API 边界 | [01-总体架构与选型](01-总体架构与选型.md) §3 |
| 23 | 降低长期 API 成本 | [08-成本控制与安全风险](08-成本控制与安全风险.md) §2 |
| 24 | 隐私/安全/微信风险 | [08-成本控制与安全风险](08-成本控制与安全风险.md) §3 |

本版的会话侧边栏、附件、DeepSeek Vision、微信语音转写与 Codemagic 手动 IPA 发布见 [11-会话附件与IPA发布](11-会话附件与IPA发布.md)。

## 一句话架构

**iPhone（Flutter，录音+播放）──WebSocket──▶ Windows PC 后端（FastAPI，流式管线）──▶ DeepSeek V4 Flash（大脑+函数调用）──▶ Tool 层（微信分析/记忆/成本……）──▶ 结果流式经 MiniMax TTS 合成为语音送回手机。**

STT 在 PC 本地（SenseVoice，免费不限量），记忆和成本账本在本地 SQLite，微信数据不出 PC（默认只把统计/摘要送给 LLM）。

## 推荐阅读顺序

1. [01-总体架构与选型](01-总体架构与选型.md) —— 先建立全局观
2. [02-流式管线与通信协议](02-流式管线与通信协议.md) —— 核心体验所在
3. [06-数据库与API设计](06-数据库与API设计.md) + [09-MVP路线图](09-MVP路线图与云迁移.md) —— 决定先写什么代码
4. 其余按需查阅；后端代码 [server/README.md](../server/README.md) 有启动步骤

## 代码状态

| 部分 | 状态 |
|------|------|
| `server/` Miru 后端（WS 会话、DeepSeek 流式+工具循环、TTS、STT 接口、记忆、成本、测试） | ✅ 已搭建，见 [server/README.md](../server/README.md) |
| `server/scripts/ws_chat.py` 终端文字对话调试 | ✅ 可用 |
| `server/scripts/voice_chat.py` PC 麦克风全链路调试（可选 sounddevice） | ✅ 可用（pcm 直播 / mp3 走 ffplay） |
| `server/scripts/download_sensevoice.py` 下载本地 STT 模型 | ✅ 可用（模型已下载） |
| `server/scripts/e2e_check.py` 一键端到端自检 | ✅ 可用（真实链路 6/6 通过，见 [10-验证报告](10-验证报告-2026-08-13.md)） |
| Flutter iOS 客户端 | ✅ 完整源码在 `app/`（lib 全套 + pubspec + 装配说明），待 Flutter 环境编译 |
