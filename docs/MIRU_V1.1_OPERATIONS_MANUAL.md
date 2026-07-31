# Miru v1.1 — 运维与使用手册

> **版本**: v1.1  
> **最后更新**: 2026-07-27  
> **适用范围**: Miru Assistant 生产环境  
> **前提**: Windows 10/11 + 微信 PC 客户端 + Python 3.12

---

# 第一章：项目简介

## Miru 是什么

Miru 是一个**个人 AI 微信秘书**。每天自动读取你关注的微信群消息，使用 DeepSeek 大模型进行智能分析，生成结构化日报，然后通过 PushPlus 推送到你的手机微信。

## 每天自动执行流程

```
Windows Task Scheduler (每天 22:00)
  │
  ├── scripts/run_daily.bat
  │     │
  │     ├── [1/6] 检测微信进程 + 数据目录
  │     ├── [2/6] 解密 message_0.db → 读取群消息
  │     ├── [3/6] 过滤 (去重 / 系统消息 / 短消息 / 非文本)
  │     ├── [4/6] DeepSeek LLM 分析 (thinking disabled, JSON mode)
  │     ├── [5/6] 生成 Markdown 日报 → 保存数据库
  │     └── [6/6] PushPlus 推送到微信
  │
  └── 日志写入 data/logs/
```

## 完整数据流

```
┌─────────────────────────────────────────────────────────┐
│                    微信 PC 客户端                          │
│  E:\wechatfiles\xwechat_files\wxid_...\db_storage\      │
│  ├── message\message_0.db  (加密 SQLCipher)              │
│  └── contact\contact.db    (加密 SQLCipher, 不同密钥)     │
└──────────────────────┬──────────────────────────────────┘
                       │ database_key (config 手动提供)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Miru Collector (消息采集)                     │
│  ├── wechat_db_decrypt.py  → SQLCipher 解密               │
│  ├── wechat_reader.py      → 读取群列表 + 消息              │
│  └── diagnostics.py        → 检测微信进程                  │
└──────────────────────┬──────────────────────────────────┘
                       │ 12 raw messages (4 groups)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Miru Filter (消息过滤)                        │
│  ├── dedup.py       → 跨天去重 (server_id)                │
│  ├── cleaner.py     → 系统消息 / 非文本 / 短消息过滤         │
│  ├── classifier.py  → 消息分类                            │
│  └── pipeline.py    → build_llm_context()                │
└──────────────────────┬──────────────────────────────────┘
                       │ 10 valid messages → formatted text
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Miru LLM (DeepSeek 分析)  ★ v1.1 升级重点   │
│  ├── client.py           → DeepSeekClient                │
│  │   ├── thinking=disabled (消除推理 Token 浪费)           │
│  │   ├── response_format=json_object                      │
│  │   ├── max_tokens=4096                                  │
│  │   ├── 自适应 retry (TokenBudget / Empty / JSON error)  │
│  │   ├── Prompt 长度保护 (24000 chars)                     │
│  │   └── 失败时自动保存 debug artifacts                    │
│  ├── prompts/daily_summary.j2 → Jinja2 模板               │
│  └── schemas.py             → GroupAnalysis (Pydantic)    │
└──────────────────────┬──────────────────────────────────┘
                       │ GroupAnalysis (JSON parsed)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Miru Report (日报生成)                        │
│  ├── generator.py  → Markdown 渲染 + DB 保存               │
│  └── templates/daily.md.j2 → 日报模板                     │
└──────────────────────┬──────────────────────────────────┘
                       │ Markdown report
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Miru Notify (推送)                            │
│  ├── pushplus.py   → PushPlus HTTP API                   │
│  │   URL: http://www.pushplus.plus/send                   │
│  │   channel=wechat, template=markdown                    │
│  └── console.py    → 控制台输出 (调试用)                    │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP POST
                       ▼
              ┌────────────────────┐
              │  你的手机微信        │
              │  (PushPlus 公众号)   │
              └────────────────────┘
```

