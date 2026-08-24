"""系统工具。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..base import Tool, ToolContext, ToolResult

WEEKDAYS = "一二三四五六日"


class GetCurrentTimeTool(Tool):
    name = "get_current_time"
    description = (
        "获取当前日期、时间和星期。当用户问'今天几号/星期几/现在几点'，"
        "或需要按时间判断（如'今天'、'昨天'、'本周'）时使用。"
    )

    async def run(self, ctx: ToolContext) -> ToolResult:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return ToolResult.success(
            {
                "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "weekday": f"星期{WEEKDAYS[now.weekday()]}",
                "timezone": "Asia/Shanghai",
            },
            summary="已获取当前时间",
        )
