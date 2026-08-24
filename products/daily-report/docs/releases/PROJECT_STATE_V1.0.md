# Project State — Miru Daily Report V1.0

> **封版日期**: 2026-07-27  
> **写给未来的自己**: 这份文档记录了 V1.0 封版时的所有工程决策和状态。  
>   如果你在半年后重新打开这个项目，从这里开始读。

---

## 1. 为什么停止继续开发

2026 年 7 月 27 日 22:00，发现 Miru Daily Report 未能自动推送日报。经过系统性故障排查，定位到根因是 Windows Task Scheduler 在处理含空格路径时的解析错误。

修复这个 bug 后，我们进行了一次全面的工程化改进（Stage 1），引入了 `launcher.bat` 和 `bootstrap.py` 作为新的自动化入口，并建立了三层日志架构。

**在当前时间点，核心功能已完整且经过验证：**
- Task Scheduler 自动触发 ✅
- 微信消息读取 ✅
- DeepSeek LLM 分析 ✅
- 日报生成 ✅
- PushPlus 手机推送 ✅
- 三层日志正常 ✅
- 失败重试机制 ✅

**继续开发的边际收益递减：** 每增加一行代码，就增加一个引入新 bug 的可能性。剩余的已知问题（见第 5 节）没有一个是阻断性的。

**决策：封版 V1.0，进入 7 天稳定运行观察期。** 在观察期内不修改任何代码。如果 7 天后一切正常，再从容规划 V1.1。

---

## 2. 为什么没有继续 Stage 2

Stage 2 的原计划是引入 `src/miru/utils/project_root.py` 作为全局路径解析入口，并修改 10 个文件中 20+ 处相对路径参数。

**不做的理由：**

1. **它解决的是假设性问题，不是实际问题。** 当前所有自动化路径（Task Scheduler → launcher.bat → bootstrap.py → MiruPipeline）都使用绝对路径。依赖 CWD 的地方只在手动 CLI 场景下存在，而 CLI 用户自然会 cd 到项目根目录。

2. **改动范围太大，风险不成比例。** 修改 10 个文件的函数签名（`str` → `str | None`）会触及每一个模块的调用链。在一个已经能正常工作的系统上做这种规模的重构，引入回归 bug 的风险远大于收益。

3. **bootstrap.py 已经实现了相同的自定位逻辑。** `Path(__file__).resolve().parent.parent.parent` 是 project_root 的核心逻辑，只是没有提取成公共模块。提取它属于代码整理，不是 bug 修复。

**替代方案：** 将来如果需要，只做 Stage 2-Lite——删除 `diagnostics.py` 中的两行硬编码路径，修复 `scheduler.py` 中的两处相对路径。改动量不到 10 行。

---

## 3. 为什么采用 launcher + bootstrap 架构

### 问题驱动

V1.0 之前，Task Scheduler 直接调用 `pythonw.exe scripts/run_daily.py`。这有两个致命缺陷：

1. **路径空格 bug**: `E:\vibe coding\...` 中的空格导致 Windows 解析错误
2. **零日志死锁**: `logs/` 目录在 `run_daily.py` 内部创建。如果 Python 无法启动，日志目录不存在，无法记录任何错误

### 方案权衡

| 方案 | 优点 | 缺点 |
|---|---|---|
| 修复 Task Scheduler 配置（只加引号）| 改动最小 | 无法解决零日志问题 |
| .bat 启动脚本 | `%~dp0` 自定位，shell 级别日志 | Windows only（本项目本身就是 Windows only）|
| .ps1 启动脚本 | 功能强大 | ExecutionPolicy 问题，版本兼容性 |
| C 语言 bootloader | 完全自包含 | 过度设计 |

### 最终选择

**launcher.bat (.bat) + bootstrap.py (.py)** — 两层启动，各司其职：

- **launcher.bat**: 处理 Python 之前的一切。创建日志目录、检查 venv 存在、检查配置存在、记录启动事件。这些工作在 shell 层面完成，不依赖 Python。
- **bootstrap.py**: 处理 Python 启动后、重型导入之前的一切。用最少的依赖（仅 stdlib + yaml + psutil）做 7 项预检，通过后才导入重型模块。

### 为什么用 pythonw.exe 而不是 python.exe

`pythonw.exe` 是 Python for Windows 的无控制台版本——不会弹出黑色命令行窗口。对于用户登录后自动触发的后台任务，这是必须的。

---

## 4. 架构决策记录 (ADR)

### ADR-1: Task Scheduler 的 Execute 用 cmd.exe 而不是直接调 pythonw.exe

**决策**: Execute = `cmd.exe`, Arguments = `/c "<quoted launcher path>"`

