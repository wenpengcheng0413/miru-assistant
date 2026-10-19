from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select, text, update

from .models import FinancePairing, FinanceSnapshot, FinanceSource, FinanceReconciliation
from .schema import Snapshot

SOURCE = "cashew"
SHANGHAI = timezone(timedelta(hours=8))
POLICY = "按原币计算已支付收支；排除待支付、跳过、转账、余额调整和借贷；日期按源账单日期。"
LEDGER_COLLECTIONS = ("wallets", "categories", "budgets", "objectives", "transactions")


class FinanceError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FinanceStore:
    def __init__(self, db):
        self.db = db

    def pairing(self):
        code = secrets.token_urlsafe(24)
        expires = int(time.time()) + 600
        with self.db() as session, session.begin():
            session.execute(delete(FinancePairing))
            session.add(FinancePairing(code_hash=digest(code), expires_at=expires))
        return {"code": code, "expires_at": expires}

    def redeem(self, code):
        token = secrets.token_urlsafe(32)
        with self.db() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            pair = session.get(FinancePairing, digest(code))
            if pair is None or pair.expires_at < int(time.time()):
                raise FinanceError("pairing_invalid_or_expired", 401)
            source = session.get(FinanceSource, SOURCE)
            if source is None:
                source = FinanceSource(id=SOURCE)
                session.add(source)
            source.token_hash = digest(token)
            session.execute(delete(FinanceReconciliation))
            session.delete(pair)
            session.commit()
        return {"source_id": SOURCE, "token": token}

    def authenticate(self, token):
        with self.db() as session:
            source = session.get(FinanceSource, SOURCE)
            if not token or source is None or not source.token_hash or not hmac.compare_digest(source.token_hash, digest(token)):
                raise FinanceError("sync_token_invalid", 401)

    def revoke(self):
        with self.db() as session, session.begin():
            session.execute(update(FinanceSource).values(token_hash=""))
            session.execute(delete(FinancePairing))
            session.execute(delete(FinanceReconciliation))
        return {"revoked": True}

    def status(self):
        with self.db() as session:
            session.execute(text("BEGIN"))
            source = session.get(FinanceSource, SOURCE)
            if source is None:
                return {"state": "unpaired", "revision": 0, "transaction_count": None, "synced_at": None}
            snapshot = session.get(FinanceSnapshot, (SOURCE, source.snapshot_id))
            pending = session.get(FinanceReconciliation, SOURCE)
            pending_data = json.loads(pending.payload) if pending else None
            return {"state": "ready" if snapshot else "awaiting_sync", "paired": bool(source.token_hash),
                    "revision": source.revision, "snapshot_id": source.snapshot_id,
                    "synced_at": source.synced_at or None,
                    "transaction_count": len(json.loads(snapshot.payload)["transactions"]) if snapshot else None,
                    "reconciliation": {"snapshot_id": pending_data["snapshot_id"],
                        "transaction_count": len(pending_data["transactions"])} if pending_data else None}

    def approve_reconciliation(self, snapshot_id):
        with self.db() as session:
            pending = session.get(FinanceReconciliation, SOURCE)
            if pending is None:
                raise FinanceError("no_reconciliation", 404)
            incoming = Snapshot.model_validate_json(pending.payload)
            if incoming.snapshot_id != snapshot_id:
                raise FinanceError("reconciliation_changed", 409)
        return self.publish(incoming, "", approve_reconcile=True)

    def publish(self, incoming: Snapshot, token: str, *, approve_reconcile=False):
        payload = canonical(incoming.model_dump(mode="json"))
        checksum = digest(payload)
        with self.db() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            source = session.get(FinanceSource, SOURCE)
            # Re-check inside the publication transaction to serialize revocation and pairing.
            if source is None or not source.token_hash or (not approve_reconcile and not hmac.compare_digest(source.token_hash, digest(token))):
                raise FinanceError("sync_token_invalid", 401)
            if approve_reconcile:
                pending = session.get(FinanceReconciliation, SOURCE)
                if pending is None or digest(pending.payload) != checksum:
                    raise FinanceError("reconciliation_changed", 409)
            prior = session.get(FinanceSnapshot, (SOURCE, incoming.snapshot_id))
            if prior:
                if prior.digest != checksum:
                    raise FinanceError("snapshot_id_reused", 409)
                return {"revision": prior.revision, "snapshot_id": prior.id, "duplicate": True}
            if source.revision != incoming.base_revision:
                raise FinanceError("revision_conflict", 409)
            old = session.get(FinanceSnapshot, (SOURCE, source.snapshot_id))
            if old and not approve_reconcile:
                old_data = json.loads(old.payload)
                old_entries = {x["id"]: x for x in old_data["transactions"]}
                new_ids = {x.id for x in incoming.transactions}
                removed = len(old_entries.keys() - new_ids)
                # Reopening/re-pairing can repeat a restore flag without changing
                # any ledger data. Only a different restored ledger needs review.
                incoming_data = json.loads(payload)
                identical_ledger = all(old_data[key] == incoming_data[key] for key in LEDGER_COLLECTIONS)
                if (incoming.restored_backup and not identical_ledger) or (old_entries and (not new_ids or removed > max(5, len(old_entries) * .25))):
                    session.merge(FinanceReconciliation(source_id=SOURCE, payload=payload))
                    session.commit()
                    raise FinanceError("reconciliation_required", 409)
            now = datetime.now(timezone.utc).isoformat()
            source.revision += 1
            source.snapshot_id = incoming.snapshot_id
            source.synced_at = now
            session.execute(delete(FinanceReconciliation))
            session.add(FinanceSnapshot(source_id=SOURCE, id=incoming.snapshot_id,
                        revision=source.revision, digest=checksum, payload=payload, created_at=now))
            # Retain the previous payload for recovery; older rows remain as idempotency receipts.
            session.execute(update(FinanceSnapshot).where(
                FinanceSnapshot.source_id == SOURCE,
                FinanceSnapshot.revision < source.revision - 1).values(payload=""))
            revision = source.revision
            session.commit()
        return {"revision": revision, "snapshot_id": incoming.snapshot_id, "duplicate": False}

    def _read(self):
        with self.db() as session:
            # One SELECT joins source and active snapshot, avoiding a mixed revision during publication.
            row = session.execute(select(FinanceSource.revision, FinanceSource.synced_at, FinanceSnapshot.payload).join(
                FinanceSnapshot, (FinanceSnapshot.source_id == FinanceSource.id) &
                (FinanceSnapshot.id == FinanceSource.snapshot_id)).where(FinanceSource.id == SOURCE)).first()
            if row is None:
                raise FinanceError("not_synced", 409)
            return row[0], row[1], json.loads(row[2])

    @staticmethod
    def _enrich(data):
        wallets = {x["id"]: x for x in data["wallets"]}
        categories = {x["id"]: x for x in data["categories"]}
        for raw in data["transactions"]:
            entry = {k: v for k, v in raw.items() if k != "raw"}
            wallet = wallets[entry["wallet_id"]]
            entry.update(currency=wallet["currency"], wallet=wallet["name"],
                         category=categories[entry["category_id"]]["name"],
                         subcategory=categories.get(entry["subcategory_id"], {}).get("name"))
            # Cashew ordinary entries default to paid=true AND skipPaid=true.
            # Its payment UI checks paid first; skipPaid only denotes a skipped
            # occurrence for unpaid upcoming/subscription/repetitive entries.
            entry["skipped"] = (entry["skipped"] and not entry["paid"] and
                                entry["kind"] in ("upcoming", "subscription", "repetitive"))
            entry["classification"] = (
                "transfer" if entry["paired_id"] else
                "adjustment" if entry["category_id"] == "0" else
                "loan" if entry["kind"] in ("credit", "debt") else
                "skipped" if entry["skipped"] else
                "pending" if not entry["paid"] else
                "income" if entry["income"] else "expense")
            yield entry

    @staticmethod
    def _filter(entries, start=None, end=None, query="", wallet_id=None, category_id=None, classification=None):
        for value in (start, end):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise FinanceError("invalid_date") from None
        if start and end and start >= end:
            raise FinanceError("invalid_date_range")
        if len(query) > 200:
            raise FinanceError("query_too_long")
        query = query.casefold()
        return [e for e in entries if
                (not start or e["local_date"] >= start) and (not end or e["local_date"] < end) and
                (not wallet_id or e["wallet_id"] == wallet_id) and
                (not category_id or e["category_id"] == category_id or e["subcategory_id"] == category_id) and
                (not classification or e["classification"] == classification) and
                (not query or query in (e["title"] + " " + e["note"] + " " + e["category"]).casefold())]

    def transactions(self, *, cursor=None, limit=30, **filters):
        if not 1 <= limit <= 100:
            raise FinanceError("invalid_limit")
        revision, synced_at, data = self._read()
        rows = self._filter(self._enrich(data), **filters)
        rows.sort(key=lambda e: (e["local_date"], e["occurred_at"], e["id"]), reverse=True)
        offset = 0
        filter_hash = digest(canonical(filters))
        if cursor:
            try:
                if len(cursor) > 1000:
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded["revision"] != revision:
                    raise FinanceError("snapshot_changed", 409)
                if decoded["filter"] != filter_hash:
                    raise ValueError()
                offset = decoded["offset"]
                if type(offset) is not int or offset < 0 or offset > len(rows):
                    raise ValueError()
            except FinanceError:
                raise
            except Exception:
                raise FinanceError("invalid_cursor") from None
        following = offset + limit
        totals = {}
        today = datetime.now(SHANGHAI).date().isoformat()
        for entry in rows:
            kind = entry['classification']
            if kind not in ('income', 'expense') or entry['local_date'] > today:
                continue
            group = totals.setdefault(entry['currency'], {'income': Decimal(0), 'expense': Decimal(0), 'count': 0})
            group[kind] += abs(Decimal(entry['amount']))
            group['count'] += 1
        totals = {currency: {k: str(v) if isinstance(v, Decimal) else v for k, v in group.items()}
                  for currency, group in totals.items()}
        next_cursor = base64.urlsafe_b64encode(canonical({"revision": revision, "filter": filter_hash,
                   "offset": following}).encode()).decode() if following < len(rows) else None
        return {"revision": revision, "synced_at": synced_at, "total": len(rows),
                "actual_totals": totals, "totals_scope": "全部匹配记录，与分页无关；" + POLICY,
                "items": rows[offset:following], "next_cursor": next_cursor}

    def transaction(self, entry_id):
        revision, synced_at, data = self._read()
        entry = next((e for e in self._enrich(data) if e["id"] == entry_id), None)
        if entry is None:
            raise FinanceError("transaction_not_found", 404)
        return {"revision": revision, "synced_at": synced_at, "item": entry}

    def summary(self, *, start=None, end=None, wallet_id=None, category_id=None):
        today = datetime.now(SHANGHAI).date()
        if not start and not end:
            monday = today - timedelta(days=today.weekday())
            start, end = monday.isoformat(), (monday + timedelta(days=7)).isoformat()
        elif not start or not end:
            raise FinanceError("both_dates_required")
        revision, synced_at, data = self._read()
        entries = self._filter(self._enrich(data), start, end, wallet_id=wallet_id, category_id=category_id)
        currencies = {}
        excluded = {}
        for e in entries:
            kind = e["classification"]
            if kind not in ("income", "expense") or e["local_date"] > today.isoformat():
                reason = "future" if e["local_date"] > today.isoformat() else kind
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            group = currencies.setdefault(e["currency"], {"income": Decimal(0), "expense": Decimal(0),
                                         "count": 0, "categories": {}, "days": {}})
            amount = abs(Decimal(e["amount"]))
            group[kind] += amount
            group["count"] += 1
            day = group["days"].setdefault(e["local_date"], {"income": Decimal(0), "expense": Decimal(0)})
            day[kind] += amount
            if kind == "expense":
                category = group["categories"].setdefault(e["category_id"], {"name": e["category"], "amount": Decimal(0)})
                category["amount"] += amount
        for group in currencies.values():
            group["balance"] = group["income"] - group["expense"]
        # Decimal never goes through binary floating point, including JSON encoding.
        currencies = json.loads(json.dumps(currencies, default=lambda d: format(d, "f")))
        return {"revision": revision, "synced_at": synced_at, "start": start, "end_exclusive": end,
                "timezone": "Asia/Shanghai", "as_of": today.isoformat(), "policy": POLICY,
                "classification_version": 2,
                "data_note": "普通已支付账单正常计入。Cashew 的 skipPaid 原始标志不等于用户跳过账单；不能据此推断用户做过批量操作。空汇总仅表示当前筛选无符合口径的记录，不代表账本为空。",
                "currencies": currencies, "excluded": excluded, "matched_count": len(entries)}

    def catalogs(self):
        revision, synced_at, data = self._read()
        return {"revision": revision, "synced_at": synced_at, **{
            key: [{k: v for k, v in item.items() if k != "raw"} for item in data[key]]
            for key in ("wallets", "categories", "budgets", "objectives")}}
