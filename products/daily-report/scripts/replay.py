"""
Miru Assistant — 日报回放入口。

用法:
    python scripts/replay.py --date 2026-07-25           # 回放指定日期 (dry-run)
    python scripts/replay.py --date 2026-07-25 --push     # 回放并推送

Replay Mode 特点:
    - 复用正式 Pipeline (不复制业务逻辑)
    - 跳过所有数据库写入
    - 默认不推送 (--push 开启)
    - 不影响正式每日任务
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Miru Replay — 回放指定日期的日报生成",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="回放日期 (YYYY-MM-DD), 例如 2026-07-25",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=False,
        help="真正推送 (默认仅 dry-run 输出)",
    )
    args = parser.parse_args()

    # 验证日期格式
    try:
        replay_dt = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"[ERROR] 日期格式错误: {args.date} — 请使用 YYYY-MM-DD")
        return 1

    if replay_dt > datetime.now():
        print(f"[ERROR] 回放日期不能在未来: {args.date}")
        return 1

    print(f"\n{'=' * 60}")
    print(f"  Miru Replay — {args.date}")
    print(f"  Push: {'ON' if args.push else 'OFF (dry-run)'}")
    print(f"{'=' * 60}\n")

    from miru.core.pipeline import MiruPipeline

    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        return 1

    start = time.time()
    pipeline = MiruPipeline(str(config_path))
    ctx = pipeline.run(
        dry_run=not args.push,
        replay_date=args.date,
    )
    elapsed = time.time() - start

    # ---- Replay Summary ----
    print(f"\n{'=' * 60}")
    print(f"  Replay Summary — {args.date}")
    print(f"{'=' * 60}")
    print(f"  Success:        {ctx.is_success}")
    print(f"  Duration:       {elapsed:.1f}s")
    print(f"  Groups:         {ctx.groups_collected} matched")
    print(f"  Raw messages:   {ctx.raw_messages_count}")
    print(f"  Filtered:       {ctx.filtered_messages_count}")
    print(f"  LLM groups:     {ctx.groups_summarized} success / {ctx.groups_failed} failed")
    print(f"  LLM tokens:     {ctx.llm_token_usage}")
    print(f"  Push status:    {ctx.push_status or 'skipped (replay)'}")

    if ctx.errors:
        print(f"  Errors:         {ctx.errors}")
    if ctx.warnings:
        print(f"  Warnings:       {ctx.warnings}")

    # ---- Report Preview ----
    if ctx.report_md:
        print(f"\n{'=' * 60}")
        print(f"  Report Preview ({len(ctx.report_md)} chars)")
        print(f"{'=' * 60}")
        print(ctx.report_md)

    return 0 if ctx.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
