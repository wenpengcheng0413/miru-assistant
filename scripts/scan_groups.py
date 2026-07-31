"""
Miru Assistant — 微信群资产扫描脚本。

从微信数据库读取全部群聊信息，分析活跃度，生成 Markdown 报告。
纯本地分析，不调用任何 LLM / 外部 API。

用法:
    python scripts/scan_groups.py

输出:
    docs/wechat_groups_report.md
"""

import hashlib
import os
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 微信数据库密钥：从环境变量 MIRU_WECHAT_DATABASE_KEY 读取，
# 或直接在本行填写（注意：勿提交含密钥的版本到公共仓库）
DATA_KEY = os.environ.get("MIRU_WECHAT_DATABASE_KEY", "")
DATA_DIR = Path(r"E:\wechatfiles\xwechat_files\<wxid>\db_storage")  # 请替换 <wxid> 为你的微信 ID
MSG_DB = DATA_DIR / "message" / "message_0.db"
OUTPUT = Path(r"docs\wechat_groups_report.md")

NOW = datetime.now()
NOW_TS = int(NOW.timestamp())
DAYS_7_AGO = int((NOW - timedelta(days=7)).timestamp())
DAYS_30_AGO = int((NOW - timedelta(days=30)).timestamp())

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
    last_msg_time: str = ""
    last_msg_ts: int = 0
    last_msg_preview: str = ""
    member_count: int = 0
    recommendation: str = ""
    priority: str = "low"  # high / medium / low


# ============================================================
# 数据库连接
# ============================================================


