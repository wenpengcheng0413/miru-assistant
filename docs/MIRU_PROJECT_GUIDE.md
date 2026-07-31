# Miru Assistant — 长期维护指南

> 最后更新: 2026-07-25
> 当前版本: V1.1
> 状态: 生产稳定运行

---

## 1. 项目简介

### 这是什么

Miru Assistant 是一个个人 AI 微信消息助理。每天 22:00 自动读取指定微信群当天的聊天记录，用 DeepSeek AI 提取重要信息，生成结构化日报并推送到手机。

### 为什么需要它

微信群消息过多，人工逐条阅读效率低。Miru 像私人秘书一样，只告诉你真正需要关注的内容。

### 完整数据流

```
微信 PC 客户端 (4.1.5.30)
  │
  ▼
SQLCipher 4 加密数据库 (E:\wechatfiles\)
  │
  ▼
chatlog_alpha DLL Hook → 提取 database key
  │
  ▼
Miru Pipeline (Python):
  ├─ 环境诊断 (微信检测 + 权限检查)
  ├─ 数据库解密 (sqlcipher3 原生库)
  ├─ 消息读取 (message_0.db → ZSTD 解压)
  ├─ 消息过滤 (去重 → 清洗 → 分类 → 分组)
  ├─ DeepSeek 分析 (V4 Flash, JSON 结构化输出)
  ├─ 日报生成 (Markdown + SQLite 持久化)
  └─ PushPlus 推送 (微信公众号消息)
  │
  ▼
手机收到 "Miru Daily Assistant" 推送
```

---

## 2. 当前系统架构

### 2.1 模块依赖

```
cli/main.py  ── CLI 入口 (run, doctor, decrypt, status)
    │
core/pipeline.py  ── Pipeline 编排器 (6 步流程)
    │
    ├─ collector/diagnostics.py  ── 微信环境诊断
    ├─ collector/wechat_db_decrypt.py ── SQLCipher 4 解密
    ├─ collector/wechat_reader.py ── 消息 + 联系人读取
    ├─ filter/  ── 去重 → 清洗 → 分类 → 分组
    ├─ llm/  ── DeepSeek API + Jinja2 模板
    ├─ report/  ── Markdown 日报生成
    ├─ notify/  ── PushPlus + Console 推送
    ├─ storage/  ── SQLite 数据库 + 备份
    └─ utils/  ── 配置、日志、错误码
```

### 2.2 加密适配层 (关键！)

Miru 本身不提取 database key。key 由外部工具提供：

| 组件 | 工具 | 版本 |
|------|------|------|
| Key 提取 | chatlog_alpha (DLL Hook) | latest (teest114514 fork) |
| Key 格式 | 64 hex chars → 32 bytes raw key | |
| 解密库 | sqlcipher3 (Python binding) | 0.6.2 |
| 支持版本 | 微信 4.1.5.30 (Windows) | |

**Key 存储**: `config/settings.yaml` → `miru.wechat.database_key`

**限制**: 当前 key 仅对 message_0.db 有效，其他分片 (message_1~5.db) 需要不同的 key（暂未处理）。

### 2.3 消息处理流程

```
message_0.db (SQLCipher 4)
  │ PRAGMA key = "x'<64hex>'"
  ▼
解密 → 读取 Msg_<MD5> 表
  │ ZSTD 解压 → UTF-8 解码
  ▼
WeChatMessage 对象
  │
  ▼
去重 (server_id, 跨运行持久化)
  ▼
清洗 (系统消息/非文本/短噪声/表情)
  ▼
分类 (keyword 规则: notice/homework/deadline/file/discussion)
  ▼
分组 (按 group_name)
  ▼
构建 LLM 上下文 (格式化消息流)
```

### 2.4 LLM 调用

| 参数 | 值 |
|------|------|
| 模型 | deepseek-v4-flash |
| 请求方式 | OpenAI SDK 兼容 API |
| 输出 | JSON (response_format: json_object) |
| 重试 | 2 次, 延迟 5s/30s |
| Token 控制 | max_tokens=2048 |
| 月费预算 | ~¥0.10 (4 群 × 每日 ≤100 条消息) |

---

## 3. 当前环境信息

### 3.1 电脑环境

