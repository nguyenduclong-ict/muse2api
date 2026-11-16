"""Admin routes for Proxy Management."""
from __future__ import annotations

import concurrent.futures
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.cookie_parser import mask_proxy
from services.proxy_utils import check_proxy_ipinfo, parse_proxy_line

router = APIRouter(prefix="/admin", tags=["proxies"])


class ProxyImportReq(BaseModel):
    proxies_text: str


def _serialize_proxy(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "proxy_masked": mask_proxy(p["proxy_url"]),
        "scheme": p["scheme"],
        "status": p["status"],
        "ip": p.get("ip") or "",
        "country": p.get("country") or "",
        "city": p.get("city") or "",
        "org": p.get("org") or "",
        "latency_ms": p.get("latency_ms") or 0,
        "last_checked_at": p.get("last_checked_at") or 0,
        "last_error": p.get("last_error") or "",
        "account_count": p.get("account_count", 0),
        "created_at": p["created_at"],
    }


@router.get("/proxies")
def list_proxies(request: Request):
    db = request.app.state.db
    return {"proxies": [_serialize_proxy(p) for p in db.list_proxies()]}


@router.post("/proxies/import", status_code=201)
def import_proxies(body: ProxyImportReq, request: Request):
    db = request.app.state.db
    imported = 0
    skipped = 0
    errors: list[str] = []
    for raw_line in body.proxies_text.splitlines():
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            proxy_url, scheme = parse_proxy_line(s)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        pid = f"prx_{secrets.token_hex(6)}"
        created = db.create_proxy(pid, proxy_url, scheme)
        if created:
            imported += 1
        else:
            skipped += 1
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
        "proxies": [_serialize_proxy(p) for p in db.list_proxies()],
    }


def _check_one_proxy(db, p: dict[str, Any]) -> dict[str, Any]:
    res = check_proxy_ipinfo(p["proxy_url"])
    updated = db.update_proxy(
        p["id"],
        status=res["status"],
        ip=res.get("ip", ""),
        country=res.get("country", ""),
        city=res.get("city", ""),
        org=res.get("org", ""),
        latency_ms=res.get("latency_ms", 0),
        last_checked_at=time.time(),
        last_error=res.get("error", ""),
    )
    return {"ok": res["ok"], "proxy": _serialize_proxy(updated or p)}


@router.post("/proxies/check-all")
def check_all_proxies(request: Request):
    db = request.app.state.db
    proxies = db.list_proxies()
    results = []
    if proxies:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(proxies))) as ex:
            results = list(ex.map(lambda p: _check_one_proxy(db, p), proxies))
    return {"results": results}


@router.post("/proxies/{proxy_id}/check")
def check_proxy(proxy_id: str, request: Request):
    db = request.app.state.db
    p = db.get_proxy(proxy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return _check_one_proxy(db, p)


@router.delete("/proxies/{proxy_id}")
def delete_proxy(proxy_id: str, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    ok, affected_accounts = db.delete_proxy(proxy_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Proxy not found")
    for aid in affected_accounts:
        pool.close_account(aid)
    return {"ok": True, "detached_accounts": len(affected_accounts)}
