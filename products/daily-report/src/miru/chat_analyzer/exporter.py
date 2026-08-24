"""
Miru Assistant — Chat Analyzer 聊天记录导出器 (Phase 1)。

从微信数据库中提取指定联系人的完整聊天记录，按时间排序，导出为 UTF-8 TXT。

不依赖 Daily Report 任何模块。
仅复用 collector/ 层的基础设施（WeChatDBReader、解密、诊断）。

用法:
    exporter = ChatExporter()
    result = exporter.export(
        contact_name="张三",
        output_dir="output",
    )

    或使用便捷函数:
    result = export_chat("张三", output_dir="output")
"""

import ctypes
from datetime import datetime
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.models import (
    ChatExportError,
    ContactInfo,
    ContactNotFoundError,
    ExportedMessage,
    ExportResult,
)
from miru.collector.wechat_reader import WeChatContact, WeChatDBReader, WeChatMessage

# ============================================================
# 联系人解析
# ============================================================


def find_contact_candidates(
    contacts: list[WeChatContact],
    contact_name: str,
) -> list[ContactInfo]:
    """
    查找所有匹配的联系人候选（供 CLI 交互选择）。

    匹配优先级:
        1. remark / nickname / alias 精确匹配 → 唯一候选
        2. 任意字段包含 contact_name (模糊匹配) → 按显示名长度排序

    Args:
        contacts: 从 WeChatDBReader.get_contacts() 获取的联系人列表。
        contact_name: 用户输入的搜索名称。

    Returns:
        匹配的联系人列表（空列表 = 无匹配）。
    """
    if not contacts:
        return []

    # Stage 1: 精确匹配 → 唯一候选
    for c in contacts:
        if c.remark == contact_name or c.nickname == contact_name or c.alias == contact_name:
            return [_to_contact_info(c)]

    # Stage 2: 模糊匹配
    candidates: list[WeChatContact] = []
    for c in contacts:
        display = c.remark or c.nickname or c.alias or c.username
        if contact_name.lower() in display.lower():
            candidates.append(c)

    # 按显示名长度排序（短的优先，通常是更接近的匹配）
    candidates.sort(key=lambda c: len(c.remark or c.nickname or c.alias or c.username))
    return [_to_contact_info(c) for c in candidates]


def resolve_contact(
    contacts: list[WeChatContact],
    contact_name: str,
) -> ContactInfo:
    """
    在联系人列表中按名称模糊匹配。

    匹配优先级:
        1. remark / nickname / alias 精确匹配
        2. 任意字段包含 contact_name (模糊匹配) — 多个候选时选显示名最短的

    Args:
        contacts: 从 WeChatDBReader.get_contacts() 获取的联系人列表。
        contact_name: 用户输入的搜索名称。

    Returns:
        解析后的 ContactInfo。

    Raises:
        ContactNotFoundError: 未找到匹配联系人。
    """
    candidates = find_contact_candidates(contacts, contact_name)

    if not candidates:
        raise ContactNotFoundError(contact_name, available_count=len(contacts))

    if len(candidates) > 1:
        logger.info(
            f"联系人 '{contact_name}' 有 {len(candidates)} 个模糊匹配，"
            f"选择: {candidates[0].display_name}"
        )
    return candidates[0]


def _to_contact_info(c: WeChatContact) -> ContactInfo:
    """将 WeChatContact 转换为 ContactInfo。"""
    return ContactInfo(
        username=c.username,
        nickname=c.nickname,
        remark=c.remark,
        alias=c.alias,
        display_name=c.display_name,
    )


# ============================================================
# 发送者识别
# ============================================================


