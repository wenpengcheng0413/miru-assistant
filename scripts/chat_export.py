#!/usr/bin/env python
"""
Miru Assistant — Chat Analyzer 聊天记录导出 CLI。

用法:
    python scripts/chat_export.py --contact "张三"
    python scripts/chat_export.py --contact "张三" --output output
    python scripts/chat_export.py --contact "张三" --start 2024-01-01 --end 2024-12-31

退出码:
    0 = 成功
    1 = 永久错误 (联系人不存在 / 配置缺失)
    2 = 临时错误 (微信未运行 / 解密失败 / 权限不足)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    """主入口。返回退出码。"""
    parser = argparse.ArgumentParser(
        description="Miru Chat Analyzer — 导出微信联系人聊天记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/chat_export.py --contact "张三"
  python scripts/chat_export.py --contact "张三" --output data/chats
  python scripts/chat_export.py --contact "李四" --start 2024-06-01 --end 2024-12-31
        """,
    )
    parser.add_argument(
        "--contact",
        "-c",
        required=True,
        help="联系人名称（昵称/备注/微信号）",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output",
        help="输出目录根路径（默认: output）",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="起始日期 (YYYY-MM-DD)，不指定则从最早消息开始",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="结束日期 (YYYY-MM-DD)，不指定则到最新消息",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="配置文件路径（默认: config/settings.yaml）",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="导出后调用 DeepSeek 进行 AI 分析（生成 analysis.md）",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="导出后生成聊天统计（生成 statistics.json）",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="导出后生成事件时间线（生成 timeline.json）",
    )

    args = parser.parse_args()

    # ---- 初始化日志 ----
    try:
        from miru.core.logging import init_logging

        init_logging()
    except Exception:
        pass  # 日志初始化失败不阻断执行

    from loguru import logger

    # ---- 验证参数 ----
    if args.start:
        try:
            datetime.strptime(args.start, "%Y-%m-%d")
        except ValueError:
            logger.error(f"无效的起始日期格式: {args.start}，应为 YYYY-MM-DD")
            return 1

    if args.end:
        try:
            datetime.strptime(args.end, "%Y-%m-%d")
        except ValueError:
            logger.error(f"无效的结束日期格式: {args.end}，应为 YYYY-MM-DD")
            return 1

    # ---- 执行导出 ----
    from miru.chat_analyzer import ChatExportError, ContactNotFoundError, export_chat

    print()
    print("=" * 60)
    print("  Miru Chat Analyzer — 聊天记录导出")
    print("=" * 60)
    print(f"  联系人: {args.contact}")
    if args.start:
        print(f"  起始日期: {args.start}")
    if args.end:
        print(f"  结束日期: {args.end}")
    print(f"  输出目录: {args.output}")
    print("=" * 60)
    print()

    try:
        result = export_chat(
            contact_name=args.contact,
            output_dir=args.output,
            start_date=args.start,
            end_date=args.end,
            config_path=args.config,
        )
    except ContactNotFoundError as e:
        print(f"\n[错误] {e}")
        if e.suggestion:
            print(f"  建议: {e.suggestion}")
        return 1
    except ChatExportError as e:
        print(f"\n[错误] {e}")
        if e.suggestion:
            print(f"  建议: {e.suggestion}")
        return 2
    except Exception as e:
        print(f"\n[致命错误] 未预期异常: {e}")
        logger.exception("未预期异常")
        return 2

    # ---- 输出结果 ----
    if not result.success:
        print("\n[失败] 导出过程中发生错误:")
        for err in result.errors:
            print(f"  - {err}")
        return 2

    print()
    print("=" * 60)
    print("  导出完成")
    print("=" * 60)
    print(f"  联系人: {result.contact_name}")
    print(f"  消息总数: {result.total_messages}")
    print(f"  文本消息: {result.text_messages}")
    print(f"  图片消息: {result.image_messages}")
    print(f"  语音消息: {result.voice_messages}")
    if result.date_range_start:
        print(f"  时间范围: {result.date_range_start} ~ {result.date_range_end}")
    print(f"  输出文件: {result.output_file}")
    if result.warnings:
        print()
        print("  警告:")
        for w in result.warnings:
            print(f"    - {w}")
    print("=" * 60)
    print()

    # ---- 可选: AI 分析 ----
    if args.analyze:
        from miru.chat_analyzer import ChatAnalysisError
        from miru.chat_analyzer.analyzer import ChatAnalyzer

        chat_dir = str(Path(result.output_file).parent)
        print()
        print("=" * 60)
        print("  DeepSeek AI 分析")
        print("=" * 60)
        print()

        try:
            analyzer = ChatAnalyzer(config_path=args.config)
            analysis = analyzer.analyze(
                contact_name=result.contact_name,
                chat_file=result.output_file,
                output_dir=chat_dir,
            )
        except ChatAnalysisError as e:
            print(f"\n[错误] {e}")
            if e.suggestion:
                print(f"  建议: {e.suggestion}")
            return 2

        if not analysis.success:
            print("\n[失败] AI 分析失败:")
            for err in analysis.errors:
                print(f"  - {err}")
            return 2

        print()
        print("=" * 60)
        print("  AI 分析完成")
        print("=" * 60)
        print(f"  分析消息数: {analysis.total_messages}")
        if analysis.token_usage:
            print(
                f"  Token 用量: {analysis.token_usage.get('total', 0)} "
                f"(prompt={analysis.token_usage.get('prompt', 0)}, "
                f"completion={analysis.token_usage.get('completion', 0)})"
            )
        print(f"  分析报告: {analysis.analysis_file}")
        print("=" * 60)
        print()

    # ---- 可选: 事件时间线 ----
    if args.timeline:
        from miru.chat_analyzer.timeline import TimelineAnalyzer

        chat_dir = str(Path(result.output_file).parent)
        print()
        print("=" * 60)
        print("  事件时间线")
        print("=" * 60)
        print()

        timeline = TimelineAnalyzer()
        tl_result = timeline.analyze(
            contact_name=result.contact_name,
            chat_file=result.output_file,
            output_dir=chat_dir,
        )

        if not tl_result.success:
            print("\n[失败] 时间线生成失败:")
            for err in tl_result.errors:
                print(f"  - {err}")
            return 2

        print()
        print("=" * 60)
        print("  时间线生成完成")
        print("=" * 60)
        print(f"  事件数量: {tl_result.total_events}")
        print(f"  时间线文件: {tl_result.timeline_file}")
        print("=" * 60)
        print()

    # ---- 可选: 聊天统计 ----
    if args.stats:
        from miru.chat_analyzer.statistics import ChatStatistics

        chat_dir = str(Path(result.output_file).parent)
        print()
        print("=" * 60)
        print("  聊天统计")
        print("=" * 60)
        print()

        stats = ChatStatistics()
        stat_result = stats.analyze(
            contact_name=result.contact_name,
            chat_file=result.output_file,
            output_dir=chat_dir,
        )

        if not stat_result.success:
            print("\n[失败] 聊天统计失败:")
            for err in stat_result.errors:
                print(f"  - {err}")
            return 2

        print()
        print("=" * 60)
        print("  聊天统计完成")
        print("=" * 60)
        print(f"  统计消息数: {stat_result.total_messages}")
        print(f"  统计文件: {stat_result.statistics_file}")
        print("=" * 60)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
