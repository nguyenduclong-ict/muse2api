"""Admin routes for Dashboard, API Key, Tasks, Media, and Settings."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import DEFAULT_SYSTEM_PROMPT
from routers.accounts import _serialize_account

router = APIRouter(prefix="/admin", tags=["admin"])


class SystemPromptUpdate(BaseModel):
    enabled: bool
    prompt: str


class MediaCleanupUpdate(BaseModel):
    enabled: bool
    retention_days: int
    max_gb: float
    interval_minutes: int


class SettingsPatchReq(BaseModel):
    system_prompt: SystemPromptUpdate | None = None
    media_cleanup: MediaCleanupUpdate | None = None


@router.get("/dashboard")
def get_dashboard(request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cleanup = request.app.state.cleanup
    accounts = db.list_accounts()
    healthy = sum(1 for a in accounts if a["enabled"] and a["status"] == "healthy")
    enabled_cnt = sum(1 for a in accounts if a["enabled"])
    serialized_accounts = [_serialize_account(a, pool.is_connected(a["id"])) for a in accounts]
    return {
        "pool": {
            "total_accounts": len(accounts),
            "enabled_accounts": enabled_cnt,
            "healthy_accounts": healthy,
            "active_wss_tunnels": pool.active_count(),
        },
        "storage": {
            "usage_bytes": cleanup.storage_usage_bytes(),
            "last_cleanup_at": cleanup.last_run_at,
            "last_freed_bytes": cleanup.last_freed_bytes,
        },
        "trend_7d": db.task_stats_7days(),
        "accounts": serialized_accounts,
    }


@router.get("/apikey")
def get_apikey(request: Request):
    return request.app.state.db.get_api_key()


@router.post("/apikey/rotate")
def rotate_apikey(request: Request):
    return request.app.state.db.rotate_api_key()


def _paginate_meta(total: int, page: int, page_size: int) -> tuple[int, int, int, int]:
    safe_size = max(1, min(100, page_size))
    total_pages = max(1, (total + safe_size - 1) // safe_size)
    safe_page = max(1, min(page, total_pages))
    offset = (safe_page - 1) * safe_size
    return safe_page, safe_size, total_pages, offset


@router.get("/tasks")
def list_tasks(request: Request, type: str = "", status: str = "", page: int = 1, page_size: int = 10):
    db = request.app.state.db
    total = db.count_tasks(task_type=type, status=status)
    safe_page, safe_size, total_pages, offset = _paginate_meta(total, page, page_size)
    items = db.list_tasks(task_type=type, status=status, limit=safe_size, offset=offset)
    return {
        "tasks": items,
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
        "total_pages": total_pages,
    }


def _remove_media_files(cfg, filenames: list[str]) -> int:
    removed = 0
    for fn in filenames:
        safe = os.path.basename(fn)
        if not safe:
            continue
        p = os.path.join(cfg.media_dir, safe)
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    return removed


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, request: Request):
    ok, orphan_files = request.app.state.db.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Task not found or currently running")
    removed_media = _remove_media_files(request.app.state.cfg, orphan_files)
    return {"ok": True, "removed_media": removed_media}


@router.post("/tasks/clear")
def clear_tasks(request: Request):
    deleted, orphan_files = request.app.state.db.clear_completed_tasks()
    removed_media = _remove_media_files(request.app.state.cfg, orphan_files)
    return {"deleted": deleted, "removed_media": removed_media}


@router.get("/media")
def list_media(request: Request, page: int = 1, page_size: int = 10):
    cfg = request.app.state.cfg
    cleanup = request.app.state.cleanup
    files: list[dict[str, Any]] = []
    if os.path.isdir(cfg.media_dir):
        for name in os.listdir(cfg.media_dir):
            p = os.path.join(cfg.media_dir, name)
            if not os.path.isfile(p):
                continue
            st = os.stat(p)
            ext = os.path.splitext(name)[1].lower()
            kind = "video" if ext in (".mp4", ".webm", ".mov") else ("audio" if ext in (".mp3", ".wav", ".ogg") else "image")
            files.append({
                "filename": name,
                "kind": kind,
                "size_bytes": st.st_size,
                "created_at": st.st_mtime,
                "url": f"/v1/media/{name}",
            })
    files.sort(key=lambda x: x["created_at"], reverse=True)
    total = len(files)
    safe_page, safe_size, total_pages, offset = _paginate_meta(total, page, page_size)
    paged = files[offset: offset + safe_size]
    return {
        "files": paged,
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
        "total_pages": total_pages,
        "usage_bytes": cleanup.storage_usage_bytes(),
    }


class MediaDeleteBatchReq(BaseModel):
    filenames: list[str]


@router.post("/media/delete")
def delete_media_batch(body: MediaDeleteBatchReq, request: Request):
    cfg = request.app.state.cfg
    deleted = 0
    for filename in body.filenames:
        safe = os.path.basename(filename)
        p = os.path.join(cfg.media_dir, safe)
        if os.path.isfile(p):
            try:
                os.remove(p)
                deleted += 1
            except OSError:
                pass
    return {"ok": True, "deleted": deleted}


@router.delete("/media/{filename}")
def delete_media(filename: str, request: Request):
    cfg = request.app.state.cfg
    safe = os.path.basename(filename)
    p = os.path.join(cfg.media_dir, safe)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Media file not found")
    os.remove(p)
    return {"ok": True}


@router.get("/settings")
def get_settings(request: Request):
    settings = request.app.state.db.get_settings()
    settings["default_system_prompt"] = DEFAULT_SYSTEM_PROMPT
    return settings


@router.post("/settings")
def update_settings(body: SettingsPatchReq, request: Request):
    db = request.app.state.db
    if body.system_prompt is not None:
        db.update_setting("system_prompt", body.system_prompt.model_dump())
    if body.media_cleanup is not None:
        mc = body.media_cleanup.model_dump()
        mc["interval_minutes"] = max(5, int(mc["interval_minutes"]))
        mc["retention_days"] = max(0, int(mc["retention_days"]))
        mc["max_gb"] = max(0.0, float(mc["max_gb"]))
        db.update_setting("media_cleanup", mc)
    return get_settings(request)


@router.post("/cleanup/run")
def run_cleanup(request: Request):
    return request.app.state.cleanup.run_now()
