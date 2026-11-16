"""Persistent WSS connection pool with LRU scheduling and failover."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from typing import Any, Iterator

from config import Config
from db import Database
from muse_wss import MuseAuthError, MuseWSSError, MuseWSSClient


def is_quota_exhausted(quota_raw: str | dict[str, Any] | None) -> bool:
    """Return True only when weekly quota is 100% used and no bonus quota remains."""
    if not quota_raw:
        return False
    if isinstance(quota_raw, str):
        try:
            quota = json.loads(quota_raw)
        except json.JSONDecodeError:
            return False
    else:
        quota = quota_raw
    if not isinstance(quota, dict):
        return False

    weekly_pct = quota.get("weekly_pct")
    extra_pct = quota.get("extra_pct")
    if isinstance(weekly_pct, (int, float)) and float(weekly_pct) >= 100.0:
        if isinstance(extra_pct, (int, float)) and float(extra_pct) < 100.0:
            return False
        return True
    return False


class WSSPool:
    """Maintains persistent encrypted WSS tunnels per healthy/enabled account."""

    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self._lock = threading.Lock()
        self._clients: dict[str, MuseWSSClient] = {}
        self._account_locks: dict[str, threading.Lock] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _get_acc_lock(self, account_id: str) -> threading.Lock:
        with self._lock:
            if account_id not in self._account_locks:
                self._account_locks[account_id] = threading.Lock()
            return self._account_locks[account_id]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for c in self._clients.values() if c.is_connected)

    def is_connected(self, account_id: str) -> bool:
        with self._lock:
            c = self._clients.get(account_id)
            return bool(c and c.is_connected)

    def close_account(self, account_id: str) -> None:
        with self._lock:
            c = self._clients.pop(account_id, None)
        if c:
            c.close()

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.close()

    def get_client(self, account_id: str) -> MuseWSSClient:
        acc = self.db.get_account(account_id)
        if not acc:
            raise MuseWSSError(f"Account {account_id} not found")
        if not acc["enabled"]:
            raise MuseWSSError(f"Account {account_id} is disabled")

        lock = self._get_acc_lock(account_id)
        with lock:
            with self._lock:
                client = self._clients.get(account_id)
            if client and client.is_connected:
                return client

            cookies = json.loads(acc["cookies_json"])
            client = MuseWSSClient(cookies=cookies, proxy_url=acc.get("effective_proxy_url") or "")
            client.connect(timeout=25.0)
            with self._lock:
                self._clients[account_id] = client
            return client

    def test_account(self, account_id: str) -> dict[str, Any]:
        t0 = time.time()
        try:
            self.close_account(account_id)
            acc = self.db.get_account(account_id)
            if not acc:
                raise MuseWSSError("Account not found")
            cookies = json.loads(acc["cookies_json"])
            client = MuseWSSClient(cookies=cookies, proxy_url=acc.get("effective_proxy_url") or "")
            client.connect(timeout=25.0)
            status, _ = client.request("GET", "/health", timeout=15.0)
            if status != 200:
                client.close()
                raise MuseWSSError(f"GET /health returned status {status}")
            if acc["enabled"]:
                with self._lock:
                    self._clients[account_id] = client
            else:
                client.close()
            self.db.update_account(account_id, status="healthy", last_error="")
            return {"ok": True, "status": "healthy", "vm_name": client.vm_name, "latency_ms": int((time.time() - t0) * 1000)}
        except MuseAuthError as exc:
            self.db.update_account(account_id, status="expired", last_error=str(exc))
            return {"ok": False, "status": "expired", "error": str(exc)}
        except Exception as exc:
            self.db.update_account(account_id, status="cooldown", last_error=str(exc))
            return {"ok": False, "status": "cooldown", "error": str(exc)}

    def _candidate_accounts(self) -> list[dict[str, Any]]:
        accs = [
            a for a in self.db.list_accounts()
            if a["enabled"]
            and a["status"] in ("healthy", "unknown", "cooldown")
            and not is_quota_exhausted(a.get("quota_json"))
        ]
        # Prefer healthy first, then LRU last_used_at
        accs.sort(key=lambda a: (0 if a["status"] == "healthy" else 1, a.get("last_used_at") or 0.0))
        return accs

    def _no_candidate_error(self) -> str:
        enabled = [a for a in self.db.list_accounts() if a["enabled"]]
        if enabled and all(is_quota_exhausted(a.get("quota_json")) for a in enabled):
            return "All enabled accounts have exhausted their quota"
        return "No healthy enabled accounts available"

    def start_background(self, interval_seconds: float = 60.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            name="wss-tunnel-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _monitor_loop(self, interval_seconds: float) -> None:
        # Short initial delay so FastAPI finishes startup cleanly
        if self._stop.wait(2.0):
            return
        while not self._stop.is_set():
            try:
                self.maintain_tunnels()
            except Exception:
                pass
            self._stop.wait(interval_seconds)

    def maintain_tunnels(self) -> None:
        """Keep WSS tunnels connected & verify health for eligible enabled accounts."""
        for acc in self.db.list_accounts():
            if self._stop.is_set():
                return
            aid = acc["id"]
            if not acc["enabled"] or acc["status"] == "expired" or is_quota_exhausted(acc.get("quota_json")):
                if self.is_connected(aid):
                    self.close_account(aid)
                continue
            if not self.is_connected(aid):
                self.test_account(aid)
                continue
            # Verify existing tunnel with lightweight /health check if lock is free
            lock = self._get_acc_lock(aid)
            if not lock.acquire(blocking=False):
                continue
            try:
                with self._lock:
                    client = self._clients.get(aid)
                if client and client.is_connected:
                    st, _ = client.request("GET", "/health", timeout=10.0)
                    if st != 200:
                        raise MuseWSSError(f"WSS /health returned {st}")
                    if acc["status"] != "healthy":
                        self.db.update_account(aid, status="healthy", last_error="")
            except MuseAuthError as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="expired", last_error=str(exc))
            except Exception as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="cooldown", last_error=str(exc))
            finally:
                lock.release()

    def _apply_system_prompt(self, prompt: str) -> str:
        settings = self.db.get_settings()
        sp = settings.get("system_prompt") or {}
        if sp.get("enabled") and sp.get("prompt"):
            return f"<system>\n{sp['prompt'].strip()}\n</system>\n\n{prompt}"
        return prompt

    def _build_chat_items(self, prompt: str, images: list[tuple[bytes, str]] | None = None) -> list[dict[str, Any]]:
        import base64 as _b64

        full_prompt = self._apply_system_prompt(prompt)
        items: list[dict[str, Any]] = []
        for media_bytes, mime in (images or []):
            b64 = _b64.b64encode(media_bytes).decode("ascii")
            if mime.startswith("image/"):
                items.append({"type": "image", "mime_type": mime, "data_base64": b64})
            else:
                items.append({"type": "file", "mime_type": mime, "data_base64": b64})
        items.append({"type": "text", "text": full_prompt})
        return items

    def execute_chat(self, prompt: str, images: list[tuple[bytes, str]] | None = None,
                     timeout: float = 180.0) -> tuple[str, str, str]:
        """Run non-streaming chat/prompt and return (account_id, session_id, response_text)."""
        items = self._build_chat_items(prompt, images)
        candidates = self._candidate_accounts()
        if not candidates:
            raise MuseWSSError(self._no_candidate_error())

        last_err: Exception | None = None
        for acc in candidates:
            aid = acc["id"]
            try:
                client = self.get_client(aid)
                self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                session_id = str(uuid.uuid4())
                st, raw = client.request(
                    "POST", "/chat/stream",
                    {"items": items, "session_id": session_id},
                    timeout=30.0,
                )
                if st == 401:
                    raise MuseAuthError("chat.stream returned 401")
                if st >= 400:
                    raise MuseWSSError(f"chat.stream HTTP {st}: {raw[:200]!r}")

                # Wait for completion via subscribe
                for _, chunk in client.stream_rpc("POST", "/chat/subscribe", {"session_id": session_id}, timeout=timeout):
                    txt = chunk.decode("utf-8", errors="replace")
                    for line in txt.splitlines():
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("event") == "task.status" and (ev.get("payload") or {}).get("status") == "completed":
                            return aid, session_id, self._extract_latest_assistant_text(client, session_id)
                return aid, session_id, self._extract_latest_assistant_text(client, session_id)
            except MuseAuthError as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="expired", last_error=str(exc))
                last_err = exc
            except Exception as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="cooldown", last_error=str(exc))
                last_err = exc

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def stream_chat_events(self, prompt: str, images: list[tuple[bytes, str]] | None = None,
                           timeout: float = 180.0) -> Iterator[tuple[str, str]]:
        """Yield (event_type, text_delta_or_done) for SSE streaming."""
        items = self._build_chat_items(prompt, images)
        candidates = self._candidate_accounts()
        if not candidates:
            raise MuseWSSError(self._no_candidate_error())

        last_err: Exception | None = None
        for acc in candidates:
            aid = acc["id"]
            try:
                client = self.get_client(aid)
                self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                session_id = str(uuid.uuid4())
                st, raw = client.request(
                    "POST", "/chat/stream",
                    {"items": items, "session_id": session_id},
                    timeout=30.0,
                )
                if st == 401:
                    raise MuseAuthError("chat.stream returned 401")
                if st >= 400:
                    raise MuseWSSError(f"chat.stream HTTP {st}: {raw[:200]!r}")

                sent_len = 0
                for _, chunk in client.stream_rpc("POST", "/chat/subscribe", {"session_id": session_id}, timeout=timeout):
                    txt = chunk.decode("utf-8", errors="replace")
                    for line in txt.splitlines():
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ev_name = ev.get("event", "")
                        payload = ev.get("payload") or {}
                        if ev_name in ("message.delta", "delta.text") and isinstance(payload.get("delta"), str):
                            yield "delta", payload["delta"]
                            sent_len += len(payload["delta"])
                        elif ev_name == "task.status" and payload.get("status") == "completed":
                            if sent_len == 0:
                                final_txt = self._extract_latest_assistant_text(client, session_id)
                                if final_txt:
                                    yield "delta", final_txt
                            yield "done", session_id
                            return
                yield "done", session_id
                return
            except MuseAuthError as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="expired", last_error=str(exc))
                last_err = exc
            except Exception as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="cooldown", last_error=str(exc))
                last_err = exc

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def generate_media(self, prompt: str, expect_kind: str = "image",
                       images: list[tuple[bytes, str]] | None = None,
                       timeout: float = 300.0) -> dict[str, Any]:
        """Generate or edit image/video via WSS and download binary to data/media/."""
        items = self._build_chat_items(prompt, images)

        candidates = self._candidate_accounts()
        if not candidates:
            raise MuseWSSError(self._no_candidate_error())

        last_err: Exception | None = None
        for acc in candidates:
            aid = acc["id"]
            try:
                client = self.get_client(aid)
                self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                session_id = str(uuid.uuid4())
                st, raw = client.request(
                    "POST", "/chat/stream",
                    {"items": items, "session_id": session_id},
                    timeout=30.0,
                )
                if st == 401:
                    raise MuseAuthError("chat.stream returned 401")
                if st >= 400:
                    raise MuseWSSError(f"chat.stream HTTP {st}: {raw[:200]!r}")

                for _, chunk in client.stream_rpc("POST", "/chat/subscribe", {"session_id": session_id}, timeout=timeout):
                    txt = chunk.decode("utf-8", errors="replace")
                    for line in txt.splitlines():
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("event") == "task.status" and (ev.get("payload") or {}).get("status") == "completed":
                            return self._fetch_media_from_history(client, aid, session_id, expect_kind)

                return self._fetch_media_from_history(client, aid, session_id, expect_kind)
            except MuseAuthError as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="expired", last_error=str(exc))
                last_err = exc
            except Exception as exc:
                self.close_account(aid)
                self.db.update_account(aid, status="cooldown", last_error=str(exc))
                last_err = exc

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def _extract_latest_assistant_text(self, client: MuseWSSClient, session_id: str) -> str:
        st, body = client.request("GET", f"/chat/history?session_id={session_id}", timeout=20.0)
        if st != 200:
            return ""
        data = json.loads(body.decode("utf-8", errors="replace"))
        events = ((data.get("result") or {}).get("chat_events") or [])
        texts = [
            e.get("display_text", "")
            for e in events
            if e.get("role") == "assistant" and e.get("event_name") == "message.assistant" and e.get("display_text")
        ]
        return texts[-1] if texts else ""

    def _fetch_media_from_history(self, client: MuseWSSClient, account_id: str,
                                  session_id: str, expect_kind: str) -> dict[str, Any]:
        media_path = ""
        mime_type = ""
        events: list[dict[str, Any]] = []
        for attempt in range(3):
            st, body = client.request("GET", f"/chat/history?session_id={session_id}", timeout=20.0)
            if st != 200:
                raise MuseWSSError(f"GET /chat/history returned {st}")
            data = json.loads(body.decode("utf-8", errors="replace"))
            events = ((data.get("result") or {}).get("chat_events") or [])
            for ev in reversed(events):
                for res in ev.get("resources") or []:
                    kind = res.get("kind", "")
                    if expect_kind in kind or not media_path:
                        meta_raw = res.get("metadata")
                        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
                        p = meta.get("path") or res.get("uri") or ""
                        if p.startswith("sandbox://"):
                            p = p[len("sandbox://"):]
                        if p:
                            media_path = p.lstrip("/")
                            mime_type = res.get("mime_type") or meta.get("mime_type") or ""
                            break
                if media_path:
                    break
                # Also check delta.presentation -> payload.data.images / videos
                pdata = ((ev.get("payload") or {}).get("data") or {})
                for key in ("images", "videos") if expect_kind == "image" else ("videos", "images"):
                    for item in pdata.get(key) or []:
                        p = item.get("path") or ""
                        if p.startswith("sandbox://"):
                            p = p[len("sandbox://"):]
                        if p:
                            media_path = p.lstrip("/")
                            mime_type = item.get("mime") or ""
                            break
                    if media_path:
                        break
                if media_path:
                    break
            if media_path:
                break
            if attempt < 2:
                time.sleep(0.8)

        if not media_path:
            assistant_txt = self._extract_latest_assistant_text(client, session_id)
            raise MuseWSSError(f"No {expect_kind} resource produced. Assistant replied: {assistant_txt[:200]}")

        dl_st, media_bytes = client.request("GET", f"/media/raw/{media_path}", timeout=120.0)
        if dl_st != 200 or not media_bytes:
            raise MuseWSSError(f"Failed to download /media/raw/{media_path}: status={dl_st}")

        ext = os.path.splitext(media_path)[1] or (".mp4" if expect_kind == "video" else ".png")
        filename = f"{expect_kind[:3]}_{secrets.token_hex(6)}{ext}"
        out_path = os.path.join(self.cfg.media_dir, filename)
        with open(out_path, "wb") as f:
            f.write(media_bytes)

        return {
            "account_id": account_id,
            "session_id": session_id,
            "filename": filename,
            "mime_type": mime_type or ("video/mp4" if expect_kind == "video" else "image/png"),
            "size_bytes": len(media_bytes),
        }