| 项目 | 值 |
|------|------|
| 操作系统 | Windows 10 Pro (10.0.19045) |
| 架构 | x64 (AMD64) |
| 用户名 | Administrator |
| Python | 3.12.10 (64-bit) |
| 虚拟环境 | `E:\vibe coding\miru-assistant\venv\` |

### 3.2 软件版本

| 软件 | 版本 | 说明 |
|------|------|------|
| 微信 PC | **4.1.5.30** | 必须保持此版本，禁止更新 |
| DeepSeek | deepseek-v4-flash | API: api.deepseek.com |
| PushPlus | 免费版 (200条/天) | Token: `<token，见 config/settings.yaml>` |
| chatlog_alpha | latest (teest114514) | 提取 key 后不需要常驻 |

### 3.3 项目路径

| 路径 | 说明 |
|------|------|
| `E:\vibe coding\miru-assistant\` | 项目根目录 |
| `E:\vibe coding\miru-assistant\config\settings.yaml` | **主配置文件** |
| `E:\vibe coding\miru-assistant\data\miru.db` | Miru 内部数据库 |
| `E:\vibe coding\miru-assistant\data\logs\` | 运行日志 |
| `E:\vibe coding\miru-assistant\scripts\run_daily.bat` | 自动任务入口 |
| `E:\vibe coding\miru-assistant\scripts\setup_scheduler.ps1` | 任务计划安装 |
| `E:\wechatfiles\` | 微信数据目录 |
| `E:\wechatfiles\xwechat_files\<wxid>\db_storage\message\` | 微信消息数据库 |

### 3.4 微信自动更新阻止

已通过 hosts 文件屏蔽:

```
127.0.0.1 dldir1.qq.com
127.0.0.1 dldir1v6.qq.com
127.0.0.1 update.weixin.qq.com
127.0.0.1 dldir1.weixin.qq.com
```

---

## 4. 日常运行机制

### 4.1 每天 22:00 发生的事情

```
22:00:00  Windows 任务计划触发
22:00:01  pythonw.exe scripts\run_daily.py 启动 (静默, 无黑窗)
22:00:02  Miru Pipeline:
          [1/6] 检查微信是否运行、数据目录是否存在
          [2/6] 用 database_key 解密 message_0.db
                从 Name2Id 匹配 6 个目标群
                读取今日消息 (00:00 ~ 当前时间)
          [3/6] 消息去重 (server_id 持久化)
                清洗 (过滤系统/非文本/短噪声)
          [4/6] 每个群独立调用 DeepSeek
                提取：通知、截止日期、文件、摘要
          [5/6] 生成 Markdown 日报
                保存到 miru.db (daily_reports 表)
          [6/6] PushPlus 推送到手机
22:01:xx  完成。手机收到推送。
```

### 4.2 监控的微信群

当前 6 个群（在 config/settings.yaml 的 miru.groups 中）:

| 群名 | 预估活跃度 |
|------|-----------|
| 21级环境工程班群 | 中等 |
| 环境工程课程群 | 中等 |
| 实验课群 | 低 |
| AI交流群 | 极低 |
| ComfyUI交流群 | 极低 |
| 家教群 | 高 |

---

## 5. 日常检查方法

### 5.1 正常运行的标志

**手机端**: 每天 22:01 左右收到 "Miru Daily Assistant" 推送，内容为当日日报。

**日志确认**:

```powershell
cd "E:\vibe coding\miru-assistant"
venv\Scripts\activate

# 查看最新调度日志
type data\logs\scheduler.log

# 成功示例:
# [2026-07-25 22:00:01] Miru Daily Run START
# [2026-07-25 22:01:15] Miru Daily Run END (exit=0)

# 查看 Miru 详细日志
type "data\logs\miru_2026-07-25.log" | findstr "SUCCESS"

# 健康检查
python -m miru.cli.main status
```

### 5.2 Token 消耗检查

```powershell
# 查看每日日志中的 token 用量
type "data\logs\miru_2026-07-25.log" | findstr "tokens\|LLM"
```

正常情况每天 3000-5000 tokens (约 ¥0.003-0.005)。

---

## 6. 手动启动方法

### 6.1 手动运行一次日报

```powershell
cd "E:\vibe coding\miru-assistant"
venv\Scripts\activate
python -m miru.cli.main run
```

### 6.2 测试模式 (不推送)

```powershell
python -m miru.cli.main run --dry-run
```

### 6.3 验证数据库解密

```powershell
python -m miru.cli.main decrypt message_0.db
```

### 6.4 环境诊断

```powershell
python -m miru.cli.main doctor
```

### 6.5 查看状态

```powershell
python -m miru.cli.main status
```

---

## 7. 自动任务管理

### 7.1 基本信息

| 项目 | 值 |
|------|------|
| 任务名称 | `Miru Daily Report` |
| 触发器 | 每天 22:00 + 用户登录时补执行 |
| 运行账户 | 当前用户 (Administrator) |
| 最高权限 | ✅ (需要读取微信进程内存) |
| 重复保护 | IgnoreNew (已在运行则跳过) |

### 7.2 常用命令

```powershell
# 图形化管理
taskschd.msc

