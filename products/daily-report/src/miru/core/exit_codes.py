"""
Miru Assistant — 退出码定义 (V1.1 Phase 4)。

Task Scheduler 根据退出码决定是否重试。

退出码:
    0 = 成功
    1 = 永久错误 (不应重试)
    2 = 临时错误 (应重试)
    3 = 环境错误 (应重试，但需检查微信)
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Miru 进程退出码。"""

    SUCCESS = 0
    """成功完成。"""

    PERMANENT_ERROR = 1
    """
    永久错误 — 不应重试。

    例如:
        - 配置文件缺失或格式错误
        - API key 未配置
        - 虚拟环境损坏
        - 必需依赖缺失
    """

    TRANSIENT_ERROR = 2
    """
    临时错误 — 可以重试。

    例如:
        - 网络连接失败
        - DeepSeek API 超时
        - PushPlus 不可达
        - 数据库暂时锁定
    """

    ENVIRONMENT_ERROR = 3
    """
    环境错误 — 需要检查微信。

    例如:
        - 微信未运行
        - 微信版本不兼容
        - 数据目录未找到
        - 权限不足
    """


def classify_pipeline_error(errors: list[str]) -> ExitCode:
    """
    根据 Pipeline 错误信息判断退出码类型。

    Args:
        errors: PipelineContext.errors 列表。

    Returns:
        对应的 ExitCode。
    """
    if not errors:
        return ExitCode.SUCCESS

    combined = " ".join(errors).lower()

    # 环境错误
    env_keywords = ["微信", "wechat", "未运行", "权限", "管理员", "数据目录", "版本"]
    if any(kw in combined for kw in env_keywords):
        return ExitCode.ENVIRONMENT_ERROR

    # 永久错误
    permanent_keywords = ["配置", "config", "api key", "未配置", "缺失"]
    if any(kw in combined for kw in permanent_keywords):
        return ExitCode.PERMANENT_ERROR

    # 默认为临时错误（网络/API 超时等）
    return ExitCode.TRANSIENT_ERROR