def find_self_sender_id(reader: WeChatDBReader, contact_username: str) -> int:
    """
    确定代表"我"的 sender_id (Name2Id rowid)。

    策略:
        1. 从 Name2Id 表中找到所有 user_name 条目（排除 @chatroom 群聊）。
        2. 排除已知联系人 username 后的第一个非群聊条目即为"我"。
           （在微信数据库中，Name2Id 包含当前用户和所有联系人的映射）

    Args:
        reader: 已初始化的 WeChatDBReader。
        contact_username: 目标联系人的微信 username。

    Returns:
        代表"我"的 sender_id。0 表示无法确定（回退模式）。
    """
    try:
        conn = reader.message_conn
        rows = conn.execute(
            "SELECT rowid, user_name FROM Name2Id WHERE user_name NOT LIKE '%@chatroom%'"
        ).fetchall()
    except Exception as e:
        logger.warning(f"无法查询 Name2Id 表: {e}")
        return 0

    # 解析行（兼容 sqlcipher3 tuple 和 sqlite3.Row）
    id_to_name: dict[int, str] = {}
    for r in rows:
        if isinstance(r, tuple):
            id_to_name[r[0]] = r[1]
        else:
            id_to_name[r["rowid"]] = r["user_name"]

    # 排除联系人的 username → 剩余第一个即为"我"
    for sid, uname in id_to_name.items():
        if uname == contact_username:
            continue
        # 可能是 "我" — 通常当前用户的 username 与联系人不同
        logger.debug(f"推测 self_sender_id={sid} (username={uname})")
        return sid

    return 0


def classify_sender(
    msg: WeChatMessage,
    self_sender_id: int,
    contact: ContactInfo,
) -> tuple[str, bool]:
    """
    将消息发送者分类为 "我" 或联系人显示名。

    Args:
        msg: 原始微信消息。
        self_sender_id: 代表"我"的 sender_id。
        contact: 已解析的联系人信息。

    Returns:
        (sender_label, is_self)
    """
    if self_sender_id > 0 and msg.sender_id == self_sender_id:
        return ("我", True)

    # 回退: 比较 sender_name
    sender_name = msg.sender_name
    if sender_name and (
        sender_name == contact.display_name
        or sender_name == contact.remark
        or sender_name == contact.nickname
    ):
        return (contact.display_name, False)

    # sender_name 不匹配联系人 → 可能是 "我"
    if sender_name:
        return ("我", True)

    return ("未知", False)


# ============================================================
# 消息格式化
# ============================================================


def format_timestamp(ts: int) -> str:
    """Unix 时间戳 → 'YYYY-MM-DD HH:MM'。"""
    if ts == 0:
        return "0000-00-00 00:00"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return str(ts)


def format_message(
    msg: WeChatMessage,
    contact: ContactInfo,
    self_sender_id: int,
) -> ExportedMessage:
    """
    将 WeChatMessage 格式化为导出行。

    Args:
        msg: 原始微信消息。
        contact: 联系人信息。
        self_sender_id: "我"的 sender_id。

    Returns:
        ExportedMessage — 格式化后的消息。
    """
    sender, is_self = classify_sender(msg, self_sender_id, contact)
    return ExportedMessage(
        timestamp=format_timestamp(msg.create_time),
        sender=sender,
        content=msg.content,
        is_self=is_self,
    )


