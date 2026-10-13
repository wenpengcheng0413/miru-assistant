import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from miru_server.finance.schema import Snapshot
from miru_server.finance.store import FinanceError, FinanceStore
from miru_server.finance.models import FinancePairing
from miru_server.main import create_app


def ledger(snapshot_id="first", base=0):
    return {"protocol": 1, "schema_version": 46, "snapshot_id": snapshot_id, "base_revision": base,
            "app_version": "5.4.3+416", "generated_at": "2026-10-13T12:00:00+08:00", "timezone": "Asia/Shanghai",
            "wallets": [{"id": "w", "name": "钱包", "currency": "CNY", "decimals": 2},
                        {"id": "usd", "name": "外币", "currency": "USD", "decimals": 2}],
            "categories": [{"id": "food", "name": "餐饮"}, {"id": "0", "name": "余额调整"}],
            "budgets": [], "objectives": [], "transactions": [entry("one", "-0.10"), entry("two", "-0.20")]}


def entry(entry_id, amount="-10.00", **kwargs):
    return {"id": entry_id, "title": "午饭", "note": "", "amount": amount,
            "occurred_at": "2020-10-12T12:00:00+08:00", "local_date": "2020-10-12",
            "income": False, "paid": True, "skipped": False,
            "wallet_id": "w", "category_id": "food", **kwargs}


@pytest.fixture
def finance(services):
    store = FinanceStore(services.db)
    token = store.redeem(store.pairing()["code"])["token"]
    return store, token


def publish(store, token, data):
    return store.publish(Snapshot.model_validate(data), token)


def test_pairing_expiry_single_use_rotation_and_revoke(finance):
    store, token = finance
    code = store.pairing()["code"]
    new = store.redeem(code)["token"]
    for value in (code, "wrong"):
        with pytest.raises(FinanceError):
            store.redeem(value)
    with pytest.raises(FinanceError):
        store.authenticate(token)
    store.authenticate(new)
    store.revoke()
    with pytest.raises(FinanceError):
        store.authenticate(new)
    expired = store.pairing()["code"]
    with store.db() as session, session.begin():
        for pair in session.query(FinancePairing).all():
            pair.expires_at = 0
    with pytest.raises(FinanceError, match="expired"):
        store.redeem(expired)


def test_snapshot_idempotence_modifications_deletions_and_stale_upload(finance):
    store, token = finance
    first = ledger()
    publish(store, token, first)
    assert publish(store, token, first)["duplicate"]
    second = ledger("second", 1)
    second["transactions"] = [entry("one", "-25.30", title="改过的午饭")]
    publish(store, token, second)
    assert store.transactions()["total"] == 1
    assert store.transaction("one")["item"]["amount"] == "-25.30"
    assert publish(store, token, first)["revision"] == 1
    assert store.status()["revision"] == 2
    with pytest.raises(FinanceError, match="revision_conflict"):
        publish(store, token, ledger("late", 0))
    first["transactions"][0]["amount"] = "-100"
    with pytest.raises(FinanceError, match="snapshot_id_reused"):
        publish(store, token, first)


def test_empty_and_restored_backup_require_exact_admin_reconciliation(finance):
    store, token = finance
    publish(store, token, ledger())
    changed = ledger("empty", 1)
    changed["transactions"] = []
    with pytest.raises(FinanceError, match="reconciliation_required"):
        publish(store, token, changed)
    assert store.status()["transaction_count"] == 2
    with pytest.raises(FinanceError, match="reconciliation_changed"):
        store.approve_reconciliation("wrong")
    store.approve_reconciliation("empty")
    assert store.status()["transaction_count"] == 0
    restored = ledger("restored", 2)
    restored["restored_backup"] = True
    with pytest.raises(FinanceError, match="reconciliation_required"):
        publish(store, token, restored)


def test_exact_decimal_currency_and_special_types(finance):
    store, token = finance
    data = ledger()
    data["transactions"] += [entry("pay", "1000", income=True), entry("dollar", "-2", wallet_id="usd"),
        entry("move", "-100", paired_id="other"), entry("adjust", "500", category_id="0", income=True),
        entry("loan", "-50", kind="credit"), entry("pending", "-20", paid=False), entry("skip", "-3", skipped=True)]
    publish(store, token, data)
    result = store.summary(start="2020-10-12", end="2020-10-13")
    assert result["currencies"]["CNY"]["expense"] == "0.30"
    assert result["currencies"]["CNY"]["balance"] == "999.70"
    assert result["currencies"]["USD"]["expense"] == "2"
    assert result["excluded"] == {"transfer": 1, "adjustment": 1, "loan": 1, "pending": 1, "skipped": 1}
    assert store.summary(start="2020-10-11", end="2020-10-12")["matched_count"] == 0
    assert store.transactions(classification="pending")["total"] == 1


