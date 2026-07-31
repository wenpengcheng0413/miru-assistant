"""
Miru Assistant — Pipeline 编排器 (Task 10)。

将 Task 5-9 的所有模块串联为一个完整的可执行流程。

用法:
    pipeline = MiruPipeline(config_path="config/settings.yaml")
    ctx = pipeline.run(dry_run=False)     # 正式模式
    ctx = pipeline.run(dry_run=True)      # Dry-run (不推送)
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from miru.core.context import PipelineContext
from miru.utils.config import AppConfig, load_config


def _get_chatlog_display_names() -> dict[str, str]:
    """从 chatlog_alpha HTTP API 获取 username → display_name 映射。"""
    try:
        import json
        from urllib.request import Request, urlopen
        url = "http://127.0.0.1:5030/api/v1/sessions?limit=2000&format=json"
        req = Request(url)
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return {
            s["username"]: s.get("chat", "")
            for s in data.get("sessions", [])
            if s.get("username")
        }
    except Exception:
        return {}


class MiruPipeline:
    """
    Miru Assistant V1 完整 Pipeline。

    6 个阶段:
        1. 环境检查
        2. 消息采集 (解密 + 读取)
        3. 消息过滤 (去重 + 清洗 + 分类)
        4. LLM 分析 (DeepSeek)
        5. 日报生成 (Markdown + DB 保存)
        6. 推送通知 (PushPlus)

    容错原则:
        - 阶段 1 失败 → 终止
        - 阶段 2-3 失败 → 终止 (没有消息就无法继续)
        - 阶段 4 部分失败 → 继续 (部分群失败不影响)
        - 阶段 5 失败 → 记录但不阻断
        - 阶段 6 失败 → 记录但不阻断 (日报已保存)
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.cfg: Optional[AppConfig] = None

    # ================================================================
    # 主入口
    # ================================================================

    def run(
        self, dry_run: bool = False, replay_date: str | None = None
    ) -> PipelineContext:
        """
        执行完整 Pipeline。

        Args:
            dry_run: True = 不推送，仅 console 输出。
            replay_date: 指定回放日期 (YYYY-MM-DD)。启用回放模式:
                - 读取指定日期的历史消息
                - 跳过所有数据库写入
                - 默认 dry-run 推送 (除非 dry_run=False)

        Returns:
            PipelineContext — 完整运行上下文。
        """
        ctx = PipelineContext(dry_run=dry_run)

        # ---- 回放模式 ----
        if replay_date is not None:
            ctx.replay_mode = True
            ctx.date = replay_date
            mode_label = f"REPLAY date={replay_date}"
        else:
            mode_label = ctx.date

        ctx.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 设置全局 run_id
        from miru.core.logging import set_run_id
        set_run_id(ctx.run_id)

        logger.info("=" * 60)
        logger.info(
            f"Miru Pipeline 启动 — run_id={ctx.run_id} date={mode_label}"
            + (" DRY-RUN" if dry_run else "")
        )
        logger.info("=" * 60)

        # 加载配置
        try:
            self.cfg = load_config(self.config_path)
        except Exception as e:
            ctx.errors.append(f"配置加载失败: {e}")
            logger.error(ctx.errors[-1])
            return ctx

        # ---- Step 1: 环境检查 ----
        self._step_header(ctx, 1, "Checking WeChat environment")
        if not self._check_environment(ctx):
            self._step_header(ctx, None, "Pipeline aborted — environment not ready")
            return ctx

        # ---- Step 2: 消息采集 ----
        self._step_header(ctx, 2, "Collecting messages")
        raw_messages, group_list = self._collect_messages(ctx)
        if raw_messages is None:
            self._step_header(ctx, None, "Pipeline aborted — message collection failed")
            return ctx

        ctx.raw_messages_count = len(raw_messages)
        ctx.groups_collected = len(group_list)
        if not raw_messages:
            logger.warning("未采集到任何消息")
            ctx.warnings.append("今日无新消息")
            # 仍然可以生成空日报
            self._step_header(ctx, 5, "Generating empty report")
            self._generate_empty_report(ctx)
            if not dry_run:
                self._notify(ctx)
            return ctx

        # ---- Step 3: 消息过滤 ----
        self._step_header(ctx, 3, "Filtering messages")
        filter_result = self._filter_messages(ctx, raw_messages)
        ctx.filtered_messages_count = filter_result.total_output

        if filter_result.total_output == 0:
            logger.warning("过滤后无有效消息")
            ctx.warnings.append("今日消息均为闲聊/系统消息")
            self._step_header(ctx, 5, "Generating empty report")
            self._generate_empty_report(ctx)
            if not dry_run:
                self._notify(ctx)
            return ctx

        # ---- Step 4: LLM 分析 ----
        self._step_header(ctx, 4, "DeepSeek analysis")
        llm_results = self._analyze_messages(ctx, filter_result)

        # ---- Step 5: 日报生成 ----
        self._step_header(ctx, 5, "Generating report")
        report = self._generate_report(ctx, llm_results)
        ctx.report_md = report.content_md if report else ""
        ctx.report_date = report.report_date if report else ctx.date

        # ---- Step 6: 推送 ----
        if dry_run:
            self._step_header(ctx, 6, "Notification SKIPPED (dry-run)")
            ctx.push_status = "skipped"
            self._print_report_to_console(ctx)
        else:
            self._step_header(ctx, 6, "PushPlus notification")
            self._notify(ctx)

        # ---- 完成 ----
        ctx.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not ctx.replay_mode:
            self._write_run_log(ctx, "success" if ctx.is_success else "failed")

        # 成功后自动备份数据库 (回放模式跳过)
        if ctx.is_success and not ctx.replay_mode:
            self._backup_database()
        logger.info("=" * 60)
        status = "SUCCESS" if ctx.is_success else f"COMPLETED with {len(ctx.errors)} errors"
        logger.info(f"Miru Pipeline 完成 — {status}")
        logger.info("=" * 60)

        # 失败通知
        if ctx.has_errors and not dry_run:
            self._send_failure_notification(ctx)

        return ctx

    # ================================================================
    # Step 1: 环境检查
    # ================================================================

    def _check_environment(self, ctx: PipelineContext) -> bool:
        """检查微信环境和权限。失败返回 False。"""
        from miru.collector.diagnostics import (
            detect_wechat_process,
            find_wechat_data_dir,
        )

        # 微信进程
        proc = detect_wechat_process()
        if not proc.found:
            ctx.errors.append("微信未运行 — 请启动并登录微信 PC 客户端")
            return False

        ctx.wechat_pid = proc.pid
        ctx.wechat_version = proc.version_raw
        logger.info(f"  微信: PID={proc.pid}, v{proc.version_raw}")

        # 数据目录
        manual_dir = self.cfg.miru.wechat.data_dir if self.cfg else ""
        data_dir = find_wechat_data_dir(manual_dir)
        if not data_dir.found:
            ctx.errors.append("未找到微信数据目录")
            return False

        ctx.wechat_data_dir = data_dir.path
        logger.info(f"  数据目录: {data_dir.path}")

        # 权限
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        if not is_admin:
            ctx.errors.append("需要管理员权限 — 请以管理员身份运行")
            return False

        logger.info("  环境检查通过")
        return True

    # ================================================================
    # Step 2: 消息采集
    # ================================================================

    def _collect_messages(self, ctx: PipelineContext):
        """解密并读取微信消息。失败返回 (None, [])。"""
        from miru.collector.wechat_db_decrypt import (
            extract_keys_from_process,
            try_decrypt_wechat_db,
        )
        from miru.collector.wechat_reader import WeChatDBReader

        version_major = 4
        try:
            version_major = int(ctx.wechat_version.split(".")[0]) if ctx.wechat_version else 4
        except Exception:
            pass

        data_path = Path(ctx.wechat_data_dir)

        # 微信 4.x 有两种目录布局:
        #   新版: <wxid>/db_storage/contact/contact.db + db_storage/message/message_0.db
        #   旧版: <wxid>/db/contact.db + db/message_0.db
        if version_major >= 4:
            new_contact = data_path / "db_storage" / "contact" / "contact.db"
            old_contact = data_path / "db" / "contact.db"
            new_msg_dir = data_path / "db_storage" / "message"
            old_msg_dir = data_path / "db"

            if new_contact.exists():
                contact_file = new_contact
                msg_files = list(new_msg_dir.glob("message_*.db"))
            else:
                contact_file = old_contact
                msg_files = list(old_msg_dir.glob("message_*.db"))
        else:
            contact_file = data_path / "Msg" / "MicroMsg.db"
            msg_files = list((data_path / "Msg").glob("MSG*.db"))
        if not msg_files:
            ctx.errors.append(f"未找到消息数据库: {db_dir}")
            return None, []

        # 提取密钥
        manual_key = (self.cfg.miru.wechat.database_key or "").strip()
        if manual_key:
            logger.info("  使用手动提供的数据库密钥")
            try:
                # 支持两种格式: 纯 64 hex 或 x'<64hex>' 包裹
                key_hex = manual_key
                if key_hex.startswith("x'") and key_hex.endswith("'"):
                    key_hex = key_hex[2:-1]
                raw_key = bytes.fromhex(key_hex)
                if len(raw_key) != 32:
                    ctx.errors.append(
                        f"手动密钥长度错误: 期望 32 bytes, 实际 {len(raw_key)} bytes"
                    )
                    return None, []
                from miru.collector.wechat_db_decrypt import ExtractedKey
                keys = [ExtractedKey(raw_key=raw_key, salt=b"", hex_key=key_hex)]
            except ValueError as e:
                ctx.errors.append(f"手动密钥格式错误: {e}")
                return None, []
        else:
            logger.info("  提取密钥...")
            try:
                keys = extract_keys_from_process(ctx.wechat_pid)
                logger.info(f"  找到 {len(keys)} 个候选密钥")
            except Exception as e:
                ctx.errors.append(f"密钥提取失败: {e}")
                return None, []

        # 解密消息数据库 (优先 — 包含 Name2Id 可回退)
        msg_file = msg_files[0]
        msg_result = try_decrypt_wechat_db(msg_file, ctx.wechat_pid, keys)
        if not msg_result.success:
            ctx.errors.append(f"消息数据库解密失败: {msg_result.error}")
            return None, []

        msg_path = Path(msg_result.db_path) if msg_result.is_decrypted else msg_file

        # 解密 contact.db (如果可用)
        ct_available = False
        ct_path = contact_file
        if contact_file.exists():
            ct_result = try_decrypt_wechat_db(contact_file, ctx.wechat_pid, keys)
            if ct_result.success:
                ct_available = True
                ct_path = Path(ct_result.db_path) if ct_result.is_decrypted else contact_file
                logger.info("  contact.db 解密成功")
            else:
                logger.warning(f"  contact.db 解密失败 (将用 message_0.db Name2Id 回退)")
        else:
            logger.warning(f"  contact.db 不存在，使用 message_0.db 回退")

        reader = WeChatDBReader(ct_path, msg_path, msg_key=keys[0].raw_key)

        # 读取群列表
        if ct_available:
            groups = reader.get_groups()
        else:
            groups = reader.get_groups_from_msg_db()

        # 筛选关注的群
        target_groups = self.cfg.miru.groups if self.cfg else []
        if target_groups:
            # 尝试从 chatlog_alpha 获取显示名映射
            name_map = _get_chatlog_display_names()
            matched_groups = []
            for g in groups:
                display = name_map.get(g.username, "")
                name = display or g.nickname or g.remark or g.username
                if any(t in name for t in target_groups):
                    # 用 chatlog_alpha 的显示名覆盖 nickname
                    if display:
                        g.nickname = display
                    matched_groups.append(g)
        else:
            matched_groups = groups[:5]  # 未配置则取前 5 个

        if not matched_groups:
            ctx.errors.append("未找到任何匹配的关注群")
            reader.close()
            return None, []

        logger.info(f"  目标群: {[g.nickname for g in matched_groups]}")

        # 读取消息 — 回放模式使用指定日期整天，正常模式使用今天
        if ctx.replay_mode:
            from datetime import timedelta
            replay_dt = datetime.strptime(ctx.date, "%Y-%m-%d")
            today_start = int(replay_dt.timestamp())
            now_ts_val = int((replay_dt + timedelta(days=1)).timestamp())
        else:
            today_start = int(datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp())
            now_ts_val = int(time.time())

        all_messages = []
        for g in matched_groups:
            msgs = reader.get_messages(
                g.username,
                start_time=today_start,
                end_time=now_ts_val,
                limit=2000,
            )
            # 设置群名
            for m in msgs:
                m.group_name = g.nickname or g.username
            all_messages.extend(msgs)

        reader.close()
        logger.info(f"  采集到 {len(all_messages)} 条消息 (来自 {len(matched_groups)} 个群)")
        return all_messages, matched_groups

    # ================================================================
    # Step 3: 消息过滤
    # ================================================================

    def _filter_messages(self, ctx: PipelineContext, raw_messages):
        """去重 + 清洗 + 分类 + 分组。"""
        from miru.filter import process as filter_process

        # 从数据库加载已知 server_id（跨运行去重）
        known_ids: set[int] = set()
        try:
            from miru.storage.database import Database
            from miru.storage.migrations import run_migrations
            from miru.storage.repository import MessageRepository

            db_path = self.cfg.miru.storage.db_path if self.cfg else "data/miru.db"
            db = Database(db_path)
            run_migrations(db)
            repo = MessageRepository(db)
            all_svr_ids = [m.server_id for m in raw_messages if m.server_id]
            if all_svr_ids:
                known_ids = repo.get_processed_svr_ids(all_svr_ids)
            db.close()
            logger.info(f"  已知消息: {len(known_ids)} 条")
        except Exception as e:
            logger.warning(f"  无法加载已知消息 ID: {e}")

        result = filter_process(raw_messages, known_ids)
        logger.info(
            f"  过滤结果: {result.total_output} 有效 / {result.total_input} 总计"
            f" (去重:{result.removed_duplicates} 系统:{result.removed_system}"
            f" 非文本:{result.removed_non_text} 短消息:{result.removed_short})"
        )
        return result

    # ================================================================
    # Step 4: LLM 分析
    # ================================================================

    def _analyze_messages(self, ctx: PipelineContext, filter_result):
        """调用 DeepSeek 分析每个群的消息。部分失败不阻断。"""
        from miru.llm import DeepSeekClient
        from miru.filter import build_llm_context

        llm_cfg = self.cfg.miru.llm if self.cfg else None
        if not llm_cfg or not llm_cfg.get_api_key():
            ctx.errors.append("DeepSeek API key 未配置")
            return []

        client = DeepSeekClient(
            api_key=llm_cfg.get_api_key(),
            model=llm_cfg.model,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_tokens,
            timeout=llm_cfg.timeout,
            max_retries=llm_cfg.max_retries,
            retry_delays=list(llm_cfg.retry_delay),
        )

        contexts = build_llm_context(filter_result.grouped, ctx.date)
        results = client.analyze_groups(contexts, ctx.date)

        # 统计
        ctx.groups_summarized = sum(1 for r in results if r.success)
        ctx.groups_failed = sum(1 for r in results if not r.success)
        ctx.llm_token_usage = {
            "prompt": client.total_prompt_tokens,
            "completion": client.total_completion_tokens,
            "total": client.total_tokens,
        }

        logger.info(
            f"  LLM: {ctx.groups_summarized} 成功, {ctx.groups_failed} 失败"
            f" — {client.total_tokens} tokens"
        )
        return results

    # ================================================================
    # Step 5: 日报生成
    # ================================================================

    def _generate_report(self, ctx: PipelineContext, llm_results):
        """生成日报 Markdown 并保存数据库（回放模式跳过 DB）。"""
        from miru.report import generate_daily_report

        db_path = (
            "" if ctx.replay_mode
            else (self.cfg.miru.storage.db_path if self.cfg else "data/miru.db")
        )

        try:
            report, items = generate_daily_report(
                llm_results, ctx.date, db_path, skip_db_save=ctx.replay_mode,
            )
            logger.info(f"  日报: {len(report.content_md)} 字符, {len(items)} 条目")
            return report
        except Exception as e:
            ctx.errors.append(f"日报生成失败: {e}")
            logger.error(f"日报生成失败: {e}")
            return None

    def _generate_empty_report(self, ctx: PipelineContext):
        """生成空日报（无消息时。回放模式跳过 DB）。"""
        from miru.report.generator import ReportGenerator
        gen = ReportGenerator()
        db_path = (
            "" if ctx.replay_mode
            else (self.cfg.miru.storage.db_path if self.cfg else "data/miru.db")
        )
        report, _ = gen.generate(
            [], ctx.date, db_path, skip_db_save=ctx.replay_mode,
        )
        ctx.report_md = report.content_md
        ctx.report_date = report.report_date

    # ================================================================
    # Step 6: 推送
    # ================================================================

    def _notify(self, ctx: PipelineContext) -> None:
        """推送日报。"""
        from miru.notify import dispatch_report, ConsoleNotifier, PushPlusNotifier

        notifiers = []
        for nc in self.cfg.miru.notifiers:
            if not nc.enabled:
                continue
            if nc.type == "pushplus":
                tk = nc.get_token()
                if tk and not tk.startswith("${"):
                    notifiers.append(PushPlusNotifier(token=tk))
            elif nc.type == "console":
                notifiers.append(ConsoleNotifier())

        if not notifiers:
            logger.warning("没有可用的推送渠道")
            ctx.push_status = "skipped"
            return

        db_path = self.cfg.miru.storage.db_path if self.cfg else "data/miru.db"
        result = dispatch_report(
            ctx.report_md, notifiers, ctx.report_date, db_path,
        )
        ctx.push_status = "sent" if result.failed == 0 else "failed"

    def _print_report_to_console(self, ctx: PipelineContext) -> None:
        """Dry-run: 输出日报到控制台。"""
        print()
        print("=" * 60)
        print("  DRY-RUN — 日报预览 (未推送)")
        print("=" * 60)
        print()
        print(ctx.report_md)
        print()
        print("=" * 60)

    # ================================================================
    # 工具
    # ================================================================

    def _backup_database(self) -> None:
        """Pipeline 成功后自动备份数据库。"""
        try:
            from miru.storage.backup import backup_database
            db_path = self.cfg.miru.storage.db_path if self.cfg else "data/miru.db"
            backup_database(db_path)
        except Exception as e:
            logger.warning(f"自动备份失败: {e}")

    @staticmethod
    def _step_header(ctx: PipelineContext, step: Optional[int], message: str) -> None:
        """打印步骤标题。"""
        if step:
            print()
            print(f"[{step}/6] {message}...", end=" ", flush=True)
        else:
            print(f"\n  {message}")

    def _write_run_log(self, ctx: PipelineContext, status: str) -> None:
        """写入运行日志到数据库。"""
        try:
            from miru.storage.database import Database
            from miru.storage.migrations import run_migrations
            from miru.storage.repository import RunLogRepository
            from miru.storage.models import RunLog

            db_path = self.cfg.miru.storage.db_path if self.cfg else "data/miru.db"
            db = Database(db_path)
            run_migrations(db)
            repo = RunLogRepository(db)

            # 计算总耗时
            duration_ms = 0
            if ctx.start_time and ctx.end_time:
                try:
                    start = datetime.strptime(ctx.start_time, "%Y-%m-%d %H:%M:%S")
                    end = datetime.strptime(ctx.end_time, "%Y-%m-%d %H:%M:%S")
                    duration_ms = int((end - start).total_seconds() * 1000)
                except Exception:
                    pass

            entry = RunLog(
                run_id=ctx.run_id,
                phase="pipeline",
                status=status,
                message=(
                    f"groups={ctx.groups_collected}/{ctx.groups_summarized}, "
                    f"msgs={ctx.raw_messages_count}/{ctx.filtered_messages_count}, "
                    f"push={ctx.push_status}"
                ),
                duration_ms=duration_ms,
            )
            repo.insert(entry)
            db.close()
        except Exception as e:
            logger.warning(f"写入运行日志失败: {e}")

    def _send_failure_notification(self, ctx: PipelineContext) -> None:
        """Pipeline 失败时发送通知。"""
        try:
            from miru.notify.pushplus import PushPlusNotifier
            from miru.scheduler.scheduler import send_failure_notification

            notifiers = []
            for nc in self.cfg.miru.notifiers:
                if nc.type == "pushplus" and nc.token and not nc.token.startswith("${"):
                    notifiers.append(PushPlusNotifier(token=nc.token))

            if notifiers:
                error_text = "\n".join(ctx.errors) if ctx.errors else "未知错误"
                send_failure_notification(
                    notifiers,
                    error_text,
                    error_stage="Pipeline",
                )
        except Exception as e:
            logger.warning(f"发送失败通知异常: {e}")
