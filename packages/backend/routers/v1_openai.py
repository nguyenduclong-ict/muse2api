"""OpenAI-compatible /v1/* endpoints powered by Muse WSS pool."""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import require_v1_api_key
from services.ref_media import RefMediaError, load_reference_list

router = APIRouter(prefix="/v1", tags=["v1"])

_IDEMPOTENCY_MAP: dict[str, str] = {}
_IDEMPOTENCY_LOCK = threading.Lock()

_MODELS = [
    "muse-spark", "muse-image", "muse-video",
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-5", "o3", "o4-mini",
    "claude-sonnet-4", "claude-opus-4", "claude-3-7-sonnet",
    "deepseek-chat", "deepseek-reasoner", "gemini-2.5-pro", "gemini-2.5-flash",
]


class ChatCompletionReq(BaseModel):
    model: str = "muse-spark"
    messages: list[dict[str, Any]] = []
    prompt: str | None = None
    stream: bool = False
    timeout: int | None = None
    tools: list[Any] | None = None
    tool_choice: Any = None


class ResponsesReq(BaseModel):
    model: str = "muse-spark"
    input: Any = None
    instructions: str | None = None
    stream: bool = False
    timeout: int | None = None


class ImageGenReq(BaseModel):
    model: str = "muse-image"
    prompt: str
    n: int = 1
    size: str | None = None
    aspect_ratio: str | None = None
    response_format: str = "url"
    timeout: int | None = None
    extra: str | None = None
    image: Any = None
    images: list[Any] | None = None
    videos: list[Any] | None = None
    audios: list[Any] | None = None
    files: list[Any] | None = None
    reference_image: str | None = None
    async_: bool = Field(False, alias="async")


class VideoGenReq(BaseModel):
    model: str = "muse-video"
    prompt: str
    duration: int | None = 5
    size: str | None = "16:9"
    aspect_ratio: str | None = None
    resolution: str | None = None
    timeout: int | None = None
    extra: str | None = None
    image: Any = None
    images: list[Any] | None = None
    videos: list[Any] | None = None
    audios: list[Any] | None = None
    files: list[Any] | None = None
    image_url: Any = None
    reference_image: str | None = None


def _collect_ref_items(obj: Any) -> list[Any]:
    refs: list[Any] = []
    if isinstance(obj, dict):
        getter = obj.get
    else:
        getter = lambda k, d=None: getattr(obj, k, d)

    for single in ("image", "image_url", "reference_image"):
        val = getter(single)
        if val is not None:
            if isinstance(val, list):
                refs.extend(val)
            else:
                refs.append(val)
    for multi in ("images", "videos", "audios", "files"):
        val = getter(multi)
        if isinstance(val, list):
            refs.extend(val)
    return refs


def _load_refs_or_400(raw_refs: list[Any], cfg) -> list[tuple[bytes, str]]:
    if not raw_refs:
        return []
    try:
        return load_reference_list(raw_refs, cfg)
    except RefMediaError as exc:
        raise HTTPException(status_code=400, detail={"error": {"message": str(exc), "type": "invalid_request_error"}})


def _extract_chat_prompt_and_refs(messages: list[dict[str, Any]], top_prompt: str | None,
                                  tools: list[Any] | None, use_tool_protocol: bool) -> tuple[str, list[Any]]:
    parts: list[str] = []
    refs: list[Any] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            txts = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype in ("text", "input_text"):
                    txts.append(c.get("text", ""))
                elif ctype in ("image_url", "input_image"):
                    u = c.get("image_url")
                    if u:
                        refs.append(u)
            txt = " ".join(txts)
        else:
            txt = str(content or "")
        if txt:
            parts.append(f"[{role}]\n{txt}")

    if not parts and top_prompt:
        parts.append(top_prompt.strip())
    prompt = "\n\n".join(parts)
    if use_tool_protocol and tools:
        prompt = f"[Available tools]\n{json.dumps(tools)}\n\n{prompt}"
    return prompt, refs


