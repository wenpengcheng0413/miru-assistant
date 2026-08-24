"""
Miru Assistant — 每日静默运行入口。

供 Windows Task Scheduler 通过 pythonw.exe 调用。
pythonw.exe 不弹黑窗口，所有输出写入日志文件。

退出码 (Task Scheduler 根据退出码决定重试):
    0 = 成功
    1 = 永久错误 (配置缺失 / API key 未配置 → 不重试)
    2 = 临时错误 (网络 / API 超时 → 重试)
    3 = 环境错误 (微信未运行 / 权限不足 → 重试)
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    """主入口。返回退出码。"""
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now().strftime('%Y-%m-%d')}.log"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"Miru Daily Run — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n\n")

        try:
            from miru.core.pipeline import MiruPipeline

            config_path = PROJECT_ROOT / "config" / "settings.yaml"
            if not config_path.exists():
                f.write("[ERROR] 配置文件不存在: config/settings.yaml\n")
                f.write("请从 config/settings.example.yaml 复制并填入配置。\n")
                return 1  # 永久错误

            pipeline = MiruPipeline(str(config_path))
            ctx = pipeline.run(dry_run=False)

            f.write(f"\n结果: {'SUCCESS' if ctx.is_success else 'FAILED'}\n")
            f.write(f"群组: {ctx.groups_collected} 采集\n")
            f.write(f"消息: {ctx.raw_messages_count} 原始, {ctx.filtered_messages_count} 有效\n")
            f.write(f"推送: {ctx.push_status}\n")

            if ctx.has_errors:
                from miru.core.exit_codes import classify_pipeline_error
                code = classify_pipeline_error(ctx.errors)
                f.write(f"错误: {ctx.errors}\n")
                f.write(f"退出码: {code.name}\n")
                return int(code)

            return 0

        except Exception:
            f.write(f"[FATAL] 未捕获异常:\n{traceback.format_exc()}\n")
            return 2  # 临时错误


if __name__ == "__main__":
    sys.exit(main())
