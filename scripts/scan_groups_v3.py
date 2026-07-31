"""
Miru Assistant — 微信群资产扫描器 V3。

纯 chatlog_alpha HTTP API 驱动。不直接读取数据库，不处理 SQLCipher key。
支持跨 message_0~5.db 分片的完整消息统计。

用法:
    1. 启动 chatlog_alpha → 选择「启动 HTTP 服务」
    2. python scripts\scan_groups_v3.py

输出:
    docs\wechat_real_groups_report.md
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ============================================================
# 配置
# ============================================================

CHATLOG = "http://127.0.0.1:5030"
OUTPUT = Path(r"E:\vibe coding\miru-assistant\docs\wechat_real_groups_report.md")
NOW = datetime.now()
MAX_WORKERS = 8  # 并发 API 请求数

# 时间范围参数
THIS_MONTH = NOW.strftime("%Y-%m")
THIS_YEAR = NOW.strftime("%Y")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
TODAY = NOW.strftime("%Y-%m-%d")
# stats API 最多支持 2 个逗号分隔的日期
RECENT_2DAYS = f"{YESTERDAY},{TODAY}"


# ============================================================
# 数据模型
# ============================================================

@dataclass
class GroupInfo:
    username: str = ""
    display_name: str = ""
    msg_count_7d: int = 0
    msg_count_30d: int = 0
    msg_count_total: int = 0
    last_time: str = ""
    last_ts: int = 0
    last_summary: str = ""
    error: str = ""


# ============================================================
# API 调用
# ============================================================

def api_get(path: str) -> dict:
    """调用 chatlog_alpha HTTP API，返回 JSON 或 YAML 解析结果。"""
    url = f"{CHATLOG}{path}"
    req = Request(url)
    try:
        with urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        return {"_error": str(e)}
    except Exception as e:
        return {"_error": str(e)}

    # 尝试 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 回退: 解析 YAML
    return _parse_stats_yaml(text)


def _parse_stats_yaml(text: str) -> dict:
    """手工解析 /api/v1/stats 的 YAML 输出。"""
    result = {}
    for line in text.split("\n"):
        line = line.rstrip()
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.isdigit():
                val = int(val)
            elif val in ("true", "false"):
                val = val == "true"
            result[key] = val
    return result


def get_all_groups() -> list[GroupInfo]:
    """从 /api/v1/sessions 获取全部微信群 (is_group=true)。"""
    data = api_get("/api/v1/sessions?limit=2000&format=json")

    if "_error" in data:
        print(f"  ⚠ API 错误: {data['_error']}")
        return []

    sessions = data.get("sessions", [])
    if not sessions and isinstance(data, dict):
        # 可能返回了非 JSON 格式
        print("  ⚠ 无法解析 sessions，请确认 chatlog_alpha HTTP 服务已启动")
        return []

    groups = []
    for s in sessions:
        if not s.get("is_group"):
            continue
        g = GroupInfo(
            username=s.get("username", ""),
            display_name=s.get("chat", ""),
            last_time=s.get("time", ""),
            last_ts=int(s.get("timestamp", 0)) if s.get("timestamp") else 0,
            last_summary=s.get("summary", ""),
        )
        groups.append(g)

    return groups


def fetch_stats(username: str) -> dict:
    """获取单个群的统计数据: 月消息 + 年消息 + 近2天消息。"""
    month = api_get(f"/api/v1/stats?chat={username}&time={THIS_MONTH}")
    year = api_get(f"/api/v1/stats?chat={username}&time={THIS_YEAR}")
    recent = api_get(f"/api/v1/stats?chat={username}&time={RECENT_2DAYS}")

    return {
        "month": month.get("total", 0) if "_error" not in month else -1,
        "year": year.get("total", 0) if "_error" not in year else -1,
        "recent": recent.get("total", 0) if "_error" not in recent else -1,
        "_error": (month.get("_error", "") or year.get("_error", "") or recent.get("_error", "")),
    }


def collect_stats(groups: list[GroupInfo]) -> list[GroupInfo]:
    """并发获取所有群的统计数据。"""
    results = []

    def _fetch_one(g: GroupInfo) -> GroupInfo:
        stats = fetch_stats(g.username)
        g.msg_count_7d = max(0, stats.get("recent", 0))
        g.msg_count_30d = max(0, stats.get("month", 0))
        g.msg_count_total = max(0, stats.get("year", 0))
        if stats.get("_error"):
            g.error = stats["_error"]
        return g

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, g): g for g in groups}
        for i, future in enumerate(as_completed(futures)):
            g = future.result()
            results.append(g)
            if (i + 1) % 10 == 0 or i == len(groups) - 1:
                print(f"  进度: {i + 1}/{len(groups)}")

    # 恢复原始顺序
    username_order = {g.username: i for i, g in enumerate(groups)}
    results.sort(key=lambda g: username_order.get(g.username, 999))
    return results


# ============================================================
# 报告生成
# ============================================================

def generate_report(groups: list[GroupInfo]) -> str:
    sorted_groups = sorted(
        groups, key=lambda g: (-g.msg_count_30d, -g.msg_count_7d, -g.msg_count_total)
    )

    lines = []
    lines.append("# 微信群资产报告 V3")
    lines.append("")
    lines.append(f"> 生成时间: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 数据源: chatlog_alpha HTTP API (跨 message_0~5.db 分片)")
    lines.append(f"> 总群数: **{len(groups)}**")
    active_7 = sum(1 for g in groups if g.msg_count_7d > 0)
    active_30 = sum(1 for g in groups if g.msg_count_30d > 0)
    lines.append(f"> 本月活跃群: {active_30} | 本年活跃群: {active_7}")
    lines.append("")

    # 活跃度分布 (基于本月消息数)
    very_high = sum(1 for g in groups if g.msg_count_30d >= 500)
    high = sum(1 for g in groups if 100 <= g.msg_count_30d < 500)
    medium = sum(1 for g in groups if 10 <= g.msg_count_30d < 100)
    low = sum(1 for g in groups if 1 <= g.msg_count_30d < 10)
    silent = sum(1 for g in groups if g.msg_count_30d == 0)
    lines.append(f"> 活跃分布: 🔥高(≥500/月): {very_high} | 📊中(100-499): {high} | 📌低(10-99): {medium} | 💤微(1-9): {low} | 🛑静(0): {silent}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 主表
    lines.append("## 全部微信群 (按本月消息数排序)")
    lines.append("")
    lines.append(
        "| # | 群名称 | 群ID | 近2天 | 本月 | 本年 | "
        "最后活动 |"
    )
    lines.append(
        "|---|--------|-------|--------|------|------|"
        "----------|"
    )

    for i, g in enumerate(sorted_groups, 1):
        name = g.display_name or g.username.split("@")[0]
        lines.append(
            f"| {i} | {name} | {g.username} | "
            f"{g.msg_count_7d} | {g.msg_count_30d} | "
            f"{g.msg_count_total} | {g.last_time} |"
        )

    # 静默群 (本月无消息)
    silent_groups = [g for g in sorted_groups if g.msg_count_30d == 0]
    if silent_groups:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## 🛑 7 天无消息的群 ({len(silent_groups)} 个)")
        lines.append("")
        for g in silent_groups:
            name = g.display_name or g.username.split("@")[0]
            lines.append(f"- {name} (`{g.username}`) — 最后活动: {g.last_time or '未知'}")

    # 错误群
    error_groups = [g for g in sorted_groups if g.error]
    if error_groups:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## ⚠️ API 查询有误的群 ({len(error_groups)} 个)")
        lines.append("")
        for g in error_groups:
            name = g.display_name or g.username.split("@")[0]
            lines.append(f"- {name}: {g.error}")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("Miru 微信群资产扫描器 V3 (纯 chatlog_alpha API)")
    print("=" * 60)
    print()

    # 1. 获取群列表
    print("[1/3] 从 chatlog_alpha 获取群列表...")
    groups = get_all_groups()

    if not groups:
        print("  ✗ 无法获取群列表。请确保:")
        print("    1. chatlog_alpha 已启动 HTTP 服务")
        print("    2. 微信 4.1.5.30 正在运行")
        sys.exit(1)

    print(f"  ✓ 找到 {len(groups)} 个微信群 (is_group=true)")
    print()

    # 2. 获取统计数据
    print(f"[2/3] 并发获取消息统计 ({MAX_WORKERS} 线程)...")
    groups = collect_stats(groups)
    print("  ✓ 统计完成")
    print()

    # 3. 生成报告
    print("[3/3] 生成报告...")
    report = generate_report(groups)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"  ✓ 报告: {OUTPUT}")
    print()

    # 摘要
    active_7 = sum(1 for g in groups if g.msg_count_7d > 0)
    print("=" * 60)
    print(f"微信群总数: {len(groups)}")
    print(f"7 天活跃:   {active_7}")
    print(f"报告位置:   {OUTPUT}")
    print()
    print("使用的 API:")
    print("  GET /api/v1/sessions?limit=2000&format=json  (群列表)")
    print("  GET /api/v1/stats?chat=<id>&time=<range>     (每群消息统计)")
    print()


if __name__ == "__main__":
    main()
