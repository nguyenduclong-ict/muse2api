"""Background keep-alive scheduler calling /api/session and /api/hatch/vm/wake."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from config import Config
from db import Database
from muse_wss import MuseAuthError, check_auth_session_http, one_tap_relogin_http, renew_session_http

logger = logging.getLogger(__name__)


class KeepAliveService:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        wss_pool: Any | None = None,
        *,
        auth_check_interval_s: float = 21600.0,
    ):
        self.cfg = cfg
        self.db = db
        self.wss_pool = wss_pool
        self.auth_check_interval_s = max(60.0, float(auth_check_interval_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._acc_locks: dict[str, threading.Lock] = {}
        self._last_auth_check: dict[str, float] = {}

    def _get_acc_lock(self, account_id: str) -> threading.Lock:
        with self._lock:
            if account_id not in self._acc_locks:
                self._acc_locks[account_id] = threading.Lock()
            return self._acc_locks[account_id]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _interval_seconds(self) -> int:
        try:
            settings = self.db.get_settings()
            mins = int((settings.get("keepalive") or {}).get("interval_minutes") or self.cfg.keepalive_interval_minutes)
        except Exception:
            mins = self.cfg.keepalive_interval_minutes
        return max(300, mins * 60)

    def _loop(self) -> None:
        if self._stop.wait(2.0):
            return
        while not self._stop.is_set():
            try:
                self.run_due()
            except Exception:
                pass
            if self._stop.wait(60.0):
                break

    def run_due(self) -> list[dict[str, Any]]:
        """Run keep-alive only for enabled accounts whose last_keepalive_at is overdue."""
        interval_s = self._interval_seconds()
        now = time.time()
        results = []
        for acc in self.db.list_accounts():
            if self._stop.is_set():
                break
            if not acc["enabled"] or acc.get("status") in ("resetting", "expired"):
                continue
            last_ka = float(acc.get("last_keepalive_at") or 0.0)
            if now - last_ka >= interval_s:
                results.append(self.run_one(acc["id"], force_auth_check=False))
        return results

    def _reauth_locked(
        self,
        account_id: str,
        acc: dict[str, Any],
        cookies: dict[str, str],
        proxy_url: str,
        *,
        close_wss: bool = True,
    ) -> dict[str, Any]:
        new_cookies = one_tap_relogin_http(
            cookies,
            account_label=acc.get("label") or "",
            proxy_url=proxy_url,
        )
        # Persist fresh hatch_sess and rotated __Host-hatch_one_tap nonce immediately
        # so a subsequent network failure on /api/session cannot lose the new nonce.
        self.db.update_account(account_id, cookies_json=json.dumps(new_cookies))
        if close_wss and self.wss_pool is not None:
            self.wss_pool.close_account(account_id)

        rotated: dict[str, str] = {}
        data = renew_session_http(new_cookies, proxy_url=proxy_url, out_cookies=rotated)
        final_cookies = rotated if rotated else new_cookies
        vm_state = data.get("vm_state", "UNKNOWN")
        now = time.time()
        self.db.update_account(
            account_id,
            cookies_json=json.dumps(final_cookies),
            status="healthy",
            last_keepalive_at=now,
            last_error="",
        )
        self._last_auth_check[account_id] = now
        self.db.add_keepalive_log(
            account_id,
            "ok",
            vm_state=vm_state,
            message="Session auto-reauthenticated via One-Tap",
        )
        return {
            "ok": True,
            "account_id": account_id,
            "status": "healthy",
            "vm_state": vm_state,
            "reauthenticated": True,
            "session_refreshed": True,
        }

    def reauth_account(self, account_id: str, *, close_wss: bool = True) -> dict[str, Any]:
        """Attempt One-Tap re-authentication for an account and persist rotated cookies."""
        with self._get_acc_lock(account_id):
            acc = self.db.get_account(account_id)
            if not acc:
                return {"ok": False, "skipped": True, "error": "Account not found"}
            if acc.get("status") == "resetting":
                return {
                    "ok": False,
                    "account_id": account_id,
                    "status": "resetting",
                    "skipped": True,
                    "error": "Account is currently resetting",
                }
            cookies = json.loads(acc["cookies_json"])
            proxy_url = acc.get("effective_proxy_url") or ""
            if not (cookies.get("__Host-hatch_one_tap") or "").strip():
                return {"ok": False, "account_id": account_id, "error": "Missing __Host-hatch_one_tap", "is_auth_error": True}
            try:
                return self._reauth_locked(account_id, acc, cookies, proxy_url, close_wss=close_wss)
            except MuseAuthError as exc:
                return {"ok": False, "account_id": account_id, "error": str(exc), "is_auth_error": True}
            except Exception as exc:
                return {"ok": False, "account_id": account_id, "error": str(exc), "is_auth_error": False}

    def run_one(self, account_id: str, *, force_auth_check: bool = True) -> dict[str, Any]:
        with self._get_acc_lock(account_id):
            acc = self.db.get_account(account_id)
            if not acc:
                return {"ok": False, "error": "Account not found"}
            if acc.get("status") == "resetting":
                return {
                    "ok": False,
                    "account_id": account_id,
                    "status": "resetting",
                    "skipped": True,
                    "error": "Account is currently resetting",
                }
            cookies = json.loads(acc["cookies_json"])
            proxy_url = acc.get("effective_proxy_url") or ""
            try:
                rotated: dict[str, str] = {}
                data = renew_session_http(cookies, proxy_url=proxy_url, out_cookies=rotated)
                vm_state = data.get("vm_state", "UNKNOWN")
                now = time.time()
                cur_cookies = rotated if rotated else cookies
                cookies_changed = bool(rotated)
                session_refreshed = False

                should_auth_check = force_auth_check or (
                    now - self._last_auth_check.get(account_id, 0.0) >= self.auth_check_interval_s
                )
                if should_auth_check:
                    try:
                        _, checked_cookies, auth_changed = check_auth_session_http(cur_cookies, proxy_url=proxy_url)
                        self._last_auth_check[account_id] = now
                        if auth_changed:
                            cur_cookies = checked_cookies
                            cookies_changed = True
                            session_refreshed = True
                    except MuseAuthError:
                        raise
                    except Exception as exc:
                        logger.warning("Proactive /api/auth/check failed for %s: %s", account_id, exc)

                updates: dict[str, Any] = {
                    "status": "healthy",
                    "last_keepalive_at": now,
                    "last_error": "",
                }
                if cookies_changed:
                    updates["cookies_json"] = json.dumps(cur_cookies)
                if session_refreshed:
                    msg = "Session renewed (hatch_sess refreshed)"
                elif cookies_changed:
                    msg = "Session renewed (cookies rotated)"
                else:
                    msg = "Session renewed"

                self.db.update_account(account_id, **updates)
                self.db.add_keepalive_log(account_id, "ok", vm_state=vm_state, message=msg)
                return {
                    "ok": True,
                    "account_id": account_id,
                    "status": "healthy",
                    "vm_state": vm_state,
                    "reauthenticated": False,
                    "session_refreshed": session_refreshed,
                }
            except MuseAuthError as orig_exc:
                if (cookies.get("__Host-hatch_one_tap") or "").strip():
                    try:
                        return self._reauth_locked(account_id, acc, cookies, proxy_url, close_wss=True)
                    except MuseAuthError as reauth_exc:
                        err_msg = f"{orig_exc}; {reauth_exc}"
                        self.db.update_account(
                            account_id,
                            status="expired",
                            last_keepalive_at=time.time(),
                            last_error=err_msg,
                        )
                        self.db.add_keepalive_log(account_id, "expired", message=err_msg)
                        return {"ok": False, "account_id": account_id, "status": "expired", "error": err_msg}
                    except Exception as reauth_exc:
                        err_msg = f"{orig_exc}; One-Tap error: {reauth_exc}"
                        self.db.update_account(
                            account_id,
                            status="cooldown",
                            last_keepalive_at=time.time(),
                            last_error=err_msg,
                        )
                        self.db.add_keepalive_log(account_id, "error", message=err_msg)
                        return {"ok": False, "account_id": account_id, "status": "cooldown", "error": err_msg}

                self.db.update_account(
                    account_id,
                    status="expired",
                    last_keepalive_at=time.time(),
                    last_error=str(orig_exc),
                )
                self.db.add_keepalive_log(account_id, "expired", message=str(orig_exc))
                return {"ok": False, "account_id": account_id, "status": "expired", "error": str(orig_exc)}
            except Exception as exc:
                self.db.update_account(
                    account_id,
                    status="cooldown",
                    last_keepalive_at=time.time(),
                    last_error=str(exc),
                )
                self.db.add_keepalive_log(account_id, "error", message=str(exc))
                return {"ok": False, "account_id": account_id, "status": "cooldown", "error": str(exc)}

    def run_all(self) -> list[dict[str, Any]]:
        results = []
        for acc in self.db.list_accounts():
            if acc["enabled"]:
                results.append(self.run_one(acc["id"]))
        return results
