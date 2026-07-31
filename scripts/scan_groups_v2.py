"""
Miru Assistant — 完整微信群资产扫描器 V2。

基于 chatlog_alpha API (准确的 is_group 标记) + SQLCipher 直接读取 message_0.db。
纯本地分析，不调用 LLM。

用法:
    python scripts/scan_groups_v2.py

输出:
    docs/wechat_real_groups_report.md
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
from urllib.request import Request, urlopen
from urllib.error import URLError

# ============================================================
# 配置
# ============================================================

# 微信数据库密钥：从环境变量 MIRU_WECHAT_DATABASE_KEY 读取，
# 或直接在本行填写（注意：勿提交含密钥的版本到公共仓库）
DATA_KEY = os.environ.get("MIRU_WECHAT_DATABASE_KEY", "")
MSG_DB = Path(r"E:\wechatfiles\xwechat_files\<wxid>\db_storage\message\message_0.db")  # 请替换 <wxid>
CHATLOG_API = "http://127.0.0.1:5030"
OUTPUT = Path(r"docs\wechat_real_groups_report.md")

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
    member_count: int = 0
    in_msg0: bool = False  # 消息表是否在 message_0.db 中


# ============================================================
# Phase 1+2: 通过 chatlog_alpha API 获取准确群列表
# ============================================================

def fetch_chatlog_yaml(url: str) -> str:
    """从 chatlog_alpha API 获取原始 YAML 响应。"""
    req = Request(url)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  ⚠ chatlog_alpha API 不可用 ({e})")
        return ""


def parse_sessions(text: str) -> list[dict]:
    """
    手工解析 chatlog_alpha 的 YAML 输出。
    格式示例:
        - chat: 示例群名
          chat_type: group
          is_group: true
          username: 111@chatroom
          time: 07-25 14:46
    """
    sessions = []
    lines = text.split("\n")
    current = None
    in_summary = False

    for line in lines:
        # 检测新条目 (以 "  - chat:" 或 "    - chat:" 开头)
        stripped = line.lstrip()
        if stripped.startswith("- chat:"):
            if current:
                sessions.append(current)
            current = {}
            in_summary = False
            val = stripped.split(":", 1)[-1].strip()
            # 去掉引号
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            current["chat"] = val
            continue

        if current is None:
            continue

        # summary 是多行字段，跳过
        if "summary:" in stripped and "|-" in stripped:
            in_summary = True
            continue

        if in_summary:
            # 检查是否回到非缩进行 (新的字段)
            if stripped and not stripped.startswith("  ") and not stripped.startswith("\t"):
                in_summary = False
            else:
                continue

        # 解析键值对
        for key in ["chat_type", "is_group", "username", "time",
                     "timestamp", "unread", "last_msg_type", "last_sender"]:
            if f"{key}:" in stripped:
                val = stripped.split(f"{key}:", 1)[-1].strip()
                if val == "true":
                    val = True
                elif val == "false":
                    val = False
                elif val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                current[key] = val
                break

    if current:
        sessions.append(current)

    return sessions


def get_groups_from_chatlog() -> list[GroupInfo]:
    """从 chatlog_alpha API 获取准确的群列表 (is_group=true)。"""
    print("  正在从 chatlog_alpha API 获取会话列表...")
    text = fetch_chatlog_yaml(f"{CHATLOG_API}/api/v1/sessions?limit=2000")
    if not text:
        print("  ⚠ 无法连接 chatlog_alpha，回退到 message_0.db Name2Id")
        return []

    sessions = parse_sessions(text)
    if not sessions:
        print("  ⚠ 解析失败，回退到 message_0.db Name2Id")
        return []

    groups = []
    for s in sessions:
        if s.get("is_group") is True:
            g = GroupInfo(
                username=s.get("username", ""),
                display_name=s.get("chat", ""),
                last_msg_ts=int(s.get("timestamp", 0)) if s.get("timestamp") else 0,
                last_msg_time=s.get("time", ""),
            )
            groups.append(g)

    print(f"  ✓ chatlog_alpha 返回 {len(groups)} 个群 (已过滤非群聊)")
    return groups


def get_groups_fallback() -> list[GroupInfo]:
    """回退方案: 从 message_0.db 的 Name2Id 获取 (仅 chatroom 且非系统账号)。"""
    from sqlcipher3 import dbapi2 as sc3

    SYSTEM_ACCOUNTS = {
        "filehelper", "medianote", "newsapp", "weixin",
        "qmessage", "qqmail", "tmessage", "brandsessionholder",
        "weibo", "fmessage", "floatbottle",
    }

    tmp = tempfile.NamedTemporaryFile(suffix="_msg0.db", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    shutil.copy2(str(MSG_DB), str(tmp_path))

    try:
        conn = sc3.connect(str(tmp_path))
        conn.execute(f"PRAGMA key = \"x'{DATA_KEY}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")

        rows = conn.execute(
            "SELECT user_name FROM Name2Id "
            "WHERE user_name LIKE '%@chatroom%'"
        ).fetchall()

        groups = []
        for r in rows:
            username = r[0] if isinstance(r, tuple) else r["user_name"]
            # 排除系统账号 (不以数字开头或包含特殊前缀)
            prefix = username.split("@")[0] if "@" in username else username
            if prefix.lower() in SYSTEM_ACCOUNTS:
                continue
            groups.append(GroupInfo(username=username, display_name=username.split("@")[0]))

        conn.close()
        return groups
    finally:
        tmp_path.unlink(missing_ok=True)


# ============================================================
# Phase 3: 消息统计
# ============================================================

def _username_to_table(username: str) -> str:
    md5 = hashlib.md5(username.encode("utf-8")).hexdigest()
    return f"Msg_{md5}"


class MsgStatCollector:
    """收集所有群的消息统计数据。"""

    def __init__(self):
        from sqlcipher3 import dbapi2 as sc3
        tmp = tempfile.NamedTemporaryFile(suffix="_msg0.db", delete=False)
        self.tmp_path = Path(tmp.name)
        tmp.close()
        shutil.copy2(str(MSG_DB), str(self.tmp_path))

        self.conn = sc3.connect(str(self.tmp_path))
        self.conn.execute(f"PRAGMA key = \"x'{DATA_KEY}'\"")
        self.conn.execute("PRAGMA cipher_compatibility = 4")

        # 缓存: 所有 Msg_ 表名
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        ).fetchall()
        self.existing_tables = {t[0] for t in tables}

    def collect(self, group: GroupInfo) -> GroupInfo:
        table = _username_to_table(group.username)

        if table not in self.existing_tables:
            return group

        group.in_msg0 = True

        # 总消息数
        total = self.conn.execute(
            f"SELECT COUNT(*) FROM [{table}]"
        ).fetchone()
        group.msg_count_total = total[0] if total else 0

        # 7 天消息
        d7 = self.conn.execute(
            f"SELECT COUNT(*) FROM [{table}] WHERE create_time >= ?",
            (DAYS_7_AGO,),
        ).fetchone()
        group.msg_count_7d = d7[0] if d7 else 0

        # 30 天消息
        d30 = self.conn.execute(
            f"SELECT COUNT(*) FROM [{table}] WHERE create_time >= ?",
            (DAYS_30_AGO,),
        ).fetchone()
        group.msg_count_30d = d30[0] if d30 else 0

        # 最后消息时间 (如果 chatlog 没有提供)
        if group.last_msg_ts == 0:
            last = self.conn.execute(
                f"SELECT create_time FROM [{table}] "
                f"ORDER BY create_time DESC LIMIT 1"
            ).fetchone()
            if last:
                group.last_msg_ts = last[0]
                group.last_msg_time = datetime.fromtimestamp(last[0]).strftime(
                    "%Y-%m-%d %H:%M"
                )

        return group

    def close(self):
        self.conn.close()
        self.tmp_path.unlink(missing_ok=True)


# ============================================================
# 成员数量获取
# ============================================================

def get_member_counts(groups: list[GroupInfo]):
    """
    尝试从 chatlog_alpha 获取群成员数量。
    通过查询每个群的 chatroom info API。
    """
    # chatlog_alpha 可能没有直接的成员数 API。
    # 尝试 /api/v1/chatroom 端点。
    # 如果不可用，保持 member_count = 0
    pass


# ============================================================
# Phase 4: 报告生成
# ============================================================

def generate_report(groups: list[GroupInfo]) -> str:
    sorted_groups = sorted(
        groups,
        key=lambda g: (-g.msg_count_30d, -g.msg_count_7d, -g.msg_count_total)
    )

    lines = []
    lines.append("# 微信群资产报告 V2")
    lines.append("")
    lines.append(f"> 生成时间: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 数据源: chatlog_alpha API (群判定) + message_0.db (消息统计)")
    lines.append(f"> 总群数: **{len(groups)}**")
    active_7 = sum(1 for g in groups if g.msg_count_7d > 0)
    active_30 = sum(1 for g in groups if g.msg_count_30d > 0)
    lines.append(f"> 7 天活跃: {active_7} | 30 天活跃: {active_30}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 主表
    lines.append("## 全部微信群 (按 30 天活跃度排序)")
    lines.append("")
    lines.append(
        "| # | 群名称 | 群 ID | 7天消息 | 30天消息 | 总消息 | "
        "最后活动 | 消息所在 |"
    )
    lines.append(
        "|---|--------|-------|---------|----------|--------|"
        "----------|----------|"
    )

    for i, g in enumerate(sorted_groups, 1):
        name = g.display_name or g.username.split("@")[0]
        shard = "msg_0" if g.in_msg0 else "其他分片"
        lines.append(
            f"| {i} | {name} | {g.username} | "
            f"{g.msg_count_7d} | {g.msg_count_30d} | "
            f"{g.msg_count_total} | {g.last_msg_time or '—'} | "
            f"{shard} |"
        )

    # 在 message_0.db 之外的群
    other_shard = [g for g in sorted_groups if not g.in_msg0]
    if other_shard:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 消息在其他分片的群")
        lines.append("")
        lines.append("以下群的消息表不在 message_0.db 中 (可能在 message_1~5.db)，")
        lines.append("消息统计为 0。需要对应的 database key 才能统计。")
        lines.append("")
        for g in other_shard:
            name = g.display_name or g.username.split("@")[0]
            lines.append(f"- {name} (`{g.username}`)")

    return "\n".join(lines)


# ============================================================
# Phase 5: 差异分析
# ============================================================

def compare_with_v1(groups_v2: list[GroupInfo]):
    """对比 V1 报告 (41 个) 和 V2 报告。"""
    v1_report = Path(r"E:\vibe coding\miru-assistant\docs\wechat_groups_report.md")
    if not v1_report.exists():
        return [], [], []

    # V2 的 username 集合
    v2_usernames = {g.username for g in groups_v2}
    v2_display = {g.username: g.display_name for g in groups_v2}

    # 从 V1 报告提取 username
    import re
    text = v1_report.read_text(encoding="utf-8")
    v1_usernames = set()
    for m in re.finditer(r'\d+@chatroom', text):
        v1_usernames.add(m.group(0))

    new_groups = v2_usernames - v1_usernames
    removed_groups = v1_usernames - v2_usernames
    common = v2_usernames & v1_usernames

    return list(new_groups), list(removed_groups), list(common)


# ============================================================
# 主流程
# ============================================================


def main():
    print("=" * 60)
    print("Miru 微信群资产扫描器 V2")
    print("=" * 60)
    print()

    # Phase 1+2: 群发现 + 过滤
    print("[Phase 1+2] 发现 & 过滤微信群...")
    print("  ⚠ 请确保 chatlog_alpha HTTP 服务已启动")
    print("    (chatlog_alpha → 启动 HTTP 服务)")
    print()

    groups = get_groups_from_chatlog()

    if not groups:
        print("  ⚠ chatlog_alpha 不可用，使用 Name2Id 回退方案")
        groups = get_groups_fallback()

    print(f"  ✓ 确认: {len(groups)} 个真实微信群")
    print()

    # Phase 3: 消息统计
    print("[Phase 3] 关联消息统计 (message_0.db)...")
    collector = MsgStatCollector()
    for i, g in enumerate(groups):
        if (i + 1) % 15 == 0:
            print(f"  进度: {i + 1}/{len(groups)}")
        groups[i] = collector.collect(g)
    collector.close()

    in_msg0 = sum(1 for g in groups if g.in_msg0)
    in_other = sum(1 for g in groups if not g.in_msg0)
    print(f"  ✓ message_0.db: {in_msg0} 个群 | 其他分片: {in_other} 个群")
    print()

    # Phase 4: 生成报告
    print("[Phase 4] 生成报告...")
    report = generate_report(groups)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"  ✓ 报告: {OUTPUT}")
    print()

    # Phase 5: 差异分析
    print("[Phase 5] 与 V1 差异分析...")
    new_g, removed_g, common = compare_with_v1(groups)
    print(f"  V1 报告: 41 个条目")
    print(f"  V2 报告: {len(groups)} 个群")
    if new_g:
        print(f"  新增: {len(new_g)} 个群")
        for u in new_g[:10]:
            name = next((g.display_name for g in groups if g.username == u), u)
            print(f"    + {name}")
    if removed_g:
        print(f"  移除: {len(removed_g)} 个 (非群聊)")
        for u in removed_g[:10]:
            print(f"    - {u}")
    print()

    # 摘要
    print("=" * 60)
    print(f"真实微信群总数: {len(groups)}")
    print(f"  message_0.db 中: {in_msg0} 个")
    print(f"  其他分片中:     {in_other} 个")
    print()
    print(f"报告: {OUTPUT}")
    print()
    print("下一步:")
    print("  1. 浏览报告，确认群列表完整性")
    print("  2. 选择要 AI 监控的群")
    print("  3. 更新 config/settings.yaml → miru.groups")


if __name__ == "__main__":
    main()