## 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| **CLI** | `src/miru/cli/` | 命令行入口 (`miru doctor`, `miru run` 等) |
| **Core** | `src/miru/core/` | Pipeline 编排器 + 运行上下文 |
| **Collector** | `src/miru/collector/` | 微信进程检测、数据库解密、消息读取 |
| **Filter** | `src/miru/filter/` | 消息去重、清洗、分类、LLM 上下文构建 |
| **LLM** | `src/miru/llm/` | DeepSeek API 客户端 (★ v1.1 核心升级) |
| **Report** | `src/miru/report/` | 日报 Markdown 生成 + 数据库持久化 |
| **Notify** | `src/miru/notify/` | PushPlus / Console 推送 |
| **Storage** | `src/miru/storage/` | SQLite 数据库 + 迁移 + 备份 |
| **Scheduler** | `src/miru/scheduler/` | Windows Task Scheduler 健康检查 |
| **Utils** | `src/miru/utils/` | 配置加载、日志、错误类型 |

---

# 第二章：v1.1 升级内容总览

## 升级时间线

```
Phase 1     → LLM Client 重构 (thinking disabled + 自适应 retry + JSON extractor)
Phase 1.5   → 完整 Debug RCA (定位 root cause: thinking Token 吃掉 JSON 输出)
Phase 1.6   → 代码质量 (ruff/mypy clean, 异常命名修正, 死代码删除)
Prod Review → 97→98 分生产评审 (B1 死代码 / B2 命名 / C2 防御性检查)
Phase 1.7   → Production Polish (6 项修复, 最终 98/100)
Phase 2     → config max_tokens 2048→4096
Phase 3     → Production Validation (dry-run + LLM test + failure paths)
Phase 3.5   → Replay Mode (历史日报回放 + Push 验证)
```

## 各 Phase 详情

### Phase 1 — LLM Client 重构

**为什么修改**: 日报偶发性为空。RCA 发现 `deepseek-v4-flash` 是 Reasoning 模型，thinking Token 占用 max_tokens 配额，导致 JSON 输出被截断或完全为空。

**修改内容**:
- `src/miru/llm/client.py` — 核心重写
- 默认 `thinking=disabled` (消除非确定性 Token 消耗)
- `max_tokens` 2048→4096 (config + 代码默认值)
- 新增 `_handle_response()` (finish_reason 前置检测)
- 新增 `_extract_json()` (处理 Markdown fence + 前置文字)
- 新增 `_save_debug_artifacts()` (失败自动保存 prompt + response)
- 自适应 inline retry (3 种错误 → 3 种策略)
- Prompt 长度保护 (24000 chars 阈值)
- 3 个异常类: `LLMError`, `TokenBudgetExceededError`, `EmptyResponseError`

**解决问题**: thinking Token 吃掉 JSON 输出 → 空日报

**提升**:
- Completion tokens: 1670→~105 (↓94%)
- API latency: 17s→~2.5s (↓84%)
- finish_reason: "length"→**"stop"** (不再截断)
- 失败自动保存 debug 文件

### Phase 1.5 — Debug RCA

**为什么**: 用户要求系统性排查 "hmac check failed" / "JSON 解析失败" 根因

**发现**:
- `hmac check failed` 来自 contact.db (不同密钥，红鲱鱼)
- 真正阻塞点: `未找到任何匹配的关注群` (chatlog 未运行)
- JSON 解析失败根因: thinking Token 吃掉 max_tokens=2048 → 输出被截断

### Phase 1.6 — 代码质量

**修改**: ruff check/format clean, mypy clean, 异常类重命名 (N818 Error suffix), 死代码删除, 类型注解补全

### Production Review — 97→98 分

**发现**: B1 死代码 / B2 命名 / C2 防御性检查 / C4 日志级别 / C1 已知限制

### Phase 1.7 — Production Polish

