"""Background keep-alive scheduler calling /api/session and /api/hatch/vm/wake."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from config import Config
from db import Database
from muse_wss import MuseAuthError, renew_session_http


class KeepAliveService:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            interval_s = max(300, self.cfg.keepalive_interval_minutes * 60)
            if self._stop.wait(interval_s):
                break
            try:
                self.run_all()
            except Exception:
                pass

    def run_one(self, account_id: str) -> dict[str, Any]:
        acc = self.db.get_account(account_id)
        if not acc:
            return {"ok": False, "error": "Account not found"}
        cookies = json.loads(acc["cookies_json"])
        proxy_url = acc.get("effective_proxy_url") or ""
        try:
            data = renew_session_http(cookies, proxy_url=proxy_url)
            vm_state = data.get("vm_state", "UNKNOWN")
            now = time.time()
            self.db.update_account(account_id, status="healthy", last_keepalive_at=now, last_error="")
            self.db.add_keepalive_log(account_id, "ok", vm_state=vm_state, message="Session renewed")
            return {"ok": True, "account_id": account_id, "status": "healthy", "vm_state": vm_state}
        except MuseAuthError as exc:
            self.db.update_account(account_id, status="expired", last_error=str(exc))
            self.db.add_keepalive_log(account_id, "expired", message=str(exc))
            return {"ok": False, "account_id": account_id, "status": "expired", "error": str(exc)}
        except Exception as exc:
            self.db.update_account(account_id, status="cooldown", last_error=str(exc))
            self.db.add_keepalive_log(account_id, "error", message=str(exc))
            return {"ok": False, "account_id": account_id, "status": "cooldown", "error": str(exc)}

    def run_all(self) -> list[dict[str, Any]]:
        results = []
        for acc in self.db.list_accounts():
            if acc["enabled"]:
                results.append(self.run_one(acc["id"]))
        return results
