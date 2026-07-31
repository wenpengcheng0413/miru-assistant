# Miru Assistant — 备份清单与恢复手册

> 生成日期: 2026-07-25
> 基于当前生产环境

---

## 1. 项目恢复目标

更换电脑或系统损坏后，需要恢复以下能力链：

```
① 微信数据读取 → ② Miru 日报生成 → ③ DeepSeek 分析 → ④ PushPlus 推送
                                      │
                              ⑤ Windows 每日 22:00 自动运行
```

具体可验证目标:

- `miru doctor` 通过
- `miru decrypt message_0.db` 成功
- `miru run --dry-run` 生成日报（不推送）
- `miru run` 手机收到推送
- Windows 任务计划 "Miru Daily Report" 显示 Ready

---

## 2. 必须备份文件 (最高优先级)

| 文件 | 作用 | 必须 | 丢失影响 |
|------|------|------|---------|
| `config/settings.yaml` | 群列表、API key、database key、PushPlus token | 🔴 是 | **项目完全不可用** |
| `E:\WeChat\weixin_4.1.5.30.exe` | 微信 4.1.5.30 安装包 (211 MB) | 🔴 是 | 需从 GitHub 重新下载旧版，可能已下架 |
| `scripts/run_daily.py` | 自动任务 Python 入口 | 🔴 是 | 自动运行失效，需重建 |
| `scripts/run_daily.bat` | 自动任务 BAT 入口 | 🔴 是 | 自动运行失效 |
| `scripts/setup_scheduler.ps1` | 任务计划安装脚本 | 🟡 建议 | 手动重建任务计划 |
| `src/` 全部源码 | Miru 核心代码 (764 KB) | 🔴 是 | 无代码可运行 |
| `tests/` 测试代码 | 237 个单元测试 (717 KB) | 🟢 否 | 不影响运行，但失去验证能力 |
| `C:\Windows\System32\drivers\etc\hosts` | 微信更新屏蔽规则 | 🟡 建议 | 微信自动更新导致 key 失效 |
| `C:\Users\Administrator\.chatlog\chatlog.json` | chatlog_alpha 缓存 (含 key) | 🟡 建议 | 需重新提取 key |

### config/settings.yaml 内容明细

此文件是整个项目的**单点关键依赖**，包含:

```yaml
miru.groups:              6 个目标微信群名
miru.llm.api_key:         DeepSeek API key (sk-xxx)
miru.llm.model:           deepseek-v4-flash
miru.llm.base_url:        https://api.deepseek.com
miru.notifiers.token:     PushPlus token (xxx)
miru.wechat.database_key: 微信 database key (64 hex)
miru.storage.db_path:     ./data/miru.db
```

**备份方式**: 复制到安全位置（U盘/云盘/邮箱），此文件包含所有密钥。

---

## 3. 建议备份文件

| 文件/目录 | 作用 | 大小 | 原因 |
|-----------|------|------|------|
| `data/miru.db` | 日报历史、消息去重记录 | ~100 KB | 保留历史数据 |
| `data/logs/` | 运行日志 | ~60 KB | 故障追溯 |
| `docs/` | 全部项目文档 | ~130 KB | 维护参考 |
| `scripts/scan_groups*.py` | 群扫描工具 | ~40 KB | 新增群时需要 |
| `pyproject.toml` | 项目依赖定义 | - | pip install -e . 需要 |

### 不需要备份的文件

| 文件/目录 | 大小 | 原因 |
|-----------|------|------|
| `venv/` | 242 MB | `pip install -e .` 可重建 |
| `__pycache__/` | - | Python 自动生成 |
| `.pytest_cache/` | - | 测试缓存 |
| `data/miru_backup_*.db` | - | 自动备份，可清理 |
| `E:\wechatfiles\` | **未知大小** | 微信聊天数据，通过手机恢复 |

---

## 4. 微信相关备份 (最特殊部分)

### 4.1 微信版本

| 项目 | 当前值 |
|------|--------|
| 版本 | **4.1.5.30** |
| 安装包 | `E:\WeChat\weixin_4.1.5.30.exe` (211 MB) |
| 安装路径 | `E:\WeChat\Weixin\Weixin.exe` |
| 数据目录 | `E:\wechatfiles\xwechat_files\<wxid>\` |

### 4.2 微信更新阻止 (hosts)

必须保留以下 hosts 规则:

```
127.0.0.1 dldir1.qq.com
127.0.0.1 dldir1v6.qq.com
127.0.0.1 update.weixin.qq.com
127.0.0.1 dldir1.weixin.qq.com
```

### 4.3 数据库 Key

| 项目 | 值 |
|------|-----|
| Key | `<64 hex 字符，见 config/settings.yaml>` |
| 提取工具 | chatlog_alpha (teest114514 fork) |
| 提取方式 | DLL Hook → setCipherKey |
| 适用范围 | message_0.db 有效，其他分片未知 |
| 稳定性 | 微信 4.x 内不变，除非重新登录或跨大版本升级 |

**如果丢失 database key**:
1. 确认微信 4.1.5.30 正在运行
2. 启动 chatlog_alpha → 重启并获取密钥
3. 将新 key 写入 `config/settings.yaml` → `miru.wechat.database_key`
4. 验证: `python -m miru.cli.main decrypt message_0.db`

**Key 的局限性**: 每个微信登录 session 的 key 不同。如果微信被卸载重装、重新登录、或升级到 4.1.11+，key 会变化。这也是为什么必须阻止微信自动更新。

### 4.4 聊天记录恢复

微信聊天记录不在备份范围内。恢复方式:
- 手机微信 → 设置 → 聊天记录迁移 → 恢复到电脑
- 或使用 chatlog_alpha 导出已有数据

---

## 5. AI 配置备份

### 5.1 DeepSeek

| 配置项 | 值 | 位置 |
|--------|-----|------|
| API Key | `<sk-xxx，见 config/settings.yaml>` | config/settings.yaml |
| Base URL | `https://api.deepseek.com` | config/settings.yaml |
| Model | `deepseek-v4-flash` | config/settings.yaml |
| Temperature | 0.3 | config/settings.yaml |
| Max Tokens | 2048 | config/settings.yaml |
| System Prompt | 见 `src/miru/llm/client.py:94-106` | 源码中硬编码 |
| User Template | 见 `src/miru/llm/prompts/daily_summary.j2` | Jinja2 模板 |