**6 项修复**: 死代码→AssertionError, `total_calls`→`total_successful_calls`, 空 choices 防御检查, Returns docstring, Known Limitation 注释, logger.debug→logger.info

### Phase 2 — Config 更新

`config/settings.yaml`: `max_tokens: 2048` → `4096`

### Phase 3 — Production Validation

- 静态验证: ruff/mypy/pytest 全通过
- Dry-run: Pipeline 完整执行 (0 messages → empty report → 正确跳过 LLM)
- LLM test (真实 API): prompt=2448, completion=106, finish=stop, retry=0
- 失败路径验证: 全部 6 种错误路径已覆盖
- 生产检查清单: 15/15 通过

### Phase 3.5 — Replay Mode

**新增**:
- `scripts/replay.py` — 历史日报回放入口
- `Pipeline.run(replay_date=...)` — 复用正式 Pipeline
- Report `skip_db_save=True` — 不写数据库

**验证**:
- 07-25 Replay (dry-run): 9 msgs, prompt=1724, completion=108, finish=stop
- 07-26 Replay (dry-run): 12 msgs, prompt=2448, completion=104, finish=stop
- 07-26 Replay (**--push**): 12 msgs, 推送成功, code=200, 手机已收到

## v1.0 → v1.1 对比

| 维度 | v1.0 | v1.1 |
|------|------|------|
| LLM 成功率 | ~33% (3 次 attempt 1 次成功) | **100%** (所有 Replay 测试一次成功) |
| API latency | ~17s | **~2.5s** |
| Completion tokens | ~1670 | **~105** |
| finish_reason | 随机 `length` 或 `stop` | **始终 `stop`** |
| Retry 策略 | 3 次相同参数无效重试 | **自适应**: 不同错误不同策略 |
| JSON 提取 | 直接 `json.loads()` | **提取器**: Markdown fence + 前置文字 |
| Debug 能力 | 无 | **失败自动保存** prompt+response |
| 代码质量 | - | **ruff/mypy clean** (0 issues) |
| 生产评分 | - | **98/100** |
| Replay Mode | 无 | **支持历史日期回放 + Push** |

---

# 第三章：每天如何使用

## 每天必须做的事情

| # | 事项 | 说明 |
|---|------|------|
| 1 | **电脑开机** | 必须。定时任务需要电脑运行 |
| 2 | **登录微信 PC** | 必须。Miru 从微信数据库读取消息 |
| 3 | **启动 chatlog** | 必须。双击 `tools/chatlog-windows-amd64.exe`，确认系统托盘有图标 |

## 完全不用做的事情

| 事项 | 说明 |
|------|------|
| 手动运行日报 | Windows Task Scheduler 每天 22:00 自动执行 |
| 手动启动 Python | `pythonw.exe` 静默运行，无黑窗口 |
| 手动备份数据库 | Pipeline 成功后自动备份到 `data/` |
| 清理日志 | 自动按 30 天保留 + 10MB 轮转 |
| 关注 PushPlus 余额 | 免费额度足够日常使用 (~105 tokens/天) |

## 每天自动执行流程

```
22:00  (Windows Task Scheduler 触发)
  │
  ├── 前提检查:
  │   ├── 微信 PC 在线 ✅ (自动检测)
  │   ├── chatlog HTTP API 在线 ✅ (127.0.0.1:5030)
  │   └── 网络正常 ✅ (DeepSeek API + PushPlus API)
  │
  ├── 消息采集:
  │   ├── 解密 message_0.db
  │   ├── 读取 4 个关注群的消息
  │   └── 过滤非文本/系统/短消息
  │
  ├── LLM 分析:
  │   ├── thinking=disabled
  │   ├── max_tokens=4096
  │   ├── response_format=json_object
  │   └── 自适应 retry (如需要)
  │
  ├── 日报推送:
  │   ├── 生成 Markdown 日报
  │   ├── 保存到 SQLite 数据库
  │   └── PushPlus → 手机微信
  │
  └── 日志 + 备份:
      ├── run_YYYY-MM-DD.log
      ├── miru_YYYY-MM-DD.log
      └── 数据库自动备份
```