def _build_media_prompt(kind: str, prompt: str, ratio: str | None, duration: int | None = None,
                        resolution: str | None = None, extra: str | None = None, has_refs: bool = False) -> str:
    specs = []
    if duration:
        specs.append(f"{duration}s")
    if ratio:
        specs.append(ratio)
    if resolution:
        specs.append(resolution)
    spec_str = f" ({', '.join(specs)})" if specs else ""
    action = f"Using the attached reference media, generate a {kind}{spec_str}" if has_refs else f"Generate a {kind}{spec_str}"
    full = f"{action}: {prompt}"
    if extra:
        full = f"{full}\n{extra}"
    return full


def _run_async_media(db, pool, task_id: str, prompt: str, expect_kind: str,
                     refs: list[tuple[bytes, str]] | None, timeout: float) -> None:
    t0 = time.time()
    db.update_task(task_id, status="running")
    try:
        res = pool.generate_media(prompt, expect_kind=expect_kind, images=refs, timeout=timeout)
        db.update_task(
            task_id,
            status="completed",
            account_id=res["account_id"],
            session_id=res["session_id"],
            media_filename=res["filename"],
            latency_ms=int((time.time() - t0) * 1000),
        )
    except Exception as exc:
        db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))


def _media_file_meta(cfg, filename: str, expect_kind: str) -> dict[str, Any]:
    p = os.path.join(cfg.media_dir, filename)
    size_bytes = os.path.getsize(p) if os.path.isfile(p) else 0
    return {"kind": expect_kind, "bytes": size_bytes}


@router.get("/models", dependencies=[Depends(require_v1_api_key)])
def list_models():
    now = int(time.time())
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "created": now, "owned_by": "muse2apiv2"} for m in _MODELS],
    }


