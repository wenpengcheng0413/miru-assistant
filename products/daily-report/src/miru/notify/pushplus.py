"""
Miru Assistant — PushPlus 推送客户端。

API 文档: http://www.pushplus.plus/doc/guide/api.html

特性:
    - Markdown 模板推送
    - 自动截断超长内容
    - 重试机制 (3 次，指数退避)
    - 超时保护
"""

import time
from typing import Optional

import httpx
from loguru import logger

from miru.notify.base import Notifier

PUSHPLUS_API_URL = "http://www.pushplus.plus/send"
DEFAULT_TIMEOUT = 30       # 秒
MAX_CONTENT_LENGTH = 9000  # PushPlus 建议 10KB 以内，留余量
DEFAULT_MAX_RETRIES = 2


class PushPlusNotifier(Notifier):
    """
    PushPlus 推送渠道。

    Args:
        token: PushPlus 用户 Token。
        timeout: HTTP 超时时间。
        max_retries: 最大重试次数。
    """

    def __init__(
        self,
        token: str,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def is_healthy(self) -> bool:
        """检查 token 是否配置。"""
        return bool(self.token) and self.token != "${MIRU_PUSHPLUS_TOKEN}"

    def send(self, title: str, content: str) -> bool:
        """
        通过 PushPlus 发送 Markdown 消息到微信。

        Args:
            title: 消息标题。
            content: Markdown 格式的消息正文。

        Returns:
            True = 成功, False = 失败。
        """
        if not self.is_healthy():
            logger.error("PushPlus token 未配置")
            return False

        # 截断过长内容
        if len(content) > MAX_CONTENT_LENGTH:
            logger.warning(f"内容过长 ({len(content)} chars)，截断到 {MAX_CONTENT_LENGTH}")
            content = content[:MAX_CONTENT_LENGTH - 100] + (
                "\n\n---\n> ⚠️ 内容过长已截断"
            )

        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": "markdown",
            "channel": "wechat",
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(PUSHPLUS_API_URL, json=payload)
                data = response.json()

                code = data.get("code", -1)
                if code == 200:
                    logger.info(f"PushPlus 推送成功 — {title}")
                    return True
                else:
                    msg = data.get("msg", "未知错误")
                    logger.warning(
                        f"PushPlus 返回非 200: code={code}, msg={msg}"
                    )
                    # 400/401 不重试
                    if code in (400, 401):
                        return False
                    # 500 可重试
                    if attempt < self.max_retries:
                        delay = (attempt + 1) * 2
                        logger.info(f"{delay}s 后重试...")
                        time.sleep(delay)
                        continue

            except httpx.TimeoutException:
                logger.warning(f"PushPlus 超时 (attempt {attempt + 1})")
                if attempt < self.max_retries:
                    time.sleep((attempt + 1) * 3)
                    continue

            except Exception as e:
                logger.error(f"PushPlus 请求异常: {e}")
                if attempt < self.max_retries:
                    time.sleep((attempt + 1) * 2)
                    continue

        logger.error(f"PushPlus 推送失败 — 已重试 {self.max_retries} 次")
        return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