### 5.2 更换模型

在 `config/settings.yaml` 中修改:

```yaml
miru:
  llm:
    provider: "deepseek"           # 改为 "openai" / "claude" 等
    api_key: "新的 API Key"
    base_url: "新的 API 地址"
    model: "新的模型名"
```

如果新模型不支持 `response_format: json_object`，需修改 `src/miru/llm/client.py` 的 `analyze_group` 方法。

### 5.3 PushPlus

| 配置项 | 值 |
|--------|-----|
| Token | `<token，见 config/settings.yaml>` |
| 免费额度 | 200 条/天 |
| 实名认证 | 需要（否则推送被拒） |

---

## 6. 自动运行配置备份

### 6.1 Windows 任务计划

| 配置项 | 值 |
|--------|-----|
| 任务名称 | `Miru Daily Report` |
| 触发器 | 每天 22:00 + 登录时补执行 |
| 执行程序 | `E:\vibe coding\miru-assistant\venv\Scripts\pythonw.exe` |
| 参数 | `E:\vibe coding\miru-assistant\scripts\run_daily.py` |
| 工作目录 | `E:\vibe coding\miru-assistant` |
| 运行级别 | 最高权限 |
| 多重实例 | IgnoreNew |

### 6.2 换电脑后重新创建

```powershell
cd "E:\vibe coding\miru-assistant"
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
```

此命令自动完成: 移除旧任务 → 创建新任务 → 配置触发器 + 权限 + 防重复。

---

## 7. 完整恢复流程 (新电脑)

### 前提

- Windows 10/11 x64
- Python 3.12+ 已安装
- 管理员权限
- 备份文件已就绪

### 步骤

```powershell
# ===== Step 1: 安装 Python 3.12+ =====
# 下载: https://www.python.org/downloads/
# 安装时勾选 "Add Python to PATH"

# ===== Step 2: 恢复项目 =====
mkdir "E:\vibe coding"
cd "E:\vibe coding"
# 从备份复制或 git clone 项目
# git clone <repo-url> miru-assistant
# 或解压备份的 zip

cd "E:\vibe coding\miru-assistant"

# ===== Step 3: 创建虚拟环境 =====
python -m venv venv
venv\Scripts\activate
pip install -e .
pip install sqlcipher3

# ===== Step 4: 恢复配置 =====
# 将备份的 settings.yaml 复制到 config\settings.yaml
# 确认 database_key、API key、PushPlus token 正确

# ===== Step 5: 验证环境 =====
python -m miru.cli.main --version
# Miru Assistant v1.0.0
python -m pytest tests/ -q
# 230+ passed

# ===== Step 6: 安装微信 4.1.5.30 =====
# 运行 E:\WeChat\weixin_4.1.5.30.exe (从备份复制)
# 安装后登录微信
# 立即: 设置 → 通用 → 取消自动更新

# ===== Step 7: 配置 hosts 阻止更新 =====
# 以管理员身份编辑 C:\Windows\System32\drivers\etc\hosts
# 添加:
# 127.0.0.1 dldir1.qq.com
# 127.0.0.1 dldir1v6.qq.com
# 127.0.0.1 update.weixin.qq.com
# 127.0.0.1 dldir1.weixin.qq.com

# ===== Step 8: 恢复聊天记录 =====
# 手机微信 → 设置 → 通用 → 聊天记录迁移与备份 → 恢复到电脑

# ===== Step 9: 提取 database key (如果 key 变化了) =====
# 1. 下载 chatlog_alpha
#    https://github.com/teest114514/chatlog_alpha/releases
# 2. 运行 chatlog_alpha → 重启并获取密钥
# 3. 复制新 key → 更新 config/settings.yaml

# ===== Step 10: 验证解密 =====
python -m miru.cli.main doctor
python -m miru.cli.main decrypt message_0.db
# 应显示 "数据库解密成功"

# ===== Step 11: 测试运行 =====
python -m miru.cli.main run --dry-run
# 确认日报内容正确
python -m miru.cli.main run
# 确认手机收到推送

# ===== Step 12: 安装自动任务 =====
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1

# ===== Step 13: 验证自动任务 =====
schtasks /Query /TN "Miru Daily Report"
schtasks /Run /TN "Miru Daily Report"
# 确认运行成功
```

