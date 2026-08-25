"""微信离线运行时、诊断和快照管理。

该模块是服务端与仓库内 daily-report ``miru`` 包之间的唯一边界。它不修改
微信原始目录；同步时只复制到 Miru 私有目录，并通过 manifest 标记完整快照。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .db.models import WechatContact, WechatSync, utcnow

logger = logging.getLogger(__name__)


def runtime_build_id() -> str:
    """返回可在手机端显示的服务构建标识，不读取或暴露敏感配置。"""
    configured = os.environ.get("MIRU_BUILD_ID", "").strip()
    if configured:
        return configured
    try:
        root = Path(__file__).resolve().parents[4]
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip() or "dev"
    except Exception:
        return "dev"


def ensure_miru_import_path() -> Path | None:
    """让后台服务和开发命令使用同一份 daily-report 包。"""
    configured = os.environ.get("MIRU_DAILY_REPORT_SRC", "")
    candidates = [Path(configured)] if configured else []
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[3] / "daily-report" / "src",
            here.parents[4] / "products" / "daily-report" / "src",
        ]
    )
    for candidate in candidates:
        if (candidate / "miru").is_dir():
            value = str(candidate)
            if value not in sys.path:
                sys.path.insert(0, value)
            return candidate
    return None


def load_offline_reader():
    ensure_miru_import_path()
    return importlib.import_module("miru.chat_analyzer.offline_reader")


def _configured_root(config) -> str:
    return str(getattr(config.tools.wechat, "data_root", "") or "")


def snapshot_root(config) -> Path:
    return config.resolve(config.tools.wechat.snapshot_dir)


def snapshot_account(config) -> Path | None:
    root = snapshot_root(config)
    account = root / "account"
    return account if (account / "db_storage" / "message").is_dir() else None


def latest_manifest(config) -> dict[str, Any] | None:
    path = snapshot_root(config) / "manifest.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        synced = value.get("synced_at")
        stale = False
        if synced:
            try:
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(str(synced))).total_seconds() / 3600
                stale = age_h > float(config.tools.wechat.snapshot_max_age_hours)
                value["age_hours"] = round(max(0.0, age_h), 1)
            except (TypeError, ValueError):
                stale = True
        value["stale"] = stale
        return value
    except Exception:
        return None


def data_root_for(config, prefer_snapshot: bool = True) -> str:
    if prefer_snapshot and snapshot_account(config) is not None:
        return str(snapshot_account(config))
    return _configured_root(config)


def runtime_diagnostics(config) -> dict[str, Any]:
    source = _configured_root(config)
    package_path = ensure_miru_import_path()
    result: dict[str, Any] = {
        "build_id": runtime_build_id(),
        "package_available": False,
        "package_path": str(package_path) if package_path else "",
        "data_dir": source,
        "account_dir": "",
        "contacts_db_readable": False,
        "message_shards": 0,
        "media_db_readable": False,
        "keys_file": False,
        "stt_available": False,
        "snapshot_available": snapshot_account(config) is not None,
        "snapshot": latest_manifest(config),
        "source": "snapshot" if snapshot_account(config) is not None else "database",
        "error_code": "",
        "error": "",
    }
    try:
        module = load_offline_reader()
        result["package_available"] = True
        db = module.OfflineWeChatDB(data_root_for(config))
        try:
            account = Path(db.account_dir)
            result["account_dir"] = str(account)
            result["data_dir"] = str(account)
            result["keys_file"] = (account / "all_keys.json").exists()
            shards = [account / "db_storage" / f"message/message_{i}.db" for i in range(6)]
            result["message_shards"] = sum(p.exists() for p in shards)
            result["media_db_readable"] = (account / "db_storage/message/media_0.db").exists()
            try:
                result["contacts_db_readable"] = bool(db.get_contacts() is not None)
            except Exception as exc:
                result["error_code"] = "contacts_db_unreadable"
                result["error"] = f"联系人数据库不可读: {exc}"
        finally:
            db.close()
    except ImportError as exc:
        result["error_code"] = "dependency_missing"
        result["error"] = str(exc)
    except FileNotFoundError as exc:
        result["error_code"] = "data_missing"
        result["error"] = str(exc)
    except PermissionError as exc:
        result["error_code"] = "permission_denied"
        result["error"] = str(exc)
    except Exception as exc:
        result["error_code"] = "reader_error"
        result["error"] = str(exc)
    try:
        engine = str(config.stt.engine).lower()
        result["stt_available"] = engine != "none" and (
            importlib.util.find_spec("sherpa_onnx") is not None
            or importlib.util.find_spec("faster_whisper") is not None
        )
    except Exception:
        result["stt_available"] = False
    return result


def _copy_tree(source: Path, target: Path, copy_media: bool) -> int:
    count = 0
    for src in source.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(source)
        if not copy_media and "media" in rel.parts:
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
    return count


def sync_snapshot(config, session_factory) -> dict[str, Any]:
    """复制一次微信账号目录并建立联系人索引。"""
    module = load_offline_reader()
    source_db = module.OfflineWeChatDB(_configured_root(config))
    source = Path(source_db.account_dir)
    root = snapshot_root(config)
    root.parent.mkdir(parents=True, exist_ok=True)
    sync_id: int | None = None
    with session_factory() as db:
        row = WechatSync(snapshot_dir=str(root), source_dir=str(source), status="running")
        db.add(row)
        db.commit()
        db.refresh(row)
        sync_id = row.id
    tmp = Path(tempfile.mkdtemp(prefix=f"{root.name}.", dir=str(root.parent)))
    try:
        target = tmp / "account"
        count = _copy_tree(source, target, bool(config.tools.wechat.sync_copy_media))
        contacts = source_db.get_contacts()
        manifest = {
            "status": "completed",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source_dir": str(source),
            "wx_version": str((source / "version.json").read_text(encoding="utf-8") if (source / "version.json").exists() else ""),
            "file_count": count,
            "contact_count": len(contacts),
            "message_shard_count": sum((target / "db_storage" / f"message/message_{i}.db").exists() for i in range(6)),
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if root.exists():
            shutil.rmtree(root)
        os.replace(tmp, root)
        with session_factory() as db:
            row = db.get(WechatSync, sync_id)
            if row:
                row.status = "completed"
                row.file_count = count
                row.contact_count = len(contacts)
                row.message_shard_count = int(manifest["message_shard_count"])
                row.wx_version = str(manifest["wx_version"])
                row.finished_at = utcnow()
                db.query(WechatContact).delete()
                for c in contacts:
                    username = str(c.get("username") or "")
                    if not username:
                        continue
                    db.add(WechatContact(
                        username=username,
                        display_name=str(c.get("display_name") or ""),
                        nickname=str(c.get("nickname") or ""),
                        remark=str(c.get("remark") or ""),
                        is_group=int(username.endswith("@chatroom")),
                        sync_id=sync_id,
                    ))
                db.commit()
        return manifest | {"sync_id": sync_id, "snapshot_dir": str(root)}
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        with session_factory() as db:
            row = db.get(WechatSync, sync_id)
            if row:
                row.status = "failed"
                row.error = str(exc)
                row.finished_at = utcnow()
                db.commit()
        raise
    finally:
        source_db.close()


def sync_status(config, session_factory) -> dict[str, Any]:
    manifest = latest_manifest(config)
    with session_factory() as db:
        row = db.scalars(select(WechatSync).order_by(WechatSync.id.desc())).first()
        latest = None
        if row:
            latest = {
                "id": row.id, "status": row.status, "source_dir": row.source_dir,
                "snapshot_dir": row.snapshot_dir, "file_count": row.file_count,
                "contact_count": row.contact_count, "message_shard_count": row.message_shard_count,
                "error": row.error, "started_at": row.started_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
    return {"available": bool(manifest), "manifest": manifest, "latest": latest}
