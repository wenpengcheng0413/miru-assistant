"""
Miru Assistant — Bootstrap 入口 (V2)。

这是自动化执行（Task Scheduler）的唯一 Python 入口。
在导入重型模块之前执行所有预检，确保即使依赖缺失，
也能在 bootstrap.log 中留下明确的诊断信息。

执行流程:
  1. 自定位项目根目录
  2. 确保 data/logs/ 存在
  3. 打开 Tier 1 日志 (bootstrap.log)
  4. Python 版本检查 (>= 3.11)
  5. 核心依赖可导入性检查
  6. 配置文件存在性 + YAML 合法性检查
  7. Windows 平台检查
  8. 管理员权限检查
  9. 微信进程运行检查 (warn only)
  10. PushPlus token 配置检查 (warn only)
  11. 初始化完整日志系统 (loguru)
  12. 运行 MiruPipeline
  13. 返回结构化退出码

退出码 (Task Scheduler 据此决定重试):
    0 = 成功
    1 = 永久错误 (配置/依赖缺失 → 不重试)
    2 = 临时错误 (未捕获异常 → 重试)
    3 = 环境错误 (非 Windows/无管理员权限 → 重试)
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

# ================================================================
# Phase 1: 自定位项目根目录
# ================================================================
# 本文件位于 src/miru/bootstrap.py → 向上 3 级到项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ================================================================
# Phase 2: 确保日志目录存在
# ================================================================
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ================================================================
# Phase 3: Tier 1 日志 — 裸文件写入 (不依赖 loguru)
# ================================================================
BOOTSTRAP_LOG = LOG_DIR / "bootstrap.log"


def _log(msg: str) -> None:
    """写入 Tier 1 bootstrap 日志。

    使用裸 open().write() — 即使 loguru 不可用也能工作。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(BOOTSTRAP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # 连日志都写不了就没办法了


# ================================================================
# Phase 4-12: main()
# ================================================================


def main() -> int:
    """执行所有预检，然后运行 Pipeline。返回退出码。"""
    _log("=" * 60)
    _log("Bootstrap starting — pre-flight checks")

    # ---- 4. Python 版本 ----
    vi = sys.version_info
    _log(f"Python {vi.major}.{vi.minor}.{vi.micro} on {sys.platform}")
    if vi < (3, 11):
        _log(f"[FATAL] Python >= 3.11 required, found {vi.major}.{vi.minor}")
        return 1

    # ---- 5. 核心依赖可导入性 ----
    essential = {
        "yaml": "pyyaml",
        "pydantic": "pydantic",
        "loguru": "loguru",
        "psutil": "psutil",
    }
    missing = []
    for mod_name, pip_name in essential.items():
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(f"{pip_name} (import {mod_name})")
    if missing:
        _log(f"[FATAL] Missing dependencies: {', '.join(missing)}")
        _log("Run: pip install -r requirements.txt")
        return 1
    _log("Essential imports: OK")

    # ---- 6. 配置文件 ----
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not config_path.exists():
        _log(f"[FATAL] Config not found: {config_path}")
        _log("Copy config/settings.example.yaml to config/settings.yaml and edit")
        return 1

    import yaml
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            _log("[FATAL] Config is empty or invalid")
            return 1
    except yaml.YAMLError as e:
        _log(f"[FATAL] Invalid YAML in config: {e}")
        return 1
    except Exception as e:
        _log(f"[FATAL] Cannot read config: {e}")
        return 1
    _log("Config file: OK")

    # ---- 7. 平台检查 ----
    if sys.platform != "win32":
        _log("[FATAL] Windows required (needs WeChat process access)")
        return 3
    _log("Platform: Windows OK")

    # ---- 8. 管理员权限 ----
    import ctypes
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False
    if not is_admin:
        _log("[FATAL] Administrator privileges required")
        return 3
    _log("Admin check: OK")

    # ---- 9. 微信进程 (warn only — Pipeline 会再次检查) ----
    import psutil
    wechat_found = False
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info["name"] or "").lower()
                if name in ("wechat.exe", "weixin.exe"):
                    wechat_found = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        _log(f"[WARN] Cannot scan processes: {e}")

    if wechat_found:
        _log("WeChat check: OK (process found)")
    else:
        _log("[WARN] WeChat not running — pipeline may fail at environment check")

    # ---- 10. PushPlus token (warn only) ----
    try:
        notifiers = raw.get("miru", {}).get("notifiers", [])
        pushplus_cfgs = [n for n in notifiers if n.get("type") == "pushplus"]
        if pushplus_cfgs:
            token = pushplus_cfgs[0].get("token", "")
            if not token or token.startswith("${"):
                _log("[WARN] PushPlus token not configured — push will be skipped")
            else:
                _log("PushPlus token: OK")
        else:
            _log("[WARN] No pushplus notifier in config")
    except Exception:
        _log("[WARN] Cannot parse PushPlus config")
    _log("Config surface check: OK")

    # ---- 11. 初始化完整日志系统 ----
    # 此时所有核心依赖已验证可用，安全导入
    from miru.core.logging import init_logging, set_run_id
    init_logging(
        log_dir=str(LOG_DIR),
        level="INFO",
    )
    _log("Loguru initialized — Tier 2 logging active")
    _log("All pre-flight checks passed — entering pipeline")

    # ---- 12. 运行 Pipeline ----
    try:
        from miru.core.pipeline import MiruPipeline

        pipeline = MiruPipeline(str(config_path))
        ctx = pipeline.run(dry_run=False)

        _log(f"Pipeline complete: {'SUCCESS' if ctx.is_success else 'FAILED'}")
        _log(f"  Groups: {ctx.groups_collected} collected")
        _log(f"  Messages: {ctx.raw_messages_count} raw / {ctx.filtered_messages_count} filtered")
        _log(f"  Push status: {ctx.push_status}")

        if ctx.has_errors:
            from miru.core.exit_codes import classify_pipeline_error
            code = classify_pipeline_error(ctx.errors)
            _log(f"  Errors: {ctx.errors}")
            _log(f"  Exit code: {code.name} ({int(code)})")
            return int(code)

        return 0

    except Exception:
        _log(f"[FATAL] Unhandled exception:\n{traceback.format_exc()}")
        return 2


# ================================================================
# 入口（双重 try/except 保护）
# ================================================================
if __name__ == "__main__":
    exit_code = 2  # 默认：临时错误
    try:
        exit_code = main()
    except Exception:
        # main() 本身的崩溃 — 最后的兜底
        with open(BOOTSTRAP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[FATAL] Bootstrap crash:\n{traceback.format_exc()}\n")
        exit_code = 2
    _log(f"Bootstrap exiting (code={exit_code})")
    sys.exit(exit_code)