---

## 8. 定期备份建议

### 每周

```powershell
# 备份配置 (文件小，随时可做)
copy config\settings.yaml config\settings.yaml.backup
copy data\miru.db data\miru.db.backup
```

### 每月

```powershell
# 完整项目备份 (不含 venv，约 2 MB)
# 压缩整个项目目录
powershell Compress-Archive -Path "E:\vibe coding\miru-assistant\*" `
    -DestinationPath "E:\miru_backup_$(Get-Date -Format yyyyMMdd).zip"
```

### 微信版本更新前

每次微信弹出更新提示时，先备份 `E:\wechatfiles\` 和 `database_key`。

---

## 9. 备份脚本

保存为 `scripts\backup_miru.bat`:

```batch
@echo off
chcp 65001 >nul
set BACKUP_DIR=%~dp0..\backup\%date:~0,4%%date:~5,2%%date:~8,2%
mkdir "%BACKUP_DIR%" 2>nul

echo [Miru Backup] %date% %time%
echo Target: %BACKUP_DIR%
echo.

REM --- 关键配置 ---
copy /Y "%~dp0..\config\settings.yaml" "%BACKUP_DIR%\" >nul && echo [OK] settings.yaml

REM --- 数据库 ---
if exist "%~dp0..\data\miru.db" (
    copy /Y "%~dp0..\data\miru.db" "%BACKUP_DIR%\" >nul && echo [OK] miru.db
)

REM --- 自动化脚本 ---
copy /Y "%~dp0run_daily.py" "%BACKUP_DIR%\" >nul && echo [OK] run_daily.py
copy /Y "%~dp0run_daily.bat" "%BACKUP_DIR%\" >nul && echo [OK] run_daily.bat
copy /Y "%~dp0setup_scheduler.ps1" "%BACKUP_DIR%\" >nul && echo [OK] setup_scheduler.ps1

REM --- 项目定义 ---
copy /Y "%~dp0..\pyproject.toml" "%BACKUP_DIR%\" >nul && echo [OK] pyproject.toml

REM --- chatlog 缓存 (含 key) ---
if exist "%USERPROFILE%\.chatlog\chatlog.json" (
    copy /Y "%USERPROFILE%\.chatlog\chatlog.json" "%BACKUP_DIR%\" >nul && echo [OK] chatlog.json
)

echo.
echo [Miru Backup] Done. Saved to %BACKUP_DIR%
```

运行方式:

```powershell
scripts\backup_miru.bat
```

输出到 `backup\YYYYMMDD\` 目录。

---

## 10. 当前项目状态快照

**生成时间**: 2026-07-25

| 类别 | 状态 |
|------|------|
| Miru 版本 | V1.1 |
| 运行状态 | 生产稳定 |
| 测试通过 | 230+ (含已知 3 个环境相关失败) |
| 微信版本 | 4.1.5.30 (已阻止更新) |
| Python | 3.12.10 x64 |
| OS | Windows 10 Pro 10.0.19045 |
| 监控群数 | 6 |
| LLM 模型 | deepseek-v4-flash |
| 推送方式 | PushPlus (200条/天免费) |
| 自动运行 | 每天 22:00 (Windows Task Scheduler) |
| 每日 Token | ~3000-5000 (¥0.003-0.005) |
| 数据库 Key | 已配置 (64 hex) |

---

## 11. 单点故障风险

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| `config/settings.yaml` 丢失 | 🔴 致命 | 备份到云端/U盘 |
| 微信自动更新到 4.1.11+ | 🔴 严重 | hosts 阻止 + 手动关闭自动更新 |
| database key 失效 | 🔴 严重 | chatlog_alpha 可重新提取 |
| DeepSeek API Key 失效 | 🔴 严重 | 登录 platform.deepseek.com 重建 |
| PushPlus token 失效 | 🟡 中等 | 登录 pushplus.plus 重新获取 |
| `weixin_4.1.5.30.exe` 丢失 | 🟡 中等 | GitHub wechat-windows-versions 仓库 |
| WeChat 数据目录路径变更 | 🟡 中等 | `miru doctor` 可自动检测常用路径 |
| chatlog_alpha 仓库被删 | 🟡 中等 | 已有预下载版本，备份 exe |

**最高风险**: `config/settings.yaml` 丢失。所有密钥集中在此文件，**必须确保有多份备份**。

---

*文档结束。最后更新: 2026-07-25*
