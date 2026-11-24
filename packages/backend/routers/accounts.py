"""Admin routes for Accounts & Keep-Alive."""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
import secrets
import time
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from db import normalize_supported_models, parse_supported_models
from muse_wss import cookies_to_header, fetch_quota_http
from services.cookie_parser import mask_cookies, mask_proxy, parse_cookies

router = APIRouter(prefix="/admin", tags=["accounts"])


class AccountCreateReq(BaseModel):
    label: str
    cookies_raw: str
    proxy_id: str | None = None
    enabled: bool = True
    supported_models: list[str] | None = None
    auto_reset: bool = False


class AccountPatchReq(BaseModel):
    label: str | None = None
    cookies_raw: str | None = None
    proxy_id: str | None = None
    enabled: bool | None = None
    supported_models: list[str] | None = None
    auto_reset: bool | None = None


def _serialize_account(acc: dict[str, Any], wss_connected: bool) -> dict[str, Any]:
    cookies = json.loads(acc.get("cookies_json") or "{}")
    quota = json.loads(acc.get("quota_json") or "{}")
    eff_proxy = (acc.get("effective_proxy_url") or acc.get("proxy_url") or "").strip()
    return {
        "id": acc["id"],
        "label": acc["label"],
        "cookies_masked": mask_cookies(cookies),
        "cookie_count": len(cookies),
        "proxy_id": acc.get("proxy_id"),
        "proxy_masked": mask_proxy(eff_proxy),
        "proxy_ip": acc.get("proxy_ip") or "",
        "proxy_status": acc.get("proxy_status") or "",
        "has_proxy": bool(eff_proxy),
        "enabled": bool(acc["enabled"]),
        "supported_models": parse_supported_models(acc.get("supported_models_json")),
        "auto_reset": bool(acc.get("auto_reset", 0)),
        "last_reset_at": float(acc.get("last_reset_at") or 0),
        "last_reset_status": acc.get("last_reset_status") or "",
        "last_reset_error": acc.get("last_reset_error") or "",
        "requests_since_reset": int(acc.get("requests_since_reset") or 0),
        "status": acc["status"],
        "wss_connected": wss_connected,
        "quota": quota,
        "last_used_at": acc["last_used_at"],
        "last_keepalive_at": acc["last_keepalive_at"],
        "last_error": acc["last_error"],
        "created_at": acc["created_at"],
        "updated_at": acc["updated_at"],
    }


@router.get("/extension/download")
def download_extension(request: Request):
    cfg = request.app.state.cfg
    ext_dir = os.path.join(cfg.project_root, "extension")
    if not os.path.isdir(ext_dir):
        raise HTTPException(status_code=404, detail="Extension directory not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(ext_dir):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, ext_dir)
                zf.write(full, arcname=os.path.join("muse2apiv2-extension", rel))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="muse2apiv2-extension.zip"'},
    )


@router.get("/accounts/export")
def export_accounts(request: Request):
    db = request.app.state.db
    exported = []
    for acc in db.list_accounts():
        cookies = json.loads(acc.get("cookies_json") or "{}")
        exported.append({
            "id": acc["id"],
            "label": acc["label"],
            "cookies": cookies,
            "cookie_header": cookies_to_header(cookies),
            "proxy_id": acc.get("proxy_id"),
            "proxy_url": acc.get("effective_proxy_url") or "",
            "enabled": bool(acc["enabled"]),
            "supported_models": parse_supported_models(acc.get("supported_models_json")),
            "auto_reset": bool(acc.get("auto_reset", 0)),
            "status": acc["status"],
            "quota": json.loads(acc.get("quota_json") or "{}"),
        })
    return JSONResponse(
        content={"accounts": exported},
        headers={"Content-Disposition": 'attachment; filename="muse2apiv2-accounts.json"'},
    )


@router.post("/accounts/quota")
def refresh_all_quotas(request: Request):
    db = request.app.state.db
    enabled_accs = [a for a in db.list_accounts() if a["enabled"]]

    def _check(acc: dict[str, Any]) -> dict[str, Any]:
        aid = acc["id"]
        cookies = json.loads(acc["cookies_json"])
        proxy_url = acc.get("effective_proxy_url") or ""
        try:
            q = fetch_quota_http(cookies, proxy_url=proxy_url)
            db.update_account(aid, quota_json=json.dumps(q), status="healthy", last_error="")
            return {"account_id": aid, "ok": True, "quota": q}
        except Exception as exc:
            return {"account_id": aid, "ok": False, "error": str(exc)}

    results = []
    if enabled_accs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(enabled_accs))) as ex:
            results = list(ex.map(_check, enabled_accs))
    return {"results": results}