# 查看任务
schtasks /Query /TN "Miru Daily Report"

# 手动触发一次
schtasks /Run /TN "Miru Daily Report"

# 禁用任务 (临时暂停)
schtasks /Change /TN "Miru Daily Report" /Disable

# 启用任务
schtasks /Change /TN "Miru Daily Report" /Enable

# 删除任务
schtasks /Delete /TN "Miru Daily Report" /F

# 重新安装
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
```

### 7.3 修改运行时间

编辑 `scripts\setup_scheduler.ps1`，将 `22:00` 改为目标时间，然后重新运行。

---

## 8. 日志查看方法

### 8.1 日志文件

| 文件 | 内容 | 路径示例 |
|------|------|---------|
| 调度日志 | bat 启动/结束、退出码 | `data/logs/scheduler.log` |
| 运行日志 | run_daily.py 输出 | `data/logs/run_YYYY-MM-DD.log` |
| Miru 日志 | Miru 内部详细日志 | `data/logs/miru_YYYY-MM-DD.log` |
| 错误日志 | 错误级别日志 | `data/logs/miru_error_YYYY-MM-DD.log` |

### 8.2 判断成功/失败

```powershell
# 成功: exit=0
type data\logs\scheduler.log | findstr "exit=0"

# 失败: exit≠0
type data\logs\scheduler.log | findstr "exit=" | findstr /V "exit=0"

# 查看最近错误
type "data\logs\miru_error_*.log"
```

---

## 9. 常见故障排查

### 9.1 手机没有收到日报

**排查顺序**:

```
1. 检查推送日志
   type data\logs\scheduler.log

2. 如果 exit=0 但没收到推送:
   → PushPlus 问题
   → 检查 PushPlus 实名认证状态
   → 登录 pushplus.plus 查看发送记录

3. 如果 exit=2 或 exit=3:
   → 看 run_YYYY-MM-DD.log 具体错误
```

### 9.2 DeepSeek 分析失败

**症状**: 日志显示 "LLM analysis failed" 或 API 错误

**检查**:

```powershell
# 1. 测试 API 连通性
curl -H "Authorization: Bearer ${MIRU_DEEPSEEK_API_KEY}" ^
     https://api.deepseek.com/v1/models

# 2. 检查 API 余额
# 登录 platform.deepseek.com → 用量管理

# 3. 检查配置
type config\settings.yaml | findstr "api_key\|model\|base_url"
```

### 9.3 微信读取失败

**症状**: "Contact 数据库解密失败" 或 "未找到微信数据目录"

**检查**:

```powershell
# 1. 微信是否在运行
tasklist | findstr Weixin

# 2. 数据目录是否存在
dir E:\wechatfiles\xwechat_files\<wxid>\db_storage\message\

# 3. 微信版本是否正确 (必须是 4.1.5.30)
# 微信 → 设置 → 关于微信

# 4. 如果微信自动更新到了新版本 → 需要重新降级并提取 key
```

### 9.4 自动任务没有执行

**检查**:

```powershell
# 1. 任务是否启用
schtasks /Query /TN "Miru Daily Report" | findstr "Ready\|Disabled"

# 2. 上次运行结果
schtasks /Query /TN "Miru Daily Report" /FO LIST /V | findstr "Last\|Result"

# 3. 手动触发测试
schtasks /Run /TN "Miru Daily Report"

# 4. 检查 pythonw.exe 路径
dir "E:\vibe coding\miru-assistant\venv\Scripts\pythonw.exe"
```

### 9.5 Token 消耗异常

**正常范围**: 每天 3000-5000 tokens

**异常信号**: 单日超过 20000 tokens

**排查**:

```powershell
# 查看哪些群产生了大量消息
type "data\logs\miru_YYYY-MM-DD.log" | findstr "读取.*条消息"

