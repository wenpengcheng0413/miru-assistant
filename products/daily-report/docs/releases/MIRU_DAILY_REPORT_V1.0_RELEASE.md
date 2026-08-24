# Miru Daily Report V1.0 — Release Document

> **封版日期**: 2026-07-27  
> **封版版本**: v1.0.0  
> **状态**: Production Ready — 进入稳定运行观察期  

---

## 1. 项目简介

Miru Daily Report 是一个 Windows 个人自动化工具。每天 22:00 自动读取电脑微信的群聊消息，通过 DeepSeek LLM 分析，生成 Markdown 日报，并通过 PushPlus 推送到手机微信。

**使用场景**: 一个人管理多个微信群，每天需要了解各群发生了什么，但不想逐群爬楼。

**一句话描述**: 每天晚上 10 点自动把微信群消息总结成日报推送到手机。

---

## 2. V1.0 实现的功能

| # | 功能 | 说明 |
|---|---|---|
| 1 | 微信消息自动采集 | 从微信 PC 客户端内存提取密钥，解密 SQLite 数据库，读取指定群的消息 |
| 2 | DeepSeek LLM 分析 | 对每个群的消息进行分类：紧急任务、截止日期、通知公告、文件资料 |
| 3 | Markdown 日报生成 | Jinja2 模板渲染，结构化日报，含 AI 行动建议 |
| 4 | SQLite 持久化 | 所有日报和运行记录本地存储，WAL 模式，自动迁移 |
| 5 | PushPlus 微信推送 | 日报通过 PushPlus API 推送到手机微信，支持重试和截断保护 |
| 6 | Windows Task Scheduler 自动化 | 每日 22:00 自动触发 + 登录补触发 + 失败 3 次重试 |
| 7 | 三层日志系统 | Shell 层 (launcher.log) → Python 预检层 (bootstrap.log) → Pipeline 层 (miru.log) |

---

## 3. 系统整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Miru Daily Report V1.0                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────┐                                    │
│  │ Windows Task        │  每日 22:00 (+ 登录触发)           │
│  │ Scheduler           │  cmd.exe /c "launcher.bat"         │
│  └────────┬────────────┘                                    │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────┐  Tier 0: Shell 级日志              │
│  │ launcher.bat        │  data/logs/launcher.log            │
│  │ (项目根目录)         │  - 检查 pythonw.exe                │
│  │                     │  - 检查 config/settings.yaml       │
│  └────────┬────────────┘  - 启动 bootstrap.py               │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────┐  Tier 1: Python 预检日志           │
│  │ bootstrap.py        │  data/logs/bootstrap.log            │
│  │ (src/miru/)          │  7 项预检 → 运行 Pipeline          │
│  └────────┬────────────┘                                    │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────────────────────────────┐            │
│  │ MiruPipeline (src/miru/core/pipeline.py)     │            │
│  │                                              │            │
│  │  [1/6] 环境检查 → 微信进程 + 数据目录 + 权限  │            │
│  │  [2/6] 消息采集 → 密钥提取 + 解密 + 读取     │            │
│  │  [3/6] 消息过滤 → 去重 + 清洗 + 分类         │            │
│  │  [4/6] LLM分析  → DeepSeek API              │            │
│  │  [5/6] 日报生成 → Jinja2 + SQLite 保存       │            │
│  │  [6/6] 推送通知 → PushPlus + Console         │            │
│  │                                              │            │
│  │  Tier 2: Pipeline 详细日志                   │            │
│  │  data/logs/miru_YYYY-MM-DD.log               │            │
│  │  data/logs/miru_error_YYYY-MM-DD.log         │            │
│  └─────────────────────────────────────────────┘            │
│                                                              │
│  ┌─────────────────────┐                                    │
│  │ PushPlus API        │  日报推送到手机微信                 │
│  └─────────────────────┘                                    │
│                                                              │
│  ┌─────────────────────┐                                    │
│  │ SQLite (data/miru.db)│ 日报 + 运行记录 + 自动备份         │
│  └─────────────────────┘                                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 自动运行流程图

