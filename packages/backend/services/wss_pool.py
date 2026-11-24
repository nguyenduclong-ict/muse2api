"""Persistent WSS connection pool with LRU scheduling and failover."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import secrets
import threading
import time
import uuid
from typing import Any, Callable, Iterator

from config import Config
from db import Database, parse_supported_models
from muse_wss import MuseAuthError, MuseWSSError, MuseWSSClient

logger = logging.getLogger(__name__)

_EXPECT_KIND_TO_CAPABILITY: dict[str, str] = {
    "chat": "chat",
    "image": "image",
    "video": "video",
    "audio": "speech",
    "speech": "speech",
}


def _as_dict(val: Any) -> dict[str, Any]:
    """Coerce a dict or JSON-encoded dict string to a dict, else empty dict."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _iter_media_items(raw: Any) -> list[Any]:
    """Normalize a media collection (list, dict, or single string path) into a list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, (dict, str)) and raw:
        return [raw]
    return []


class NoCandidateAccountError(MuseWSSError):
    """Raised when no enabled healthy account can serve the requested capability."""


class AccountResettingError(MuseWSSError):
    """Raised when an account is reserved for reset before a request can start."""


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
        self._in_flight: dict[str, int] = {}
        self._resetting_accounts: set[str] = set()
        self._reset_cond = threading.Condition(self._lock)
        self._waiters_count: int = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._reauth_fn: Callable[[str], dict[str, Any]] | None = None

    def set_reauth_callback(self, fn: Callable[[str], dict[str, Any]] | None) -> None:
        self._reauth_fn = fn

    def _try_reauth(self, account_id: str) -> bool:
        if self._reauth_fn is None:
            return False
        try:
            res = self._reauth_fn(account_id)
            return isinstance(res, dict) and res.get("ok") is True
        except Exception as exc:
            logger.warning("One-Tap re-auth callback failed for %s: %s", account_id, exc)
            return False

    def in_flight_count(self, account_id: str) -> int:
        with self._lock:
            return self._in_flight.get(account_id, 0)

    def begin_reset(self, account_id: str, *, require_idle: bool = False) -> bool:
        with self._lock:
            if require_idle and (account_id in self._resetting_accounts or self._in_flight.get(account_id, 0) > 0):
                return False
            self._resetting_accounts.add(account_id)
            return True

    def end_reset(self, account_id: str) -> None:
        with self._reset_cond:
            self._resetting_accounts.discard(account_id)
            self._reset_cond.notify_all()

    def is_resetting(self, account_id: str) -> bool:
        with self._lock:
            return account_id in self._resetting_accounts

    def wait_for_in_flight_drain(
        self,
        account_id: str,
        timeout: float,
        stop_event: threading.Event | None = None,
    ) -> bool:
        deadline = time.time() + max(0.0, float(timeout))
        with self._reset_cond:
            while self._in_flight.get(account_id, 0) > 0:
                if (stop_event is not None and stop_event.is_set()) or self._stop.is_set():
                    return False
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                wait_s = min(0.5, remaining) if stop_event is not None else remaining
                self._reset_cond.wait(timeout=wait_s)
            return True

    @contextmanager
    def _track_in_flight(self, account_id: str) -> Iterator[None]:
        with self._lock:
            if account_id in self._resetting_accounts:
                raise AccountResettingError(f"Account {account_id} is currently resetting")
            self._in_flight[account_id] = self._in_flight.get(account_id, 0) + 1
        try:
            yield
        finally:
            with self._reset_cond:
                cur = self._in_flight.get(account_id, 0)
                if cur <= 1:
                    self._in_flight.pop(account_id, None)
                    self._reset_cond.notify_all()
                else:
                    self._in_flight[account_id] = cur - 1

    def healthy_available_count(self, capability: str | None = None) -> int:
        cap = capability.strip().lower() if capability else None
        with self._lock:
            resetting = set(self._resetting_accounts)
        return sum(
            1
            for a in self.db.list_accounts()
            if a["enabled"]
            and a["status"] == "healthy"
            and a["id"] not in resetting
            and not is_quota_exhausted(a.get("quota_json"))
            and (not cap or cap in parse_supported_models(a.get("supported_models_json")))
        )

    def can_auto_reset_account(self, acc: dict[str, Any]) -> tuple[bool, str | None]:
        for cap in parse_supported_models(acc.get("supported_models_json")):
            if self.healthy_available_count(cap) < 2:
                return False, f"insufficient_healthy_pool:{cap}"
        return True, None

    def _is_resetting(self, account_id: str) -> bool:
        if self.is_resetting(account_id):
            return True
        acc = self.db.get_account(account_id)
        return bool(acc and acc.get("status") == "resetting")

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
        if acc.get("status") == "resetting" or self.is_resetting(account_id):
            raise AccountResettingError(f"Account {account_id} is currently resetting")

        lock = self._get_acc_lock(account_id)
        with lock:
            with self._lock:
                client = self._clients.get(account_id)
            if client and client.is_connected:
                return client

            cookies = json.loads(acc["cookies_json"])
            client = MuseWSSClient(cookies=cookies, proxy_url=acc.get("effective_proxy_url") or "")
            try:
                client.connect(timeout=25.0)
            except MuseAuthError:
                if not self._try_reauth(account_id):
                    raise
                acc = self.db.get_account(account_id)
                if not acc:
                    raise MuseWSSError(f"Account {account_id} not found")
                if not acc["enabled"]:
                    raise MuseWSSError(f"Account {account_id} is disabled")
                if acc.get("status") == "resetting":
                    raise MuseWSSError(f"Account {account_id} is currently resetting")
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
            try:
                client.connect(timeout=25.0)
            except MuseAuthError:
                if not self._try_reauth(account_id):
                    raise
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

    def _candidate_accounts_with_resetting(
        self,
        capability: str | None,
        resetting: set[str],
    ) -> list[dict[str, Any]]:
        cap = capability.strip().lower() if capability else None
        accs = [
            a for a in self.db.list_accounts()
            if a["enabled"]
            and a["status"] in ("healthy", "unknown", "cooldown")
            and a["id"] not in resetting
            and not is_quota_exhausted(a.get("quota_json"))
            and (not cap or cap in parse_supported_models(a.get("supported_models_json")))
        ]
        # Prefer healthy first, then LRU last_used_at
        accs.sort(key=lambda a: (0 if a["status"] == "healthy" else 1, a.get("last_used_at") or 0.0))
        return accs

    def _candidate_accounts(self, capability: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            resetting = set(self._resetting_accounts)
        return self._candidate_accounts_with_resetting(capability, resetting)

    def _has_resetting_account_with_resetting(
        self,
        capability: str | None,
        resetting: set[str],
    ) -> bool:
        cap = capability.strip().lower() if capability else None
        for a in self.db.list_accounts():
            if not a["enabled"]:
                continue
            if is_quota_exhausted(a.get("quota_json")):
                continue
            if cap and cap not in parse_supported_models(a.get("supported_models_json")):
                continue
            if a.get("status") == "resetting" or a["id"] in resetting:
                return True
        return False

    def has_resetting_account(self, capability: str | None = None) -> bool:
        with self._lock:
            resetting = set(self._resetting_accounts)
        return self._has_resetting_account_with_resetting(capability, resetting)

    def _no_candidate_error(self, capability: str | None = None) -> str:
        cap = capability.strip().lower() if capability else None
        enabled = [a for a in self.db.list_accounts() if a["enabled"]]
        if cap:
            matching = [a for a in enabled if cap in parse_supported_models(a.get("supported_models_json"))]
            if not matching:
                return f"No enabled accounts support '{cap}'"
            if all(is_quota_exhausted(a.get("quota_json")) for a in matching):
                return f"All enabled accounts supporting '{cap}' have exhausted their quota"
            return f"No healthy enabled accounts available for '{cap}'"
        if enabled and all(is_quota_exhausted(a.get("quota_json")) for a in enabled):
            return "All enabled accounts have exhausted their quota"
        return "No healthy enabled accounts available"

    def ensure_candidate(self, capability: str) -> list[dict[str, Any]]:
        """Return candidate accounts for capability or raise NoCandidateAccountError."""
        candidates = self._candidate_accounts(capability)
        if not candidates:
            raise NoCandidateAccountError(self._no_candidate_error(capability))
        return candidates

    def ensure_candidate_or_resetting(self, capability: str) -> None:
        """Allow async tasks to queue if a matching account is currently resetting."""
        if self._candidate_accounts(capability):
            return
        if self.cfg.reset_wait_timeout_seconds > 0 and self.has_resetting_account(capability):
            return
        raise NoCandidateAccountError(self._no_candidate_error(capability))

    def wait_for_candidate(self, capability: str, timeout: float | None = None) -> list[dict[str, Any]]:
        """Return candidates immediately or wait until a resetting account becomes available."""
        try:
            candidates = self.ensure_candidate(capability)
            if candidates:
                return candidates
        except NoCandidateAccountError:
            pass

        cfg_wait = max(0.0, float(self.cfg.reset_wait_timeout_seconds))
        if timeout is not None and float(timeout) > 0:
            effective_wait = min(cfg_wait, float(timeout))
        else:
            effective_wait = cfg_wait

        if effective_wait <= 0 or not self.has_resetting_account(capability):
            raise NoCandidateAccountError(self._no_candidate_error(capability))

        deadline = time.time() + effective_wait
        with self._reset_cond:
            if self._waiters_count >= max(1, int(self.cfg.reset_max_waiters)):
                raise NoCandidateAccountError("Too many requests waiting for account reset")
            self._waiters_count += 1
            try:
                while True:
                    resetting = set(self._resetting_accounts)
                    candidates = self._candidate_accounts_with_resetting(capability, resetting)
                    if candidates:
                        return candidates
                    if self._stop.is_set() or not self._has_resetting_account_with_resetting(capability, resetting):
                        raise NoCandidateAccountError(self._no_candidate_error(capability))
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise NoCandidateAccountError(self._no_candidate_error(capability))
                    self._reset_cond.wait(timeout=min(1.0, remaining))
            finally:
                self._waiters_count -= 1

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
            if not acc["enabled"] or acc["status"] in ("expired", "resetting") or self.is_resetting(aid) or is_quota_exhausted(acc.get("quota_json")):
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

    def _build_chat_items(self, prompt: str, images: list[tuple[bytes, str]] | None = None,
                          skip_system_prompt: bool = False) -> list[dict[str, Any]]:
        import base64 as _b64

        full_prompt = prompt if skip_system_prompt else self._apply_system_prompt(prompt)
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
        cfg_wait = max(0.0, float(self.cfg.reset_wait_timeout_seconds))
        wait_budget = min(cfg_wait, float(timeout)) if (timeout and timeout > 0) else cfg_wait
        wait_deadline = time.time() + wait_budget
        candidates = self.wait_for_candidate("chat", timeout=timeout)

        last_err: Exception | None = None
        while True:
            saw_resetting = False
            for acc in candidates:
                aid = acc["id"]
                try:
                    with self._track_in_flight(aid):
                        client = self.get_client(aid)
                        self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                        self.db.increment_requests_since_reset(aid)
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
                                if not isinstance(ev, dict):
                                    continue
                                if ev.get("event") == "task.status" and _as_dict(ev.get("payload")).get("status") == "completed":
                                    return aid, session_id, self._extract_latest_assistant_text(client, session_id)
                        return aid, session_id, self._extract_latest_assistant_text(client, session_id)
                except AccountResettingError as exc:
                    logger.info("execute_chat skipped resetting account %s: %s", aid, exc)
                    saw_resetting = True
                    last_err = exc
                except MuseAuthError as exc:
                    logger.warning("execute_chat auth error on account %s: %s", aid, exc)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="expired", last_error=str(exc))
                    last_err = exc
                except Exception as exc:
                    logger.exception("execute_chat failed on account %s", aid)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="cooldown", last_error=str(exc))
                    last_err = exc

            if saw_resetting and self.has_resetting_account("chat"):
                rem_wait = wait_deadline - time.time()
                if rem_wait > 0:
                    candidates = self.wait_for_candidate("chat", timeout=rem_wait)
                    continue
            break

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def stream_chat_events(self, prompt: str, images: list[tuple[bytes, str]] | None = None,
                           timeout: float = 180.0) -> Iterator[tuple[str, str]]:
        """Yield (event_type, text_delta_or_done) for SSE streaming."""
        items = self._build_chat_items(prompt, images)
        cfg_wait = max(0.0, float(self.cfg.reset_wait_timeout_seconds))
        wait_budget = min(cfg_wait, float(timeout)) if (timeout and timeout > 0) else cfg_wait
        wait_deadline = time.time() + wait_budget
        candidates = self.wait_for_candidate("chat", timeout=timeout)

        last_err: Exception | None = None
        while True:
            saw_resetting = False
            sent_len = 0
            for acc in candidates:
                aid = acc["id"]
                try:
                    with self._track_in_flight(aid):
                        client = self.get_client(aid)
                        self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                        self.db.increment_requests_since_reset(aid)
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
                                if not isinstance(ev, dict):
                                    continue
                                ev_name = ev.get("event", "")
                                payload = _as_dict(ev.get("payload"))
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
                except AccountResettingError as exc:
                    logger.info("stream_chat_events skipped resetting account %s: %s", aid, exc)
                    saw_resetting = True
                    last_err = exc
                except MuseAuthError as exc:
                    logger.warning("stream_chat_events auth error on account %s: %s", aid, exc)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="expired", last_error=str(exc))
                    last_err = exc
                except Exception as exc:
                    logger.exception("stream_chat_events failed on account %s", aid)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="cooldown", last_error=str(exc))
                    last_err = exc

            if saw_resetting and sent_len == 0 and self.has_resetting_account("chat"):
                rem_wait = wait_deadline - time.time()
                if rem_wait > 0:
                    candidates = self.wait_for_candidate("chat", timeout=rem_wait)
                    continue
            break

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def generate_media(self, prompt: str, expect_kind: str = "image",
                       images: list[tuple[bytes, str]] | None = None,
                       timeout: float = 300.0,
                       skip_system_prompt: bool = False,
                       idle_timeout: float | None = None,
                       on_account_selected: Any = None,
                       expected_output_filename: str | None = None) -> dict[str, Any]:
        """Generate or edit image/video/audio via WSS and download binary to data/media/."""
        items = self._build_chat_items(prompt, images, skip_system_prompt=skip_system_prompt)
        capability = _EXPECT_KIND_TO_CAPABILITY.get(expect_kind, expect_kind)
        cfg_wait = max(0.0, float(self.cfg.reset_wait_timeout_seconds))
        wait_budget = min(cfg_wait, float(timeout)) if (timeout and timeout > 0) else cfg_wait
        wait_deadline = time.time() + wait_budget
        candidates = self.wait_for_candidate(capability, timeout=timeout)

        total_deadline = time.time() + max(10.0, float(timeout))
        default_idle = 180.0 if expect_kind == "video" else 120.0
        effective_idle = float(idle_timeout) if (idle_timeout and idle_timeout > 0) else default_idle

        last_err: Exception | None = None
        while True:
            saw_resetting = False
            for acc in candidates:
                remaining = total_deadline - time.time()
                if remaining <= 5.0:
                    last_err = last_err or TimeoutError(f"Media generation timed out after {int(timeout)}s")
                    break
                aid = acc["id"]
                try:
                    with self._track_in_flight(aid):
                        client = self.get_client(aid)
                        self.db.update_account(aid, last_used_at=time.time(), status="healthy", last_error="")
                        self.db.increment_requests_since_reset(aid)
                        session_id = str(uuid.uuid4())
                        if callable(on_account_selected):
                            try:
                                on_account_selected(aid, session_id)
                            except Exception:
                                pass
                        st, raw = client.request(
                            "POST", "/chat/stream",
                            {"items": items, "session_id": session_id},
                            timeout=min(30.0, remaining),
                        )
                        if st == 401:
                            raise MuseAuthError("chat.stream returned 401")
                        if st >= 400:
                            raise MuseWSSError(f"chat.stream HTTP {st}: {raw[:200]!r}")

                        stream_rem = max(5.0, total_deadline - time.time())
                        stream_idle = min(effective_idle, stream_rem)
                        for _, chunk in client.stream_rpc(
                            "POST", "/chat/subscribe",
                            {"session_id": session_id},
                            timeout=stream_rem,
                            idle_timeout=stream_idle,
                        ):
                            txt = chunk.decode("utf-8", errors="replace")
                            for line in txt.splitlines():
                                if not line.strip():
                                    continue
                                try:
                                    ev = json.loads(line)
                                except json.JSONDecodeError:
                                    logger.debug("generate_media non-JSON subscribe line (acc=%s, sid=%s): %r", aid, session_id, line[:200])
                                    continue
                                if not isinstance(ev, dict):
                                    logger.debug("generate_media non-dict subscribe event (acc=%s, sid=%s): %r", aid, session_id, ev)
                                    continue
                                logger.debug("generate_media subscribe event (acc=%s, sid=%s, kind=%s): %s", aid, session_id, expect_kind, ev.get("event"))
                                if ev.get("event") == "task.status" and _as_dict(ev.get("payload")).get("status") == "completed":
                                    return self._fetch_media_from_history(
                                        client, aid, session_id, expect_kind,
                                        expected_output_filename=expected_output_filename,
                                    )

                        return self._fetch_media_from_history(
                            client, aid, session_id, expect_kind,
                            expected_output_filename=expected_output_filename,
                        )
                except AccountResettingError as exc:
                    logger.info("generate_media skipped resetting account %s (kind=%s): %s", aid, expect_kind, exc)
                    saw_resetting = True
                    last_err = exc
                except MuseAuthError as exc:
                    logger.warning("generate_media auth error (acc=%s, kind=%s): %s", aid, expect_kind, exc)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="expired", last_error=str(exc))
                    last_err = exc
                except Exception as exc:
                    logger.exception("generate_media failed (acc=%s, kind=%s)", aid, expect_kind)
                    self.close_account(aid)
                    if not self._is_resetting(aid):
                        self.db.update_account(aid, status="cooldown", last_error=str(exc))
                    last_err = exc

            if saw_resetting and (total_deadline - time.time()) > 5.0 and self.has_resetting_account(capability):
                rem_wait = min(wait_deadline - time.time(), total_deadline - time.time() - 5.0)
                if rem_wait > 0:
                    candidates = self.wait_for_candidate(capability, timeout=rem_wait)
                    continue
            break

        raise MuseWSSError(f"All accounts failed: {last_err}")

    def _extract_latest_assistant_text(self, client: MuseWSSClient, session_id: str) -> str:
        st, body = client.request("GET", f"/chat/history?session_id={session_id}", timeout=20.0)
        if st != 200:
            return ""
        data = _as_dict(json.loads(body.decode("utf-8", errors="replace")))
        events = _as_dict(data.get("result")).get("chat_events") or []
        if not isinstance(events, list):
            return ""
        texts = [
            e.get("display_text", "")
            for e in events
            if isinstance(e, dict)
            and e.get("role") == "assistant"
            and e.get("event_name") == "message.assistant"
            and e.get("display_text")
        ]
        return texts[-1] if texts else ""

    def _fetch_media_from_history(self, client: MuseWSSClient, account_id: str,
                                  session_id: str, expect_kind: str,
                                  expected_output_filename: str | None = None) -> dict[str, Any]:
        safe_expected = os.path.basename((expected_output_filename or "").strip())
        expected_lower = safe_expected.lower()
        media_path = ""
        mime_type = ""
        media_bytes = b""
        dl_st = 0
        raw_txt = ""
        events: list[dict[str, Any]] = []

        def _is_match(k: str, m: str, p: str) -> bool:
            if expect_kind == "audio":
                return (
                    "audio" in k.lower()
                    or (m or "").startswith("audio/")
                    or any((p or "").lower().endswith(ext) for ext in (".mp3", ".wav", ".ogg", ".m4a"))
                )
            return expect_kind in k

        def _is_expected_file(p: str) -> bool:
            if not expected_lower:
                return False
            return os.path.basename(p).lower() == expected_lower

        for attempt in range(3):
            st, body = client.request("GET", f"/chat/history?session_id={session_id}", timeout=20.0)
            if st != 200:
                raise MuseWSSError(f"GET /chat/history returned {st}")
            raw_txt = body.decode("utf-8", errors="replace")
            data = _as_dict(json.loads(raw_txt))
            events = _as_dict(data.get("result")).get("chat_events") or []
            if not isinstance(events, list):
                events = []
            logger.debug(
                "history fetch (acc=%s, sid=%s, kind=%s, attempt=%d, events=%d)",
                account_id, session_id, expect_kind, attempt + 1, len(events),
            )

            media_path = ""
            mime_type = ""
            first_match_path = ""
            first_match_mime = ""
            fallback_path = ""
            fallback_mime = ""

            for ev in reversed(events):
                if not isinstance(ev, dict):
                    continue
                for res in _iter_media_items(ev.get("resources")):
                    if isinstance(res, str):
                        kind, p, m = "", res, ""
                    elif isinstance(res, dict):
                        kind = str(res.get("kind") or "")
                        meta = _as_dict(res.get("metadata"))
                        p = str(meta.get("path") or res.get("uri") or "")
                        m = str(res.get("mime_type") or meta.get("mime_type") or "")
                    else:
                        continue
                    if p.startswith("sandbox://"):
                        p = p[len("sandbox://"):]
                    p_clean = p.lstrip("/")
                    if not p_clean:
                        continue
                    if _is_expected_file(p_clean):
                        media_path, mime_type = p_clean, m
                        break
                    if _is_match(kind, m, p_clean) and not first_match_path:
                        first_match_path, first_match_mime = p_clean, m
                    elif not fallback_path:
                        fallback_path, fallback_mime = p_clean, m
                if media_path:
                    break

                pdata = _as_dict(_as_dict(ev.get("payload")).get("data"))
                if expect_kind == "audio":
                    keys_to_check = ("audios", "audio", "files", "images", "videos")
                elif expect_kind == "image":
                    keys_to_check = ("images", "videos")
                else:
                    keys_to_check = ("videos", "images")
                for key in keys_to_check:
                    for item in _iter_media_items(pdata.get(key)):
                        if isinstance(item, str):
                            p, m = item, ""
                        elif isinstance(item, dict):
                            p = str(item.get("path") or item.get("uri") or "")
                            m = str(item.get("mime") or item.get("mime_type") or "")
                        else:
                            continue
                        if p.startswith("sandbox://"):
                            p = p[len("sandbox://"):]
                        p_clean = p.lstrip("/")
                        if not p_clean:
                            continue
                        if _is_expected_file(p_clean):
                            media_path, mime_type = p_clean, m
                            break
                        if _is_match(key, m, p_clean) and not first_match_path:
                            first_match_path, first_match_mime = p_clean, m
                        elif not fallback_path:
                            fallback_path, fallback_mime = p_clean, m
                    if media_path:
                        break
                if media_path:
                    break

            if not media_path:
                if first_match_path:
                    media_path, mime_type = first_match_path, first_match_mime
                elif fallback_path:
                    media_path, mime_type = fallback_path, fallback_mime

            if media_path:
                dl_st, cand_bytes = client.request("GET", f"/media/raw/{media_path}", timeout=120.0)
                if dl_st == 200 and cand_bytes:
                    media_bytes = cand_bytes
                    break

            if expect_kind == "audio" and safe_expected and not media_bytes:
                for direct_path in (
                    f"workspace/your_files/{safe_expected}",
                    f"your_files/{safe_expected}",
                ):
                    d_st, d_bytes = client.request("GET", f"/media/raw/{direct_path}", timeout=120.0)
                    if d_st == 200 and d_bytes:
                        logger.info(
                            "Direct audio download fallback succeeded (acc=%s, sid=%s, path=%s, bytes=%d)",
                            account_id, session_id, direct_path, len(d_bytes),
                        )
                        media_path = direct_path
                        media_bytes = d_bytes
                        mime_type = "audio/wav" if expected_lower.endswith(".wav") else "audio/mpeg"
                        break
                if media_bytes:
                    break

            if attempt < 2:
                time.sleep(0.8)

        if not media_bytes:
            if not media_path:
                logger.warning(
                    "No %s resource produced (acc=%s, sid=%s). Raw history snippet: %s",
                    expect_kind, account_id, session_id, raw_txt[:1000],
                )
                assistant_txt = self._extract_latest_assistant_text(client, session_id)
                raise MuseWSSError(f"No {expect_kind} resource produced. Assistant replied: {assistant_txt[:200]}")
            raise MuseWSSError(f"Failed to download /media/raw/{media_path}: status={dl_st}")

        default_ext = ".mp3" if expect_kind == "audio" else (".mp4" if expect_kind == "video" else ".png")
        ext = os.path.splitext(media_path)[1] or default_ext
        prefix = "aud" if expect_kind == "audio" else expect_kind[:3]
        filename = f"{prefix}_{secrets.token_hex(6)}{ext}"
        out_path = os.path.join(self.cfg.media_dir, filename)
        with open(out_path, "wb") as f:
            f.write(media_bytes)

        default_mime = "audio/mpeg" if expect_kind == "audio" else ("video/mp4" if expect_kind == "video" else "image/png")
        return {
            "account_id": account_id,
            "session_id": session_id,
            "filename": filename,
            "mime_type": mime_type or default_mime,
            "size_bytes": len(media_bytes),
        }
