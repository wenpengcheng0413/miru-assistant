"""
Miru Assistant — DeepSeek LLM 客户端。

基于 OpenAI SDK，兼容 DeepSeek API。
提供 retry、timeout、token 统计、JSON 模式支持。
"""

from pathlib import Path
from typing import Any

import jinja2
from loguru import logger
from openai import OpenAI

from miru.llm.schemas import (
    ChatAnalysis,
    ChatAnalysisResult,
    GroupAnalysis,
    LLMCallResult,
    TokenUsage,
)

# ============================================================
# 常量
# ============================================================

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAYS = [5, 30]  # seconds

#  Prompt 长度保护阈值 (估算: 4 chars ≈ 1 token)
PROMPT_CHAR_LIMIT = 24_000  # ≈ 6000 tokens


# ============================================================
# LLM 异常
# ============================================================


class LLMError(Exception):
    """LLM 调用失败。retryable 表示是否可重试。"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class TokenBudgetExceededError(LLMError):
    """finish_reason='length' — 输出被 max_tokens 截断。"""

    def __init__(self, message: str = "Token budget exceeded — output truncated"):
        super().__init__(message, retryable=True)


class EmptyResponseError(LLMError):
    """API 返回空 content。"""

    def __init__(self, message: str = "LLM returned empty response"):
        super().__init__(message, retryable=True)


# ============================================================
# LLM 客户端
# ============================================================


class DeepSeekClient:
    """DeepSeek API 客户端。

    使用 OpenAI SDK (base_url 指向 api.deepseek.com)。
    支持:
        - 自动重试 (指数退避)
        - Token 用量统计
        - JSON 模式 (强制结构化输出)
        - Prompt 模板 (Jinja2)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delays: list[int] | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delays = retry_delays or DEFAULT_RETRY_DELAYS

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        # Jinja2 模板引擎
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(PROMPT_DIR)),
            autoescape=False,
        )

        # 累计统计
        self.total_successful_calls: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0

    # ---- Prompt 渲染 ----

    def render_system_prompt(self) -> str:
        """渲染 system role 的 prompt（不含消息内容，可被 API cache）。"""
        return (
            "你是一个个人学习助手，帮助用户从微信群聊消息中提取关键信息。"
            "你的任务是识别需要用户关注的重要信息，并忽略闲聊、表情包和无意义对话。"
            "你必须严格按照 JSON 格式输出结果。\n\n"
            "## 信息优先级 (从高到低)\n"
            "1. 学业通知: 课程调整、考试安排、作业、实验报告、论文\n"
            "2. 项目/技术信息: AI相关、编程、技术讨论、工具推荐\n"
            "3. AI相关内容: ComfyUI、DeepSeek、大模型、AI工具\n"
            "4. 工作兼职机会: 家教、实习、招聘信息\n"
            "5. 重要群公告: @所有人、群主通知\n\n"
            "## 应该忽略\n"
            "- 闲聊、问候、简单确认回复\n"
            "- 表情包、纯表情\n"
            "- 广告和营销信息(除非与用户兴趣直接相关)\n"
            "- 与用户学业/技术/工作无关的讨论"
        )

    def render_user_prompt(
        self,
        group_name: str,
        date_str: str,
        messages_text: str,
    ) -> str:
        """渲染 user role 的 prompt（包含实际消息内容）。

        Args:
            group_name: 群名。
            date_str: 日期字符串。
            messages_text: build_llm_context() 的输出。
        """
        template = self._jinja.get_template("daily_summary.j2")
        return template.render(
            group_name=group_name,
            date=date_str,
            messages_text=messages_text,
        )

    # ---- API 调用 ----

    def analyze_group(
        self,
        group_name: str,
        messages_text: str,
        date_str: str = "",
    ) -> LLMCallResult:
        """
        对单个群的消息进行分析。

        内置自适应重试:
            - TokenBudgetExceededError → 增大 max_tokens 重试
            - EmptyResponseError        → 确保 thinking disabled 重试
            - JSON Parse Error     → 降低 temperature 重试

        Args:
            group_name: 群名。
            messages_text: 格式化后的消息文本 (来自 build_llm_context)。
            date_str: 日期字符串 (YYYY-MM-DD)。

        Returns:
            LLMCallResult — 含分析结果、token 用量、耗时。
        """
        import time as _time

        start = _time.time()
        result = LLMCallResult(group_name=group_name)

        system_prompt = self.render_system_prompt()
        user_prompt = self.render_user_prompt(group_name, date_str, messages_text)

        # ---- Prompt 长度保护 ----
        prompt_chars = len(system_prompt) + len(user_prompt)
        if prompt_chars > PROMPT_CHAR_LIMIT:
            logger.warning(
                f"[{group_name}] Prompt 过长 ({prompt_chars} chars, "
                f"≈ {prompt_chars // 4} tokens)，跳过分析"
            )
            result.error = f"Prompt too long: {prompt_chars} chars"
            result.duration_ms = int((_time.time() - start) * 1000)
            return result

        # ---- 自适应重试参数 ----
        current_max_tokens = self.max_tokens
        current_temperature = self.temperature
        thinking_disabled = True  # 默认关闭 thinking

        for attempt in range(self.max_retries + 1):
            # ---- 构建 extra_body ----
            extra_body: dict[str, Any] = {}
            if thinking_disabled:
                extra_body["thinking"] = {"type": "disabled"}

            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=current_temperature,
                    max_tokens=current_max_tokens,
                    response_format={"type": "json_object"},
                    extra_body=extra_body if extra_body else None,
                )
            except Exception as e:
                error_msg = str(e)

                # thinking 参数不支持 → 回退
                if "thinking" in error_msg.lower():
                    logger.info(f"[{group_name}] 模型不支持 thinking 参数，回退普通请求")
                    thinking_disabled = False
                    extra_body = {}
                    try:
                        response = self._client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=current_temperature,
                            max_tokens=current_max_tokens,
                            response_format={"type": "json_object"},
                        )
                    except Exception as e2:
                        result.error = str(e2)
                        result.retry_count = attempt
                        result.duration_ms = int((_time.time() - start) * 1000)
                        return result
                else:
                    # 网络/服务端错误 → 可重试
                    is_retryable = any(
                        kw in error_msg.lower()
                        for kw in (
                            "timeout",
                            "rate",
                            "server",
                            "connection",
                            "503",
                            "502",
                            "429",
                        )
                    )
                    if is_retryable and attempt < self.max_retries:
                        delay = self.retry_delays[attempt]
                        logger.warning(
                            f"[{group_name}] API 错误 (attempt {attempt + 1}): "
                            f"{error_msg[:120]} — {delay}s 后重试"
                        )
                        _time.sleep(delay)
                        continue

                    result.error = error_msg
                    result.retry_count = attempt
                    result.duration_ms = int((_time.time() - start) * 1000)
                    return result

            # ---- 处理响应 ----
            try:
                parsed = self._handle_response(response, group_name)
            except TokenBudgetExceededError:
                self._save_debug_artifacts(
                    attempt,
                    group_name,
                    system_prompt,
                    user_prompt,
                    response.choices[0].message.content or "",
                    "TokenBudgetExceededError",
                )
                if attempt < self.max_retries:
                    current_max_tokens = min(current_max_tokens * 2, 16384)
                    logger.warning(
                        f"[{group_name}] Token budget exceeded "
                        f"(attempt {attempt + 1}), "
                        f"max_tokens → {current_max_tokens} 重试"
                    )
                    continue
                result.error = "Token budget exceeded after all retries"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            except EmptyResponseError:
                self._save_debug_artifacts(
                    attempt,
                    group_name,
                    system_prompt,
                    user_prompt,
                    "",
                    "EmptyResponseError",
                )
                if attempt < self.max_retries:
                    # 确保 thinking 已关闭
                    if not thinking_disabled:
                        thinking_disabled = True
                        logger.warning(
                            f"[{group_name}] Empty response "
                            f"(attempt {attempt + 1}), disabling thinking 重试"
                        )
                    else:
                        current_max_tokens = min(current_max_tokens * 2, 16384)
                        logger.warning(
                            f"[{group_name}] Empty response "
                            f"(attempt {attempt + 1}), "
                            f"max_tokens → {current_max_tokens} 重试"
                        )
                    continue
                result.error = "Empty response after all retries"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            except LLMError as e:
                self._save_debug_artifacts(
                    attempt,
                    group_name,
                    system_prompt,
                    user_prompt,
                    response.choices[0].message.content or "",
                    str(e),
                )
                if e.retryable and attempt < self.max_retries:
                    current_temperature = max(0.0, current_temperature - 0.15)
                    logger.warning(
                        f"[{group_name}] JSON 解析失败 "
                        f"(attempt {attempt + 1}), "
                        f"temperature → {current_temperature} 重试"
                    )
                    continue
                result.error = f"重试 {self.max_retries} 次后仍然失败: {e}"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            # ---- 成功 ----
            result.raw_response = response.choices[0].message.content or ""
            result.analysis = GroupAnalysis(**parsed)
            result.success = True
            result.retry_count = attempt
            result.duration_ms = int((_time.time() - start) * 1000)

            # Token 统计
            if response.usage:
                result.usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
                )
                self.total_prompt_tokens += result.usage.prompt_tokens
                self.total_completion_tokens += result.usage.completion_tokens

            self.total_successful_calls += 1

            finish = response.choices[0].finish_reason or "unknown"
            logger.info(
                f"[{group_name}] LLM 完成 — "
                f"model={self.model} "
                f"prompt={result.usage.prompt_tokens} "
                f"completion={result.usage.completion_tokens} "
                f"finish={finish} "
                f"duration={result.duration_ms}ms"
            )
            return result

        # ---- 所有重试耗尽 (不应可达: 最后一次 iteration 的 except 分支均直接 return) ----
        raise AssertionError(f"Unreachable: all retries exhausted for [{group_name}]")

    # ---- 响应处理 ----

    def _handle_response(self, response: Any, group_name: str = "") -> dict[str, Any]:
        """
        处理 LLM 原始响应: finish_reason 检测 → content 提取 → JSON 解析。

        Returns:
            Parsed JSON dict from LLM response.

        Raises:
            TokenBudgetExceededError: finish_reason == 'length'
            EmptyResponseError: content 为空或 choices 列表为空
            LLMError: JSON 解析失败
        """
        if not response.choices:
            raise EmptyResponseError(f"[{group_name}] API returned empty choices list")

        finish = response.choices[0].finish_reason or "unknown"

        if finish == "length":
            raise TokenBudgetExceededError(
                f"[{group_name}] Output truncated — finish_reason=length"
            )

        raw = response.choices[0].message.content or ""

        if not raw or not raw.strip():
            raise EmptyResponseError(f"[{group_name}] Empty content (finish={finish})")

        json_str = self._extract_json(raw)

        import json as _json

        try:
            return _json.loads(json_str)  # type: ignore[no-any-return]
        except _json.JSONDecodeError as e:
            raise LLMError(
                f"[{group_name}] JSON decode failed: {e}\nRaw (first 200): {raw[:200]}",
                retryable=True,
            ) from e

    # ---- JSON 提取器 ----

    @staticmethod
    def _extract_json(text: str) -> str:
        """
        从 LLM 原始输出中提取 JSON 字符串。

        处理顺序:
            1. 剥离前后空白
            2. 移除 Markdown fence (```json ... ``` 或 ``` ... ```)
            3. 跳过前置解释文字 (定位第一个 '{')

        Known Limitation:
            使用简单的花括号计数定位 JSON 边界；假设 JSON 字符串值内部
            不包含影响 brace matching 的未转义花括号。此假设在 LLM +
            json_object 模式下始终成立。如需完整实现，可替换为字符级 parser。

        Raises:
            LLMError: 无法提取 JSON 结构。
        """
        text = text.strip()

        if not text:
            raise EmptyResponseError("Empty content after strip")

        # 1. 移除 Markdown fence
        if text.startswith("```"):
            # 找到第一行换行后的内容
            newline_idx = text.find("\n")
            if newline_idx != -1:
                text = text[newline_idx + 1 :]
            # 移除末尾的 ```
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        # 2. 定位 JSON 对象
        brace_start = text.find("{")
        if brace_start == -1:
            raise LLMError(
                f"No JSON object found in response. First 200 chars: {text[:200]}",
                retryable=True,
            )

        # 3. 找到匹配的 }
        depth = 0
        for i in range(brace_start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start : i + 1]

        raise LLMError(
            "Unterminated JSON object — missing closing brace",
            retryable=True,
        )

    # ---- Debug Artifacts ----

    def _save_debug_artifacts(
        self,
        attempt: int,
        group_name: str,
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        error: str,
    ) -> None:
        """LLM 调用失败时，自动保存 prompt 和 response 到 data/logs/。"""
        import contextlib
        from datetime import datetime as _datetime
        from pathlib import Path as _Path

        log_dir = _Path("data") / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return  # 无法创建目录则跳过

        ts = _datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_group = "".join(c if c.isalnum() or c in "_-" else "_" for c in group_name)[:30]

        # 保存 prompt
        prompt_file = log_dir / f"debug_prompt_{safe_group}_{ts}_a{attempt + 1}.txt"
        with contextlib.suppress(Exception):
            prompt_file.write_text(
                f"=== SYSTEM ===\n{system_prompt}\n\n=== USER ===\n{user_prompt}",
                encoding="utf-8",
            )

        # 保存 response
        resp_file = log_dir / f"debug_response_{safe_group}_{ts}_a{attempt + 1}.txt"
        with contextlib.suppress(Exception):
            resp_file.write_text(
                f"=== ERROR: {error} ===\n\n{raw_response}",
                encoding="utf-8",
            )

        logger.info(f"[{group_name}] Debug artifacts saved → {prompt_file.name}, {resp_file.name}")

    def analyze_groups(
        self,
        contexts: dict[str, str],
        date_str: str = "",
    ) -> list[LLMCallResult]:
        """
        对多个群的消息进行顺序分析。

        Args:
            contexts: {group_name: messages_text} 字典。
            date_str: 日期字符串。

        Returns:
            LLMCallResult 列表（包含成功和失败）。
        """
        results: list[LLMCallResult] = []
        for group_name, text in contexts.items():
            result = self.analyze_group(group_name, text, date_str)
            results.append(result)
        return results

    # ================================================================
    # Chat Analysis (Chat Analyzer V2 — 联系人聊天分析)
    # 与 analyze_group() 完全独立。不修改任何日报逻辑。
    # ================================================================

    def render_chat_system_prompt(self) -> str:
        """渲染 chat analysis system role prompt（不含消息内容，可被 API cache）。"""
        return (
            "你是一个专业的个人聊天记录分析助手。"
            "你的任务是分析微信对话记录中的沟通模式、主要话题、情感基调与人际关系。"
            "你必须严格按照 JSON 格式输出结果。"
        )

    def render_chat_user_prompt(
        self,
        contact_name: str,
        messages_text: str,
    ) -> str:
        """渲染 chat analysis user role prompt（包含实际聊天内容）。"""
        template = self._jinja.get_template("chat_analysis.j2")
        return template.render(
            contact_name=contact_name,
            messages_text=messages_text,
        )

    def analyze_chat(
        self,
        contact_name: str,
        messages_text: str,
    ) -> ChatAnalysisResult:
        """
        对单个联系人的聊天记录进行分析。

        内置自适应重试 (与 analyze_group 相同策略):
            - TokenBudgetExceededError → 增大 max_tokens 重试
            - EmptyResponseError        → 确保 thinking disabled 重试
            - JSON Parse Error     → 降低 temperature 重试

        Args:
            contact_name: 联系人名称。
            messages_text: 格式化后的聊天记录文本。

        Returns:
            ChatAnalysisResult — 含分析结果、token 用量、耗时。
        """
        import time as _time

        start = _time.time()
        result = ChatAnalysisResult(contact_name=contact_name)

        system_prompt = self.render_chat_system_prompt()
        user_prompt = self.render_chat_user_prompt(contact_name, messages_text)

        # ---- Prompt 长度保护 ----
        prompt_chars = len(system_prompt) + len(user_prompt)
        if prompt_chars > PROMPT_CHAR_LIMIT:
            logger.warning(
                f"[{contact_name}] Prompt 过长 ({prompt_chars} chars, "
                f"≈ {prompt_chars // 4} tokens)，跳过分析"
            )
            result.error = f"Prompt too long: {prompt_chars} chars"
            result.duration_ms = int((_time.time() - start) * 1000)
            return result

        # ---- 自适应重试参数 ----
        current_max_tokens = self.max_tokens
        current_temperature = self.temperature
        thinking_disabled = True  # 默认关闭 thinking

        for attempt in range(self.max_retries + 1):
            # ---- 构建 extra_body ----
            extra_body: dict[str, Any] = {}
            if thinking_disabled:
                extra_body["thinking"] = {"type": "disabled"}

            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=current_temperature,
                    max_tokens=current_max_tokens,
                    response_format={"type": "json_object"},
                    extra_body=extra_body if extra_body else None,
                )
            except Exception as e:
                error_msg = str(e)

                # thinking 参数不支持 → 回退
                if "thinking" in error_msg.lower():
                    logger.info(f"[{contact_name}] 模型不支持 thinking 参数，回退普通请求")
                    thinking_disabled = False
                    extra_body = {}
                    try:
                        response = self._client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=current_temperature,
                            max_tokens=current_max_tokens,
                            response_format={"type": "json_object"},
                        )
                    except Exception as e2:
                        result.error = str(e2)
                        result.retry_count = attempt
                        result.duration_ms = int((_time.time() - start) * 1000)
                        return result
                else:
                    # 网络/服务端错误 → 可重试
                    is_retryable = any(
                        kw in error_msg.lower()
                        for kw in (
                            "timeout",
                            "rate",
                            "server",
                            "connection",
                            "503",
                            "502",
                            "429",
                        )
                    )
                    if is_retryable and attempt < self.max_retries:
                        delay = self.retry_delays[attempt]
                        logger.warning(
                            f"[{contact_name}] API 错误 (attempt {attempt + 1}): "
                            f"{error_msg[:120]} — {delay}s 后重试"
                        )
                        _time.sleep(delay)
                        continue

                    result.error = error_msg
                    result.retry_count = attempt
                    result.duration_ms = int((_time.time() - start) * 1000)
                    return result

            # ---- 处理响应 ----
            try:
                parsed = self._handle_response(response, contact_name)
            except TokenBudgetExceededError:
                self._save_debug_artifacts(
                    attempt,
                    contact_name,
                    system_prompt,
                    user_prompt,
                    response.choices[0].message.content or "",
                    "TokenBudgetExceededError",
                )
                if attempt < self.max_retries:
                    current_max_tokens = min(current_max_tokens * 2, 16384)
                    logger.warning(
                        f"[{contact_name}] Token budget exceeded "
                        f"(attempt {attempt + 1}), "
                        f"max_tokens → {current_max_tokens} 重试"
                    )
                    continue
                result.error = "Token budget exceeded after all retries"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            except EmptyResponseError:
                self._save_debug_artifacts(
                    attempt,
                    contact_name,
                    system_prompt,
                    user_prompt,
                    "",
                    "EmptyResponseError",
                )
                if attempt < self.max_retries:
                    # 确保 thinking 已关闭
                    if not thinking_disabled:
                        thinking_disabled = True
                        logger.warning(
                            f"[{contact_name}] Empty response "
                            f"(attempt {attempt + 1}), disabling thinking 重试"
                        )
                    else:
                        current_max_tokens = min(current_max_tokens * 2, 16384)
                        logger.warning(
                            f"[{contact_name}] Empty response "
                            f"(attempt {attempt + 1}), "
                            f"max_tokens → {current_max_tokens} 重试"
                        )
                    continue
                result.error = "Empty response after all retries"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            except LLMError as e:
                self._save_debug_artifacts(
                    attempt,
                    contact_name,
                    system_prompt,
                    user_prompt,
                    response.choices[0].message.content or "",
                    str(e),
                )
                if e.retryable and attempt < self.max_retries:
                    current_temperature = max(0.0, current_temperature - 0.15)
                    logger.warning(
                        f"[{contact_name}] JSON 解析失败 "
                        f"(attempt {attempt + 1}), "
                        f"temperature → {current_temperature} 重试"
                    )
                    continue
                result.error = f"重试 {self.max_retries} 次后仍然失败: {e}"
                result.retry_count = attempt
                result.duration_ms = int((_time.time() - start) * 1000)
                return result

            # ---- 成功 ----
            result.raw_response = response.choices[0].message.content or ""
            result.analysis = ChatAnalysis(**parsed)
            result.success = True
            result.retry_count = attempt
            result.duration_ms = int((_time.time() - start) * 1000)

            # Token 统计
            if response.usage:
                result.usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
                )
                self.total_prompt_tokens += result.usage.prompt_tokens
                self.total_completion_tokens += result.usage.completion_tokens

            self.total_successful_calls += 1

            finish = response.choices[0].finish_reason or "unknown"
            logger.info(
                f"[{contact_name}] Chat 分析完成 — "
                f"model={self.model} "
                f"prompt={result.usage.prompt_tokens} "
                f"completion={result.usage.completion_tokens} "
                f"finish={finish} "
                f"duration={result.duration_ms}ms"
            )
            return result

        # ---- 所有重试耗尽 (不应可达) ----
        raise AssertionError(f"Unreachable: all retries exhausted for [{contact_name}]")

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def reset_stats(self) -> None:
        """重置累计统计。"""
        self.total_successful_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
