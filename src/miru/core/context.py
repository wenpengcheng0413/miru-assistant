"""
Miru Assistant — Pipeline 运行上下文。

保存一次完整运行的元数据和中间结果。
方便日志记录、调试和未来 V2 扩展。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PipelineContext:
    """一次 Pipeline 运行的完整上下文。"""

    # 元数据
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    start_time: str = ""
    end_time: str = ""
    dry_run: bool = False
    replay_mode: bool = False  # True = 回放模式: 跳过 DB 写入, 使用指定日期

    # 微信状态
    wechat_pid: int = 0
    wechat_version: str = ""
    wechat_data_dir: str = ""

    # 各阶段统计
    raw_messages_count: int = 0
    filtered_messages_count: int = 0
    groups_collected: int = 0
    groups_summarized: int = 0
    groups_failed: int = 0

    # 中间结果
    llm_token_usage: dict = field(default_factory=dict)  # {prompt, completion, total}

    # 输出
    report_md: str = ""
    report_date: str = ""
    push_status: str = ""  # pending / sent / failed / skipped

    # 错误
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def is_success(self) -> bool:
        return len(self.errors) == 0
