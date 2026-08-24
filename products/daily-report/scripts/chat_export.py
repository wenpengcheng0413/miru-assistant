#!/usr/bin/env python
"""
Miru Assistant — Chat Analyzer 聊天记录导出 CLI。

用法:
    python scripts/chat_export.py 张三                    # 导出 TXT
    python scripts/chat_export.py 张三 --analyze          # 导出 + AI 分析
    python scripts/chat_export.py 张三 --full             # 导出 + 统计 + 时间线 + 分析
    python scripts/chat_export.py                         # 列出所有联系人供选择
    python scripts/chat_export.py 张 --output data/chats  # 部分昵称 → 交互选择

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
  python scripts/chat_export.py 张三
  python scripts/chat_export.py 张三 --analyze
  python scripts/chat_export.py 张三 --full
  python scripts/chat_export.py 张三 --start 2024-06-01 --end 2024-12-31
  python scripts/chat_export.py              (列出联系人供选择)
        """,
    )
    parser.add_argument(
        "contact",
        nargs="?",
        default=None,
        help="联系人名称（昵称/备注/微信号），留空则列出所有联系人",
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
    parser.add_argument(
        "--full",
        action="store_true",
        help="一键完成: 导出 + 统计 + 时间线 + AI 分析",
    )

    args = parser.parse_args()

    # --full 等价于三个功能全开
    if args.full:
        args.analyze = True
        args.stats = True
        args.timeline = True

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

    # ---- 确定联系人（支持交互选择） ----
    from miru.chat_analyzer import ChatExportError, ContactNotFoundError, export_chat

    contact_name, contact_username = _resolve_contact_interactive(
        args.contact,
        args.config,
        args.output,
    )
    if contact_name is None:
        return 2  # 交互选择被取消或失败

    print()
    print("=" * 60)
    print("  Miru Chat Analyzer — 聊天记录导出")
    print("=" * 60)
    print(f"  联系人: {contact_name}")
    if args.start:
        print(f"  起始日期: {args.start}")
    if args.end:
        print(f"  结束日期: {args.end}")
    print(f"  输出目录: {args.output}")
    if args.full:
        print("  模式: 全流程 (导出 + 统计 + 时间线 + AI 分析)")
    print("=" * 60)
    print()

    try:
        result = export_chat(
            contact_name=contact_name,
            output_dir=args.output,
            start_date=args.start,
            end_date=args.end,
            config_path=args.config,
            username=contact_username,
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


def _resolve_contact_interactive(
    contact_input: str | None,
    config_path: str,
    output_dir: str,
) -> tuple[str | None, str | None]:
    """
    解析联系人名称（支持交互选择）。

    流程:
        0. 白名单精确匹配 (name / username / remark) → 直接命中
        1. 未提供名称 → 列出所有联系人供选择
        2. 名称精确/唯一匹配 → 直接使用
        3. 多个模糊匹配 → 列出候选供选择
        4. 无匹配 → 报错

    Returns:
        (显示名称, username) — username 为白名单命中时的微信号；
        失败/取消返回 (None, None)。
    """
    from miru.chat_analyzer import ChatExportError
    from miru.chat_analyzer.contacts import load_contact_aliases, resolve_via_aliases
    from miru.chat_analyzer.exporter import ChatExporter, find_contact_candidates

    # ---- 0. 白名单优先（离线可靠，contact.db 解密失败也能用） ----
    if contact_input:
        aliases = load_contact_aliases("config/contacts.yaml")
        alias = resolve_via_aliases(aliases, contact_input)
        if alias is not None:
            print(f"  [白名单] 命中联系人: {alias.name} ({alias.username})")
            return alias.name, alias.username or None

    try:
        exporter = ChatExporter(config_path=config_path)
        contacts = exporter.list_contacts()
    except ChatExportError as e:
        print(f"\n[错误] {e}")
        if e.suggestion:
            print(f"  建议: {e.suggestion}")
        return None, None

    if not contact_input:
        # ---- 模式: 列出所有联系人 ----
        if not contacts:
            print("\n[错误] 数据库中没有可用联系人")
            return None, None
        return _select_from_list(contacts, "可用联系人"), None

    # ---- 模式: 名称匹配 ----
    candidates = find_contact_candidates(contacts, contact_input)
    if not candidates:
        print(f"\n[错误] 未找到联系人: {contact_input}")
        print(f"  建议: 数据库中有 {len(contacts)} 个联系人。请使用完整昵称、备注或微信号重试。")
        return None, None
    if len(candidates) == 1:
        return candidates[0].display_name, None
    # 多个候选 → 交互选择
    return _select_from_list(candidates, f"联系人 '{contact_input}' 有多个匹配"), None


def _select_from_list(contacts, title: str) -> str | None:
    """
    打印联系人列表并让用户输入编号选择。

    Args:
        contacts: ContactInfo 列表。
        title: 列表标题。

    Returns:
        选中的联系人显示名称；取消返回 None。
    """
    total = len(contacts)
    page_size = 50
    page = 0

    while True:
        start = page * page_size
        end = min(start + page_size, total)
        print()
        print("=" * 60)
        print(f"  {title}")
        if total > page_size:
            print(f"  (第 {page + 1}/{(total + page_size - 1) // page_size} 页，共 {total} 个)")
        print("=" * 60)
        for i in range(start, end):
            c = contacts[i]
            extra = f" ({c.username})" if c.username else ""
            print(f"  [{i + 1:4d}] {c.display_name}{extra}")
        print("=" * 60)

        prompt = f"请输入编号 (1-{total})"
        if total > page_size:
            prompt += "，或输入 n/p 翻页/上一页"
        prompt += "，按回车取消: "

        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return None

        if not raw:
            print("已取消")
            return None

        # 翻页
        if total > page_size:
            if raw.lower() == "n" and end < total:
                page += 1
                continue
            if raw.lower() == "p" and page > 0:
                page -= 1
                continue

        try:
            idx = int(raw)
            if 1 <= idx <= total:
                return contacts[idx - 1].display_name
        except ValueError:
            pass

        print(f"[错误] 无效的编号: {raw}")
        return None


if __name__ == "__main__":
    sys.exit(main())
