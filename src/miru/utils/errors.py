"""
Miru Assistant — 自定义异常。

所有 Miru 异常的基类为 MiruError。
按模块分类以便于错误处理和日志记录。
"""


class MiruError(Exception):
    """Miru Assistant 基础异常。"""


# --- 配置错误 ---
class ConfigError(MiruError):
    """配置文件相关错误。"""


class ConfigNotFoundError(ConfigError):
    """配置文件未找到。"""


class ConfigValidationError(ConfigError):
    """配置校验失败。"""


# --- 采集错误 ---
class CollectorError(MiruError):
    """消息采集相关错误。"""


class WeChatNotRunningError(CollectorError):
    """微信未运行。"""


class WeChatVersionError(CollectorError):
    """微信版本不兼容。"""


class DatabaseDecryptError(CollectorError):
    """数据库解密失败。"""


class KeyExtractionError(DatabaseDecryptError):
    """密钥提取失败。"""


# --- LLM 错误 ---
class LLMError(MiruError):
    """LLM API 调用错误。"""


class LLMTimeoutError(LLMError):
    """LLM API 超时。"""


class LLMResponseError(LLMError):
    """LLM 返回格式错误。"""


# --- 推送错误 ---
class NotifyError(MiruError):
    """消息推送错误。"""


class PushPlusError(NotifyError):
    """PushPlus 推送失败。"""


# --- 调度错误 ---
class SchedulerError(MiruError):
    """调度器相关错误。"""


# --- 存储错误 ---
class StorageError(MiruError):
    """数据库相关错误。"""