## 如果错过了 22:00

Windows Task Scheduler 配置了 `AtLogon` 触发器。如果你在 22:00 之后开机+登录，任务会在**开机后 2 分钟内**自动补执行。

## 如果想手动生成

```bash
# 生成今天的日报 (dry-run, 不推送)
python scripts/replay.py --date 2026-07-27

# 生成今天并推送
python scripts/replay.py --date 2026-07-27 --push

# 回放历史日期
python scripts/replay.py --date 2026-07-25
```

---

# 第四章：Replay Mode 使用指南

## 设计目的

Replay Mode 允许你**回放任意历史日期**的日报生成过程，而不影响正式数据库和定时任务。

**使用场景**:
- 昨天忘记了启动 chatlog，想补看昨天的日报
- 想测试 LLM 是否正常工作
- 想对比不同日期的群聊活跃度
- 调试 Prompt 或 LLM 参数

**不要使用 Replay 的场景**:
- 今天的日报 → 等 22:00 自动运行或手动跑 `scripts/run_daily.py`
- 想修改数据库 → Replay 不写 DB

## 命令

```bash
# Dry-run (默认): 查看日报但不推送
python scripts/replay.py --date 2026-07-25

# 实际推送: 生成并推送到手机
python scripts/replay.py --date 2026-07-25 --push
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--date YYYY-MM-DD` | ✅ | 回放日期。不能是未来日期 |
| `--push` | 否 | 真正推送到手机 (默认仅控制台输出) |

## Replay vs 正式运行

| 维度 | Replay | 正式运行 (22:00) |
|------|--------|-------------------|
| 消息来源 | 指定日期整天 | 今天 00:00~当前 |
| LLM 参数 | 完全相同 | 完全相同 |
| thinking | disabled | disabled |
| 数据库写入 | **跳过** | 写入 daily_reports + run_log |
| 数据库备份 | **跳过** | 成功后自动备份 |
| 推送 | 默认 dry-run (`--push` 开启) | 始终推送 |
| 日志文件 | 写入同日志文件 | 写入同日志文件 |

---

# 第五章：日志说明

## 日志文件位置

```
data/logs/
├── miru_YYYY-MM-DD.log         # 主日志 (INFO 级别)
├── miru_error_YYYY-MM-DD.log   # 错误日志 (ERROR 级别)
├── run_YYYY-MM-DD.log          # run_daily.py 运行摘要
├── scheduler.log               # 定时任务调度日志
├── debug_prompt_*.txt           # ★ 失败时: 完整 System + User Prompt
└── debug_response_*.txt         # ★ 失败时: 原始 LLM Response + 错误信息
```

## LLM 日志解读

正常运行时，日志包含:

```
[示例群名] LLM 完成 —
  model=deepseek-v4-flash
  prompt=2448
  completion=105
  finish=stop
  duration=2687ms
```

| 字段 | 含义 | 正常值 |
|------|------|--------|
| `model` | 使用的模型 | `deepseek-v4-flash` |
| `prompt` | 输入的 Token 数 | 1500~3000 (取决于消息量) |
| `completion` | 输出的 Token 数 | 100~1000 (thinking disabled 后显著减少) |
| `finish` | 结束原因 | **`stop`** = 正常。`length` = 截断 (v1.1 不应出现) |
| `duration` | API 耗时 | 2~8s |

## 排查问题时查看

1. **日报没收到** → 先看 `run_YYYY-MM-DD.log`
2. **LLM 报错** → 看 `miru_error_YYYY-MM-DD.log` + `debug_response_*.txt`
3. **定时任务没触发** → 看 `scheduler.log`
4. **消息为空** → 看 `miru_YYYY-MM-DD.log` 中 "未采集到任何消息"

---

# 第六章：故障排查

## 常见问题速查表

### ❌ 没有收到日报

**排查步骤**:

