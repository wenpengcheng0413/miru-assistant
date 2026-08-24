"""
Miru Assistant — 消息过滤层数据模型。

CleanMessage 是过滤层输出格式 — 供 LLM 和日报生成使用。
从 WeChatMessage 转换而来，仅保留 LLM 需要的字段。
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

# 预分类类别
CategoryType = Literal[
    "通知",      # 老师/群主正式通知
    "作业",      # 作业/任务布置
    "deadline",  # 截止日期
    "文件",      # 分享的PDF/文件/链接
    "讨论",      # 普通讨论（可能包含有价值信息）
    "其他",      # 未分类
]

# 重要度
Importance = Literal["high", "medium", "low"]


@dataclass
class CleanMessage:
    """
    清洗后的消息 — LLM 输入格式。

    从 WeChatMessage 转换而来:
        - 仅保留文本消息
        - 已过滤系统消息/空消息/表情包
        - 已去重
        - 带预分类标签
    """

    # 核心字段
    server_id: int = 0                    # 微信服务端消息ID (去重后唯一)
    group_name: str = ""                  # 所属群名
    sender_name: str = ""                 # 发送者
    content: str = ""                     # 消息文本内容
    create_time: int = 0                  # Unix 时间戳
    time_str: str = ""                    # "HH:MM"

    # 预分类 (规则引擎 — LLM 会重新分类)
    category: CategoryType = "其他"
    importance: Importance = "low"

    # 元数据
    has_deadline_keyword: bool = False    # 包含截止日期关键词
    has_file_indicator: bool = False      # 包含文件/资料线索
    is_short: bool = False                # 短消息 (<5字)


@dataclass
class FilterResult:
    """
    过滤 Pipeline 完整输出。
    """

    # 按群分组的结果
    grouped: dict[str, list[CleanMessage]] = field(default_factory=dict)

    # 统计
    total_input: int = 0                  # 输入消息总数
    total_output: int = 0                 # 输出消息总数
    removed_duplicates: int = 0           # 去重移除
    removed_system: int = 0               # 系统消息移除
    removed_empty: int = 0                # 空消息移除
    removed_non_text: int = 0             # 非文本移除
    removed_short: int = 0                # 无意义短消息移除

    # 分类统计
    category_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_removed(self) -> int:
        return (
            self.removed_duplicates
            + self.removed_system
            + self.removed_empty
            + self.removed_non_text
            + self.removed_short
        )
