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

## 联系人聊天记录导出（V2 Chat Analyzer）

Miru V2 支持**离线导出指定联系人的全部聊天记录**并自动分析（AI 总结 / 统计 / 时间线）。
离线模式直接读取微信加密数据库，**无需微信运行**，也**不需要管理员权限**。

### 1. 配置联系人白名单

在 `config/settings.yaml` 中添加（推荐填 `wxid`，最可靠）：

```yaml
miru:
  contacts:
    enabled: true
    whitelist:
      - name: Krista                 # 显示名（输出目录名）
        wxid: "wxid_xxxxxxxxxxxxxxxx"  # 微信内部 ID（真实匹配依据）
        enabled: true
```

> 不知道 wxid？运行 `miru doctor` 查看微信账号，或使用 `scripts/extract_db_keys.py`
> 配合 `config/contacts.yaml`（旧格式：`name` + `username` + `remark`，兼容回退）。

### 2. 导出与分析

```bash
# 导出单个联系人（导出 + AI 分析 + 统计 + 时间线）
miru export --contact Krista

# 只导出不分析（省钱）
miru export --contact Krista --skip-analyze

# 导出白名单全部联系人
miru export --all

# 群聊导出（在线模式，需微信运行 + 管理员权限）
miru export --group "测试群"

# 媒体处理开关（图片附件 + 语音转文字，默认跟随 settings.yaml 配置）
miru export --contact Krista --with-media    # 强制开启
miru export --contact Krista --no-media      # 强制关闭
```

### 3. 语音转文字 + 图片保留（媒体导出）

导出时自动处理语音与图片消息（默认开启，可在 `settings.yaml` 的 `miru.export.media` 关闭）：

- **语音转文字**：从 `media_0.db` 提取语音（SILK 格式），本地 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 转写为中文文本。`chat.txt` 中显示为 `[语音转文字] xxx（时长 3s）`。首次使用自动下载模型（small 约 460MB，存于 `data/models/`）；转写结果缓存（`data/stt_cache.json`），重复导出不重复转写。
- **图片保留**：解密微信 4.x 图片 `.dat`（V1 固定密钥 / V2 从微信进程内存提取），导出到 `media/img/` 并在 `chat.txt` 中引用路径。解密失败自动保留 `.dat` 原件并标注 `[图片未解密]`。

输出结构（启用媒体后）：

```
output/
└── Krista/
    ├── chat.txt            # 可读版（语音行含转写文本，图片行含路径）
    ├── chat_raw.txt        # 原始完整版（全部 message_content 原样，含 XML）
    ├── analysis.md         # AI 分析报告（--skip-analyze 时无）
    ├── statistics.json     # 统计指标（消息数/高频词/响应时间等）
    ├── timeline.json       # 事件时间线（话题聚类）
    └── media/
        ├── img/xxx.jpg     # 解密导出的图片（失败时保留 .dat 原件）
        └── voice/xxx.wav   # 语音原件（keep_voice_files 开启时）
```

> **图片解密说明**：微信 4.x 图片 `.dat` 为 V2 加密，Miru 会自动从磁盘派生密钥
> （`aes_key = MD5(uin + wxid)`，从账号目录后缀 + 图片尾部投票推断），**无需微信运行，
> 完全离线**。解密失败（如未下载的图片）自动保留 `.dat` 原件，不丢数据。
>
> **格式说明**：微信 4.x 高清原图是私有 **WXGF/HEVC 格式**（压缩率高但标准解码器
> 无法恢复色度，ffmpeg/libde265 均验证色度丢失）。Miru 因此采用：
> - **`xxx.jpg`** — 微信标准缩略图（`_t.dat` 解密，颜色正确、可直接查看）
> - **`xxx.wxgf`** — 高清原图备份（微信客户端可正常查看）
> - 聊天记录中引用 jpg，高清原件不丢失

### 4. 批量脚本

```bash
# 与 CLI 等价的一键批量流程
python scripts/analyze_all.py                    # 白名单全部
python scripts/analyze_all.py --contacts Krista  # 指定联系人
python scripts/analyze_all.py --skip-analyze     # 跳过 AI 分析
```

### 5. 实现原理（简述）

- 会话表名 = `Msg_{MD5(wxid)}`（微信 4.x），同一会话跨分片（message_0~5.db）存储
- 密钥来自微信账号目录 `all_keys.json` 或 `config/database_keys.yaml`（由 `scripts/extract_db_keys.py` 提取）
- 会话定位：各分片 `Name2Id`（wxid → rowid）+ `Msg_*` 表 `real_sender_id` 精准匹配
- 消息内容：ZSTD 解压 + `sender_id\ncontent` 解析；非文本（图片/语音/链接）提取摘要

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
