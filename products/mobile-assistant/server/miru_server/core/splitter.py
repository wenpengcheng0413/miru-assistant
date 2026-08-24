"""句级分块器：把 LLM 的 token 流切成适合 TTS 的句子。

规则（详见 docs/02 §4）：
- 遇边界符 。！？；… 或换行，且缓冲 ≥ min_len → 出句
- 首句早吐：≥ first_min 即可出句（压低"开始说话"延迟）
- 缓冲 ≥ max_len 无边界 → 按最后一个逗号/空格硬切
- 英文句点 "." 不是边界符（防切碎 URL/小数）
"""
from __future__ import annotations

BOUNDARIES = "。！？；…"


class SentenceSplitter:
    def __init__(self, min_len: int = 8, max_len: int = 60, first_min: int = 6):
        self.min_len = min_len
        self.max_len = max_len
        self.first_min = first_min
        self._buf: list[str] = []
        self._emitted = 0  # 已出句数（首句用 first_min）

    def feed(self, text: str) -> list[str]:
        """输入文本增量，返回完整句子列表。"""
        if not text:
            return []
        self._buf.append(text)
        return self._split()

    def flush(self, force: bool = False) -> list[str]:
        """冲刷残余缓冲。force=False 且缓冲 < min_len 时保留缓冲（供周期冲刷用）。"""
        buf = "".join(self._buf)
        stripped = buf.strip()
        if not stripped:
            self._buf = []
            return []
        if not force and len(stripped) < self.min_len:
            return []  # 太短，留着等下轮
        self._buf = []
        self._emitted += 1
        return [stripped]

    def pending(self) -> str:
        return "".join(self._buf)

    def _split(self) -> list[str]:
        out: list[str] = []
        buf = "".join(self._buf)

        while True:
            min_len = self.first_min if self._emitted == 0 else self.min_len
            cut = self._find_cut(buf, min_len)
            if cut is None:
                break
            sentence = buf[:cut].strip()
            if sentence:
                out.append(sentence)
                self._emitted += 1
            buf = buf[cut:]
        self._buf = [buf]
        return out

    def _find_cut(self, buf: str, min_len: int) -> int | None:
        if len(buf) >= self.max_len:
            # 硬切：优先最后一个逗号/空格（在 max_len 附近），否则 max_len
            window = buf[: self.max_len + 1]
            for i in range(len(window) - 1, max(min_len, self.max_len // 2), -1):
                if window[i] in "，, 、 ":
                    return i + 1
            return self.max_len
        for i, ch in enumerate(buf):
            if ch in BOUNDARIES or ch == "\n":
                if i + 1 >= min_len:
                    return i + 1
        return None
