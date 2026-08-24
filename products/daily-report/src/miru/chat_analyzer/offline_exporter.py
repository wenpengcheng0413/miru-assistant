"""
Miru Assistant — Chat Analyzer 离线全量导出器 (联系人白名单模式)。

从微信加密分片数据库中离线导出指定联系人的全部消息
（不依赖微信进程运行 / 管理员权限 / 内存密钥扫描）。

输出文件:
    chat.txt      — 可读版（文本原样 + 媒体摘要，[图片]/[语音]/[链接] 等）
    chat_raw.txt  — 原始完整版（全部 message_content 原样，含 XML）

与 exporter.py 的 ChatExporter（在线模式）互补:
    - ChatExporter:  需要微信运行，按 MD5(微信号) 找表
    - ContactFullExporter: 离线直读密钥，按 MD5(wxid) + real_sender_id 定位

用法:
    exporter = ContactFullExporter()
    result = exporter.export(contact_name="Krista", output_dir="output")
"""

from datetime import datetime
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.models import ChatMessage, ExportResult
from miru.chat_analyzer.offline_reader import (
    MSG_TYPE_TEXT,
    OfflineWeChatDB,
    summarize_content,
)

# 非文本消息的占位标签（内容为空时使用）
_TYPE_LABELS = {
    MSG_TYPE_TEXT: "",
    3: "[图片]",
    34: "[语音]",
    43: "[视频]",
    47: "[表情]",
    49: "[链接/文件]",
    10000: "[系统消息]",
}


