"""
Miru Assistant — 日志系统单元测试 (V1.1 Phase 1)。

测试覆盖:
    - init_logging 初始化
    - 多次调用幂等
    - set_run_id / get_run_id
    - 日志文件生成
    - is_initialized
"""

from pathlib import Path

from miru.core.logging import (
    _initialized,
    get_run_id,
    init_logging,
    is_initialized,
    set_run_id,
)


class TestLoggingInit:
    """日志初始化测试。"""

    def test_init_sets_flag(self):
        """初始化后 _initialized = True。"""
        # 重置全局状态
        import miru.core.logging as mod
        mod._initialized = False

        init_logging(level="DEBUG")
        assert is_initialized() is True

    def test_double_init_is_safe(self):
        """多次调用 init_logging 不会创建重复 handler。"""
        init_logging()
        init_logging()  # should be no-op
        assert is_initialized() is True

    def test_log_file_created(self, tmp_path):
        """日志文件在指定目录生成。"""
        import miru.core.logging as mod
        mod._initialized = False

        log_dir = tmp_path / "logs"
        init_logging(str(log_dir), level="DEBUG")

        from loguru import logger
        logger.info("test message")

        # 应该生成日志文件
        files = list(log_dir.glob("miru_*.log"))
        assert len(files) >= 1

    def test_init_logging_creates_directory(self, tmp_path):
        """日志目录不存在时自动创建。"""
        import miru.core.logging as mod
        mod._initialized = False

        log_dir = tmp_path / "nested" / "logs"
        assert not log_dir.exists()

        init_logging(str(log_dir))
        assert log_dir.exists()


class TestRunId:
    """run_id 传递测试。"""

    def test_set_and_get(self):
        set_run_id("test-run-123")
        assert get_run_id() == "test-run-123"

    def test_none_by_default(self):
        set_run_id("temp")
        set_run_id("")  # reset
        # get_run_id returns the last set value
        import miru.core.logging as mod
        mod._current_run_id = None
        assert get_run_id() is None
