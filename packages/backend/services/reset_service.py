"""Manual and periodic auto-reset service for muse.ai accounts."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from config import Config
from db import Database
from muse_wss import (
    MuseAuthError,
    MuseWSSError,
    MuseWSSClient,
    fetch_live_session_http,
    replace_vm_http,
    sync_vm_selection_best_effort,
    wake_vm_http,
)
from services.wss_pool import WSSPool, is_quota_exhausted

logger = logging.getLogger(__name__)


class ResetService:
    """Handles manual Reset Muse (202 async) and sequential periodic auto-reset."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        wss_pool: WSSPool,
        *,
        drain_timeout_s: float = 30.0,
        ready_timeout_s: float = 120.0,
        backoff_seconds: float = 900.0,
        poll_interval_s: float = 60.0,
        ready_poll_s: float = 4.0,
    ):
        self.cfg = cfg
        self.db = db
        self.wss_pool = wss_pool
        self.drain_timeout_s = drain_timeout_s
        self.ready_timeout_s = ready_timeout_s
        self.backoff_seconds = backoff_seconds
        self.poll_interval_s = poll_interval_s
        self.ready_poll_s = ready_poll_s

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._acc_locks: dict[str, threading.Lock] = {}
        self._auto_lock = threading.Lock()
        self._backoff_until: dict[str, float] = {}

    def _get_acc_lock(self, account_id: str) -> threading.Lock:
        with self._lock:
            if account_id not in self._acc_locks:
                self._acc_locks[account_id] = threading.Lock()
            return self._acc_locks[account_id]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="muse-auto-reset",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _loop(self) -> None:
        if self._stop.wait(5.0):
            return
        while not self._stop.is_set():
            try:
                self.run_due()
            except Exception:
                logger.exception("ResetService.run_due failed")
            if self._stop.wait(self.poll_interval_s):
                break

    def _auto_reset_settings(self) -> tuple[bool, int]:
        try:
            settings = self.db.get_settings()
            cfg_ar = settings.get("auto_reset") or {}
            enabled = bool(cfg_ar.get("enabled", False))
            interval_m = max(60, int(cfg_ar.get("interval_minutes") or 1440))
            return enabled, interval_m
        except Exception:
            return False, 1440

    def start_manual_reset(self, account_id: str) -> dict[str, Any]:
        """Mark account as resetting and run the reset workflow in a background thread."""
        acc = self.db.get_account(account_id)
        if not acc:
            raise KeyError("Account not found")
        if acc.get("status") == "resetting" or self.wss_pool.is_resetting(account_id):
            raise RuntimeError("Account is already resetting")

        prev_status = acc.get("status") or "unknown"
        self.wss_pool.begin_reset(account_id, require_idle=False)
        updated = self.db.update_account(account_id, status="resetting", last_error="")
        t = threading.Thread(
            target=self._execute_reset,
            args=(account_id, "manual"),
            kwargs={"prev_status": prev_status},
            name=f"muse-reset-{account_id}",
            daemon=True,
        )
        t.start()
        return updated or acc

    def _wait_for_drain(self, account_id: str) -> bool:
        return self.wss_pool.wait_for_in_flight_drain(
            account_id,
            self.drain_timeout_s,
            stop_event=self._stop,
        )

    def _verify_new_vm_wss(
        self,
        account_id: str,
        cookies: dict[str, str],
        proxy_url: str,
        new_vm_id: str,
    ) -> MuseWSSClient:
        deadline = time.time() + max(5.0, self.ready_timeout_s)
        last_err: Exception | None = None
        while time.time() < deadline:
            if self._stop.is_set():
                raise MuseWSSError("Reset aborted due to server shutdown")
            client = MuseWSSClient(cookies=cookies, proxy_url=proxy_url)
            try:
                client.connect(timeout=25.0)
                if client.vm_name != new_vm_id:
                    raise MuseWSSError(
                        f"Bootstrap returned old/unexpected vmName {client.vm_name!r} != {new_vm_id!r}"
                    )
                st, _ = client.request("GET", "/health", timeout=15.0)
                if st != 200:
                    raise MuseWSSError(f"GET /health returned status {st}")
                return client
            except MuseAuthError:
                client.close()
                raise
            except Exception as exc:
                client.close()
                last_err = exc
                try:
                    wake_vm_http(cookies, new_vm_id, proxy_url=proxy_url, timeout=10.0)
                except Exception:
                    pass
                time.sleep(self.ready_poll_s)
        raise MuseWSSError(f"New VM {new_vm_id} did not become healthy within {int(self.ready_timeout_s)}s: {last_err}")

    def _execute_reset(self, account_id: str, trigger: str, *, prev_status: str = "unknown") -> dict[str, Any]:
        acc_lock = self._get_acc_lock(account_id)
        if not acc_lock.acquire(blocking=False):
            return {"ok": False, "account_id": account_id, "skipped": True, "error": "Reset already in progress"}

        t0 = time.time()
        old_vm_id = ""
        new_vm_id = ""
        reserved = False
        try:
            acc = self.db.get_account(account_id)
            if not acc:
                if trigger == "manual" and self.wss_pool.is_resetting(account_id):
                    reserved = True
                return {"ok": False, "account_id": account_id, "error": "Account not found"}

            if trigger == "auto":
                if not self.wss_pool.begin_reset(account_id, require_idle=True):
                    return {"ok": False, "account_id": account_id, "skipped": True, "error": "Account has in-flight requests"}
                reserved = True
                self.db.update_account(account_id, status="resetting", last_error="")
            else:
                self.wss_pool.begin_reset(account_id, require_idle=False)
                reserved = True
                if acc.get("status") != "resetting":
                    self.db.update_account(account_id, status="resetting", last_error="")
                self._wait_for_drain(account_id)

            self.wss_pool.close_account(account_id)

            cookies = json.loads(acc["cookies_json"])
            proxy_url = acc.get("effective_proxy_url") or ""

            session_data = fetch_live_session_http(cookies, proxy_url=proxy_url, timeout=20.0)
            old_vm_id = str(session_data.get("vm_id") or session_data.get("vm_name") or "")
            vm_type = str(session_data.get("vm_type") or "")
            if vm_type != "hatch_vm":
                raise MuseWSSError(f"Reset Muse only supports standard hatch_vm (got vm_type={vm_type!r})")
            if not old_vm_id:
                raise MuseWSSError("Missing source vm_id from /api/session?vm_state=live")

            old_rev = (session_data.get("vm_selection") or {}).get("revision")
            rep = replace_vm_http(
                cookies,
                source_env_id=old_vm_id,
                destination_type="standard",
                intent="reset",
                proxy_url=proxy_url,
                timeout=60.0,
            )
            new_vm_id = str(rep["vmId"])

            new_gateway_url = f"wss://{new_vm_id}.metaaivm.com/"
            try:
                post_session = fetch_live_session_http(cookies, proxy_url=proxy_url, timeout=15.0)
                for vm in post_session.get("vms") or []:
                    if vm.get("id") == new_vm_id or vm.get("vm_id") == new_vm_id:
                        if vm.get("endpoint_url"):
                            new_gateway_url = str(vm["endpoint_url"])
                        break
            except Exception:
                pass

            sync_vm_selection_best_effort(
                cookies,
                new_vm_id=new_vm_id,
                new_gateway_url=new_gateway_url,
                expected_revision=old_rev,
                proxy_url=proxy_url,
                timeout=20.0,
            )

            client = self._verify_new_vm_wss(account_id, cookies, proxy_url, new_vm_id)
            latest_acc = self.db.get_account(account_id)
            if latest_acc and latest_acc["enabled"]:
                with self.wss_pool._lock:
                    self.wss_pool._clients[account_id] = client
            else:
                client.close()

            now = time.time()
            duration_ms = int((now - t0) * 1000)
            with self._lock:
                self._backoff_until.pop(account_id, None)
            self.db.update_account(
                account_id,
                status="healthy",
                last_error="",
                last_reset_at=now,
                last_reset_status="ok",
                last_reset_error="",
                requests_since_reset=0,
            )
            self.db.add_reset_log(
                account_id,
                trigger_type=trigger,
                status="ok",
                old_vm_id=old_vm_id,
                new_vm_id=new_vm_id,
                message=f"Reset completed ({duration_ms}ms)",
                duration_ms=duration_ms,
            )
            return {
                "ok": True,
                "account_id": account_id,
                "status": "healthy",
                "old_vm_id": old_vm_id,
                "new_vm_id": new_vm_id,
                "duration_ms": duration_ms,
            }
        except MuseAuthError as exc:
            duration_ms = int((time.time() - t0) * 1000)
            err_msg = str(exc)
            with self._lock:
                self._backoff_until[account_id] = time.time() + self.backoff_seconds
            self.db.update_account(
                account_id,
                status="expired",
                last_error=err_msg,
                last_reset_status="error",
                last_reset_error=err_msg,
            )
            self.db.add_reset_log(
                account_id,
                trigger_type=trigger,
                status="error",
                old_vm_id=old_vm_id,
                new_vm_id=new_vm_id,
                message=err_msg,
                duration_ms=duration_ms,
            )
            return {"ok": False, "account_id": account_id, "status": "expired", "error": err_msg}
        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            err_msg = str(exc)
            with self._lock:
                self._backoff_until[account_id] = time.time() + self.backoff_seconds
            self.db.update_account(
                account_id,
                status="cooldown",
                last_error=err_msg,
                last_reset_status="error",
                last_reset_error=err_msg,
            )
            self.db.add_reset_log(
                account_id,
                trigger_type=trigger,
                status="error",
                old_vm_id=old_vm_id,
                new_vm_id=new_vm_id,
                message=err_msg,
                duration_ms=duration_ms,
            )
            return {"ok": False, "account_id": account_id, "status": "cooldown", "error": err_msg}
        finally:
            if reserved:
                self.wss_pool.end_reset(account_id)
            acc_lock.release()

    def _find_due_accounts(self, interval_minutes: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        now = time.time()
        interval_s = max(60, int(interval_minutes)) * 60
        due: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for acc in self.db.list_accounts():
            aid = acc["id"]
            if not acc["enabled"] or not acc.get("auto_reset"):
                continue
            status = acc.get("status") or "unknown"
            if status in ("expired", "resetting"):
                skipped.append({"account_id": aid, "reason": f"status_{status}"})
                continue
            if is_quota_exhausted(acc.get("quota_json")):
                skipped.append({"account_id": aid, "reason": "quota_exhausted"})
                continue
            if int(acc.get("requests_since_reset") or 0) <= 0:
                skipped.append({"account_id": aid, "reason": "no_requests_since_reset"})
                continue
            if self.wss_pool.in_flight_count(aid) > 0:
                skipped.append({"account_id": aid, "reason": "in_flight_busy"})
                continue
            with self._lock:
                backoff_until = self._backoff_until.get(aid, 0.0)
            if now < backoff_until:
                skipped.append({"account_id": aid, "reason": "error_backoff"})
                continue
            last_reset_at = float(acc.get("last_reset_at") or 0.0)
            if last_reset_at <= 0.0:
                # First-time baseline: wait a full interval before auto-resetting
                self.db.update_account(aid, last_reset_at=now)
                skipped.append({"account_id": aid, "reason": "initialized_baseline"})
                continue
            if now - last_reset_at < interval_s:
                skipped.append({"account_id": aid, "reason": "not_due_yet"})
                continue
            ok_pool, pool_reason = self.wss_pool.can_auto_reset_account(acc)
            if not ok_pool:
                skipped.append({"account_id": aid, "reason": "insufficient_healthy_pool", "detail": pool_reason})
                continue
            due.append(acc)
        return due, skipped

    def run_due(self, *, ignore_global_enabled: bool = False) -> dict[str, Any]:
        """Run auto-reset sequentially for eligible due accounts."""
        if not self._auto_lock.acquire(blocking=False):
            return {"ok": True, "triggered": [], "skipped": [{"reason": "auto_reset_already_running"}]}
        try:
            enabled, interval_m = self._auto_reset_settings()
            if not ignore_global_enabled and not enabled:
                return {"ok": True, "triggered": [], "skipped": [{"reason": "global_disabled"}]}

            due, skipped = self._find_due_accounts(interval_m)
            results: list[dict[str, Any]] = []
            for acc in due:
                if self._stop.is_set():
                    break
                # Re-check pool safety before each sequential reset
                ok_pool, pool_reason = self.wss_pool.can_auto_reset_account(acc)
                if not ok_pool:
                    skipped.append({"account_id": acc["id"], "reason": "insufficient_healthy_pool", "detail": pool_reason})
                    continue
                if self.wss_pool.in_flight_count(acc["id"]) > 0:
                    skipped.append({"account_id": acc["id"], "reason": "in_flight_busy"})
                    continue
                res = self._execute_reset(acc["id"], "auto")
                results.append(res)
            return {"ok": True, "triggered": results, "skipped": skipped}
        finally:
            self._auto_lock.release()

    def trigger_due_async(self) -> dict[str, Any]:
        """Enqueue due auto-resets sequentially in background for manual Run Due Resets Now."""
        _, interval_m = self._auto_reset_settings()
        due, skipped = self._find_due_accounts(interval_m)
        due_ids = [a["id"] for a in due]
        if not due_ids:
            return {"ok": True, "triggered_ids": [], "skipped": skipped}

        def _worker() -> None:
            self.run_due(ignore_global_enabled=True)

        t = threading.Thread(target=_worker, name="muse-auto-reset-now", daemon=True)
        t.start()
        return {"ok": True, "triggered_ids": due_ids, "skipped": skipped}