def render_export_file(
    messages: list[ExportedMessage],
    contact: ContactInfo,
    export_time: str,
    output_path: Path,
) -> None:
    """
    将消息列表渲染为 UTF-8 TXT 文件。

    格式:
        ==============================
        联系人：张三
        导出时间：2026-08-08 10:30:00
        消息数量：523
        ==============================

        [2026-07-01 10:32] 我：
        今天考试怎么样？

        [2026-07-01 10:35] 张三：
        还可以

    Args:
        messages: 格式化后的消息列表（已排序）。
        contact: 联系人信息。
        export_time: 导出时间字符串。
        output_path: 输出文件路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"联系人：{contact.display_name}")
    lines.append(f"导出时间：{export_time}")
    lines.append(f"消息数量：{len(messages)}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("")

    for msg in messages:
        lines.append(f"[{msg.timestamp}] {msg.sender}：")
        lines.append(msg.content)
        lines.append("")
        lines.append("")

    # 移除末尾多余空行
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")  # 文件末尾一个换行

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"聊天记录已导出 → {output_path} ({len(messages)} 条)")


# ============================================================
# ChatExporter
# ============================================================


class ChatExporter:
    """
    联系人聊天记录导出器。

    复用 collector/ 层的基础设施:
        - diagnostics: 微信环境检测
        - wechat_db_decrypt: SQLCipher 密钥提取与解密
        - wechat_reader: 数据库读取

    不依赖 Daily Report 的任何模块 (core.pipeline, filter, report, notify)。

    用法:
        exporter = ChatExporter()
        result = exporter.export(
            contact_name="张三",
            output_dir="output",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        """
        Args:
            config_path: 配置文件路径（用于读取 wechat.data_dir 覆盖）。
        """
        self.config_path = config_path

    # ---- 主入口 ----

    def export(
        self,
        contact_name: str,
        output_dir: str = "output",
        start_date: str | None = None,
        end_date: str | None = None,
        username: str | None = None,
    ) -> ExportResult:
        """
        导出指定联系人的聊天记录为 TXT 文件。

        Args:
            contact_name: 联系人显示名称（昵称/备注/微信号）。
            output_dir: 输出目录根路径。
            start_date: 起始日期 (YYYY-MM-DD，包含)。
            end_date: 结束日期 (YYYY-MM-DD，包含)。
            username: 微信 username 直接指定（白名单模式，跳过名称匹配）。
                      为 None 时使用数据库模糊匹配。

        Returns:
            ExportResult — 导出结果（含统计信息）。

        Raises:
            ContactNotFoundError: 联系人未找到。
            ChatExportError: 环境/解密失败。
        """
        result = ExportResult(contact_name=contact_name)
        result.export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"开始导出联系人 '{contact_name}' 的聊天记录...")

        # ---- 1-5. 环境检查 + 解密 + 打开所有分片 Reader ----
        try:
            readers, ct_available = self._open_readers()
        except ChatExportError as e:
            result.errors.append(str(e))
            return result

        try:
            # ---- 6. 查找联系人 ----
            if username:
                # 白名单模式: 直接使用指定 username（跳过数据库模糊匹配）
                contact = ContactInfo(
                    username=username,
                    nickname=contact_name,
                    remark="",
                    alias=username,
                    display_name=contact_name,
                )
            else:
                contacts = (
                    readers[0].get_contacts()
                    if ct_available
                    else _get_contacts_from_msg_db(readers[0])
                )
                logger.info(f"数据库中有 {len(contacts)} 个联系人")
                contact = resolve_contact(contacts, contact_name)
            result.contact_username = contact.username
            logger.info(f"联系人已解析: {contact.display_name} (username={contact.username})")

            # ---- 7. 跨分片读取消息 ----
            start_ts = _parse_date_to_ts(start_date) if start_date else None
            end_ts = _parse_date_to_ts(end_date, is_end=True) if end_date else None

            # 每个分片查询一次，同时用于统计和格式化
            reader_messages: list[tuple[WeChatDBReader, list[WeChatMessage]]] = []
            all_messages: list[WeChatMessage] = []
            for reader in readers:
                try:
                    msgs = reader.get_messages(
                        contact.username,
                        start_time=start_ts,
                        end_time=end_ts,
                        limit=100000,  # 私聊消息通常不会超过此数量
                    )
                    reader_messages.append((reader, msgs))
                    all_messages.extend(msgs)
                except Exception:
                    logger.debug(
                        f"分片 {reader.message_db_path.name} 中无 {contact.username} 的消息表"
                    )
            logger.info(f"跨 {len(readers)} 个分片读取到 {len(all_messages)} 条消息")

            # ---- 8. 格式化消息（仅文本，按各分片 self_sender_id 识别"我"） ----
            exported: list[ExportedMessage] = []
            for reader, msgs in reader_messages:
                self_sender_id = find_self_sender_id(reader, contact.username)
                for msg in msgs:
                    if msg.local_type != WeChatDBReader.MSG_TYPE_TEXT:
                        continue
                    exported.append(format_message(msg, contact, self_sender_id))

            # 按时间排序（跨分片合并后排序）
            exported.sort(key=lambda m: m.timestamp)

            # ---- 9. 生成输出文件 ----
            output_root = Path(output_dir)
            safe_name = _sanitize_dirname(contact.display_name)
            chat_dir = output_root / safe_name
            output_file = chat_dir / "chat.txt"

            render_export_file(exported, contact, result.export_time, output_file)

            # ---- 10. 统计 ----
            result.total_messages = len(exported)
            result.text_messages = sum(
                1 for m in all_messages if m.local_type == WeChatDBReader.MSG_TYPE_TEXT
            )
            result.image_messages = sum(
                1 for m in all_messages if m.local_type == WeChatDBReader.MSG_TYPE_IMAGE
            )
            result.voice_messages = sum(
                1 for m in all_messages if m.local_type == WeChatDBReader.MSG_TYPE_VOICE
            )
            result.output_file = str(output_file.resolve())

            if exported:
                result.date_range_start = exported[0].timestamp[:10]
                result.date_range_end = exported[-1].timestamp[:10]

            logger.info(f"导出完成: {result.total_messages} 条消息 → {output_file}")

        finally:
            for reader in readers:
                reader.close()

        return result

    # ---- 联系人发现（供 CLI 交互选择） ----

    def list_contacts(self) -> list[ContactInfo]:
        """
        列出微信中的所有可用联系人。

        供 CLI 交互选择使用（不导出消息，只读取联系人列表）。

        Returns:
            ContactInfo 列表。

        Raises:
            ChatExportError: 环境/解密失败。
        """
        readers, ct_available = self._open_readers()
        try:
            contacts = (
                readers[0].get_contacts() if ct_available else _get_contacts_from_msg_db(readers[0])
            )
            # 过滤系统账号: @openim 开放平台消息账号
            filtered = [c for c in contacts if not c.username.lower().endswith("@openim")]
            logger.info(
                f"数据库中有 {len(contacts)} 个联系人，过滤系统账号后剩余 {len(filtered)} 个"
            )
            return [_to_contact_info(c) for c in filtered]
        finally:
            for reader in readers:
                reader.close()

    # ---- 内部方法 ----

    def _open_readers(self) -> tuple[list[WeChatDBReader], bool]:
        """
        执行导出前置步骤并打开所有可解密的消息分片 Reader。

        步骤:
            1. 加载配置（data_dir / database_key / database_keys.yaml）
            2. 微信环境检查
            3. 定位数据库文件
            4. 提取密钥 + 验证解密（优先分片密钥表，回退手动 key）
            5. 为每个可解密的消息分片创建 WeChatDBReader

        Returns:
            (readers, contact_db_available) — readers 至少含 message_0.db。

        Raises:
            ChatExportError: 环境/解密/数据库缺失。
        """
        from miru.chat_analyzer.keys import load_database_keys
        from miru.collector.wechat_db_decrypt import try_decrypt_wechat_db

        # ---- 1. 加载配置 ----
        manual_data_dir, manual_db_key = self._load_config_values()
        shard_keys = load_database_keys()

        # ---- 2. 微信环境检查 ----
        proc_info, data_dir_info = self._check_environment(manual_data_dir)
        logger.info(
            f"微信: PID={proc_info.pid}, v{proc_info.version_raw}, data_dir={data_dir_info.path}"
        )

        # ---- 3. 定位数据库文件 ----
        version_major = proc_info.version_major or 4
        data_path = Path(data_dir_info.path)
        contact_file, msg_files = self._find_databases(data_path, version_major)

        # ---- 4. 提取密钥 & 解密 ----
        keys, msg_key = self._prepare_keys(proc_info.pid, manual_db_key)

        # 主分片 (message_0.db) 必须可解密
        main_result = try_decrypt_wechat_db(msg_files[0], proc_info.pid, keys)
        if not main_result.success:
            raise ChatExportError(f"消息数据库解密失败: {main_result.error}")

        # contact.db 可能使用不同于 message_0.db 的密钥，无法直接解密。
        # 与 Daily Report 的 get_groups_from_msg_db() 类似，
        # 当 contact.db 不可用时，从 message_0.db 的 Name2Id 表读取联系人。
        ct_available = False
        if contact_file.exists():
            ct_result = try_decrypt_wechat_db(contact_file, proc_info.pid, keys)
            ct_available = ct_result.success
            if ct_available:
                logger.info("contact.db 验证通过")
            else:
                logger.warning(
                    f"contact.db 不可用 ({ct_result.error[:60]})，"
                    f"将从 message_0.db Name2Id 读取联系人"
                )
        else:
            raise ChatExportError(f"联系人数据库不存在: {contact_file}")

        # ---- 5. 创建所有分片 Reader ----
        readers: list[WeChatDBReader] = []
        for msg_file in msg_files:
            # 优先使用分片密钥表 (database_keys.yaml)，回退主 key
            key = shard_keys.get(msg_file.name, msg_key)
            try:
                reader = WeChatDBReader(contact_file, msg_file, msg_key=key)
                # 验证可读（懒连接，触发一次查询）
                _ = reader.message_conn
                readers.append(reader)
                logger.info(f"分片 {msg_file.name} 已加载")
            except Exception as e:
                logger.warning(f"分片 {msg_file.name} 打开失败: {str(e)[:60]}")

        if not readers:
            raise ChatExportError("无法打开任何消息数据库分片")

        return readers, ct_available

    def _load_config_values(self) -> tuple[str, str]:
        """从配置文件读取 wechat.data_dir 和 wechat.database_key。"""
        try:
            from miru.utils.config import load_config

            cfg = load_config(self.config_path)
            return cfg.miru.wechat.data_dir, cfg.miru.wechat.database_key
        except Exception:
            return "", ""

    @staticmethod
    def _check_environment(manual_data_dir: str):
        """检查微信环境和数据目录。"""
        from miru.collector.diagnostics import (
            detect_wechat_process,
            find_wechat_data_dir,
        )

        proc = detect_wechat_process()
        if not proc.found:
            from miru.chat_analyzer.models import ChatExportError

            raise ChatExportError(
                "微信未运行 — 请启动并登录微信 PC 客户端",
                suggestion="启动微信 PC 客户端后重试。",
            )

        # 管理员权限检查
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        if not is_admin:
            from miru.chat_analyzer.models import ChatExportError

            raise ChatExportError(
                "需要管理员权限 — 请以管理员身份运行",
                suggestion="右键终端 → 以管理员身份运行，或使用管理员 PowerShell。",
            )

        data_dir = find_wechat_data_dir(manual_data_dir)
        if not data_dir.found:
            from miru.chat_analyzer.models import ChatExportError

            raise ChatExportError(
                "未找到微信数据目录",
                suggestion=(
                    "请在 config/settings.yaml 中设置 wechat.data_dir，或确认微信已正确安装。"
                ),
            )

        return proc, data_dir

    @staticmethod
    def _find_databases(data_path: Path, version_major: int):
        """定位 contact.db 和所有消息分片。"""
        if version_major >= 4:
            # 新版布局: db_storage/contact/contact.db + db_storage/message/message_*.db
            new_contact = data_path / "db_storage" / "contact" / "contact.db"
            old_contact = data_path / "db" / "contact.db"
            new_msg_dir = data_path / "db_storage" / "message"
            old_msg_dir = data_path / "db"

            contact_file = new_contact if new_contact.exists() else old_contact

            if new_msg_dir.exists():
                msg_files = sorted(new_msg_dir.glob("message_*.db"))
            else:
                msg_files = sorted(old_msg_dir.glob("message_*.db"))
        else:
            contact_file = data_path / "Msg" / "MicroMsg.db"
            msg_files = sorted((data_path / "Msg").glob("MSG*.db"))

        if not msg_files:
            from miru.chat_analyzer.models import ChatExportError

            raise ChatExportError(
                "未找到消息数据库分片",
                suggestion="请确认微信数据目录包含 message_*.db。",
            )

        return contact_file, msg_files

    @staticmethod
    def _prepare_keys(pid: int, manual_key_hex: str = ""):
        """
        提取密钥并准备 msg_key。

        优先级:
            1. 手动配置的 database_key (config/settings.yaml)
            2. 自动内存扫描 (extract_keys_from_process)

        Args:
            pid: 微信进程 PID。
            manual_key_hex: 手动配置的 64 字符 hex 密钥。
        """
        from miru.collector.wechat_db_decrypt import ExtractedKey, extract_keys_from_process

        # ---- 优先使用手动密钥 ----
        if manual_key_hex:
            key_hex = manual_key_hex.strip()
            if key_hex.startswith("x'") and key_hex.endswith("'"):
                key_hex = key_hex[2:-1]
            try:
                raw_key = bytes.fromhex(key_hex)
                if len(raw_key) == 32:
                    logger.info("使用手动配置的 database_key")
                    key = ExtractedKey(raw_key=raw_key, salt=b"", hex_key=key_hex)
                    return [key], raw_key
                else:
                    logger.warning(f"手动密钥长度错误: 期望 32 bytes, 实际 {len(raw_key)} bytes")
            except ValueError as e:
                logger.warning(f"手动密钥格式错误: {e}")

        # ---- 回退: 自动内存扫描 ----
        logger.info("从微信进程提取密钥...")
        keys = extract_keys_from_process(pid)
        logger.info(f"找到 {len(keys)} 个候选密钥")

        msg_key = keys[0].raw_key if keys else None
        return keys, msg_key