```bash
# 1. 检查定时任务是否触发
cat data/logs/scheduler.log
# 应该看到: [2026-07-27 22:00] Miru Daily Run START

# 2. 如果没有触发 → 检查任务是否存在
schtasks /Query /TN "Miru Daily Report"

# 3. 如果任务存在但未触发 → 手动运行测试
python scripts/replay.py --date 2026-07-27 --push

# 4. 查看今天运行日志
cat data/logs/run_2026-07-27.log
```

### ❌ PushPlus 推送失败

**可能原因速查**:

| 错误 | 原因 | 解决 |
|------|------|------|
| `code=905, 账户未进行实名认证` | PushPlus 账号需要实名 | 登录 pushplus.plus 完成认证 |
| `code=401` | Token 过期/错误 | 重新获取 PushPlus Token |
| 网络超时 | 网络问题 | 检查能否访问 `http://www.pushplus.plus` |
| `推送完成 — 0/1 成功` | PushPlus 服务异常 | 等待后重试 `replay --push` |

### ❌ 微信未运行

```
错误: 未检测到 WeChat.exe 进程
```

**解决**: 启动微信 PC 客户端并登录。

### ❌ LLM 返回异常

查看 `data/logs/miru_error_YYYY-MM-DD.log`:

| 日志关键词 | 含义 | v1.1 自动处理 |
|-----------|------|--------------|
| `finish_reason=length` | Token 超限 | 自动 2× max_tokens 重试 |
| `Empty content` | 空响应 | 自动 disable thinking + 2× max_tokens |
| `JSON decode failed` | 格式异常 | 自动降 temperature 重试 |
| `thinking` not supported | 模型不支持 thinking 参数 | 自动回退普通请求 |
| `Debug artifacts saved` | 失败时已保存 debug 文件 | 查看 `data/logs/debug_*` |

### ❌ Replay 无数据

```
未采集到任何消息
```

**可能原因**:
1. 该日期确实没有群消息
2. 微信数据库已被清理 (微信会定期清理旧消息)
3. 群名匹配失败 (chatlog 未运行)

### ❌ 数据库问题

```bash
# 检查数据库完整性
python -c "
from miru.storage.database import Database
from miru.storage.migrations import run_migrations
db = Database('data/miru.db')
run_migrations(db)
cnt = db.conn.execute('SELECT COUNT(*) FROM daily_reports').fetchone()
print(f'Reports: {cnt[0]}')
db.close()
"

# 从备份恢复 (自动备份在 data/ 目录)
ls data/miru_backup_*.db
```

### ❌ Debug 文件

Debug 文件在 `data/logs/` 中:
- `debug_prompt_*.txt` — 发送给 LLM 的完整 Prompt
- `debug_response_*.txt` — LLM 原始返回 + 错误信息

这些文件仅在 LLM 调用失败时生成。文件名含时间戳，可用于诊断。

---

# 第七章：维护指南

## 不要修改的文件

| 文件 | 原因 |
|------|------|
| `src/miru/llm/client.py` | LLM 核心逻辑，经过完整生产验证 |
| `src/miru/core/pipeline.py` | Pipeline 编排器，改动影响全局 |
| `config/settings.yaml` 中的 `database_key` | 微信数据库密钥，格式敏感 |
| `data/miru.db` | 日报历史数据库 |
| `src/miru/llm/prompts/daily_summary.j2` | Prompt 模板 |

## 可以安全修改的配置

| 配置路径 | 说明 | 修改建议 |
|----------|------|----------|
| `miru.groups` | 关注的微信群名 | 添加/删除群名即可 (支持模糊匹配) |
| `miru.scheduler.daily_report_time` | 触发时间 | 改完后需重新运行 `setup_scheduler.ps1` |
| `miru.llm.max_tokens` | LLM 输出上限 | 当前 4096 足够。不要低于 2048 |
| `miru.storage.log_level` | 日志级别 | DEBUG/INFO/WARNING/ERROR |