```
每日 22:00
    │
    ▼
Task Scheduler 触发
    │ Execute: cmd.exe
    │ Arguments: /c "E:\vibe coding\miru-assistant\launcher.bat"
    │ WorkingDirectory: E:\vibe coding\miru-assistant
    │
    ▼
launcher.bat ──────────────────────────────────────────────
    │                                                       │
    │ mkdir data\logs (如果不存在)                           │
    │ echo START >> launcher.log                            │
    │                                                       │
    │ pythonw.exe 存在? ──── NO ──→ [FATAL] exit 1         │
    │ YES                                                   │
    │ config/settings.yaml 存在? ──── NO ──→ [FATAL] exit 1 │
    │ YES                                                   │
    │ pythonw.exe bootstrap.py                               │
    │                                                       │
    │ echo exit code >> launcher.log                        │
    └───────────────────────────────────────────────────────┘
    │
    ▼
bootstrap.py ──────────────────────────────────────────────
    │                                                       │
    │ [预检 1] Python >= 3.11? ── NO ──→ exit 1            │
    │ [预检 2] 依赖可导入?    ── NO ──→ exit 1            │
    │ [预检 3] Config 合法?   ── NO ──→ exit 1            │
    │ [预检 4] Windows 平台?  ── NO ──→ exit 3            │
    │ [预检 5] 管理员权限?    ── NO ──→ exit 3            │
    │ [预检 6] 微信运行?      ── WARN (不阻断)            │
    │ [预检 7] PushPlus Token?── WARN (不阻断)            │
    │                                                       │
    │ 全部 PASS → 初始化 loguru → MiruPipeline.run()        │
    │                                                       │
    │ 退出码: 0=成功 1=永久错误 2=临时错误 3=环境错误       │
    └───────────────────────────────────────────────────────┘
    │
    ▼
MiruPipeline ──────────────────────────────────────────────
    │
    │ 退出码 0/1/2/3 返回给 bootstrap.py
    │ bootstrap.py 返回给 launcher.bat
    │ launcher.bat 返回给 Task Scheduler
    │
    │ Task Scheduler:
    │   退出码 0 → 不重试，下次 22:00 再运行
    │   退出码 1 → 不重试 (永久错误)
    │   退出码 2 → 15 分钟后重试，最多 3 次
    │   退出码 3 → 15 分钟后重试，最多 3 次
    │
    ▼
手机微信收到 Miru Daily 日报推送
```

---

## 5. 三层日志架构

| 层级 | 文件 | 写入者 | 依赖 | 内容 |
|---|---|---|---|---|
| **Tier 0** | `data/logs/launcher.log` | launcher.bat (shell redirect) | 仅 cmd.exe | pythonw.exe 存在性、启动时间、退出码 |
| **Tier 1** | `data/logs/bootstrap.log` | bootstrap.py (open().write()) | Python stdlib | 7 项预检结果、Pipeline 入口/出口 |
| **Tier 2** | `data/logs/miru_YYYY-MM-DD.log` | loguru | 所有 Python 依赖 | Pipeline 6 阶段详细日志 |
| **Tier 2** | `data/logs/miru_error_YYYY-MM-DD.log` | loguru (ERROR only) | 所有 Python 依赖 | 仅错误级别日志 |

**排查流程**: launcher.log → bootstrap.log → miru_*.log  
**日志保留**: Tier 2 自动 30 天滚动；Tier 0/1 手动清理  
**容量估算**: 每天 ~5KB，一个月 ~150KB

---

## 6. 各核心模块说明

### 6.1 launcher.bat（Shell 层入口）

- **位置**: 项目根目录
- **调用者**: Windows Task Scheduler（或手动）
- **职责**: 
  - 确保 `data/logs/` 目录存在
  - 检查 `pythonw.exe` 存在（venv 未损坏）
  - 检查 `config/settings.yaml` 存在
  - 启动 `pythonw.exe bootstrap.py`（静默，无黑窗）
  - 传递退出码给 Task Scheduler
- **关键设计**: `%~dp0` 自定位（移动项目目录无需修改）、所有输出重定向到 launcher.log

### 6.2 bootstrap.py（Python 预检层）

- **位置**: `src/miru/bootstrap.py`
- **调用者**: launcher.bat
- **职责**:
  - 7 项预检（Python 版本、依赖、配置、平台、权限、微信、Token）
  - 预检通过后初始化 loguru 并运行 MiruPipeline
  - 返回结构化退出码
