"""
Miru Assistant — 控制台推送（开发调试用）。

将日报输出到控制台，不发送到任何外部服务。
"""

from miru.notify.base import Notifier


class ConsoleNotifier(Notifier):
    """控制台输出 Notifier — 开发/调试用。"""

    def is_healthy(self) -> bool:
        return True

    def send(self, title: str, content: str) -> bool:
        """打印日报到控制台。"""
        print()
        print("=" * 60)
        print(f"  {title}")
        print("=" * 60)
        print()
        print(content)
        print()
        print("=" * 60)
        print("  [ConsoleNotifier] 以上内容仅输出到控制台，未推送")
        print("=" * 60)
        print()
        return True
