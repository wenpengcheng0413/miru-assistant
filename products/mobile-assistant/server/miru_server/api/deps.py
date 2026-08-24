"""鉴权：REST Bearer token / WS hello token（常数时间比较）。"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request


def check_token(token: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(token or "", expected)


def verify_rest_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    token = auth[len("Bearer "):].strip()
    expected = request.app.state.services.config.server.token
    if not check_token(token, expected):
        raise HTTPException(status_code=401, detail="token 无效")
