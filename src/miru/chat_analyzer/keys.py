"""
Miru Assistant — Chat Analyzer 数据库密钥加载。

从 config/database_keys.yaml 加载微信各数据库分片的 SQLCipher 密钥。
密钥由 scripts/extract_db_keys.py 从微信进程内存自动提取。

用法:
    keys = load_database_keys()
    msg_key = keys.get("message_1.db")
"""

from pathlib import Path

from loguru import logger


def load_database_keys(
    config_path: str | Path = "config/database_keys.yaml",
) -> dict[str, bytes]:
    """
    加载数据库密钥映射 {db_name: raw_key_bytes}。

    文件不存在或解析失败时返回空字典（调用方回退到手动密钥）。

    Args:
        config_path: database_keys.yaml 路径。

    Returns:
        {数据库文件名: 32 字节密钥} 映射。
    """
    path = Path(config_path)
    if not path.exists():
        logger.debug(f"数据库密钥文件不存在: {path}")
        return {}

    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or not isinstance(raw, dict):
            return {}

        keys: dict[str, bytes] = {}
        for name, key_hex in (raw.get("keys") or {}).items():
            if not isinstance(key_hex, str):
                continue
            try:
                raw_key = bytes.fromhex(key_hex.strip())
                if len(raw_key) == 32:
                    keys[name] = raw_key
            except ValueError:
                logger.warning(f"密钥格式错误: {name}")

        logger.info(f"加载数据库密钥: {len(keys)} 个数据库")
        return keys
    except Exception as e:
        logger.warning(f"数据库密钥解析失败: {e}")
        return {}