**理由**: `cmd.exe` 在 `C:\Windows\System32\` 下，路径永远不含空格。`/c` 后面的参数是一个被双引号包裹的完整路径，即使该路径含空格也能正确解析。这是 Windows 上对抗路径空格最可靠的方式。

### ADR-2: 三层日志而非单一日志

**决策**: launcher.log (shell) + bootstrap.log (预检) + miru_*.log (pipeline)

**理由**: 单一日志的假设是"所有日志写作者都能正常工作"。但现实中，loguru 可能无法导入、Python 可能无法启动、甚至 pythonw.exe 可能不存在。每一层都有自己的依赖范围：Tier 0 依赖 shell，Tier 1 依赖 Python stdlib，Tier 2 依赖完整依赖链。这样当上层失败时，下层仍有日志。

### ADR-3: 预检放在独立 bootstrap.py 而非 pipeline.py 开头

**决策**: 独立的 `bootstrap.py` 入口文件

**理由**: `from miru.core.pipeline import MiruPipeline` 会触发整个依赖链的导入（loguru, jinja2, httpx, openai, pymem...）。如果任何一个依赖缺失，import 就会在 call stack 深处崩溃，错误信息难以解读。bootstrap.py 先用 stdlib 检查依赖，再安全地导入重型模块。

### ADR-4: 微信未运行不阻断预检

**决策**: 微信检查失败 → WARN，不 exit

**理由**: MiruPipeline 的 Step 1 会再次检查微信并给出更详细的错误信息。bootstrap 的职责是"确保能安全进入 Pipeline"，而不是"确保 Pipeline 一定成功"。

---

## 5. 目前还有哪些问题

### 已知但不紧急（计划 V1.1）

| # | 问题 | 为什么没修 |
|---|---|---|
| 1 | contact.db 解密偶发失败 | Name2Id 回退方案已验证有效 |
| 2 | ConsoleNotifier GBK emoji 错误 | PushPlus 推送正常，控制台输出是 debug 用途 |
| 3 | debug_* 文件散落 logs/ | 不影响功能，只是目录整洁问题 |
| 4 | diagnostics.py 硬编码 E:/ C:/ | 本项目运行在这台机器上，这些路径恰好存在 |
| 5 | scheduler.py 相对路径 | 自动化链路传绝对路径，不触发此 bug |

### 计划但未实施（V1.2+）

| # | 功能 | 为什么没做 |
|---|---|---|
| 1 | 每日健康确认推送 | 需要增加配置开关和新的通知类型 |
| 2 | settings.yaml 自动备份 | 需要修改 bootstrap.py 和 backup.py |
| 3 | Docker 化 | 当前 Windows-only 架构需要较大改动 |
| 4 | 项目路径加固 (project_root.py) | 见第 2 节分析 |

---

## 6. 以后继续开发时建议从哪里开始

### 如果你是未来的自己，想继续这个项目：

**第一步：检查系统是否还在正常运行。**

```powershell
schtasks /query /tn "Miru Daily Report" /v /fo LIST | findstr "上次"
Get-Content "data\logs\launcher.log" -Tail 5
Get-Content "data\logs\bootstrap.log" -Tail 5
```

如果一切正常 → 你可以放心地开始开发。

**第二步：读 Release 文档。**
打开 `MIRU_DAILY_REPORT_V1.0_RELEASE.md`，重新理解整体架构。

**第三步：从 V1.1 计划开始。**
V1.1 的目标是修复所有已知的低风险问题（见第 5 节）。这些改动都很小（每个 < 10 行），是熟悉代码的最佳起点：

1. 删除 `diagnostics.py` L365-366 的硬编码路径
2. 在 ConsoleNotifier 中对 emoji 做 encode fallback
3. debug 文件输出到子目录

**第四步：观察稳定后再做 V1.2。**
V1.2 的两个功能（健康推送 + 配置备份）需要在 bootstrap.py 和 pipeline.py 中增加逻辑。改动量 ~50 行。

**第五步：考虑是否值得做跨平台/Docker。**
V2.0 的大改动（Docker 化）需要评估：你是否还需要在 Linux 上运行？如果是，微信的内存读取方案需要完全重做。如果只是想在 Windows 上隔离运行，Docker for Windows + 微信是个复杂的组合。

### 不建议的下一步

- ❌ **不要做 project_root.py 全项目路径统一。** 这是预防性重构，成本大于收益。除非你发现有人在非项目根目录运行 CLI 并且遇到了实际错误。
- ❌ **不要重写 Pipeline。** 6 阶段架构工作正常。在出现真正的扩展需求之前，保持简单。
- ❌ **不要换 LLM 提供商。** DeepSeek 的 JSON mode 与当前 Pydantic schema 紧密耦合。如果要换，需要重写整个 `llm/` 模块。

---

## 7. 给未来的自己的备忘录

- **如果系统突然不工作了**，先看 `launcher.log`。90% 的故障在这一层就能定位。
- **如果换电脑**，参考 `MIRU_DAILY_REPORT_V1.0_RELEASE.md` 第 14 节的迁移指南。
- **如果微信更新了**，运行 `python -m miru.cli.main doctor` 检查兼容性。
- **如果 PushPlus 挂了**，这是外部服务，无需改代码。考虑换一个推送渠道（`notify/` 下有 base class，新渠道只需实现 `send()` 方法）。
- **settings.yaml 里的密钥是这台机器的。** 不要提交到 git。

---

## 8. 项目文件索引

| 文档 | 用途 |
|---|---|
| `MIRU_DAILY_REPORT_V1.0_RELEASE.md` | 完整 Release 文档 — 架构、功能、运维 |
| `CHANGELOG.md` | 版本变更记录 |
| `GITHUB_RELEASE_NOTES_V1.0.md` | GitHub Release 发布说明 |
| `PROJECT_STATE_V1.0.md` | **本文档** — 开发归档和决策记录 |
| `docs/` | 旧版设计文档（V0.x 时期，可能已过时） |

---

> **封版时间**: 2026-07-27 23:00  
> **封版人**: Miru Assistant Project  
> **下次回顾**: 2026-08-03（7 天观察期结束后）
