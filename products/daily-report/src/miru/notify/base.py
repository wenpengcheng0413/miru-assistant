"""
Miru Assistant — 消息推送抽象基类。

所有推送渠道必须实现此接口。
"""

from abc import ABC, abstractmethod


class Notifier(ABC):
    """推送渠道抽象基类。"""

    @abstractmethod
    def send(self, title: str, content: str) -> bool:
        """
        发送消息。

        Args:
            title: 消息标题。
            content: 消息正文 (Markdown)。

        Returns:
            True = 发送成功, False = 发送失败。
        """
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """检查推送渠道是否可用。"""
        ...
