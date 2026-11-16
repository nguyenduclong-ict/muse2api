"""Bearer API Key authentication dependency for /v1/* endpoints."""
from __future__ import annotations

import secrets
from fastapi import Depends, Header, HTTPException, Request

from db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_v1_api_key(
    authorization: str | None = Header(default=None),
    db: Database = Depends(get_db),
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Missing Bearer API key", "type": "invalid_request_error", "code": "invalid_api_key"}},
        )
    token = authorization.split(" ", 1)[1].strip()
    expected = db.get_api_key().get("raw_key", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}},
        )
    return token
