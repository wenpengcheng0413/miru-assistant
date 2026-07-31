"""Miru Assistant — 消息采集层。

包含:
    diagnostics       — 微信环境诊断 (Task 5A)
    wechat_db_decrypt — 微信数据库解密 (Task 5B)
    wechat_reader     — 微信消息读取 (Task 5C)
"""

from miru.collector.diagnostics import DiagnosticReport, run_full_diagnostics
from miru.collector.wechat_db_decrypt import (
    DecryptResult,
    ExtractedKey,
    decrypt_and_open,
    extract_keys_from_process,
    inspect_schema,
    try_decrypt_wechat_db,
    verify_decryption_key,
)
from miru.collector.wechat_reader import (
    WeChatDBReader,
    WeChatGroup,
    WeChatMessage,
    list_groups,
    read_recent_messages,
)

__all__ = [
    # Diagnostics (5A)
    "DiagnosticReport",
    "run_full_diagnostics",
    # Decryption (5B)
    "DecryptResult",
    "ExtractedKey",
    "extract_keys_from_process",
    "verify_decryption_key",
    "decrypt_and_open",
    "inspect_schema",
    "try_decrypt_wechat_db",
    # Reader (5C)
    "WeChatDBReader",
    "WeChatGroup",
    "WeChatMessage",
    "list_groups",
    "read_recent_messages",
]
