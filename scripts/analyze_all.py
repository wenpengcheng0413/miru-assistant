#!/usr/bin/env python
"""
Miru Assistant — Chat Analyzer 批量全流程 (白名单模式)。

读取 config/contacts.yaml 白名单，对每个联系人执行:
    导出 chat.txt → AI 分析 analysis.md → 统计 statistics.json → 时间线 timeline.json

用法:
    python scripts/analyze_all.py                 # 处理白名单全部联系人
    python scripts/analyze_all.py --contacts Krista,张三   # 只处理指定联系人
    python scripts/analyze_all.py --output data/chats      # 自定义输出目录
    python scripts/analyze_all.py --skip-analyze           # 跳过 AI 分析（省钱）

退出码:
    0 = 全部成功
    1 = 无白名单配置 / 参数错误
    2 = 部分或全部失败
"""

import argparse
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    """主入口。返回退出码。"""
    parser = argparse.ArgumentParser(
        description="Miru Chat Analyzer — 批量全流程 (白名单模式)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/analyze_all.py
  python scripts/analyze_all.py --contacts Krista
  python scripts/analyze_all.py --skip-analyze
        """,
    )
    parser.add_argument(
        "--contacts",
        default=None,
        help="只处理指定联系人（逗号分隔，用 name 匹配白名单）",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output",
        help="输出目录根路径（默认: output）",
    )
    parser.add_argument(
        "--contacts-config",
        default="config/contacts.yaml",
        help="白名单配置文件路径（默认: config/contacts.yaml）",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="主配置文件路径（默认: config/settings.yaml）",
    )
    parser.add_argument(
        "--skip-analyze",
        action="store_true",
        help="跳过 DeepSeek AI 分析（只导出 + 统计 + 时间线）",
    )

    args = parser.parse_args()

    # ---- 初始化日志 ----
    try:
        from miru.core.logging import init_logging

        init_logging()
    except Exception:
        pass

    from miru.chat_analyzer.contacts import load_contact_aliases, load_contacts_config

    # ---- 1. 加载白名单（双源） ----
    # 优先 settings.yaml → miru.contacts.whitelist（带 wxid，离线全量导出）
    # 回退 config/contacts.yaml（旧白名单，在线导出）
    aliases = load_contacts_config(args.config)
    if not aliases:
        aliases = load_contact_aliases(args.contacts_config)
    if not aliases:
        print()
        print("=" * 60)
        print("  [错误] 没有可用的联系人白名单")
        print("=" * 60)
        print(f"  主配置: {args.config}  (miru.contacts.whitelist)")
        print(f"  旧配置: {args.contacts_config}")
        print("  请填写 wxid（推荐）或参考 config/contacts.example.yaml")
        print("=" * 60)
        print()
        return 1

    # ---- 2. 过滤指定联系人 ----
    if args.contacts:
        wanted = {name.strip().lower() for name in args.contacts.split(",") if name.strip()}
        aliases = [a for a in aliases if a.name.lower() in wanted]
        if not aliases:
            print(f"\n[错误] 白名单中没有匹配的联系人: {args.contacts}")
            return 1

    print()
    print("=" * 60)
    print("  Miru Chat Analyzer — 批量全流程")
    print("=" * 60)
    print(f"  联系人数量: {len(aliases)}")
    print(f"  输出目录:   {args.output}")
    print(f"  AI 分析:    {'跳过' if args.skip_analyze else '开启'}")
    print("=" * 60)
    print()

    # ---- 3. 逐个处理 ----
    from miru.chat_analyzer.analyzer import ChatAnalyzer
    from miru.chat_analyzer.exporter import ChatExporter
    from miru.chat_analyzer.offline_exporter import ContactFullExporter
    from miru.chat_analyzer.statistics import ChatStatistics
    from miru.chat_analyzer.timeline import TimelineAnalyzer

    # 双导出后端: 有 wxid → 离线全量（推荐）；无 wxid → 在线（微信运行中）
    offline_exporter = ContactFullExporter()
    online_exporter = ChatExporter(config_path=args.config)
    analyzer = ChatAnalyzer(config_path=args.config)
    stats_runner = ChatStatistics()
    timeline_runner = TimelineAnalyzer()

    results: list[dict] = []
    total_start = time.time()

    for i, alias in enumerate(aliases, 1):
        results.append(
            _process_one(
                index=i,
                total=len(aliases),
                alias=alias,
                offline_exporter=offline_exporter,
                online_exporter=online_exporter,
                analyzer=analyzer,
                stats_runner=stats_runner,
                timeline_runner=timeline_runner,
                output_dir=args.output,
                skip_analyze=args.skip_analyze,
            )
        )

    # ---- 4. 汇总 ----
    total_elapsed = time.time() - total_start
    ok = sum(1 for r in results if r["success"])
    failed = len(results) - ok

    print()
    print("=" * 60)
    print("  批量处理汇总")
    print("=" * 60)
    print(f"  成功: {ok} / {len(results)}")
    if failed:
        print(f"  失败: {failed}")
    print(f"  总耗时: {total_elapsed:.1f}s")
    print()
    for r in results:
        status = "[OK]  " if r["success"] else "[FAIL]"
        detail = r.get("detail", "")
        print(f"  {status} {r['name']:<20s} {detail}")
    print("=" * 60)
    print()
    print(f"  输出目录: {Path(args.output).resolve()}")
    print()

    return 0 if failed == 0 else 2


def _process_one(
    index: int,
    total: int,
    alias,
    offline_exporter,
    online_exporter,
    analyzer,
    stats_runner,
    timeline_runner,
    output_dir: str,
    skip_analyze: bool,
) -> dict:
    """
    处理单个联系人: 导出 + (分析) + 统计 + 时间线。

    导出后端选择:
        - alias.wxid → ContactFullExporter（离线全量，推荐）
        - 无 wxid    → ChatExporter（在线，需微信运行）

    Returns:
        {name, success, detail} 汇总条目。
    """
    from loguru import logger

    name = alias.name
    username = alias.username or name

    print()
    print("=" * 60)
    print(f"  [{index}/{total}] 正在处理: {name}" + (f" ({username})" if alias.username else ""))
    print("=" * 60)
    print()

    # ---- 1. 导出（按 wxid 选择后端） ----
    mode = "离线全量" if alias.wxid else "在线"
    if alias.wxid:
        export = offline_exporter.export(
            contact_name=name,
            wxid=alias.wxid,
            output_dir=output_dir,
        )
    else:
        export = online_exporter.export(
            contact_name=name,
            output_dir=output_dir,
            username=username if alias.username else None,
        )
    logger.info(f"[{name}] 导出后端: {mode}")
    if not export.success:
        logger.error(f"[{name}] 导出失败: {export.errors}")
        return {"name": name, "success": False, "detail": "导出失败"}

    if export.total_messages == 0:
        logger.warning(f"[{name}] 无聊天记录（0 条消息）")
        print(
            f"  [提示] {name} 在本地数据库中没有可读取的消息记录。\n"
            f"         可能原因:\n"
            f"           - 该联系人未在本机微信聊过（或记录已删除）\n"
            f"           - 记录位于无法解密的历史分片 (message_1+ 需要对应密钥)\n"
            f"           - 微信号填写有误（需要微信内部 ID，非微信号 alias）"
        )
        return {
            "name": name,
            "success": True,
            "detail": "0 条消息 (chat.txt 已生成)",
        }

    chat_dir = str(Path(export.output_file).parent)

    # ---- 2. AI 分析（可选） ----
    if not skip_analyze:
        analysis = analyzer.analyze(
            contact_name=name,
            chat_file=export.output_file,
            output_dir=chat_dir,
        )
        if not analysis.success:
            logger.error(f"[{name}] AI 分析失败: {analysis.errors}")
            return {"name": name, "success": False, "detail": "AI 分析失败"}

    # ---- 3. 统计 ----
    stats = stats_runner.analyze(
        contact_name=name,
        chat_file=export.output_file,
        output_dir=chat_dir,
    )
    if not stats.success:
        logger.error(f"[{name}] 统计失败: {stats.errors}")
        return {"name": name, "success": False, "detail": "统计失败"}

    # ---- 4. 时间线 ----
    timeline = timeline_runner.analyze(
        contact_name=name,
        chat_file=export.output_file,
        output_dir=chat_dir,
    )
    if not timeline.success:
        logger.error(f"[{name}] 时间线失败: {timeline.errors}")
        return {"name": name, "success": False, "detail": "时间线失败"}

    detail = f"{export.total_messages} 条消息"
    if not skip_analyze and analysis.token_usage:
        detail += f", {analysis.token_usage.get('total', 0)} tokens"
    return {"name": name, "success": True, "detail": detail}


if __name__ == "__main__":
    sys.exit(main())