class ContactFullExporter:
    """
    联系人全量聊天记录导出器（离线模式）。

    用法:
        exporter = ContactFullExporter()
        result = exporter.export("Krista", output_dir="output")
    """

    def __init__(self, data_root: str | Path = ""):
        """
        Args:
            data_root: 微信数据目录（空 = 自动检测）。
        """
        self.data_root = data_root
        # 媒体处理器类（测试可注入替换）
        self._processor_cls = None

    # ---- 主入口 ----

    def export(
        self,
        contact_name: str,
        wxid: str | None = None,
        output_dir: str | Path = "output",
        media_config: "MediaConfig | None" = None,
        media_stt: "STTEngine | None" = None,
    ) -> ExportResult:
        """
        导出指定联系人的全部消息。

        Args:
            contact_name: 联系人显示名称（用于输出目录名）。
            wxid: 微信内部 ID（最可靠）。为 None 时自动从 contact.db 解析。
            output_dir: 输出目录根路径。
            media_config: 媒体处理配置（语音转写 + 图片导出）；
                None 表示不处理媒体（保持原行为）。
            media_stt: 共享 STT 引擎（并行导出时多个联系人复用同一
                模型实例，避免重复加载模型）；None = 每个处理器自建。

        Returns:
            ExportResult — 含 chat.txt 与 chat_raw.txt 路径。
        """
        result = ExportResult(contact_name=contact_name)
        result.export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db = OfflineWeChatDB(self.data_root)
        try:
            # ---- 1. 解析联系人 ----
            # 显示名一律用调用方传入的 contact_name（白名单 name），
            # contact.db 的 display_name（如备注 🐱👀）只用于匹配 wxid。
            try:
                contact = db.resolve_contact(contact_name) if not wxid else None
            except LookupError as e:
                result.errors.append(str(e))
                return result
            target_wxid = wxid or (contact or {}).get("username", "")
            display_name = contact_name
            if not target_wxid:
                result.errors.append(f"未找到联系人 '{contact_name}' 的 wxid")
                return result
            result.contact_username = target_wxid
            logger.info(f"联系人已解析: {display_name} (wxid={target_wxid})")

            # ---- 2. 定位会话表 ----
            # 一对一聊天的表名由 wxid 的 MD5 唯一决定。使用精确定位，
            # 避免 find_session_tables 按发送者反查时混入共同群聊内容。
            tables = db.find_direct_session_tables(target_wxid)
            if not tables:
                logger.warning(f"未找到 {display_name} 的消息表（wxid={target_wxid}）")
                result.warnings.append("数据库中没有该联系人的消息记录")
                self._write_empty_files(display_name, result, output_dir)
                return result

            # ---- 3. 全量读取（多表合并） ----
            msgs: list[ChatMessage] = []
            for table, shard_rel, _n in tables:
                part = db.read_all_messages(table, shard_rel)
                logger.info(f"表 {table} @ {shard_rel}: {len(part)} 条消息")
                msgs.extend(part)
            msgs.sort(key=lambda m: (m.timestamp, m.sender_id, m.content[:16]))

            # ---- 4. 发送者命名与格式化 ----
            self_wxid = self._self_wxid(db)

            # ---- 4.5 媒体处理（语音转写 + 图片导出） ----
            overrides: dict[int, str] = {}
            if media_config is not None and media_config.enabled:
                try:
                    from miru.chat_analyzer.media.processor import MediaProcessor

                    processor_cls = self._processor_cls or MediaProcessor
                    out_dir = Path(output_dir) / self._safe_dirname(display_name)
                    if media_stt is not None:
                        # 显式传入共享/外部 STT 引擎
                        processor = processor_cls(db.account_dir, db, media_config, stt=media_stt)
                    else:
                        # 未指定 → 走 sentinel 默认（按配置自动创建）
                        processor = processor_cls(db.account_dir, db, media_config)
                    media_result, overrides = processor.process(
                        msgs,
                        target_wxid,
                        out_dir / "media",
                    )
                    result.media_dir = media_result.media_dir
                    result.voice_transcribed = media_result.voice_transcribed
                    result.voice_failed = media_result.voice_failed
                    result.image_exported = media_result.image_exported
                    result.image_failed = media_result.image_failed
                    result.warnings.extend(media_result.warnings[:10])
                    logger.info(
                        f"媒体处理完成: 语音 {media_result.voice_transcribed}/"
                        f"{media_result.voice_total} 转写, "
                        f"图片 {media_result.image_exported}/{media_result.image_total} 导出"
                    )
                except Exception as e:
                    logger.warning(f"媒体处理失败（跳过，继续导出文本）: {e}")
                    result.warnings.append(f"媒体处理失败: {str(e)[:100]}")

            lines, lines_raw, text_count = self._render(
                msgs, target_wxid, display_name, self_wxid, overrides=overrides
            )

            # ---- 5. 写文件 ----
            out_dir = Path(output_dir) / self._safe_dirname(display_name)
            out_dir.mkdir(parents=True, exist_ok=True)
            chat_file = out_dir / "chat.txt"
            raw_file = out_dir / "chat_raw.txt"
            header = self._header(display_name, len(msgs), result.export_time)

            chat_file.write_text(header + "\n" + "\n".join(lines), encoding="utf-8")
            raw_file.write_text(header + "\n" + "\n".join(lines_raw), encoding="utf-8")

            # ---- 6. 统计 ----
            result.output_file = str(chat_file.resolve())
            result.raw_output_file = str(raw_file.resolve())
            result.total_messages = len(msgs)
            result.text_messages = text_count
            result.image_messages = sum(1 for m in msgs if m.msg_type == 3)
            result.voice_messages = sum(1 for m in msgs if m.msg_type == 34)
            if msgs:
                result.date_range_start = datetime.fromtimestamp(msgs[0].timestamp).strftime("%Y-%m-%d")
                result.date_range_end = datetime.fromtimestamp(msgs[-1].timestamp).strftime("%Y-%m-%d")

            logger.info(
                f"导出完成: {len(msgs)} 条消息 → {chat_file}"
            )
            return result
        except FileNotFoundError as e:
            result.errors.append(str(e))
            return result
        finally:
            db.close()

    # ---- 内部方法 ----

    @staticmethod
    def _self_wxid(db: OfflineWeChatDB) -> str:
        """当前微信账号 wxid（账号目录名前缀，去除 _aXX 后缀）。"""
        return db.account_dir.name.split("_a")[0]

    @staticmethod
    def _safe_dirname(name: str) -> str:
        """清理输出目录名中的非法字符。"""
        invalid = '<>:"/\\|?*'
        result = name
        for ch in invalid:
            result = result.replace(ch, "_")
        return result.strip() or "unknown_contact"

    @staticmethod
    def _header(display_name: str, total: int, export_time: str) -> str:
        """文件头（与 exporter.py render_export_file 格式兼容）。

        注意: 不要用相邻字符串字面量拼接（"\n" + f-string + "=" 会被
        Python 编译期隐式拼接后整体乘算，导致头部重复）。
        """
        return "\n".join(
            [
                "=" * 60,
                f"联系人：{display_name}",
                f"导出时间：{export_time}",
                f"消息数量：{total}",
                "=" * 60,
            ]
        ) + "\n"

    @staticmethod
    def _render(
        msgs: list[ChatMessage],
        target_wxid: str,
        display_name: str,
        self_wxid: str,
        overrides: dict[int, str] | None = None,
    ) -> tuple[list[str], list[str], int]:
        """渲染可读版与原始版内容。返回 (lines, lines_raw, text_count)。

        overrides: {消息下标: 渲染文本} — 媒体处理（语音转写/图片路径）覆盖默认摘要。
        """
        overrides = overrides or {}
        lines: list[str] = []
        lines_raw: list[str] = []
        text_count = 0
        # sender 显示名 → wxid 反查需要 sender_name，ChatMessage.sender 已是显示名；
        # "我"判定: sender_name 与当前账号一致（名称缓存中显示名可能等于 wxid）
        for i, m in enumerate(msgs):
            if m.msg_type == MSG_TYPE_TEXT:
                text_count += 1
            label = ContactFullExporter._sender_label(m, target_wxid, display_name, self_wxid)
            # 分钟级时间戳（与在线 ChatExporter 格式一致，供 statistics/analyzer 解析）
            ts = datetime.fromtimestamp(m.timestamp).strftime("%Y-%m-%d %H:%M")
            if i in overrides:
                summary = overrides[i]
            else:
                summary = summarize_content(m.content, m.msg_type) or _TYPE_LABELS.get(
                    m.msg_type, f"[消息类型{m.msg_type}]"
                )
            lines.append(f"[{ts}] {label}：")
            lines.append(summary)
            lines.append("")
            lines.append("")
            lines_raw.append(f"[{ts}] {label}：")
            lines_raw.append(m.raw_content or "")
            lines_raw.append("")
            lines_raw.append("")

        # 去除末尾多余空行
        while lines and lines[-1] == "":
            lines.pop()
        while lines_raw and lines_raw[-1] == "":
            lines_raw.pop()
        return lines, lines_raw, text_count

    @staticmethod
    def _sender_label(
        m: ChatMessage, target_wxid: str, display_name: str, self_wxid: str
    ) -> str:
        """确定发送者标签: 我 / 联系人 / 其他参与者。

        身份判定以 sender_username（原始 wxid）为准，显示名仅作展示：
        sender_username 最可靠（显示名可能与 wxid 不同，如备注"文"）。
        """
        uname = m.sender_username or ""
        if uname == self_wxid:
            return "我"
        if uname == target_wxid:
            return display_name
        if uname:
            return m.sender or uname
        return m.sender or f"用户_{m.sender_id}"

    def _write_empty_files(
        self, display_name: str, result: ExportResult, output_dir: str | Path
    ) -> None:
        """无消息时生成空 chat.txt（保持输出目录结构一致）。"""
        out_dir = Path(output_dir) / self._safe_dirname(display_name)
        out_dir.mkdir(parents=True, exist_ok=True)
        chat_file = out_dir / "chat.txt"
        chat_file.write_text(self._header(display_name, 0, result.export_time), encoding="utf-8")
        result.output_file = str(chat_file.resolve())


def export_contact_full(
    contact_name: str,
    wxid: str | None = None,
    output_dir: str | Path = "output",
    data_root: str | Path = "",
    media_config: "MediaConfig | None" = None,
) -> ExportResult:
    """便捷函数: 一键导出联系人全量聊天记录。"""
    exporter = ContactFullExporter(data_root=data_root)
    return exporter.export(
        contact_name=contact_name,
        wxid=wxid,
        output_dir=output_dir,
        media_config=media_config,
    )
