"""
Miru Assistant — 消息预分类器。

基于关键词规则引擎进行预分类。
这只是初步分类 — LLM（Task 7）会做最终分类和优先级判断。

分类规则:
    通知   — 老师/助教/群主/管理员发言 + 正式语气关键词
    deadline — 日期/截止/期限 相关
    作业   — 习题/作业/实验报告/论文 相关
    文件   — PDF/文件/链接/资料 相关
    讨论   — 技术讨论/推荐/问题回答
"""

import re
from datetime import datetime

from miru.collector.wechat_reader import WeChatMessage
from miru.filter.models import CategoryType, CleanMessage, Importance


# ============================================================
# 关键词表
# ============================================================

_DEADLINE_KEYWORDS = [
    r"(?:截止|ddl|deadline|到期|最后期限)",
    r"(?:下?周[一二三四五六日天]|明天|后天|今天).{0,10}(?:前|交|截止)",
    r"(?:\d+月\d+[日号]|\d+[\.\-]\d+).{0,8}(?:前|交|截止|ddl)",
    r"(?:这周|本周|下周).{0,5}(?:交|截止)",
]

_NOTICE_KEYWORDS = [
    r"(?:通知|公告|提醒|注意|请.{0,5}注意|重要)",
    r"(?:调[课课]|考试|补[课课]|放假|班会|开会)",
    r"(?:时间|地点|安排|更改|变动|取消)",
]

_HOMEWORK_KEYWORDS = [
    r"(?:作业|习题|练习|实验报告|小论文|大作业|pre)",
    r"(?:第[一二三四五六七八九十\d]+章|第[一二三四五六七八九十\d]+节)",
    r"(?:提交|上交|发到|交到|发送到)",
    r"(?:课后题|思考题|复习题)",
]

_FILE_KEYWORDS = [
    r"(?:pdf|PDF|文件|资料|课件|PPT|ppt|下载|附件)",
    r"(?:链接|网盘|百度云|蓝奏|阿里云盘)",
    r"(?:分享|上传|发了)",
]

# 编译正则
_DEADLINE_RE = re.compile("|".join(_DEADLINE_KEYWORDS))
_NOTICE_RE = re.compile("|".join(_NOTICE_KEYWORDS))
_HOMEWORK_RE = re.compile("|".join(_HOMEWORK_KEYWORDS))
_FILE_RE = re.compile("|".join(_FILE_KEYWORDS))

# 权威发送者关键词（班主任/老师/助教/管理员）
_AUTHORITY_SENDERS = [
    r"(?:老师|教授|助教|班主任|辅导员|导师)",
    r"(?:admin|管理员|群主)",
]


def classify_message(
    msg: WeChatMessage,
    group_name: str = "",
) -> CleanMessage:
    """
    对单条消息进行预分类。

    Args:
        msg: WeChatMessage 输入。
        group_name: 群显示名称。

    Returns:
        带预分类标签的 CleanMessage。
    """
    content = msg.content.strip()
    cm = CleanMessage(
        server_id=msg.server_id,
        group_name=group_name or msg.group_name,
        sender_name=msg.sender_name,
        content=content,
        create_time=msg.create_time,
        time_str=msg.time_str,
    )

    # 短消息标记
    if len(content) <= 4:
        cm.is_short = True

    # 关键词匹配
    has_deadline = bool(_DEADLINE_RE.search(content))
    has_notice = bool(_NOTICE_RE.search(content))
    has_homework = bool(_HOMEWORK_RE.search(content))
    has_file = bool(_FILE_RE.search(content))

    cm.has_deadline_keyword = has_deadline
    cm.has_file_indicator = has_file

    # 发送者权威性
    sender = msg.sender_name
    is_authority = any(
        re.search(kw, sender) for kw in _AUTHORITY_SENDERS
    ) if sender else False

    # 分类逻辑（按优先级）
    if has_deadline:
        # deadline 通常伴随作业或通知
        if has_homework:
            cm.category = "作业"
        elif has_notice:
            cm.category = "通知"
        else:
            cm.category = "deadline"
        cm.importance = "high"
    elif has_homework:
        cm.category = "作业"
        cm.importance = "high"
    elif has_notice and is_authority:
        cm.category = "通知"
        cm.importance = "high"
    elif has_notice:
        cm.category = "通知"
        cm.importance = "medium"
    elif has_file:
        cm.category = "文件"
        cm.importance = "medium"
    elif is_authority and len(content) > 20:
        # 权威发送者发送的长消息 → 可能是通知
        cm.category = "通知"
        cm.importance = "medium"
    else:
        cm.category = "讨论"
        cm.importance = "low"

    return cm


def classify_all(
    messages: list[WeChatMessage],
    group_name: str = "",
) -> list[CleanMessage]:
    """批量预分类。"""
    return [classify_message(m, group_name) for m in messages]