# 如果某个群消息暴增，考虑暂时移除:
# 编辑 config/settings.yaml → 注释掉该群名
```

### 9.6 微信版本自动更新 (重大风险)

**如果微信被自动更新到 4.1.11+**:

1. chatlog_alpha 的 DLL Hook 可能失效
2. database_key 可能变化
3. 需要重新降级到 4.1.5.30 并重新提取 key

**预防**: hosts 已屏蔽更新域名（见 3.4 节），不要删除这些规则。

---

## 10. 当前不要修改的部分

以下模块已经验证稳定，非必要不修改：

| 模块 | 原因 |
|------|------|
| `collector/wechat_db_decrypt.py` | SQLCipher 4 解密已验证正确 |
| `collector/wechat_reader.py` | 消息表 schema 映射已修正 |
| `filter/cleaner.py` | 过滤规则已调优 |
| `llm/client.py` | DeepSeek 集成稳定 |
| `llm/prompts/daily_summary.j2` | Prompt 模板已优化 |
| `core/pipeline.py` | 6 步流程已验证 |
| `config/settings.yaml` | 群配置、key、API 均已配置 |
| `scripts/setup_scheduler.ps1` | 任务计划配置正确 |
| hosts 文件规则 | 阻止微信自动更新 |

### chatlog_alpha 和 key 的关系

**重要**: `database_key` 在 config/settings.yaml 中。这个 key:
- 由 chatlog_alpha 通过 DLL Hook 提取
- 仅在微信不跨大版本更新时有效
- 是 64 hex 字符 (32 bytes)
- 每个微信登录 session 可能不同
- 如果微信重装或升级，需要重新提取

**当前有效 key**: `<64 hex 字符，从 chatlog_alpha 提取>`

---

## 11. 当前配置备份

### 11.1 必须备份的文件

| 文件 | 内容 | 优先级 |
|------|------|--------|
| `config/settings.yaml` | 群列表、API key、database key | 🔴 最高 |
| `data/miru.db` | 日报历史、消息去重记录 | 🟡 中 |
| `scripts/run_daily.py` | 自动任务入口 | 🟢 低 (可重建) |
| `C:\Windows\System32\drivers\etc\hosts` | 微信更新屏蔽 | 🟡 中 |

### 11.2 快速备份

```powershell
# 备份关键配置
copy config\settings.yaml config\settings.yaml.backup

# 备份数据库
copy data\miru.db data\miru.db.backup
```

### 11.3 当前配置摘要

```yaml
# config/settings.yaml 中的关键字段
miru.groups:        6 个目标群
miru.llm.model:     deepseek-v4-flash
miru.llm.api_key:   <sk-xxx，见 config/settings.yaml>
miru.wechat.database_key: <64 hex>
miru.notifiers:     pushplus (token: <token>)
```

---

## 12. 项目恢复流程

如果换了新电脑或环境损坏，按此顺序恢复：

```powershell
# 1. 安装 Python 3.12+
# 2. 克隆/复制项目
git clone <repo> "E:\vibe coding\miru-assistant"

# 3. 创建虚拟环境
cd "E:\vibe coding\miru-assistant"
python -m venv venv
venv\Scripts\activate
pip install -e .
pip install sqlcipher3  # 额外依赖

# 4. 恢复 config/settings.yaml (从备份)

# 5. 安装微信 4.1.5.30 (从 E:\WeChat\weixin_4.1.5.30.exe 或 GitHub)

# 6. 配置 hosts 阻止微信更新

# 7. 登录微信 → 恢复聊天记录

# 8. 用 chatlog_alpha 提取新 database key
#    更新 config/settings.yaml

# 9. 验证
python -m miru.cli.main doctor
python -m miru.cli.main decrypt message_0.db
python -m miru.cli.main run --dry-run

# 10. 重新安装任务计划
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
```

---

## 13. 未来扩展方向

以下为**想法记录**，当前版本不实现：

1. **更多微信群** — 修改 config/settings.yaml 的 groups 列表
2. **智能多群分类** — DeepSeek 自动识别群类型并分类
3. **Web Dashboard** — 本地网页查看历史日报
4. **AI 主动提醒** — 检测到截止日期时额外推送
5. **多模型支持** — 切换 Claude/GPT 等模型
6. **跨分片 message 支持** — 解决 message_1~5.db key 问题
7. **Contact DB 解密** — 获取完整群成员信息

---

*文档结束。最后更新: 2026-07-25*
