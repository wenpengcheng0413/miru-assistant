"""
Miru Assistant — Chat Analyzer 联系人白名单 (自动化增强)。

从 config/contacts.yaml 加载用户关心的联系人映射，
提供离线、可靠的名称 → 微信号解析。

当 contact.db 解密失败时（微信版本变化等），
Name2Id fallback 只能提供 username 无法提供昵称。
白名单通过用户预配置解决此问题:
    - name: 显示名（用于输出目录）
    - username: 微信号或微信 ID（最可靠）
    - remark: 备注名（可选）

用法:
    aliases = load_contact_aliases("config/contacts.yaml")
    alias = resolve_via_aliases(aliases, "Krista")
"""

from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class ContactAlias:
    """白名单中的单个联系人映射。"""

    name: str  # 显示名 / 输出目录名
    username: str = ""  # 微信号或微信 ID
    remark: str = ""  # 备注名
    wxid: str = ""  # 微信内部 ID（离线全量导出匹配依据，最可靠）


def load_contact_aliases(
    config_path: str | Path = "config/contacts.yaml",
) -> list[ContactAlias]:
    """
    从 YAML 加载联系人白名单。

    文件不存在或解析失败时返回空列表（不抛异常）。

    Args:
        config_path: contacts.yaml 路径。

    Returns:
        ContactAlias 列表。
    """
    path = Path(config_path)
    if not path.exists():
        logger.debug(f"联系人白名单不存在: {path}（使用数据库解析）")
        return []

    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or not isinstance(raw, dict):
            return []

        aliases: list[ContactAlias] = []
        for item in raw.get("contacts", []) or []:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            aliases.append(
                ContactAlias(
                    name=name,
                    username=(item.get("username") or "").strip(),
                    remark=(item.get("remark") or "").strip(),
                )
            )

        logger.info(f"加载联系人白名单: {len(aliases)} 个联系人")
        return aliases
    except Exception as e:
        logger.warning(f"联系人白名单解析失败: {e}（使用数据库解析）")
        return []


def resolve_via_aliases(
    aliases: list[ContactAlias],
    query: str,
) -> ContactAlias | None:
    """
    在白名单中按名称/微信号/备注匹配。

    匹配规则（大小写不敏感）:
        1. wxid 精确匹配（微信内部 ID，最可靠）
        2. username 精确匹配（微信号/微信 ID）
        3. name 精确匹配（显示名）
        4. remark 精确匹配（备注名）

    Args:
        aliases: 白名单列表。
        query: 用户输入的名称/微信号。

    Returns:
        匹配的 ContactAlias；无匹配返回 None。
    """
    if not aliases or not query:
        return None

    q = query.strip().lower()
    for alias in aliases:
        if alias.wxid and alias.wxid.lower() == q:
            return alias
    for alias in aliases:
        if alias.username and alias.username.lower() == q:
            return alias
    for alias in aliases:
        if alias.name.lower() == q:
            return alias
    for alias in aliases:
        if alias.remark and alias.remark.lower() == q:
            return alias
    return None


def load_contacts_config(config_path: str | Path = "config/settings.yaml") -> list[ContactAlias]:
    """
    从主配置文件加载联系人白名单（settings.yaml → miru.contacts.whitelist）。

    与 load_contact_aliases()（config/contacts.yaml）互补：
    新配置带 wxid（离线全量导出匹配依据），旧配置保持兼容回退。

    Args:
        config_path: settings.yaml 路径。

    Returns:
        ContactAlias 列表（仅启用且 name 非空的条目）。
    """
    from miru.utils.config import load_config

    try:
        cfg = load_config(config_path)
    except Exception as e:
        logger.debug(f"主配置加载失败（使用 contacts.yaml 回退）: {e}")
        return []

    aliases: list[ContactAlias] = []
    for item in cfg.miru.contacts.active_whitelist():
        name = (item.name or "").strip()
        if not name:
            continue
        aliases.append(
            ContactAlias(
                name=name,
                username=item.wxid or "",  # 兼容：无独立 username 字段时用 wxid
                remark="",
                wxid=item.wxid or "",
            )
        )

    if aliases:
        logger.info(f"从 settings.yaml 加载联系人白名单: {len(aliases)} 个联系人")
    return aliases