- **关键设计**: 预检阶段仅使用 stdlib + yaml + psutil，确保重型依赖缺失时仍能留下日志

### 6.3 MiruPipeline（核心编排器）

- **位置**: `src/miru/core/pipeline.py`
- **6 阶段**: 环境检查 → 消息采集 → 过滤 → LLM → 日报 → 推送
- **容错**: Step 1 失败终止；Step 2-3 失败终止；Step 4-6 部分失败不阻断
- **自动备份**: 成功后自动备份数据库

### 6.4 消息采集 (src/miru/collector/)

- `diagnostics.py`: 微信进程检测、数据目录定位
- `wechat_db_decrypt.py`: 密钥提取 + SQLCipher 解密
- `wechat_reader.py`: 群列表 + 消息读取（支持 ZSTD 压缩内容）

### 6.5 消息过滤 (src/miru/filter/)

- `dedup.py`: 跨运行去重（基于 server_id）
- `cleaner.py`: 系统消息/非文本/短消息过滤
- `classifier.py`: 基于规则的关键词分类
- `group_filter.py`: 按群名分组

### 6.6 LLM 分析 (src/miru/llm/)

- `client.py`: DeepSeek API 客户端（OpenAI SDK，JSON mode，重试）
- `schemas.py`: Pydantic 结构化输出模型
- `prompts/daily_summary.j2`: Jinja2 提示模板

### 6.7 日报生成 (src/miru/report/)

- `generator.py`: 合并多群结果 + 渲染 Markdown + SQLite 保存
- `formatter.py`: Markdown 截断和转义
- `templates/daily.md.j2`: 日报模板

### 6.8 推送通知 (src/miru/notify/)

- `pushplus.py`: PushPlus HTTP 客户端（重试、截断、超时）
- `console.py`: 控制台输出（debug 用）
- `dispatcher.py`: 推送调度 + DB 状态追踪

### 6.9 存储层 (src/miru/storage/)

- `database.py`: SQLite WAL 模式连接管理
- `models.py`: 数据模型（ChatGroup, RawMessage, DailyReport 等）
- `repository.py`: 仓库层（Group, Message, Report, RunLog）
- `migrations.py`: Schema 版本迁移
- `backup.py`: 自动备份（保留 30 份滚动）

---

## 7. 文件结构说明

```
miru-assistant/                          # 项目根目录
│
├── launcher.bat          ★ V1.0 新增    # Shell 层自动化入口
│
├── config/
│   └── settings.yaml                    # 主配置 (含 API Key/Token/密钥)
│
├── scripts/
│   ├── setup_scheduler.ps1 ★ V1.0 修改  # 安装/更新 Task Scheduler 任务
│   ├── run_daily.py                     # 旧入口 (保留，手动测试用)
│   └── run_daily.bat                    # 旧 bat (保留，参考)
│
├── src/miru/
│   ├── bootstrap.py      ★ V1.0 新增    # Python 预检入口
│   ├── cli/main.py                      # Typer CLI (miru run/status/doctor)
│   ├── collector/                       # 微信消息采集
│   ├── core/                            # Pipeline + 日志 + 退出码
│   ├── filter/                          # 消息过滤
│   ├── llm/                             # DeepSeek 客户端
│   ├── notify/                          # PushPlus 推送
│   ├── report/                          # 日报生成
│   ├── scheduler/                       # 调度器检测 + 健康检查
│   ├── storage/                         # SQLite + 备份
│   └── utils/                           # 配置加载 + 错误类型
│
├── data/
│   ├── miru.db                          # 主数据库
│   ├── logs/                            # ★ V1.0 三层日志输出
│   │   ├── launcher.log                 # Tier 0
│   │   ├── bootstrap.log                # Tier 1
│   │   ├── miru_YYYY-MM-DD.log          # Tier 2
│   │   └── miru_error_YYYY-MM-DD.log    # Tier 2 (Error)
│   └── backups/                         # 数据库自动备份 (30 份)
│
├── tools/                               # 第三方工具 (chatlog_alpha 等)
├── tests/                               # 单元测试
├── docs/                                # 旧版文档
│
├── pyproject.toml                       # Python 项目元数据
├── requirements.txt                     # Python 依赖
│
├── MIRU_DAILY_REPORT_V1.0_RELEASE.md    # ★ 本文档
├── CHANGELOG.md                         # ★ V1.0 新增
└── PROJECT_STATE_V1.0.md                # ★ V1.0 新增
```