## 不要随便修改的配置

| 配置 | 原因 |
|------|------|
| `miru.llm.model` | 换模型需要验证 JSON mode + thinking 支持 |
| `miru.llm.temperature` | 0.3 已验证。改太低(0)可能降低输出多样性；改太高(>0.5)可能不稳定 |
| `miru.notifiers[pushplus].token` | 改了推送会失败。新 Token 从 pushplus.plus 获取 |
| `miru.wechat.database_key` | 微信升级后可能变化 |

## 如何升级模型

1. 修改 `config/settings.yaml`:
   ```yaml
   miru:
     llm:
       model: "deepseek-v4-pro"  # 新模型名
   ```

2. 测试:
   ```bash
   python scripts/replay.py --date 2026-07-26
   ```

3. 检查日志中:
   - `finish=stop` (不能是 `length`)
   - `completion` Token 数合理 (100~2000)
   - 日报内容正确

4. 如果模型是 Reasoning 类型 (如 deepseek-r1, deepseek-v4-pro)，Miru 会自动尝试 `thinking=disabled`。如果模型不支持该参数，会自动回退。

## 如何升级 max_tokens

1. 修改 `config/settings.yaml`: `max_tokens: 8192`
2. 测试: `python scripts/replay.py --date 2026-07-26`

不需要改代码。`DeepSeekClient.__init__()` 从 config 读取。

## 如何升级 Prompt

编辑 `src/miru/llm/prompts/daily_summary.j2` (Jinja2 模板)。

**注意事项**:
- 保持 JSON 输出格式示例不变
- 保持字段名与 `schemas.py` 中的 `GroupAnalysis` 一致
- 测试: `python scripts/replay.py --date 2026-07-26`
- 检查 Pydantic 校验是否通过

---

# 第八章：项目目录说明

