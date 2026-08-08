"""
Miru Assistant — Chat Analyzer 聊天分析器 (Phase 2)。

读取导出的聊天记录 TXT，调用 DeepSeek 进行分析，
生成 Markdown 分析报告 analysis.md。

不依赖 Daily Report 任何模块。
仅复用:
    - miru.llm.client.DeepSeekClient (analyze_chat 方法)
    - miru.utils.config.load_config (读取 LLM 配置)

用法:
    analyzer = ChatAnalyzer()
    result = analyzer.analyze(
        contact_name="张三",
        chat_file="output/张三/chat.txt",
        output_dir="output",
    )
"""

from datetime import datetime
from pathlib import Path

import jinja2
from loguru import logger

from miru.chat_analyzer.models import AnalysisResult, ChatAnalysisError
from miru.llm.client import DeepSeekClient

TEMPLATE_DIR = Path(__file__).parent / "templates"

# 单次分析可发送的最大字符数 (≈5000 tokens，低于 PROMPT_CHAR_LIMIT 24000)
MAX_ANALYSIS_CHARS = 20_000


class ChatAnalyzer:
    """
    聊天记录分析器。

    流程:
        1. 读取导出聊天记录 (chat.txt)
        2. 解析消息为紧凑文本
        3. 调用 DeepSeekClient.analyze_chat() 分析
        4. 渲染 analysis.md 并写入输出目录

    用法:
        analyzer = ChatAnalyzer()
        result = analyzer.analyze(
            contact_name="张三",
            chat_file="output/张三/chat.txt",
        )
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        """
        Args:
            config_path: 配置文件路径（用于读取 LLM API key）。
        """
        self.config_path = config_path
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
        )

    # ---- 主入口 ----

    def analyze(
        self,
        contact_name: str,
        chat_file: str | Path,
        output_dir: str | Path = "output",
    ) -> AnalysisResult:
        """
        分析导出的聊天记录并生成 analysis.md。

        Args:
            contact_name: 联系人显示名称。
            chat_file: 导出的聊天记录 TXT 路径。
            output_dir: 输出目录根路径。

        Returns:
            AnalysisResult — 分析结果（含 analysis.md 路径）。

        Raises:
            ChatAnalysisError: 环境/配置级错误（如 API key 缺失）。
        """
        result = AnalysisResult(contact_name=contact_name)
        chat_path = Path(chat_file)

        if not chat_path.exists():
            result.errors.append(f"聊天记录文件不存在: {chat_path}")
            return result

        # ---- 1. 读取聊天记录并解析 ----
        text = chat_path.read_text(encoding="utf-8")
        messages_text, total = extract_messages(text)
        logger.info(f"从聊天记录中解析出 {total} 条消息")

        if total == 0:
            result.errors.append("聊天记录为空，无法分析")
            return result

        # ---- 2. 截断保护（保留最近消息） ----
        if len(messages_text) > MAX_ANALYSIS_CHARS:
            truncated_count = len(messages_text) - MAX_ANALYSIS_CHARS
            messages_text = truncate_recent(messages_text, MAX_ANALYSIS_CHARS)
            logger.warning(f"聊天记录过长，已截断约 {truncated_count} 字符（保留最近部分）")

        # ---- 3. 创建 LLM 客户端 ----
        client = self._build_client()
        if client is None:
            raise ChatAnalysisError(
                "DeepSeek API key 未配置",
                suggestion="请在 config/settings.yaml 中设置 miru.llm.api_key",
            )

        # ---- 4. 调用 DeepSeek ----
        llm_result = client.analyze_chat(contact_name, messages_text)
        result.llm_success = llm_result.success
        result.token_usage = {
            "prompt": llm_result.usage.prompt_tokens,
            "completion": llm_result.usage.completion_tokens,
            "total": llm_result.usage.total_tokens,
        }

        if not llm_result.success or llm_result.analysis is None:
            result.errors.append(f"AI 分析失败: {llm_result.error}")
            return result

        analysis = llm_result.analysis

        # ---- 5. 渲染 Markdown 报告 ----
        md = self._render_report(
            contact_name=contact_name,
            analysis=analysis,
            total_messages=total,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        # ---- 6. 写入 analysis.md ----
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        analysis_file = output_root / "analysis.md"
        analysis_file.write_text(md, encoding="utf-8")

        result.analysis_file = str(analysis_file.resolve())
        result.total_messages = total
        logger.info(f"聊天分析完成 → {analysis_file} ({result.token_usage.get('total', 0)} tokens)")
        return result

    # ---- 内部方法 ----

    def _build_client(self) -> DeepSeekClient | None:
        """从配置文件创建 DeepSeekClient。失败返回 None。"""
        try:
            from miru.utils.config import load_config

            cfg = load_config(self.config_path)
            llm_cfg = cfg.miru.llm
            api_key = llm_cfg.get_api_key()
            if not api_key:
                logger.warning("DeepSeek API key 未配置")
                return None
            return DeepSeekClient(
                api_key=api_key,
                model=llm_cfg.model,
                temperature=llm_cfg.temperature,
                max_tokens=llm_cfg.max_tokens,
                timeout=llm_cfg.timeout,
                max_retries=llm_cfg.max_retries,
                retry_delays=list(llm_cfg.retry_delay),
            )
        except Exception as e:
            logger.warning(f"LLM 客户端创建失败: {e}")
            return None

    def _render_report(
        self,
        contact_name: str,
        analysis,
        total_messages: int,
        generated_at: str,
    ) -> str:
        """渲染 analysis.md Jinja2 模板。"""
        template = self._jinja.get_template("analysis.md.j2")
        return template.render(
            contact_name=contact_name,
            total_messages=total_messages,
            generated_at=generated_at,
            communication_style=analysis.communication_style,
            main_topics=analysis.main_topics,
            emotional_tone=analysis.emotional_tone,
            relationship_insights=analysis.relationship_insights,
            key_conversations=analysis.key_conversations,
            overall_summary=analysis.overall_summary,
        )


# ============================================================
# 工具函数
# ============================================================


def extract_messages(text: str) -> tuple[str, int]:
    """
    从 chat.txt 解析消息记录。

    chat.txt 格式:
        [2026-07-26 17:33] 我：
        明天考试加油

    Returns:
        (compact_messages_text, message_count)
        compact 格式: "[2026-07-26 17:33] 我：明天考试加油"
    """
    lines = text.splitlines()
    messages: list[str] = []

    current_header: str | None = None
    content_parts: list[str] = []

    def _flush() -> None:
        """将当前积累的消息追加到 messages。"""
        nonlocal current_header
        if current_header is None:
            return
        content = " ".join(p.strip() for p in content_parts if p.strip())
        if content:
            messages.append(f"{current_header}{content}")
        current_header = None
        content_parts.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 消息头部: "[YYYY-MM-DD HH:MM] 发送者："
        if stripped.startswith("[") and "] " in stripped:
            _flush()
            current_header = stripped
        elif (
            stripped.startswith("===")
            or stripped.startswith("联系人")
            or stripped.startswith("导出时间")
            or stripped.startswith("消息数量")
        ):
            continue  # 文件头信息，跳过
        elif current_header is not None:
            content_parts.append(stripped)

    _flush()

    return "\n".join(messages), len(messages)


def truncate_recent(text: str, max_chars: int) -> str:
    """
    截断文本，保留最近的部分。

    从尾部逐行保留，直到达到 max_chars。用于长聊天记录的 prompt 保护。
    截断说明前缀会计入总长度预算。

    Args:
        text: 原始文本。
        max_chars: 最大字符数。

    Returns:
        截断后的文本（保留最近的消息）。
    """
    lines = text.splitlines()
    keep: list[str] = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > max_chars:
            break
        keep.append(line)
        total += len(line) + 1
    keep.reverse()

    dropped = len(lines) - len(keep)
    if dropped <= 0:
        return text

    prefix = f"[较早的 {dropped} 条消息因长度限制已截断]\n"
    # 前缀也计入预算；若超出则去掉前缀中最长的消息
    while prefix and total + len(prefix) > max_chars and keep:
        removed = keep.pop(0)
        total -= len(removed) + 1
        dropped += 1
        prefix = f"[较早的 {dropped} 条消息因长度限制已截断]\n"

    return prefix + "\n".join(keep)
