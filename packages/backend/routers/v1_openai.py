"""OpenAI-compatible /v1/* endpoints powered by Muse WSS pool."""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import require_v1_api_key
from services.audio_format import (
    AUDIO_MEDIA_TYPES,
    BINARY_SPEECH_FORMATS,
    SUPPORTED_SPEECH_FORMATS,
    ensure_audio_file_format,
)
from services.ref_media import RefMediaError, load_reference_list
from services.voice_preview import build_speech_prompt as _build_speech_prompt
from services.voices import (
    get_voice_language_code,
    get_voice_language_group,
    has_multiple_language_groups,
    is_voice_allowed,
    list_voices,
    normalize_voice_languages,
    resolve_voice,
)
from services.wss_pool import NoCandidateAccountError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["v1"])


def _ensure_capability_or_503(pool: Any, capability: str) -> None:
    if hasattr(pool, "ensure_candidate"):
        try:
            pool.ensure_candidate(capability)
        except NoCandidateAccountError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": {"message": str(exc), "type": "service_unavailable_error"}},
            )

_IDEMPOTENCY_MAP: dict[str, str] = {}
_IDEMPOTENCY_LOCK = threading.Lock()

_MODELS = [
    "muse-spark", "muse-image", "muse-video",
    "muse-tts", "tts-1", "tts-1-hd", "gpt-4o-mini-tts",
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


class SpeechReq(BaseModel):
    model: str = "muse-tts"
    input: str
    voice: str | None = None
    instructions: str | None = None
    speed: float | None = None
    response_format: str = "mp3"
    timeout: int | None = None


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


def _safe_fail_task(db: Any, task_id: str, error_message: str, latency_ms: int) -> None:
    """Persist failed task status without letting a secondary DB error mask the root cause."""
    try:
        db.update_task(task_id, status="failed", error_message=error_message, latency_ms=latency_ms)
    except Exception:
        logger.warning("Failed to record failed status for task %s", task_id, exc_info=True)


def _run_async_media(db, pool, task_id: str, prompt: str, expect_kind: str,
                     refs: list[tuple[bytes, str]] | None, timeout: float) -> None:
    t0 = time.time()
    db.update_task(task_id, status="running")
    try:
        res = pool.generate_media(
            prompt,
            expect_kind=expect_kind,
            images=refs,
            timeout=timeout,
            on_account_selected=lambda aid, sid: db.update_task(task_id, account_id=aid, session_id=sid),
        )
        db.update_task(
            task_id,
            status="completed",
            account_id=res["account_id"],
            session_id=res["session_id"],
            media_filename=res["filename"],
            latency_ms=int((time.time() - t0) * 1000),
        )
    except Exception as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))


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
    _ensure_capability_or_503(pool, "chat")
    timeout = float(body.timeout or 180)

    task_id = f"tsk_{secrets.token_hex(6)}"
    db.create_task(
        task_id,
        "chat",
        status="running",
        model=body.model,
        prompt_preview=prompt,
        input_request=body.model_dump(exclude_none=True),
    )
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
                _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
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
    except NoCandidateAccountError as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("POST %s failed (task_id=%s)", request.url.path, task_id)
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/responses", dependencies=[Depends(require_v1_api_key)])
def responses_endpoint(body: ResponsesReq, request: Request):
    pool = request.app.state.wss_pool
    db = request.app.state.db
    raw_input = body.input if isinstance(body.input, str) else json.dumps(body.input or "")
    prompt = f"{body.instructions.strip()}\n\n{raw_input}" if body.instructions else raw_input
    if not prompt.strip():
        raise HTTPException(status_code=400, detail={"error": {"message": "input is required"}})
    _ensure_capability_or_503(pool, "chat")
    timeout = float(body.timeout or 180)

    task_id = f"tsk_{secrets.token_hex(6)}"
    db.create_task(
        task_id,
        "chat",
        status="running",
        model=body.model,
        prompt_preview=prompt,
        input_request=body.model_dump(exclude_none=True),
    )
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
                _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
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
    except NoCandidateAccountError as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("POST %s failed (task_id=%s)", request.url.path, task_id)
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.post("/images/generations", dependencies=[Depends(require_v1_api_key)])
def images_generations(body: ImageGenReq, request: Request):
    db = request.app.state.db
    pool = request.app.state.wss_pool
    cfg = request.app.state.cfg
    refs = _load_refs_or_400(_collect_ref_items(body), cfg)
    _ensure_capability_or_503(pool, "image")
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt("image", body.prompt, ratio, extra=body.extra, has_refs=bool(refs))
    timeout = float(body.timeout or 300)
    task_id = f"img_{secrets.token_hex(6)}"
    input_payload = body.model_dump(by_alias=True, exclude_none=True)

    if body.async_:
        db.create_task(task_id, "image", status="queued", model=body.model, prompt_preview=body.prompt, input_request=input_payload)
        threading.Thread(target=_run_async_media, args=(db, pool, task_id, prompt, "image", refs, timeout), daemon=True).start()
        return {"id": task_id, "status": "queued", "progress": 10}

    db.create_task(task_id, "image", status="running", model=body.model, prompt_preview=body.prompt, input_request=input_payload)
    t0 = time.time()
    try:
        res = pool.generate_media(
            prompt,
            expect_kind="image",
            images=refs,
            timeout=timeout,
            on_account_selected=lambda aid, sid: db.update_task(task_id, account_id=aid, session_id=sid),
        )
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
    except NoCandidateAccountError as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("POST %s failed (task_id=%s)", request.url.path, task_id)
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
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
    uploaded_files_meta: list[dict[str, Any]] = []
    raw_refs: list[Any] = []
    json_body: dict[str, Any] | None = None

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
                        uploaded_files_meta.append({
                            "field": field_name,
                            "filename": getattr(item, "filename", None) or "upload",
                            "content_type": mime,
                            "size_bytes": len(data),
                        })
                elif isinstance(item, str) and item.strip():
                    raw_refs.append(item)
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={"error": {"message": "Invalid JSON or multipart body"}})
        json_body = body
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
    _ensure_capability_or_503(pool, "image")

    full_prompt = _build_media_prompt("image", prompt, ratio, extra=extra, has_refs=True)
    task_id = f"img_{secrets.token_hex(6)}"
    input_payload = (
        json_body
        if json_body is not None
        else {
            "prompt": prompt,
            "model": model,
            "aspect_ratio": ratio,
            "extra": extra,
            "response_format": response_format,
            "async": async_flag,
            "timeout": timeout,
            "files": uploaded_files_meta,
            "refs": raw_refs,
        }
    )

    if async_flag:
        db.create_task(task_id, "image", status="queued", model=model, prompt_preview=prompt, input_request=input_payload)
        threading.Thread(target=_run_async_media, args=(db, pool, task_id, full_prompt, "image", img_tuples, timeout), daemon=True).start()
        return {"id": task_id, "status": "queued", "progress": 10}

    db.create_task(task_id, "image", status="running", model=model, prompt_preview=prompt, input_request=input_payload)
    t0 = time.time()
    try:
        res = await run_in_threadpool(
            pool.generate_media,
            full_prompt,
            "image",
            img_tuples,
            timeout,
            on_account_selected=lambda aid, sid: db.update_task(task_id, account_id=aid, session_id=sid),
        )
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
    except NoCandidateAccountError as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("POST %s failed (task_id=%s)", request.url.path, task_id)
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
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
    _ensure_capability_or_503(pool, "image")
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt("image", body.prompt, ratio, extra=body.extra, has_refs=bool(refs))
    timeout = float(body.timeout or 300)

    task_id = f"img_{secrets.token_hex(6)}"
    db.create_task(
        task_id,
        "image",
        status="queued",
        model=body.model,
        prompt_preview=body.prompt,
        input_request=body.model_dump(by_alias=True, exclude_none=True),
    )
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
    _ensure_capability_or_503(pool, "video")
    ratio = body.aspect_ratio or body.size or "16:9"
    prompt = _build_media_prompt(
        "video", body.prompt, ratio, duration=body.duration, resolution=body.resolution, extra=body.extra, has_refs=bool(refs)
    )
    timeout = float(body.timeout or 360)
    task_id = f"vid_{secrets.token_hex(6)}"
    db.create_task(
        task_id,
        "video",
        status="queued",
        model=body.model,
        prompt_preview=body.prompt,
        input_request=body.model_dump(exclude_none=True),
    )
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


