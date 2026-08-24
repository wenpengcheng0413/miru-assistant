"""
Miru Assistant — 退出码测试 (V1.1 Phase 4)。

测试覆盖:
    - 成功退出码
    - 永久错误分类
    - 临时错误分类
    - 环境错误分类
    - 空错误列表
"""

from miru.core.exit_codes import ExitCode, classify_pipeline_error


class TestExitCodes:
    """退出码分类测试。"""

    def test_empty_errors_is_success(self):
        assert classify_pipeline_error([]) == ExitCode.SUCCESS

    def test_config_error_is_permanent(self):
        assert classify_pipeline_error(
            ["配置文件加载失败: File not found"]
        ) == ExitCode.PERMANENT_ERROR

    def test_api_key_error_is_permanent(self):
        assert classify_pipeline_error(
            ["DeepSeek API key 未配置"]
        ) == ExitCode.PERMANENT_ERROR

    def test_wechat_not_running_is_env(self):
        assert classify_pipeline_error(
            ["微信未运行 — 请启动并登录微信 PC 客户端"]
        ) == ExitCode.ENVIRONMENT_ERROR

    def test_permission_error_is_env(self):
        assert classify_pipeline_error(
            ["需要管理员权限 — 请以管理员身份运行"]
        ) == ExitCode.ENVIRONMENT_ERROR

    def test_network_error_is_transient(self):
        assert classify_pipeline_error(
            ["Connection timeout"]
        ) == ExitCode.TRANSIENT_ERROR

    def test_api_timeout_is_transient(self):
        assert classify_pipeline_error(
            ["API 请求超时"]
        ) == ExitCode.TRANSIENT_ERROR

    def test_mixed_errors_env_first(self):
        """混合错误中环境关键词优先。"""
        assert classify_pipeline_error(
            ["网络超时", "微信未运行"]
        ) == ExitCode.ENVIRONMENT_ERROR