**★ 标记 = V1.0 新增或修改的文件**

---

## 8. 自动化流程说明

### 触发方式

| 触发器 | 时间 | 说明 |
|---|---|---|
| Daily | 每天 22:00 | 主触发器 |
| AtLogon | 用户登录后 2 分钟（随机延迟）| 补执行（如果错过了 22:00） |

### 重试策略

| 退出码 | 含义 | Task Scheduler 行为 |
|---|---|---|
| 0 | SUCCESS | 不重试，等待下次触发 |
| 1 | PERMANENT_ERROR | 不重试（配置/依赖问题，重试无意义） |
| 2 | TRANSIENT_ERROR | 重试 3 次，间隔 15 分钟 |
| 3 | ENVIRONMENT_ERROR | 重试 3 次，间隔 15 分钟 |

### 超时保护

- Task Scheduler: 10 分钟执行时间上限
- 正常 Pipeline 耗时: ~10 秒
- 最坏情况 (LLM 超时 + 重试): ~3 分钟

---

## 9. 已解决的问题

### V1.0 修复的主要 Bug

**Bug #1: Task Scheduler 启动 pythonw.exe 失败 (ERROR_FILE_NOT_FOUND)**

- **根因**: `setup_scheduler.ps1` 把含空格的路径 `E:\vibe coding\miru-assistant\venv\Scripts\pythonw.exe` 传给 Task Scheduler 时未用引号包裹
- **现象**: `Last Result: 2`，Python 从未启动，零日志
- **修复**: Task Scheduler 改为 `cmd.exe /c "path\to\launcher.bat"` — cmd.exe 无空格，launcher.bat 路径双引号包裹

### V1.0 工程化改进

| 改进 | 说明 |
|---|---|
| 三层日志架构 | Shell → Python 预检 → Pipeline，从外到内，每层都有日志 |
| 启动前预检 | 7 项检查，失败时明确告知原因，不盲目启动 |
| 自定位路径 | launcher.bat 使用 `%~dp0`，bootstrap.py 使用 `Path(__file__).resolve()` |
| 优雅退出 | 0/1/2/3 结构化退出码，Task Scheduler 据此决策重试 |
| Shell 级防御 | pythonw.exe 不存在或 config 缺失时，在 Shell 层就拦截并记录 |

---

## 10. 已知问题 (Known Issues)

| # | 问题 | 严重程度 | 计划 |
|---|---|---|---|
| 1 | contact.db 解密偶发失败，回退到 Name2Id | 低 — 回退方案工作正常 | V1.1 |
| 2 | ConsoleNotifier GBK emoji 编码错误 | 低 — 不影响 PushPlus 推送 | V1.1 |
| 3 | debug_prompt_* / debug_response_* 散落 logs/ | 低 — 不影响功能 | V1.1 |
| 4 | diagnostics.py 硬编码 E:/ C:/ 路径 | 低 — 仅影响其他电脑上的 `miru doctor` | V1.1 |
| 5 | scheduler.py 相对路径依赖 CWD | 低 — 自动化链路传绝对路径 | V1.1 |
| 6 | settings.yaml 无自动备份 | 中 — 手动备份已文档化 | V1.2 |
| 7 | 无每日健康确认推送（失败才通知） | 中 — 静默成功期无法确认 | V1.2 |
| 8 | 未在非本项目机器上验证过 | 中 — 微信版本/路径假设仅验证了当前环境 | V1.2 |

---

## 11. 运维指南

### 每日检查（30 秒）
22:05 看一眼手机，确认收到微信推送。如果收到 → 一切正常。

### 每周检查（1 分钟）
```powershell
python -m miru.cli.main status
```

### 故障排查流程