def _get_allowed_voice_languages(db: Any) -> list[str]:
    cfg = (db.get_settings().get("voice_languages") or {}) if hasattr(db, "get_settings") else {}
    if cfg.get("enabled"):
        return normalize_voice_languages(cfg.get("languages") or [])
    return []


@router.get("/audio/voices", dependencies=[Depends(require_v1_api_key)])
@router.get("/voices", dependencies=[Depends(require_v1_api_key)])
def get_audio_voices(
    request: Request,
    gender: str = "",
    accent: str = "",
    language: str = "",
    tone: str = "",
    q: str = "",
):
    allowed_langs = _get_allowed_voice_languages(request.app.state.db)
    voices = list_voices(
        gender=gender,
        accent=accent,
        language=language,
        tone=tone,
        q=q,
        allowed_languages=allowed_langs,
    )
    base = str(request.base_url).rstrip("/")
    preview_svc = getattr(request.app.state, "voice_preview", None)
    enriched = []
    for v in voices:
        lang_group = get_voice_language_group(v)
        preview_url = f"{base}/v1/audio/voices/{v['id']}/preview"
        if has_multiple_language_groups(v["id"]):
            preview_url = f"{preview_url}?language={quote(lang_group)}"
        v_copy = {
            "id": v["id"],
            "name": v["name"],
            "gender": v["gender"],
            "accent": v["accent"],
            "tone": v["tone"],
            "language": v["language"],
            "language_group": lang_group,
            "description": v.get("description", ""),
            "long_description": v.get("long_description", ""),
            "cached": preview_svc.is_cached(v["id"], lang_group) if preview_svc else False,
            "preview_url": preview_url,
        }
        enriched.append(v_copy)
    return {"object": "list", "total": len(enriched), "data": enriched}