```
miru-assistant/
│
├── config/                         # 配置文件
│   ├── settings.yaml               # ★ 主配置 (groups, LLM, push, wechat)
│   ├── settings.example.yaml       # 配置模板 (供参考)
│   └── groups.example.yaml         # 群配置模板
│
├── src/miru/                       # ★ 源代码
│   ├── cli/                        # CLI 入口 (typer)
│   ├── core/                       # 核心
│   │   ├── pipeline.py             #   ★ Pipeline 编排器 (6 步流程)
│   │   ├── context.py              #   运行上下文 (PipelineContext)
│   │   └── exit_codes.py           #   退出码定义
│   ├── collector/                  # 微信数据采集
│   │   ├── diagnostics.py          #   微信进程检测 + 数据目录
│   │   ├── wechat_db_decrypt.py    #   SQLCipher 解密
│   │   └── wechat_reader.py        #   群列表 + 消息读取
│   ├── filter/                     # 消息过滤
│   │   ├── pipeline.py             #   过滤管线 + build_llm_context()
│   │   ├── dedup.py                #   去重
│   │   ├── cleaner.py              #   清洗
│   │   └── classifier.py           #   分类
│   ├── llm/                        # ★ LLM 客户端 (v1.1 核心升级)
│   │   ├── client.py               #   ★ DeepSeekClient (thinking disabled + retry + extractor)
│   │   ├── schemas.py              #   GroupAnalysis + TokenUsage + LLMCallResult
│   │   └── prompts/
│   │       └── daily_summary.j2    #   ★ Prompt 模板
│   ├── report/                     # 日报生成
│   │   ├── generator.py            #   日报生成 + DB 保存
│   │   ├── formatter.py            #   Markdown 格式化
│   │   └── templates/
│   │       └── daily.md.j2         #   日报模板
│   ├── notify/                     # 推送
│   │   ├── base.py                 #   Notifier 抽象基类
│   │   ├── pushplus.py             #   PushPlus HTTP 客户端
│   │   ├── console.py              #   控制台输出
│   │   └── dispatcher.py           #   推送调度器
│   ├── storage/                    # 数据持久化
│   │   ├── database.py             #   SQLite 连接管理
│   │   ├── migrations.py           #   数据库迁移
│   │   ├── repository.py           #   Repository 模式
│   │   ├── models.py               #   数据模型
│   │   └── backup.py               #   自动备份
│   ├── scheduler/                  # 定时任务
│   │   └── scheduler.py            #   健康检查 + 失败通知
│   └── utils/                      # 工具
│       ├── config.py               #   配置加载 (环境变量替换)
│       ├── logger.py               #   日志系统 (loguru)
│       └── errors.py               #   自定义异常
│
├── scripts/                        # ★ 运行脚本
│   ├── run_daily.bat               # ★ 定时任务入口 (Windows Task Scheduler 调用)
│   ├── run_daily.py                # ★ 每日静默运行入口 (pythonw.exe)
│   ├── setup_scheduler.ps1         # Windows Task Scheduler 安装脚本
│   └── replay.py                   # ★ v1.1 新增: Replay Mode 入口
│
├── tests/                          # 测试
│   └── unit/                       # 单元测试
│       ├── test_llm.py             #   LLM Client 测试 (20 tests)
│       ├── test_pipeline.py        #   Pipeline 测试
│       ├── test_report.py          #   Report 测试
│       ├── test_notify.py          #   Notify 测试
│       ├── test_filter.py          #   Filter 测试
│       └── ...                     #   其他模块测试
│
├── tools/                          # ★ 外部工具
│   ├── chatlog-windows-amd64.exe   # ★ chatlog_alpha (群名解析 HTTP API)
│   ├── wx_key-windows-v2.1.8/      #   wx_key (微信密钥提取 GUI)
│   └── WeChatDataAnalysis.Setup... #   微信数据分析工具
│
├── data/                           # 运行时数据
│   ├── miru.db                     #   ★ SQLite 数据库 (日报 + 运行日志)
│   ├── miru_backup_*.db            #   自动备份
│   └── logs/                       #   ★ 日志目录
│       ├── miru_YYYY-MM-DD.log
│       ├── miru_error_YYYY-MM-DD.log
│       ├── run_YYYY-MM-DD.log
│       ├── scheduler.log
│       ├── debug_prompt_*.txt       #   失败时的 Prompt 快照
│       └── debug_response_*.txt     #   失败时的 Response 快照
│
├── docs/                           # 文档
│   ├── MIRU_V1.1_OPERATIONS_MANUAL.md  # ★ 本手册
│   ├── CLI_REFACTOR_PLAN.md
│   └── README_CN.md
│
├── backup/                         # 历史备份
├── venv/                           # Python 虚拟环境
├── pyproject.toml                  # 项目元数据 + 工具配置
├── requirements.txt                # 生产依赖
├── requirements-dev.txt            # 开发依赖
└── README.md                       # 项目说明
```

---

# 第九章：生产环境检查清单

## 每日检查 (可选，系统自动完成)

| # | 项目 | 自动? |
|---|------|-------|
| 1 | Windows Task Scheduler 触发 | ✅ |
| 2 | 微信 PC 在线 | ✅ (Pipeline Step 1 自动检测) |
| 3 | chatlog HTTP API 在线 | ✅ (群名解析失败会记录 warning) |
| 4 | 日报生成成功 | ✅ (看 `run_YYYY-MM-DD.log`) |
| 5 | PushPlus 推送成功 | ✅ (看 `push_status=sent`) |
| 6 | 手机收到日报 | 手动确认 |

## 每周检查 (建议)

```bash
# 1. 检查本周日报
python -c "
from miru.storage.database import Database
from miru.storage.migrations import run_migrations
db = Database('data/miru.db'); run_migrations(db)
rows = db.conn.execute(\"SELECT report_date, push_status FROM daily_reports ORDER BY report_date DESC LIMIT 7\").fetchall()
for r in rows: print(f'{r[\"report_date\"]}: {r[\"push_status\"]}')
db.close()
"

# 2. 检查日志是否有异常
grep -i "error\|failed\|重试" data/logs/miru_*.log | tail -20

# 3. 检查磁盘空间
ls -lh data/miru.db data/logs/
```