def open_message_db():
    """复制加密数据库并用 sqlcipher3 打开。"""
    from sqlcipher3 import dbapi2 as sc3

    tmp = tempfile.NamedTemporaryFile(suffix="_msg0.db", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    shutil.copy2(str(MSG_DB), str(tmp_path))

    conn = sc3.connect(str(tmp_path))
    conn.execute(f"PRAGMA key = \"x'{DATA_KEY}'\"")
    conn.execute("PRAGMA cipher_compatibility = 4")
    return conn, tmp_path


# ============================================================
# 群列表获取
# ============================================================


def get_all_groups(conn) -> list[GroupInfo]:
    """
    从 message_0.db 的 Name2Id 表获取全部群聊。
    返回 GroupInfo 列表（仅含 username，后续填充其他字段）。
    """
    groups: list[GroupInfo] = {}

    rows = conn.execute(
        "SELECT user_name FROM Name2Id "
        "WHERE user_name LIKE '%@chatroom%'"
    ).fetchall()

    for r in rows:
        username = r[0] if isinstance(r, tuple) else r["user_name"]
        groups[username] = GroupInfo(username=username)

    return list(groups.values())


# ============================================================
# 消息统计
# ============================================================


def _username_to_table(username: str) -> str:
    """计算群聊对应的 Msg 表名: Msg_<MD5(username)>"""
    md5 = hashlib.md5(username.encode("utf-8")).hexdigest()
    return f"Msg_{md5}"


def _get_display_name(conn, username: str) -> str:
    """尝试从 chatlog_alpha API 获取显示名。"""
    try:
        import urllib.request, json
        url = "http://127.0.0.1:5030/api/v1/sessions?limit=500"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

    # 用简单的文本解析从 YAML 输出中提取 chat 名
    lines = text.split("\n")
    current_username = ""
    for line in lines:
        line = line.rstrip()
        if "username:" in line and "@chatroom" in line:
            current_username = line.split("username:")[-1].strip()
        if "chat:" in line and current_username == username:
            name = line.split("chat:")[-1].strip()
            # 去掉可能的前导空格/破折号
            if name.startswith("- "):
                name = name[2:]
            return name
    return ""


def analyze_group(conn, g: GroupInfo) -> GroupInfo:
    """统计单个群的消息数据。"""
    table_name = _username_to_table(g.username)

    # 检查表是否存在
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    if not exists:
        return g

    # 总消息数
    total = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()
    g.msg_count_total = total[0] if total else 0

    # 最近 7 天消息数
    d7 = conn.execute(
        f"SELECT COUNT(*) FROM [{table_name}] WHERE create_time >= ?",
        (DAYS_7_AGO,),
    ).fetchone()
    g.msg_count_7d = d7[0] if d7 else 0

    # 最近 30 天消息数
    d30 = conn.execute(
        f"SELECT COUNT(*) FROM [{table_name}] WHERE create_time >= ?",
        (DAYS_30_AGO,),
    ).fetchone()
    g.msg_count_30d = d30[0] if d30 else 0

    # 最后一条消息
    last = conn.execute(
        f"SELECT create_time, message_content FROM [{table_name}] "
        f"ORDER BY create_time DESC LIMIT 1"
    ).fetchone()
    if last:
        g.last_msg_ts = last[0]
        g.last_msg_time = datetime.fromtimestamp(last[0]).strftime(
            "%Y-%m-%d %H:%M"
        )
        # 消息内容预览（截取前 80 字符）
        content = last[1] or b""
        if isinstance(content, bytes):
            # 尝试 ZSTD 解压或直接显示
            if content[:4] == b"\x28\xb5\x2f\xfd":
                try:
                    import zstandard
                    dctx = zstandard.ZstdDecompressor()
                    content = dctx.decompress(content, max_output_size=102400)
                except Exception:
                    pass
            content = content.decode("utf-8", errors="replace")
        g.last_msg_preview = str(content)[:80].replace("\n", " ")

    return g


# ============================================================
# 建议规则（纯规则引擎，不调用 LLM）
# ============================================================

HIGH_VALUE_KEYWORDS = [
    "班级", "学校", "课程", "项目", "实验室",
    "AI", "技术", "工作", "家庭", "自己",
    "宿舍", "学院", "大学", "老师", "学习",
    "班群", "通知", "作业", "小组",
]

LOW_VALUE_KEYWORDS = [
    "广告", "福利", "外卖", "红包", "优惠",
    "拼单", "二手", "薅", "秒杀",
]


def recommend(g: GroupInfo) -> tuple[str, str]:
    """
    根据规则给群打分。
    返回 (priority, recommendation)
    """
    name = g.display_name or g.username

    # 高活跃且名称包含高价值关键词 → 高优先级
    high_kw = [kw for kw in HIGH_VALUE_KEYWORDS if kw in name]
    low_kw = [kw for kw in LOW_VALUE_KEYWORDS if kw in name]

    # 30 天无消息 → 低
    if g.msg_count_30d == 0:
        return "low", "🛑 30 天无消息，建议忽略或退群"

    # 低价值关键词 → 低
    if low_kw and g.msg_count_7d > 50:
        return "low", f"📢 疑似营销/广告群 (关键词: {', '.join(low_kw)})，不建议监控"

    # 高价值关键词且活跃 → 高
    if high_kw and g.msg_count_7d > 0:
        return "high", f"⭐ 高价值群 (关键词: {', '.join(high_kw)})，推荐监控"

    # 7 天消息 < 5 但最近有活动 → 中
    if g.msg_count_7d < 5 and g.msg_count_30d > 0:
        return "medium", "📌 低频使用，可按需监控"

    # 7 天消息 > 20 → 中（需要人工判断）
    if g.msg_count_7d > 20:
        return "medium", f"💬 较活跃 ({g.msg_count_7d}条/7天)，建议人工判断是否监控"

    # 有高价值关键词但不活跃
    if high_kw:
        return "medium", f"🔔 含关键词 ({', '.join(high_kw)}) 但近期不活跃"

    # 默认低
    return "low", "📭 低活跃度群"


# ============================================================
# 报告生成
# ============================================================


def generate_report(groups: list[GroupInfo]) -> str:
    """生成 Markdown 报告。"""
    lines = []
    lines.append("# 微信群监控筛选报告")
    lines.append("")
    lines.append(f"> 生成时间: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 数据库: message_0.db (MB)")
    lines.append(f"> 总群数: {len(groups)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 统计概览
    high = sum(1 for g in groups if g.priority == "high")
    medium = sum(1 for g in groups if g.priority == "medium")
    low = sum(1 for g in groups if g.priority == "low")
    active_7d = sum(1 for g in groups if g.msg_count_7d > 0)
    lines.append("## 概览")
    lines.append("")
    lines.append(f"| 类别 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| ⭐ 高价值 (推荐监控) | {high} |")
    lines.append(f"| 📌 中等 (可考虑) | {medium} |")
    lines.append(f"| 📭 低价值 (不建议) | {low} |")
    lines.append(f"| 有 7 天活动的群 | {active_7d} |")
    lines.append("")

    # 高价值群
    if high:
        lines.append("---")
        lines.append("")
        lines.append("## ⭐ 高价值群 (推荐加入 miru.groups)")
        lines.append("")
        lines.append(
            "| # | 群名称 | 群 ID | 7天消息 | 30天消息 | 总消息 | "
            "最后活动 | 建议 |"
        )
        lines.append(
            "|---|--------|-------|---------|----------|--------|"
            "----------|------|"
        )
        for i, g in enumerate(
            sorted([g for g in groups if g.priority == "high"],
                   key=lambda g: -g.msg_count_7d), 1
        ):
            name = g.display_name or g.username.split("@")[0]
            lines.append(
                f"| {i} | {name} | {g.username} | "
                f"{g.msg_count_7d} | {g.msg_count_30d} | "
                f"{g.msg_count_total} | {g.last_msg_time} | "
                f"{g.recommendation} |"
            )

    # 全部群（按活跃度排序）
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 全部群聊 (按 7 天活跃度排序)")
    lines.append("")
    lines.append(
        "| # | 群名称 | 群 ID | 7天消息 | 30天消息 | 总消息 | "
        "最后活动 | 优先级 | 建议 |"
    )
    lines.append(
        "|---|--------|-------|---------|----------|--------|"
        "----------|--------|------|"
    )

    priority_emoji = {"high": "⭐高", "medium": "📌中", "low": "📭低"}
    for i, g in enumerate(
        sorted(groups, key=lambda g: (-g.msg_count_7d, -g.msg_count_30d)), 1
    ):
        name = g.display_name or g.username.split("@")[0]
        lines.append(
            f"| {i} | {name} | {g.username} | "
            f"{g.msg_count_7d} | {g.msg_count_30d} | "
            f"{g.msg_count_total} | {g.last_msg_time} | "
            f"{priority_emoji.get(g.priority, '?')} | "
            f"{g.recommendation} |"
        )

    # 推荐 miru.groups 配置
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 推荐 miru.groups 配置")
    lines.append("")
    lines.append("将以下内容复制到 `config/settings.yaml` 的 `miru.groups` 字段：")
    lines.append("")
    lines.append("```yaml")
    lines.append("miru:")
    lines.append("  groups:")
    for g in sorted(groups, key=lambda g: -g.msg_count_7d):
        if g.priority == "high":
            name = g.display_name or g.username.split("@")[0]
            lines.append(f'    - "{name}"  # {g.msg_count_7d}条/7天')
    lines.append("```")
    lines.append("")
    lines.append("> 💡 你也可以从中等优先级中手动挑选加入。")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================


def main():
    print("=" * 60)
    print("Miru 微信群资产扫描")
    print("=" * 60)
    print()

    # 1. 打开数据库
    print("[1/4] 连接微信数据库...")
    conn, tmp_path = open_message_db()
    print(f"  ✓ 已连接 (临时文件: {tmp_path})")

    try:
        # 2. 获取群列表
        print("[2/4] 扫描微信群...")
        groups = get_all_groups(conn)
        print(f"  ✓ 找到 {len(groups)} 个群")

        # 3. 分析每个群 & 获取显示名
        print("[3/4] 分析群活跃度...")
        for i, g in enumerate(groups):
            if (i + 1) % 10 == 0:
                print(f"  进度: {i + 1}/{len(groups)}")
            g = analyze_group(conn, g)
            g.display_name = _get_display_name(conn, g.username)
            g.priority, g.recommendation = recommend(g)

        # 4. 生成报告
        print("[4/4] 生成报告...")
        report = generate_report(groups)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(report, encoding="utf-8")
        print(f"  ✓ 报告已生成: {OUTPUT}")
        print()

        # 打印摘要
        high = sum(1 for g in groups if g.priority == "high")
        medium = sum(1 for g in groups if g.priority == "medium")
        low = sum(1 for g in groups if g.priority == "low")
        print(f"群总数: {len(groups)}")
        print(f"  ⭐ 高价值 (推荐监控): {high}")
        print(f"  📌 中等 (可考虑):    {medium}")
        print(f"  📭 低价值 (不建议):  {low}")
        print()
        print(f"详细报告: {OUTPUT}")
        print()
        print("下一步:")
        print("  1. 打开报告，浏览群列表")
        print("  2. 选择要监控的群")
        print("  3. 更新 config/settings.yaml 的 miru.groups")
        print("  4. 运行 miru run --dry-run 验证")

    finally:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        print()
        print("临时文件已清理。")


if __name__ == "__main__":
    main()
