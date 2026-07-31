# Miru Assistant

> 🤖 AI 微信秘书 —— 自动总结微信群消息，生成日报推送到手机。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-V1%20开发中-orange.svg)]()

---

## 这是什么？

Miru（ミル，日语"看/观察"）是一个运行在你 Windows 电脑上的 AI 助理。

它**不是聊天机器人**。它更像一个每天默默帮你梳理信息的秘书：

- 每天定时自动读取你指定微信群的消息
- 用 AI 识别老师通知、作业、Deadline、文件等重要信息
- 自动忽略闲聊和表情包
- 生成一份结构化的日报，推送到你的手机微信

## 当前状态

**V1.0 开发中** — 项目骨架阶段 (Task 0)

| 阶段 | 功能 | 状态 |
|------|------|------|
| V1.0 | 项目骨架 + 基础架构 | 🚧 进行中 |
| V1.0 | 微信消息自动采集 | ⏳ 待开发 |
| V1.0 | DeepSeek AI 智能总结 | ⏳ 待开发 |
| V1.0 | 日报生成 + 推送 | ⏳ 待开发 |
| V1.1 | 定时调度 + Windows 集成 | ⏳ 待开发 |
| V2 | Todo 自动维护 | 📋 规划中 |
| V3 | 自然语言问答 | 📋 规划中 |

## 系统架构

```
微信群消息（微信 PC 本地数据库）
    ↓
消息采集层（SQLCipher 解密 + SQL 查询）
    ↓
消息过滤层（去重 / 清洗 / 分组）
    ↓
LLM 调用层（DeepSeek V4 Flash API）
    ↓
日报生成层（Jinja2 模板渲染）
    ↓
消息推送层（PushPlus → 手机微信）
```

## 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.11+ |
| CLI | Typer + Rich |
| 日志 | Loguru |
| 配置 | YAML + Pydantic |
| 数据库 | SQLite |
| 调度 | APScheduler 3.11 |
| LLM | DeepSeek V4 Flash (OpenAI SDK) |
| 推送 | PushPlus |
| 模板 | Jinja2 |
| 质量 | Ruff + MyPy + Pytest |

## 快速开始

### 环境要求

- Windows 10/11 x64
- Python 3.11 或更高版本
- 微信 PC 版（已登录）
- DeepSeek API Key
- PushPlus Token

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/miru-team/miru-assistant.git
cd miru-assistant

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate    # Windows CMD
# 或
source venv/Scripts/activate  # Git Bash

# 3. 安装依赖
pip install -e .
# 开发依赖
pip install -e ".[dev]"

# 4. 初始化配置
cp config/settings.example.yaml config/settings.yaml
# 编辑 settings.yaml，填入你的群名

# 5. 设置环境变量
export MIRU_DEEPSEEK_API_KEY=sk-xxxxxxxx
export MIRU_PUSHPLUS_TOKEN=xxxxxxxx
```

### 使用

```bash
# 查看帮助
miru --help

# 校验配置
miru config validate

# 查看运行状态
miru status

# 手动运行一次日报（V1.0 完成后可用）
# miru run
```

## 项目结构

```
miru-assistant/
├── config/                         # 配置文件
│   ├── settings.example.yaml       #   配置模板
│   └── groups.example.yaml         #   群组配置模板
├── src/miru/                       # 源码
│   ├── cli/                        #   命令行界面
│   ├── core/                       #   核心编排
│   ├── collector/                  #   消息采集（微信 DB 解密）
│   ├── filter/                     #   消息过滤（去重/清洗）
│   ├── llm/                        #   LLM 调用（DeepSeek）
│   ├── report/                     #   日报生成
│   ├── notify/                     #   消息推送
│   ├── scheduler/                  #   定时调度
│   ├── storage/                    #   数据持久化
│   └── utils/                      #   工具（日志/配置/异常）
├── tests/                          # 测试
├── scripts/                        # 运维脚本
├── docs/                           # 文档
└── data/                           # 运行时数据（gitignore）
    ├── miru.db                     #   SQLite 数据库
    └── logs/                       #   日志文件
```

## 开发路线

详见 [`docs/`](docs/) 目录下的设计文档：

- [消息采集方案研究报告](docs/miru-assistant-v1-design.md)
- [V1 Implementation Design](docs/miru-assistant-v1-design.md)
- [V1.0 Technical Specification](docs/miru-assistant-v1-technical-spec.md)

## 许可证

MIT License — 见 [LICENSE](LICENSE) 文件。

## 致谢

- [WeChatMsg](https://github.com/LC044/WeChatMsg) — 微信数据库解密参考
- [wechat-decrypt](https://github.com/328336690/wechat-decrypt) — 微信 4.x 解密方案
- [DeepSeek](https://deepseek.com/) — 高性价比 LLM API
- [PushPlus](http://www.pushplus.plus/) — 免费微信推送服务

---

> 🏗️ **当前处于 V1.0 开发早期阶段。** 如果你对这个项目感兴趣，欢迎 Watch 或 Star。
