"""Unit and Integration tests for Manual Reset Muse and Periodic Auto-Reset."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from main import app
from muse_wss import MuseAuthError
from services.keepalive import KeepAliveService
from services.reset_service import ResetService
from services.wss_pool import WSSPool


async def call_asgi(
    app_instance,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    query_string: bytes = b"",
):
    status_code = None
    response_headers: list[tuple[bytes, bytes]] = []
    body_chunks: list[bytes] = []
    req_sent = False

    async def receive():
        nonlocal req_sent
        if not req_sent:
            req_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)

    async def send(message):
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = message["status"]
            response_headers.extend(message.get("headers", []))
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method.upper(),
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": headers or [],
        "state": getattr(app_instance, "state", {}),
    }
    task = asyncio.create_task(app_instance(scope, receive, send))
    try:
        await task
    except asyncio.CancelledError:
        pass
    return status_code, dict(response_headers), b"".join(body_chunks)


class TestMuseResetAndAutoReset(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=self.tmpdir.name)
        self.db = Database(self.cfg)
        self.wss_pool = WSSPool(self.cfg, self.db)
        self.keepalive = KeepAliveService(self.cfg, self.db)
        self.reset_service = ResetService(
            self.cfg,
            self.db,
            self.wss_pool,
            drain_timeout_s=0.5,
            ready_timeout_s=2.0,
            backoff_seconds=900.0,
            ready_poll_s=0.01,
        )

        app.state.cfg = self.cfg
        app.state.db = self.db
        app.state.wss_pool = self.wss_pool
        app.state.keepalive = self.keepalive
        app.state.reset_service = self.reset_service

    def tearDown(self):
        self.reset_service.stop()
        self.wss_pool.close_all()
        self.db.close()
        self.tmpdir.cleanup()

    def _request(self, method: str, path: str, payload: dict | None = None, query: str = ""):
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = [(b"content-type", b"application/json")] if payload is not None else []
        st, _, raw = asyncio.run(
            call_asgi(app, method, path, headers=headers, body=body, query_string=query.encode("utf-8"))
        )
        return st, json.loads(raw.decode("utf-8")) if raw else {}

    def test_ac015_migration_crash_recovery_and_reset_logs_pruning(self):
        legacy_dir = os.path.join(self.tmpdir.name, "legacy")
        os.makedirs(legacy_dir, exist_ok=True)
        legacy_db_path = os.path.join(legacy_dir, "legacy.db")
        conn = sqlite3.connect(legacy_db_path)
        conn.executescript(
            """
            CREATE TABLE proxies (
                id TEXT PRIMARY KEY, proxy_url TEXT NOT NULL UNIQUE, scheme TEXT NOT NULL DEFAULT 'http',
                status TEXT NOT NULL DEFAULT 'unknown', ip TEXT DEFAULT '', country TEXT DEFAULT '',
                city TEXT DEFAULT '', org TEXT DEFAULT '', latency_ms INTEGER DEFAULT 0,
                last_checked_at REAL DEFAULT 0, last_error TEXT DEFAULT '', created_at REAL NOT NULL
            );
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, cookies_json TEXT NOT NULL,
                proxy_url TEXT DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'unknown', quota_json TEXT DEFAULT '{}',
                last_used_at REAL DEFAULT 0, last_keepalive_at REAL DEFAULT 0,
                last_error TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            """
        )
        now = time.time()
        conn.execute(
            "INSERT INTO accounts (id, label, cookies_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("acc_old", "legacy-01", '{"hatch_sess":"x"}', "resetting", now, now),
        )
        conn.commit()
        conn.close()

        legacy_cfg = Config(data_dir=legacy_dir, db_path_override=legacy_db_path)
        legacy_db = Database(legacy_cfg)
        try:
            acc = legacy_db.get_account("acc_old")
            self.assertIsNotNone(acc)
            self.assertEqual(acc["auto_reset"], 0)
            self.assertEqual(acc["requests_since_reset"], 0)
            self.assertEqual(acc["status"], "resetting")

            recovered = legacy_db.recover_resetting_accounts()
            self.assertEqual(recovered, 1)
            self.assertEqual(legacy_db.get_account("acc_old")["status"], "unknown")

            for i in range(35):
                legacy_db.add_reset_log("acc_old", "manual", "ok", "old", f"new_{i}", f"msg {i}", 100)
            logs = legacy_db.list_reset_logs(limit=50, account_id="acc_old")
            self.assertEqual(len(logs), 30)
            self.assertEqual(logs[0]["new_vm_id"], "new_34")
        finally:
            legacy_db.close()

    def test_ac305_settings_auto_reset_clamp_and_persistence(self):
        st, data = self._request("GET", "/admin/settings")
        self.assertEqual(st, 200)
        self.assertEqual(data["auto_reset"], {"enabled": False, "interval_minutes": 1440})

        st, updated = self._request("POST", "/admin/settings", {"auto_reset": {"enabled": True, "interval_minutes": 10}})
        self.assertEqual(st, 200)
        self.assertEqual(updated["auto_reset"], {"enabled": True, "interval_minutes": 60})

        st, reloaded = self._request("GET", "/admin/settings")
        self.assertEqual(st, 200)
        self.assertEqual(reloaded["auto_reset"], {"enabled": True, "interval_minutes": 60})

    def test_ac019_account_crud_export_and_first_enable_baseline(self):
        self.db.create_account("acc_1", "muse-01", {"hatch_sess": "abc"}, status="healthy", auto_reset=False)
        acc = self.db.get_account("acc_1")
        self.assertEqual(acc["auto_reset"], 0)
        self.assertEqual(acc["last_reset_at"], 0)

        st, patched = self._request("PATCH", "/admin/accounts/acc_1", {"auto_reset": True})
        self.assertEqual(st, 200)
        self.assertTrue(patched["account"]["auto_reset"])
        self.assertGreater(patched["account"]["last_reset_at"], 0)

        st, exported = self._request("GET", "/admin/accounts/export")
        self.assertEqual(st, 200)
        self.assertEqual(exported["accounts"][0]["auto_reset"], True)

    def test_ac016_manual_reset_202_409_cvm_reject_and_concurrency_skip(self):
        self.db.create_account("acc_m1", "manual-01", {"hatch_sess": "abc"}, status="healthy")
        self.db.increment_requests_since_reset("acc_m1")
        self.assertEqual(self.db.get_account("acc_m1")["requests_since_reset"], 1)

        fake_client = MagicMock()
        fake_client.vm_name = "new-vm-uuid"
        fake_client.is_connected = True
        fake_client.request.return_value = (200, b"ok")

        with patch("services.reset_service.fetch_live_session_http") as m_sess, \
             patch("services.reset_service.replace_vm_http") as m_rep, \
             patch("services.reset_service.sync_vm_selection_best_effort") as m_sync, \
             patch("services.reset_service.MuseWSSClient", return_value=fake_client):
            m_sess.side_effect = [
                {"status": "assigned", "vm_id": "old-vm-uuid", "vm_type": "hatch_vm", "vm_selection": {"revision": 2}},
                {"status": "assigned", "vm_id": "new-vm-uuid", "vms": [{"id": "new-vm-uuid", "endpoint_url": "wss://new-vm-uuid.metaaivm.com/"}]},
            ]
            m_rep.return_value = {"ok": True, "vmId": "new-vm-uuid", "releasedOld": True}
            m_sync.return_value = True

            # Synchronous execution check
            res = self.reset_service._execute_reset("acc_m1", "manual")
            self.assertTrue(res["ok"])
            acc = self.db.get_account("acc_m1")
            self.assertEqual(acc["status"], "healthy")
            self.assertEqual(acc["requests_since_reset"], 0)
            self.assertGreater(acc["last_reset_at"], 0)
            self.assertEqual(acc["last_reset_status"], "ok")
            logs = self.db.list_reset_logs(account_id="acc_m1")
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["old_vm_id"], "old-vm-uuid")
            self.assertEqual(logs[0]["new_vm_id"], "new-vm-uuid")

        # 202 + 409 + concurrency guards when status == "resetting"
        self.db.create_account("acc_cvm", "cvm-01", {"hatch_sess": "abc"}, status="healthy")
        self.db.update_account("acc_cvm", status="resetting")
        st_409, _ = self._request("POST", "/admin/accounts/acc_cvm/reset")
        self.assertEqual(st_409, 409)

        # Concurrency skip checks while resetting
        self.assertEqual(self.wss_pool._candidate_accounts("chat"), [a for a in self.wss_pool._candidate_accounts("chat") if a["id"] != "acc_cvm"])
        ka_res = self.keepalive.run_one("acc_cvm")
        self.assertTrue(ka_res.get("skipped"))
        st_ref, ref_data = self._request("POST", "/admin/accounts/acc_cvm/refresh")
        self.assertEqual(st_ref, 200)
        self.assertTrue(ref_data.get("skipped"))

        # Reject hatch_cvm
        with patch("services.reset_service.fetch_live_session_http") as m_sess:
            m_sess.return_value = {"status": "assigned", "vm_id": "cvm-1", "vm_type": "hatch_cvm"}
            err_res = self.reset_service._execute_reset("acc_cvm", "manual")
            self.assertFalse(err_res["ok"])
            self.assertEqual(self.db.get_account("acc_cvm")["status"], "cooldown")
            self.assertIn("hatch_vm", self.db.get_account("acc_cvm")["last_reset_error"])

    def test_ac016_202_endpoint_and_drain(self):
        self.db.create_account("acc_async", "async-01", {"hatch_sess": "abc"}, status="healthy")
        with patch.object(self.reset_service, "_execute_reset", return_value={"ok": True}) as m_exec:
            st, body = self._request("POST", "/admin/accounts/acc_async/reset")
            self.assertEqual(st, 202)
            self.assertEqual(body["status"], "resetting")
            time.sleep(0.1)
            m_exec.assert_called_once()

    def test_ac017_ac018_auto_reset_conditions_and_error_backoff(self):
        self.db.update_setting("auto_reset", {"enabled": True, "interval_minutes": 60})
        old_ts = time.time() - 7200

        # Account 1: healthy anchor (no auto_reset) -> keeps pool healthy_count >= 2
        self.db.create_account("acc_anchor", "anchor", {"hatch_sess": "1"}, status="healthy", auto_reset=False)
        # Account 2: due & has requests -> SHOULD reset
        self.db.create_account("acc_due", "due", {"hatch_sess": "2"}, status="healthy", auto_reset=True)
        self.db.update_account("acc_due", last_reset_at=old_ts, requests_since_reset=3)
        # Account 3: due but 0 requests -> MUST postpone
        self.db.create_account("acc_idle", "idle", {"hatch_sess": "3"}, status="healthy", auto_reset=True)
        self.db.update_account("acc_idle", last_reset_at=old_ts, requests_since_reset=0)
        # Account 4: due & has requests but quota exhausted -> MUST postpone
        self.db.create_account("acc_exhaust", "exhaust", {"hatch_sess": "4"}, status="healthy", auto_reset=True)
        self.db.update_account("acc_exhaust", last_reset_at=old_ts, requests_since_reset=5, quota_json=json.dumps({"weekly_pct": 100}))

        fake_client = MagicMock()
        fake_client.vm_name = "vm-new-due"
        fake_client.is_connected = True
        fake_client.request.return_value = (200, b"ok")

        with patch("services.reset_service.fetch_live_session_http") as m_sess, \
             patch("services.reset_service.replace_vm_http") as m_rep, \
             patch("services.reset_service.sync_vm_selection_best_effort", return_value=True), \
             patch("services.reset_service.MuseWSSClient", return_value=fake_client):
            m_sess.return_value = {"status": "assigned", "vm_id": "vm-old-due", "vm_type": "hatch_vm", "vm_selection": {"revision": 1}}
            m_rep.return_value = {"ok": True, "vmId": "vm-new-due", "releasedOld": True}

            res = self.reset_service.run_due()
            triggered_ids = [r["account_id"] for r in res["triggered"]]
            self.assertEqual(triggered_ids, ["acc_due"])
            self.assertEqual(self.db.get_account("acc_due")["requests_since_reset"], 0)
            self.assertEqual(self.db.get_account("acc_idle")["requests_since_reset"], 0)
            self.assertEqual(self.db.get_account("acc_exhaust")["requests_since_reset"], 5)

        # In-flight busy must postpone auto-reset
        self.db.update_account("acc_due", last_reset_at=old_ts, requests_since_reset=2)
        with self.wss_pool._track_in_flight("acc_due"):
            res_busy = self.reset_service.run_due()
            self.assertEqual(res_busy["triggered"], [])

        # Error 401 -> expired, keeps requests_since_reset, and triggers 15m backoff
        with patch("services.reset_service.fetch_live_session_http", side_effect=MuseAuthError("401 unauthorized")):
            res_err = self.reset_service.run_due()
            self.assertEqual(len(res_err["triggered"]), 1)
            self.assertFalse(res_err["triggered"][0]["ok"])
            acc_after = self.db.get_account("acc_due")
            self.assertEqual(acc_after["status"], "expired")
            self.assertEqual(acc_after["requests_since_reset"], 2)

        # Even if status restored to healthy, backoff blocks immediate retry
        self.db.update_account("acc_due", status="healthy")
        res_backoff = self.reset_service.run_due()
        self.assertEqual(res_backoff["triggered"], [])

        # Single healthy account in pool (<= 1) -> must postpone
        self.db.update_account("acc_anchor", enabled=0)
        self.db.update_account("acc_idle", enabled=0)
        self.reset_service._backoff_until.clear()
        with patch("services.reset_service.fetch_live_session_http") as m_sess_unused:
            res_single = self.reset_service.run_due()
            self.assertEqual(res_single["triggered"], [])
            self.assertEqual(res_single["skipped"][0]["reason"], "insufficient_healthy_pool")
            m_sess_unused.assert_not_called()


if __name__ == "__main__":
    unittest.main()