# ============================================================
# 便捷函数
# ============================================================


def export_chat(
    contact_name: str,
    output_dir: str = "output",
    start_date: str | None = None,
    end_date: str | None = None,
    config_path: str = "config/settings.yaml",
    username: str | None = None,
) -> ExportResult:
    """
    一键导出联系人聊天记录。

    Args:
        contact_name: 联系人名称。
        output_dir: 输出目录。
        start_date: 起始日期 (YYYY-MM-DD)。
        end_date: 结束日期 (YYYY-MM-DD)。
        config_path: 配置文件路径。
        username: 微信 username 直接指定（白名单模式）。

    Returns:
        ExportResult。
    """
    exporter = ChatExporter(config_path=config_path)
    return exporter.export(
        contact_name=contact_name,
        output_dir=output_dir,
        start_date=start_date,
        end_date=end_date,
        username=username,
    )


# ============================================================
# 工具函数
# ============================================================


def _parse_date_to_ts(date_str: str, is_end: bool = False) -> int:
    """
    YYYY-MM-DD → Unix 时间戳。

    Args:
        date_str: 日期字符串。
        is_end: True → 返回该日 23:59:59 的时间戳（用于 end_time）。
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if is_end:
            dt = dt.replace(hour=23, minute=59, second=59)
        else:
            dt = dt.replace(hour=0, minute=0, second=0)
        return int(dt.timestamp())
    except ValueError:
        logger.warning(f"无效日期格式: {date_str}，已忽略")
        return 0


def _sanitize_dirname(name: str) -> str:
    """清理名称中的非法文件名字符。"""
    invalid_chars = '<>:"/\\|?*'
    result = name
    for ch in invalid_chars:
        result = result.replace(ch, "_")
    return result.strip() or "unknown_contact"


def _get_contacts_from_msg_db(reader: WeChatDBReader) -> list[WeChatContact]:
    """
    从 message_0.db 的 Name2Id 表读取联系人列表。

    当 contact.db 加密且无法用 message_0.db 的密钥解密时，
    回退到此方法。类似于 WeChatDBReader.get_groups_from_msg_db()。

    Name2Id 表结构: rowid (sender_id), user_name (微信 username)
    联系人: user_name 不以 @chatroom 结尾的条目。

    Args:
        reader: 已初始化的 WeChatDBReader（已连接 message_0.db）。

    Returns:
        WeChatContact 列表（仅含 username，无显示名）。
    """
    contacts: list[WeChatContact] = []
    try:
        conn = reader.message_conn
        rows = conn.execute(
            "SELECT rowid, user_name FROM Name2Id WHERE user_name NOT LIKE '%@chatroom%'"
        ).fetchall()
    except Exception as e:
        logger.warning(f"无法从 Name2Id 读取联系人: {e}")
        return contacts

    # 需要跳过的系统账号
    skip_usernames = {"medianote", "weixin", "qmessage", "filehelper", "wechat"}

    for r in rows:
        uname = r[1] if isinstance(r, tuple) else r["user_name"]

        if not uname or not uname.strip():
            continue
        if uname.lower() in skip_usernames:
            continue

        # 用 username 作为 display_name（无 contact.db 时无法获取昵称）
        contacts.append(
            WeChatContact(
                username=uname,
                nickname=uname,
                remark="",
                alias="",
                display_name=uname,
            )
        )

    logger.info(f"从 Name2Id 读取到 {len(contacts)} 个联系人")
    return contacts
