"""Separate upload credentials from the existing single-owner read/admin token."""
import asyncio
import hashlib
import hmac
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from ..finance.schema import Snapshot
from ..finance.store import FinanceError, FinanceStore
from .deps import verify_rest_token

router = APIRouter(prefix="/api/finance", dependencies=[Depends(verify_rest_token)])
sync_router = APIRouter(prefix="/api/finance/sync")
MAX_BYTES = 16 * 1024 * 1024


def store(request):
    return FinanceStore(request.app.state.services.db)


async def call(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except FinanceError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code}) from None


async def limited_body(request, limit=MAX_BYTES):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, detail={"code": "snapshot_too_large"})
    return bytes(body)


async def upload_token(request):
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    await call(store(request).authenticate, token)
    return token


@router.post("/pairing")
async def pairing(request: Request):
    return await call(store(request).pairing)


@router.post("/revoke")
async def revoke(request: Request):
    return await call(store(request).revoke)


@sync_router.post("/pair")
async def pair(request: Request):
    # 192-bit one-time secret, not a guessable short PIN. Never placed in URLs/logs.
    body = await limited_body(request, 1024)
    try:
        import json
        code = json.loads(body)["code"]
        if not isinstance(code, str) or len(code) > 100:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, detail={"code": "invalid_pairing_request"}) from None
    return await call(store(request).redeem, code)


@sync_router.get("/status")
async def sync_status(request: Request):
    await upload_token(request)
    return await call(store(request).status)


@sync_router.post("/snapshot")
async def snapshot(request: Request):
    token = await upload_token(request)
    body = await limited_body(request)
    checksum = request.headers.get("X-Content-SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum) or not hmac.compare_digest(hashlib.sha256(body).hexdigest(), checksum):
        raise HTTPException(400, detail={"code": "checksum_mismatch"})
    try:
        incoming = await asyncio.to_thread(Snapshot.model_validate_json, body)
    except ValidationError:
        # Pydantic's default errors may echo private transaction input.
        raise HTTPException(422, detail={"code": "invalid_snapshot"}) from None
    return await call(store(request).publish, incoming, token)


@router.get("/status")
async def status(request: Request):
    return await call(store(request).status)


@router.post("/reconciliation/{snapshot_id}/approve")
async def approve_reconciliation(request: Request, snapshot_id: str):
    return await call(store(request).approve_reconciliation, snapshot_id)


@router.get("/catalogs")
async def catalogs(request: Request):
    return await call(store(request).catalogs)


@router.get("/summary")
async def summary(request: Request, start: str | None = None, end: str | None = None,
                  wallet_id: str | None = None, category_id: str | None = None):
    return await call(store(request).summary, start=start, end=end, wallet_id=wallet_id, category_id=category_id)


@router.get("/transactions")
async def transactions(request: Request, cursor: str | None = None, limit: int = 30,
                       start: str | None = None, end: str | None = None, query: str = "",
                       wallet_id: str | None = None, category_id: str | None = None,
                       classification: str | None = None):
    return await call(store(request).transactions, cursor=cursor, limit=limit, start=start, end=end,
                      query=query, wallet_id=wallet_id, category_id=category_id, classification=classification)


@router.get("/transactions/{entry_id}")
async def transaction(request: Request, entry_id: str):
    return await call(store(request).transaction, entry_id)