def test_pagination_is_complete_and_rejects_changed_snapshot_and_filters(finance):
    store, token = finance
    data = ledger()
    data["transactions"] = [entry(str(i)) for i in range(137)]
    publish(store, token, data)
    page = store.transactions(limit=30)
    first_cursor = page["next_cursor"]
    ids = [e["id"] for e in page["items"]]
    while page["next_cursor"]:
        page = store.transactions(cursor=page["next_cursor"], limit=30)
        ids.extend(e["id"] for e in page["items"])
    assert len(ids) == len(set(ids)) == 137
    with pytest.raises(FinanceError, match="invalid_cursor"):
        store.transactions(cursor=first_cursor, query="different")
    data.update(snapshot_id="second", base_revision=1)
    publish(store, token, data)
    with pytest.raises(FinanceError, match="snapshot_changed"):
        store.transactions(cursor=first_cursor)


@pytest.mark.parametrize("change", ["duplicate", "reference", "nan", "precision", "timezone", "schema"])
def test_invalid_snapshot_cannot_replace_valid_data(finance, change):
    store, token = finance
    publish(store, token, ledger())
    data = ledger("invalid", 1)
    if change == "duplicate": data["transactions"].append(copy.deepcopy(data["transactions"][0]))
    if change == "reference": data["transactions"][0]["wallet_id"] = "missing"
    if change == "nan": data["transactions"][0]["amount"] = "NaN"
    if change == "precision": data["transactions"][0]["amount"] = "0.123"
    if change == "timezone": data["transactions"][0]["occurred_at"] = "2020-10-12T12:00:00"
    if change == "schema": data["schema_version"] = 47
    with pytest.raises(ValueError): publish(store, token, data)
    assert store.status()["revision"] == 1


def test_api_auth_checksum_privacy_and_query(app_config):
    app_config.server.advertise_lan = False
    app_config.backup.enabled = False
    with TestClient(create_app(app_config)) as client:
        admin = {"Authorization": "Bearer test-token"}
        assert client.get("/api/finance/status").status_code == 401
        code = client.post("/api/finance/pairing", headers=admin).json()["code"]
        token = client.post("/api/finance/sync/pair", json={"code": code}).json()["token"]
        upload = {"Authorization": "Bearer " + token}
        assert client.get("/api/finance/status", headers=upload).status_code == 401
        body = json.dumps(ledger()).encode()
        assert client.post("/api/finance/sync/snapshot", content=body, headers=upload).status_code == 400
        upload["X-Content-SHA256"] = hashlib.sha256(body).hexdigest()
        response = client.post("/api/finance/sync/snapshot", content=body, headers=upload)
        assert response.status_code == 200, response.text
        assert client.get("/api/finance/transactions", headers=admin).json()["total"] == 2
        assert client.post("/api/finance/reconciliation/no/approve", headers=upload).status_code == 401
        private = b'{"private-note":"do not echo me"}'
        upload["X-Content-SHA256"] = hashlib.sha256(private).hexdigest()
        response = client.post("/api/finance/sync/snapshot", content=private, headers=upload)
        assert response.status_code == 422
        assert "do not echo" not in response.text


def test_no_sync_is_not_zero(finance):
    store, _ = finance
    assert store.status()["transaction_count"] is None
    with pytest.raises(FinanceError, match="not_synced"):
        store.summary()


def test_concurrent_publish_accepts_one_revision_only(finance):
    store, token = finance
    def send(i):
        try:
            return publish(store, token, ledger(str(i)))['revision']
        except FinanceError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(4)))
    assert results.count(1) == 1
    assert results.count('revision_conflict') == 3
    assert store.status()['transaction_count'] == 2


async def test_finance_tools_registered_and_return_valid_bounded_json(services, finance):
    from miru_server.tools.builtin.finance import FinanceTransactionsTool, FinanceSummaryTool, FINANCE_TOOLS
    from miru_server.tools.base import ToolContext
    from miru_server.tools.registry import build_registry
    store, token = finance
    data = ledger()
    data['transactions'] = [entry(str(i), note='私密备注' * 300) for i in range(50)]
    publish(store, token, data)
    result = await FinanceTransactionsTool().run(ToolContext(services, 'test'))
    parsed = json.loads(result.to_llm())
    assert parsed['data']['total'] == 50
    assert parsed['data']['next_cursor']
    assert all(len(x['note_preview']) <= 120 for x in parsed['data']['items'])
    services.config.tools.enabled.extend(t.name for t in FINANCE_TOOLS)
    registry = build_registry(services.config)
    assert all(registry.get(t.name) is not None for t in FINANCE_TOOLS)