@router.get("/accounts")
def list_accounts(request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    items = [_serialize_account(a, pool.is_connected(a["id"])) for a in db.list_accounts()]
    return {"accounts": items}


@router.post("/accounts", status_code=201)
def create_account(body: AccountCreateReq, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    try:
        cookies = parse_cookies(body.cookies_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    proxy_id = (body.proxy_id or "").strip() or None
    if proxy_id and not db.get_proxy(proxy_id):
        raise HTTPException(status_code=400, detail="Selected proxy not found")

    supported_models: list[str] | None = None
    if body.supported_models is not None:
        try:
            supported_models = normalize_supported_models(body.supported_models)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    aid = f"acc_{secrets.token_hex(6)}"
    acc = db.create_account(
        account_id=aid,
        label=body.label.strip() or aid,
        cookies=cookies,
        proxy_id=proxy_id,
        enabled=body.enabled,
        status="unknown",
        supported_models=supported_models,
        auto_reset=body.auto_reset,
    )
    test_res = pool.test_account(aid)
    if test_res.get("ok"):
        try:
            fresh_acc = db.get_account(aid) or acc
            fresh_cookies = json.loads(fresh_acc["cookies_json"])
            eff_proxy = fresh_acc.get("effective_proxy_url") or ""
            q = fetch_quota_http(fresh_cookies, proxy_url=eff_proxy)
            db.update_account(aid, quota_json=json.dumps(q))
        except Exception:
            pass
    acc = db.get_account(aid) or acc
    return {"account": _serialize_account(acc, pool.is_connected(aid)), "test": test_res}


@router.patch("/accounts/{account_id}")
def patch_account(account_id: str, body: AccountPatchReq, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    acc = db.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc.get("status") == "resetting":
        return {
            "ok": False,
            "account_id": account_id,
            "skipped": True,
            "error": "Account is currently resetting",
            "account": _serialize_account(acc, pool.is_connected(account_id)),
        }

    updates: dict[str, Any] = {}
    if body.label is not None:
        updates["label"] = body.label.strip() or acc["label"]
    if body.cookies_raw is not None and body.cookies_raw.strip():
        try:
            cookies = parse_cookies(body.cookies_raw)
            updates["cookies_json"] = json.dumps(cookies)
            updates["status"] = "unknown"
            pool.close_account(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if "proxy_id" in body.model_fields_set:
        pid = (body.proxy_id or "").strip() or None
        if pid and not db.get_proxy(pid):
            raise HTTPException(status_code=400, detail="Selected proxy not found")
        updates["proxy_id"] = pid
        pool.close_account(account_id)
    if body.enabled is not None:
        updates["enabled"] = 1 if body.enabled else 0
        if not body.enabled:
            pool.close_account(account_id)
    if "supported_models" in body.model_fields_set:
        try:
            normalized_models = normalize_supported_models(body.supported_models)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        updates["supported_models_json"] = json.dumps(normalized_models)
    if body.auto_reset is not None:
        updates["auto_reset"] = 1 if body.auto_reset else 0
        if body.auto_reset and not bool(acc.get("auto_reset")) and float(acc.get("last_reset_at") or 0) <= 0:
            updates["last_reset_at"] = time.time()

    updated = db.update_account(account_id, **updates)
    return {"account": _serialize_account(updated, pool.is_connected(account_id))}


@router.get("/accounts/{account_id}/cookies")
def get_account_cookies(account_id: str, request: Request):
    acc = request.app.state.db.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    cookies = json.loads(acc.get("cookies_json") or "{}")
    return {
        "id": acc["id"],
        "label": acc["label"],
        "cookie_header": cookies_to_header(cookies),
        "cookies": cookies,
    }


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    pool.close_account(account_id)
    if not db.delete_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}


@router.post("/accounts/{account_id}/test")
def test_account(account_id: str, request: Request):
    pool = request.app.state.wss_pool
    res = pool.test_account(account_id)
    return res


@router.post("/accounts/{account_id}/quota")
def check_quota(account_id: str, request: Request):
    db = request.app.state.db
    acc = db.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc.get("status") == "resetting":
        return {
            "ok": False,
            "account_id": account_id,
            "skipped": True,
            "error": "Account is currently resetting",
            "account": _serialize_account(acc, pool.is_connected(account_id)),
        }
    cookies = json.loads(acc["cookies_json"])
    proxy_url = acc.get("effective_proxy_url") or ""
    try:
        quota = fetch_quota_http(cookies, proxy_url=proxy_url)
        db.update_account(account_id, quota_json=json.dumps(quota), status="healthy", last_error="")
        return {"ok": True, "quota": quota}
    except Exception as exc:
        return {"ok": False, "quota": json.loads(acc.get("quota_json") or "{}"), "error": str(exc)}


def _refresh_account_full(app_state: Any, account_id: str) -> dict[str, Any]:
    """Run status/keepalive check + WSS tunnel check/connect + quota fetch."""
    db = app_state.db
    pool = app_state.wss_pool
    keepalive = app_state.keepalive

    acc = db.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc.get("status") == "resetting":
        return {
            "ok": False,
            "account_id": account_id,
            "skipped": True,
            "error": "Account is currently resetting",
            "account": _serialize_account(acc, pool.is_connected(account_id)),
        }

    ka_res = keepalive.run_one(account_id)
    if ka_res.get("status") == "expired":
        updated = db.get_account(account_id) or acc
        return {
            "ok": False,
            "account_id": account_id,
            "keepalive": ka_res,
            "wss": {"ok": False, "status": "expired", "error": ka_res.get("error", "")},
            "quota": json.loads(updated.get("quota_json") or "{}"),
            "error": ka_res.get("error", "Session expired"),
            "account": _serialize_account(updated, pool.is_connected(account_id)),
        }

    wss_res = pool.test_account(account_id)

    acc = db.get_account(account_id) or acc
    cookies = json.loads(acc["cookies_json"])
    proxy_url = acc.get("effective_proxy_url") or ""
    quota = json.loads(acc.get("quota_json") or "{}")
    quota_err = ""
    try:
        quota = fetch_quota_http(cookies, proxy_url=proxy_url)
        db.update_account(account_id, quota_json=json.dumps(quota))
    except Exception as exc:
        quota_err = str(exc)

    updated = db.get_account(account_id) or acc
    ok = bool(ka_res.get("ok")) and bool(wss_res.get("ok")) and not quota_err
    err = wss_res.get("error") or ka_res.get("error") or quota_err or ""
    return {
        "ok": ok,
        "account_id": account_id,
        "keepalive": ka_res,
        "wss": wss_res,
        "quota": quota,
        "error": err,
        "account": _serialize_account(updated, pool.is_connected(account_id)),
    }


@router.post("/accounts/{account_id}/refresh")
def refresh_account(account_id: str, request: Request):
    return _refresh_account_full(request.app.state, account_id)


@router.post("/accounts/refresh")
def refresh_all_accounts(request: Request):
    db = request.app.state.db
    enabled_accs = [a for a in db.list_accounts() if a["enabled"] and a.get("status") != "resetting"]
    results: list[dict[str, Any]] = []
    if enabled_accs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(enabled_accs))) as ex:
            results = list(ex.map(lambda a: _refresh_account_full(request.app.state, a["id"]), enabled_accs))
    return {"results": results}


@router.post("/accounts/reset-due")
def reset_due_accounts(request: Request):
    reset_svc = getattr(request.app.state, "reset_service", None)
    if not reset_svc:
        raise HTTPException(status_code=503, detail="Reset service unavailable")
    return reset_svc.trigger_due_async()


@router.get("/accounts/reset-logs")
def reset_logs(request: Request, limit: int = 30, account_id: str | None = None):
    return {"logs": request.app.state.db.list_reset_logs(limit=limit, account_id=account_id)}


@router.post("/accounts/{account_id}/reset", status_code=202)
def reset_account_manual(account_id: str, request: Request):
    reset_svc = getattr(request.app.state, "reset_service", None)
    if not reset_svc:
        raise HTTPException(status_code=503, detail="Reset service unavailable")
    pool = request.app.state.wss_pool
    try:
        acc = reset_svc.start_manual_reset(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Account not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "ok": True,
        "status": "resetting",
        "account": _serialize_account(acc, pool.is_connected(account_id)),
    }


@router.post("/accounts/{account_id}/keepalive")
def keepalive_one(account_id: str, request: Request):
    return request.app.state.keepalive.run_one(account_id)


@router.post("/accounts/keepalive")
def keepalive_all(request: Request):
    results = request.app.state.keepalive.run_all()
    return {"results": results}


@router.get("/keepalive/logs")
def keepalive_logs(request: Request, limit: int = 30):
    return {"logs": request.app.state.db.list_keepalive_logs(limit=limit)}