@router.get("/audio/voices/{voice_id:path}/preview", dependencies=[Depends(require_v1_api_key)])
@router.get("/voices/{voice_id:path}/preview", dependencies=[Depends(require_v1_api_key)])
async def preview_voice(
    voice_id: str,
    request: Request,
    response_format: str = "mp3",
    refresh: bool = False,
    language: str = "",
):
    db = request.app.state.db
    preview_svc = getattr(request.app.state, "voice_preview", None)
    if not preview_svc:
        raise HTTPException(status_code=500, detail="Voice preview service unavailable")

    raw_voice = voice_id.strip()
    voice_info = resolve_voice(raw_voice, language=language)
    if not voice_info:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Voice '{raw_voice}' not found. See GET /v1/audio/voices for available voices.", "type": "invalid_request_error"}},
        )

    allowed_langs = _get_allowed_voice_languages(db)
    if allowed_langs and not is_voice_allowed(voice_info, allowed_langs):
        v_group = get_voice_language_group(voice_info)
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        f"Voice '{voice_info['name']}' ({voice_info['id']}) belongs to language group '{v_group}', "
                        f"which is not currently enabled in settings. Allowed languages: {', '.join(allowed_langs)}. "
                        "See GET /v1/audio/voices for currently available voices."
                    ),
                    "type": "invalid_request_error",
                }
            },
        )

    fmt = (response_format or "mp3").strip().lower()
    if fmt not in {"mp3", "url", "json"}:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Unsupported response_format '{response_format}'. Only 'mp3', 'url', and 'json' are supported.", "type": "invalid_request_error"}},
        )

    try:
        res = await run_in_threadpool(
            preview_svc.get_or_generate_preview,
            voice_info,
            refresh=refresh,
        )
    except NoCandidateAccountError as exc:
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("Voice preview generation failed for %s", voice_info["id"])
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})

    if fmt in {"url", "json"}:
        base = str(request.base_url).rstrip("/")
        preview_url = f"{base}/v1/voice-previews/{res['filename']}"
        return {
            "voice_id": res["voice_id"],
            "voice_name": res["voice_name"],
            "language_group": res["language_group"],
            "sample_text": res["sample_text"],
            "cached": res["cached"],
            "url": preview_url,
            "bytes": res["bytes"],
        }

    return FileResponse(
        res["file_path"],
        media_type="audio/mpeg",
        filename=res["filename"],
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Voice-Preview-Cache": "HIT" if res["cached"] else "MISS",
        },
    )