@router.post("/chat/completions", dependencies=[Depends(require_v1_api_key)])
def chat_completions(body: ChatCompletionReq, request: Request):
    cfg = request.app.state.cfg
    db = request.app.state.db
    pool = request.app.state.wss_pool
    prompt, raw_refs = _extract_chat_prompt_and_refs(body.messages, body.prompt, body.tools, cfg.tool_protocol)
    if not prompt.strip():
        raise HTTPException(status_code=400, detail={"error": {"message": "messages or prompt is required"}})
    refs = _load_refs_or_400(raw_refs, cfg)
    timeout = float(body.timeout or 180)

    task_id = f"tsk_{secrets.token_hex(6)}"
    db.create_task(task_id, "chat", status="running", model=body.model, prompt_preview=prompt)
    t0 = time.time()

    if body.stream:
        def sse_gen():
            cid = f"chatcmpl-{secrets.token_hex(8)}"
            created = int(time.time())
            try:
                for kind, data in pool.stream_chat_events(prompt, images=refs, timeout=timeout):
                    if kind == "delta":
                        chunk = {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": body.model,
                            "choices": [{"index": 0, "delta": {"content": data}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif kind == "done":
                        end_chunk = {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": body.model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        }
                        yield f"data: {json.dumps(end_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                db.update_task(task_id, status="completed", latency_ms=int((time.time() - t0) * 1000))
            except Exception as exc:
                db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
                yield f"data: {json.dumps({'error': {'message': str(exc)}})}\n\n"

        return StreamingResponse(sse_gen(), media_type="text/event-stream")

    try:
        aid, sid, text = pool.execute_chat(prompt, images=refs, timeout=timeout)
        db.update_task(task_id, status="completed", account_id=aid, session_id=sid, latency_ms=int((time.time() - t0) * 1000))
        return {
            "id": f"chatcmpl-{secrets.token_hex(8)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        }
    except Exception as exc:
        db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/responses", dependencies=[Depends(require_v1_api_key)])
def responses_endpoint(body: ResponsesReq, request: Request):
    pool = request.app.state.wss_pool
    db = request.app.state.db
    raw_input = body.input if isinstance(body.input, str) else json.dumps(body.input or "")
    prompt = f"{body.instructions.strip()}\n\n{raw_input}" if body.instructions else raw_input
    if not prompt.strip():
        raise HTTPException(status_code=400, detail={"error": {"message": "input is required"}})
    timeout = float(body.timeout or 180)

    task_id = f"tsk_{secrets.token_hex(6)}"
    db.create_task(task_id, "chat", status="running", model=body.model, prompt_preview=prompt)
    t0 = time.time()

    if body.stream:
        def resp_sse():
            rid = f"resp_{secrets.token_hex(8)}"
            created = int(time.time())
            yield f"event: response.created\ndata: {json.dumps({'type': 'response.created', 'response': {'id': rid, 'model': body.model, 'created_at': created, 'status': 'in_progress'}})}\n\n"
            chunks: list[str] = []
            try:
                for kind, data in pool.stream_chat_events(prompt, timeout=timeout):
                    if kind == "delta":
                        chunks.append(data)
                        ev = {"type": "response.output_text.delta", "delta": data}
                        yield f"event: response.output_text.delta\ndata: {json.dumps(ev)}\n\n"
                    elif kind == "done":
                        full_txt = "".join(chunks)
                        comp = {
                            "type": "response.completed",
                            "response": {
                                "id": rid,
                                "object": "response",
                                "created_at": created,
                                "model": body.model,
                                "status": "completed",
                                "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": full_txt}]}],
                            },
                        }
                        yield f"event: response.completed\ndata: {json.dumps(comp)}\n\n"
                db.update_task(task_id, status="completed", latency_ms=int((time.time() - t0) * 1000))
            except Exception as exc:
                db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
                yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': str(exc)}})}\n\n"

        return StreamingResponse(resp_sse(), media_type="text/event-stream")

    try:
        aid, sid, text = pool.execute_chat(prompt, timeout=timeout)
        db.update_task(task_id, status="completed", account_id=aid, session_id=sid, latency_ms=int((time.time() - t0) * 1000))
        return {
            "id": f"resp_{secrets.token_hex(8)}",
            "object": "response",
            "created_at": int(time.time()),
            "model": body.model,
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
        }
    except Exception as exc:
        db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/images/generations", dependencies=[Depends(require_v1_api_key)])
def images_generations(body: ImageGenReq, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cfg = request.app.state.cfg
    refs = _load_refs_or_400(_collect_ref_items(body), cfg)
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt("image", body.prompt, ratio, extra=body.extra, has_refs=bool(refs))
    timeout = float(body.timeout or 300)
    task_id = f"img_{secrets.token_hex(6)}"

    if body.async_:
        db.create_task(task_id, "image", status="queued", model=body.model, prompt_preview=body.prompt)
        threading.Thread(target=_run_async_media, args=(db, pool, task_id, prompt, "image", refs, timeout), daemon=True).start()
        return {"id": task_id, "status": "queued", "progress": 10}

    db.create_task(task_id, "image", status="running", model=body.model, prompt_preview=body.prompt)
    t0 = time.time()
    try:
        res = pool.generate_media(prompt, expect_kind="image", images=refs, timeout=timeout)
        db.update_task(
            task_id,
            status="completed",
            account_id=res["account_id"],
            session_id=res["session_id"],
            media_filename=res["filename"],
            latency_ms=int((time.time() - t0) * 1000),
        )
        base = str(request.base_url).rstrip("/")
        item: dict[str, Any] = {
            "revised_prompt": body.prompt,
            "url": f"{base}/v1/media/{res['filename']}",
            "size": ratio,
            "kind": "image",
            "bytes": res["size_bytes"],
        }
        if body.response_format == "b64_json":
            with open(os.path.join(cfg.media_dir, res["filename"]), "rb") as f:
                item["b64_json"] = base64.b64encode(f.read()).decode("ascii")
        return {"created": int(time.time()), "data": [item]}
    except Exception as exc:
        db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/images/edits", dependencies=[Depends(require_v1_api_key)])
async def images_edits(request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cfg = request.app.state.cfg

    ct = (request.headers.get("content-type") or "").lower()
    prompt = ""
    model = "muse-image"
    ratio = "16:9"
    extra = None
    response_format = "url"
    async_flag = False
    timeout = 300.0
    img_tuples: list[tuple[bytes, str]] = []
    raw_refs: list[Any] = []

    if "multipart/form-data" in ct:
        form = await request.form()
        prompt = str(form.get("prompt") or "").strip()
        model = str(form.get("model") or "muse-image")
        ratio = str(form.get("aspect_ratio") or form.get("size") or "16:9")
        extra = str(form.get("extra")) if form.get("extra") else None
        response_format = str(form.get("response_format") or "url")
        async_flag = str(form.get("async") or "").lower() in ("1", "true")
        if form.get("timeout"):
            try:
                timeout = float(form.get("timeout"))
            except ValueError:
                pass
        for field_name in ("image", "image[]", "video", "audio", "file", "images"):
            for item in form.getlist(field_name):
                if hasattr(item, "read"):
                    data = await item.read()
                    mime = getattr(item, "content_type", None) or "image/png"
                    if data:
                        img_tuples.append((data, mime))
                elif isinstance(item, str) and item.strip():
                    raw_refs.append(item)
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={"error": {"message": "Invalid JSON or multipart body"}})
        prompt = str(body.get("prompt") or "").strip()
        model = str(body.get("model") or "muse-image")
        ratio = str(body.get("aspect_ratio") or body.get("size") or "16:9")
        extra = body.get("extra")
        response_format = str(body.get("response_format") or "url")
        async_flag = bool(body.get("async", False))
        if body.get("timeout"):
            timeout = float(body["timeout"])
        raw_refs = _collect_ref_items(body)

    if raw_refs:
        img_tuples.extend(_load_refs_or_400(raw_refs, cfg))
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": {"message": "prompt is required"}})
    if not img_tuples:
        raise HTTPException(status_code=400, detail={"error": {"message": "At least one non-empty reference media is required"}})

    full_prompt = _build_media_prompt("image", prompt, ratio, extra=extra, has_refs=True)
    task_id = f"img_{secrets.token_hex(6)}"

    if async_flag:
        db.create_task(task_id, "image", status="queued", model=model, prompt_preview=prompt)
        threading.Thread(target=_run_async_media, args=(db, pool, task_id, full_prompt, "image", img_tuples, timeout), daemon=True).start()
        return {"id": task_id, "status": "queued", "progress": 10}

    db.create_task(task_id, "image", status="running", model=model, prompt_preview=prompt)
    t0 = time.time()
    try:
        res = await run_in_threadpool(pool.generate_media, full_prompt, "image", img_tuples, timeout)
        db.update_task(
            task_id,
            status="completed",
            account_id=res["account_id"],
            session_id=res["session_id"],
            media_filename=res["filename"],
            latency_ms=int((time.time() - t0) * 1000),
        )
        base = str(request.base_url).rstrip("/")
        item_out: dict[str, Any] = {
            "revised_prompt": prompt,
            "url": f"{base}/v1/media/{res['filename']}",
            "size": ratio,
            "kind": "image",
            "bytes": res["size_bytes"],
        }
        if response_format == "b64_json":
            with open(os.path.join(cfg.media_dir, res["filename"]), "rb") as fp:
                item_out["b64_json"] = base64.b64encode(fp.read()).decode("ascii")
        return {"created": int(time.time()), "data": [item_out]}
    except Exception as exc:
        db.update_task(task_id, status="failed", error_message=str(exc), latency_ms=int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/images/tasks", dependencies=[Depends(require_v1_api_key)])
def create_image_task(
    body: ImageGenReq,
    request: Request,
    idempotency_key: str | None = Header(default=None),
):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cfg = request.app.state.cfg
    if idempotency_key:
        with _IDEMPOTENCY_LOCK:
            existing_id = _IDEMPOTENCY_MAP.get(idempotency_key)
        if existing_id:
            existing = db.get_task(existing_id)
            if existing:
                return {"id": existing["id"], "status": existing["status"]}

    refs = _load_refs_or_400(_collect_ref_items(body), cfg)
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt("image", body.prompt, ratio, extra=body.extra, has_refs=bool(refs))
    timeout = float(body.timeout or 300)

    task_id = f"img_{secrets.token_hex(6)}"
    db.create_task(task_id, "image", status="queued", model=body.model, prompt_preview=body.prompt)
    if idempotency_key:
        with _IDEMPOTENCY_LOCK:
            _IDEMPOTENCY_MAP[idempotency_key] = task_id
    threading.Thread(target=_run_async_media, args=(db, pool, task_id, prompt, "image", refs, timeout), daemon=True).start()
    return {"id": task_id, "status": "queued", "progress": 10}


@router.get("/images/tasks/{task_id}", dependencies=[Depends(require_v1_api_key)])
def get_image_task(task_id: str, request: Request, response_format: str = "url"):
    cfg = request.app.state.cfg
    t = request.app.state.db.get_task(task_id)
    if not t or t["type"] != "image":
        raise HTTPException(status_code=404, detail={"error": {"message": "Task not found"}})
    base = str(request.base_url).rstrip("/")
    progress = 100 if t["status"] == "completed" else (50 if t["status"] == "running" else 10)
    out: dict[str, Any] = {"id": t["id"], "status": t["status"], "progress": progress, "error": t["error_message"] or None}
    if t["media_filename"]:
        out["url"] = f"{base}/v1/media/{t['media_filename']}"
        out.update(_media_file_meta(cfg, t["media_filename"], "image"))
        if response_format == "b64_json":
            fp = os.path.join(cfg.media_dir, t["media_filename"])
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    out["b64_json"] = base64.b64encode(f.read()).decode("ascii")
    return out


@router.post("/videos", dependencies=[Depends(require_v1_api_key)])
@router.post("/videos/generations", dependencies=[Depends(require_v1_api_key)])
def create_video_task(body: VideoGenReq, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cfg = request.app.state.cfg
    refs = _load_refs_or_400(_collect_ref_items(body), cfg)
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt(
        "video", body.prompt, ratio, duration=body.duration, resolution=body.resolution, extra=body.extra, has_refs=bool(refs)
    )
    timeout = float(body.timeout or 600)
    task_id = f"vid_{secrets.token_hex(6)}"
    db.create_task(task_id, "video", status="queued", model=body.model, prompt_preview=body.prompt)
    threading.Thread(target=_run_async_media, args=(db, pool, task_id, prompt, "video", refs, timeout), daemon=True).start()
    return {"id": task_id, "status": "queued", "progress": 10}


@router.get("/videos/{task_id}", dependencies=[Depends(require_v1_api_key)])
@router.get("/videos/generations/{task_id}", dependencies=[Depends(require_v1_api_key)])
def get_video_task(task_id: str, request: Request):
    cfg = request.app.state.cfg
    t = request.app.state.db.get_task(task_id)
    if not t or t["type"] != "video":
        raise HTTPException(status_code=404, detail={"error": {"message": "Task not found"}})
    base = str(request.base_url).rstrip("/")
    progress = 100 if t["status"] == "completed" else (50 if t["status"] == "running" else 10)
    out: dict[str, Any] = {"id": t["id"], "status": t["status"], "progress": progress, "error": t["error_message"] or None}
    if t["media_filename"]:
        out["url"] = f"{base}/v1/media/{t['media_filename']}"
        out.update(_media_file_meta(cfg, t["media_filename"], "video"))
    return out


@router.get("/media/{filename}")
def serve_media(filename: str, request: Request):
    cfg = request.app.state.cfg
    safe = os.path.basename(filename)
    p = os.path.join(cfg.media_dir, safe)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})