```
手机没收到推送？
    │
    ▼
Step 1: 检查 Task Scheduler
    schtasks /query /tn "Miru Daily Report" /v /fo LIST | findstr "上次"
    上次结果 = 0? → 继续 Step 2
    上次结果 != 0? → 查看 launcher.log
    │
    ▼
Step 2: 检查 launcher.log
    Get-Content "data\logs\launcher.log" -Tail 10
    有 [FATAL]? → 按提示修复
    有 START 但没有 exit? → Python 崩溃 → 查看 bootstrap.log
    Bootstrap exited (code=0)? → 继续 Step 3
    │
    ▼
Step 3: 检查 bootstrap.log
    Get-Content "data\logs\bootstrap.log" -Tail 15
    有 [FATAL]? → 按提示修复
    Pipeline complete: SUCCESS? → 继续 Step 4
    │
    ▼
Step 4: 检查 miru.log
    Get-Content "data\logs\miru_2026-07-XX.log" -Tail 20
    搜索 "ERROR" 或 "失败"
    推送阶段是否成功?
    │
    ▼
Step 5: 手动测试
    & "E:\vibe coding\miru-assistant\launcher.bat"
    观察终端输出
```

---

## 12. Backup 与恢复方案

### 必须备份（P0）

| 文件 | 说明 |
|---|---|
| `config/settings.yaml` | API Key、PushPlus Token、微信数据库密钥 |
| `data/miru.db` | 所有历史日报和运行记录 |

### 自动备份

- 数据库：每次 Pipeline 成功后自动备份到 `data/backups/miru_backup_YYYYMMDD_HHMMSS.db`，保留 30 份
- 配置文件：无自动备份，**建议手动备份到安全位置**

### 手动全量备份命令

```powershell
$d = "D:\miru_backup_$(Get-Date -Format 'yyyyMMdd')"
mkdir $d -Force
Copy-Item "config" "$d\config" -Recurse
Copy-Item "data\miru.db" "$d\miru.db"
Copy-Item "launcher.bat" "$d\launcher.bat"
Copy-Item "scripts\setup_scheduler.ps1" "$d\setup_scheduler.ps1"
```

### 恢复

```powershell
Copy-Item "$backupDir\config" "config" -Recurse -Force
Copy-Item "$backupDir\miru.db" "data\miru.db" -Force
python -m miru.cli.main status
```

---

## 13. 部署流程

### 首次部署

```powershell
# 1. 安装 Python 3.11+ (https://python.org)

# 2. 获取项目文件
git clone <repo>  # 或直接复制文件夹
cd miru-assistant

# 3. 创建虚拟环境
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 4. 配置
copy config\settings.example.yaml config\settings.yaml
# 编辑 settings.yaml:
#   填入 DeepSeek API Key
#   填入 PushPlus Token
#   填入关注群名列表
#   填入微信数据库密钥 (通过 miru doctor 获取)

# 5. 诊断验证
python -m miru.cli.main doctor

# 6. 安装自动任务 (以管理员身份)
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1

# 7. 测试
launcher.bat
```

---

## 14. 迁移流程

从旧电脑迁移到新电脑：

```powershell
# 1. 复制项目文件夹到新电脑

# 2. 重建 venv (不能直接复制)
cd "新路径\miru-assistant"
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 3. 更新 config/settings.yaml
#    - wechat.database_key: 运行 miru doctor 获取新环境的密钥
#    - wechat.data_dir: 如果微信数据目录路径不同则更新

# 4. 复制数据库 (保留历史日报)
copy "旧电脑\data\miru.db" "data\miru.db"

# 5. 安装 Task Scheduler
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1

# 6. 测试
launcher.bat
```

---

## 15. 故障排查流程

详见 [第 11 节 — 故障排查流程](#11-运维指南)。

---

## 16. 后续 Roadmap

| 版本 | 内容 | 预计时间 |
|---|---|---|
| **V1.0** | 当前版本 — 稳定运行观察期 | 2026-07-27 |
| **V1.1** | 修复 8 个已知问题 (diagnostics 路径、GBK 编码、debug 文件整理、contact.db 解密优化) | 观察 7 天后 |
| **V1.2** | 每日健康确认推送 + settings.yaml 自动备份 | TBD |
| **V1.3** | 多日趋势分析报告 | TBD |
| **V2.0** | Docker 化 + 跨平台支持 | TBD |

---

> **文档维护者**: Miru Assistant Project  
> **最后更新**: 2026-07-27  
> **版本**: V1.0