@router.post("/audio/speech", dependencies=[Depends(require_v1_api_key)])
async def create_speech(body: SpeechReq, request: Request):
    cfg = request.app.state.cfg
    db = request.app.state.db
    pool = request.app.state.wss_pool

    text = (body.input or "").strip()
    if not text or len(text) > 4096:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "input must be non-empty and up to 4096 characters", "type": "invalid_request_error"}},
        )

    fmt = (body.response_format or "mp3").strip().lower()
    if fmt not in SUPPORTED_SPEECH_FORMATS:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Unsupported response_format '{body.response_format}'. Only 'mp3', 'wav', 'url', and 'json' are supported.", "type": "invalid_request_error"}},
        )

    allowed_langs = _get_allowed_voice_languages(db)
    voice_info = resolve_voice(body.voice)
    if not voice_info:
        v_name = body.voice or ""
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"Voice '{v_name}' not found. See GET /v1/audio/voices for available voices.", "type": "invalid_request_error"}},
        )

    if allowed_langs and not is_voice_allowed(voice_info, allowed_langs):
        v_group = get_voice_language_group(voice_info)
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        f"Voice '{voice_info['name']}' ({voice_info['id']}) belongs to language group '{v_group}', "
                        f"which is not currently enabled in settings. Allowed languages: {', '.join(allowed_langs)}. "
                        "See GET /v1/audio/voices for currently available voices."
                    ),
                    "type": "invalid_request_error",
                }
            },
        )

    _ensure_capability_or_503(pool, "speech")

    prompt = _build_speech_prompt(
        text=text,
        voice_id=voice_info["id"],
        voice_name=voice_info["name"],
        instructions=body.instructions,
        speed=body.speed,
        language=get_voice_language_code(voice_info),
        output_format="wav" if fmt == "wav" else "mp3",
    )
    timeout = float(body.timeout or 180)
    task_id = f"aud_{secrets.token_hex(6)}"
    db.create_task(
        task_id,
        "audio",
        status="running",
        model=body.model,
        prompt_preview=text[:200],
        input_request=body.model_dump(exclude_none=True),
    )
    t0 = time.time()

    try:
        res = await run_in_threadpool(
            pool.generate_media,
            prompt,
            "audio",
            None,
            timeout,
            skip_system_prompt=True,
            on_account_selected=lambda aid, sid: db.update_task(task_id, account_id=aid, session_id=sid),
        )
        final_filename = res["filename"]
        file_path = os.path.join(cfg.media_dir, final_filename)
        final_size = res.get("size_bytes", res.get("bytes", 0))
        converted = False

        if fmt in BINARY_SPEECH_FORMATS:
            file_path, converted = await run_in_threadpool(ensure_audio_file_format, file_path, fmt)
            final_filename = os.path.basename(file_path)
            if os.path.isfile(file_path):
                final_size = os.path.getsize(file_path)

        db.update_task(
            task_id,
            status="completed",
            account_id=res["account_id"],
            session_id=res["session_id"],
            media_filename=final_filename,
            latency_ms=int((time.time() - t0) * 1000),
        )

        base = str(request.base_url).rstrip("/")
        media_url = f"{base}/v1/media/{final_filename}"
        if fmt in {"url", "json"}:
            return {
                "created": int(time.time()),
                "model": body.model,
                "voice": voice_info["id"],
                "voice_name": voice_info["name"],
                "url": media_url,
                "kind": "audio",
                "bytes": final_size,
            }

        return FileResponse(
            file_path,
            media_type=AUDIO_MEDIA_TYPES[fmt],
            filename=final_filename,
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Muse-Media-Url": media_url,
                "X-Audio-Converted": "1" if converted else "0",
            },
        )
    except NoCandidateAccountError as exc:
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=503, detail={"error": {"message": str(exc), "type": "service_unavailable_error"}})
    except Exception as exc:
        logger.exception("POST %s failed (task_id=%s)", request.url.path, task_id)
        _safe_fail_task(db, task_id, str(exc), int((time.time() - t0) * 1000))
        raise HTTPException(status_code=502, detail={"error": {"message": str(exc), "type": "server_error"}})


@router.get("/media/{filename}")
def serve_media(filename: str, request: Request):
    cfg = request.app.state.cfg
    safe = os.path.basename(filename)
    p = os.path.join(cfg.media_dir, safe)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/voice-previews/{filename}")
def serve_voice_preview(filename: str, request: Request):
    cfg = request.app.state.cfg
    safe = os.path.basename(filename)
    p = os.path.join(cfg.voice_preview_dir, safe)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Voice preview not found")
    return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})