## 每月维护

| # | 项目 | 命令 |
|---|------|------|
| 1 | 数据库备份 | `cp data/miru.db data/miru_backup_$(date +%Y%m).db` |
| 2 | 清理旧日志 | `find data/logs -name "*.log" -mtime +30 -delete` |
| 3 | 清理 debug 文件 | `rm data/logs/debug_*.txt` (仅保留最近的) |
| 4 | 验证系统健康 | `python -m miru doctor` |
| 5 | Replay 测试 | `python scripts/replay.py --date $(date -d "yesterday" +%F)` |

## 微信升级后

| # | 检查项 |
|---|--------|
| 1 | 微信版本是否变化 |
| 2 | `database_key` 是否仍然有效 (用 Replay 测试) |
| 3 | 数据目录路径是否变化 |
| 4 | chatlog 是否需要更新 |

---

# 第十章：最终总结

## 当前成熟度

**Production Ready — 98/100**

Miru v1.1 已经达到可以长期无人值守稳定运行的生产质量。

| 能力 | 成熟度 |
|------|--------|
| 微信消息采集 | ✅ 稳定 (WeChat 4.1.5.30) |
| LLM 分析 | ✅ 稳定 (thinking disabled, 0 次失败) |
| 日报生成 | ✅ 稳定 |
| PushPlus 推送 | ✅ 稳定 (已验证真实推送) |
| 定时任务 | ✅ 已安装 Windows Task Scheduler |
| 错误恢复 | ✅ 自适应 retry + debug artifacts |
| 代码质量 | ✅ ruff/mypy clean, 20/20 tests |
| Replay Mode | ✅ 支持历史回放 + 推送 |

## 已稳定的功能

- ✅ 多群消息采集 (4 个微信群)
- ✅ 消息过滤 (去重/系统/非文本/短消息)
- ✅ DeepSeek LLM 分析 (JSON mode, thinking disabled)
- ✅ 结构化输出 (urgent_tasks, deadlines, notices, files, summary)
- ✅ Markdown 日报生成
- ✅ PushPlus 微信推送
- ✅ SQLite 持久化 + 自动备份
- ✅ Windows Task Scheduler 自动化
- ✅ 失败调试 (prompt + response 自动保存)
- ✅ 历史回放 (Replay Mode)

## 未来可优化方向

| 方向 | 优先级 | 说明 |
|------|--------|------|
| contact.db 解密 | 低 | 消除 chatlog 依赖 (需要获取 contact.db 密钥) |
| 支持更多 LLM 模型 | 低 | 当前 deepseek-v4-flash 已充分满足需求 |
| 日报多媒体 (图片/文件) | 低 | 当前仅文本消息 |
| Web Dashboard | 低 | 当前 CLI + 手机推送已足够 |
| 多用户支持 | 极低 | 个人项目，不需要 |

## 长期使用建议

1. **保持微信登录** — 电脑开机后确保微信 PC 自动登录
2. **保持 chatlog 运行** — 设为开机自启可减少手动操作
3. **每月一次 Replay 测试** — `python scripts/replay.py --date $(昨天)` 确认系统正常
4. **微信升级后验证** — 微信版本更新后运行 Replay 确认 database_key 仍然有效
5. **不要随意修改 LLM 参数** — 当前参数经过完整生产验证
6. **关注 PushPlus 通知** — 如果连续多天没收到日报，检查 timed task + chatlog
7. **保留本手册** — 作为唯一运维参考文档

---

> 📋 **Miru v1.1 — Production Ready**
>
> 98/100 · 20 tests passing · ruff/mypy clean · thinking disabled · 0 retries needed
>
> 最后验证: 2026-07-27 · Replay 07-25/07-26 全部成功 · Push 真实推送已验证
