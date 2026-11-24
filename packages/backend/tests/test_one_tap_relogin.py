"""Unit and integration tests for One-Tap auto re-login and Set-Cookie persistence."""
from __future__ import annotations

import asyncio
import json
import os
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
from muse_wss import (
    MuseAuthError,
    MuseWSSError,
    _pick_one_tap_account,
    apply_set_cookies,
    check_auth_session_http,
    one_tap_relogin_http,
)
from services.keepalive import KeepAliveService
from services.wss_pool import WSSPool


class _FakeRawHeaders:
    def __init__(self, set_cookies: list[str]):
        self._set_cookies = list(set_cookies)

    def getlist(self, name: str) -> list[str]:
        if name.lower() == "set-cookie":
            return list(self._set_cookies)
        return []


class _FakeRaw:
    def __init__(self, set_cookies: list[str]):
        self.headers = _FakeRawHeaders(set_cookies)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: dict | None = None,
        set_cookies: list[str] | None = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self._json_data = json_data
        self.headers = dict(headers or {})
        self.raw = _FakeRaw(set_cookies or [])
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


async def _call_asgi(
    app_instance,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
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
        "query_string": b"",
        "headers": headers or [],
        "state": getattr(app_instance, "state", {}),
    }
    task = asyncio.create_task(app_instance(scope, receive, send))
    try:
        await task
    except asyncio.CancelledError:
        pass
    return status_code, dict(response_headers), b"".join(body_chunks)


class TestSetCookieAndPickerHelpers(unittest.TestCase):
    def test_apply_set_cookies_delete_then_set_and_skip_ephemeral(self):
        orig = {
            "hatch_sess": "old_sess",
            "hatch_gw": "old_gw",
            "__Host-hatch_one_tap": "old_ot",
            "datr": "keep_datr",
        }
        resp = _FakeResponse(
            200,
            set_cookies=[
                "hatch_native_auth_csrf=ephemeral_csrf; Max-Age=600; Path=/; HttpOnly",
                "hatch_native_auth_state=ephemeral_state; Max-Age=600; Path=/",
                "hatch_sess=; Max-Age=0; Path=/; SameSite=Lax; HttpOnly; Secure",
                "hatch_sess=new_sess; Max-Age=2592000; Path=/; Domain=.muse.ai; HttpOnly; Secure",
                "hatch_gw=; Max-Age=0; Path=/; Domain=.muse.ai",
                "__Host-hatch_one_tap=; Max-Age=0; Path=/",
                "__Host-hatch_one_tap=new_ot; Max-Age=7776000; Path=/; SameSite=Strict",
            ],
        )
        updated, changed = apply_set_cookies(orig, resp, skip_ephemeral=True)
        self.assertTrue(changed)
        self.assertEqual(updated["hatch_sess"], "new_sess")
        self.assertEqual(updated["__Host-hatch_one_tap"], "new_ot")
        self.assertEqual(updated["datr"], "keep_datr")
        self.assertNotIn("hatch_gw", updated)
        self.assertNotIn("hatch_native_auth_csrf", updated)
        self.assertNotIn("hatch_native_auth_state", updated)

    def test_apply_set_cookies_no_headers_returns_unchanged(self):
        orig = {"hatch_sess": "s1", "__Host-hatch_one_tap": "ot1"}
        updated, changed = apply_set_cookies(orig, _FakeResponse(200), skip_ephemeral=True)
        self.assertFalse(changed)
        self.assertEqual(updated, orig)

    def test_pick_one_tap_account_matches_masked_label_and_errors_when_empty(self):
        accounts = [
            {"saved_account_id": "id_1", "masked_contact": "s***1@g***.com", "one_tap_available": True},
            {"saved_account_id": "id_2", "masked_contact": "d**************7@h*****.online", "one_tap_available": True},
        ]
        picked = _pick_one_tap_account(accounts, account_label="debraohagard2007@h4nabi.online")
        self.assertEqual(picked["saved_account_id"], "id_2")

        fallback = _pick_one_tap_account(accounts, account_label="unrelated@example.com")
        self.assertEqual(fallback["saved_account_id"], "id_1")

        with self.assertRaises(MuseAuthError):
            _pick_one_tap_account([{"saved_account_id": "x", "one_tap_available": False}])


class TestOneTapReloginHttp(unittest.TestCase):
    def test_missing_one_tap_cookie_raises(self):
        with self.assertRaises(MuseAuthError):
            one_tap_relogin_http({"hatch_sess": "expired"})

    @patch("muse_wss.requests.Session")
    def test_happy_path_restart_saved_accounts_one_tap_login(self, mock_session_cls):
        session = MagicMock()
        session.cookies = MagicMock()
        mock_session_cls.return_value = session

        r_restart = _FakeResponse(
            201,
            json_data={"csrf_token": "csrf_1", "flow_state": "started", "saved_accounts_available": True},
            set_cookies=[
                "hatch_native_auth_csrf=tmp_csrf; Max-Age=600; Path=/",
                "hatch_native_auth_device=dev_new; Max-Age=2592000; Path=/",
            ],
        )
        r_saved = _FakeResponse(
            200,
            json_data={
                "saved_accounts": [
                    {"saved_account_id": "pfbid_1", "masked_contact": "d***7@h***.online", "one_tap_available": True}
                ]
            },
        )
        r_login = _FakeResponse(
            200,
            json_data={"redirect_to": "/"},
            set_cookies=[
                "hatch_sess=; Max-Age=0; Path=/",
                "hatch_sess=fresh_sess; Max-Age=2592000; Path=/; Domain=.muse.ai",
                "__Host-hatch_one_tap=; Max-Age=0; Path=/",
                "__Host-hatch_one_tap=fresh_ot; Max-Age=7776000; Path=/",
                "hatch_gw=; Max-Age=0; Path=/",
            ],
        )
        session.post.side_effect = [r_restart, r_saved, r_login]

        merged = one_tap_relogin_http(
            {"hatch_sess": "old", "hatch_gw": "old_gw", "__Host-hatch_one_tap": "old_ot"},
            account_label="debraohagard2007@h4nabi.online",
        )
        self.assertEqual(merged["hatch_sess"], "fresh_sess")
        self.assertEqual(merged["__Host-hatch_one_tap"], "fresh_ot")
        self.assertEqual(merged["hatch_native_auth_device"], "dev_new")
        self.assertNotIn("hatch_gw", merged)
        self.assertNotIn("hatch_native_auth_csrf", merged)
        self.assertEqual(session.post.call_count, 3)

    @patch("muse_wss.requests.Session")
    def test_flow_state_new_calls_start(self, mock_session_cls):
        session = MagicMock()
        session.cookies = MagicMock()
        mock_session_cls.return_value = session

        r_restart = _FakeResponse(201, json_data={"csrf_token": "csrf_1", "flow_state": "new"})
        r_start = _FakeResponse(200, json_data={"flow_state": "started", "saved_accounts_available": True})
        r_saved = _FakeResponse(
            200,
            json_data={"saved_accounts": [{"saved_account_id": "pfbid_1", "one_tap_available": True}]},
        )
        r_login = _FakeResponse(
            200,
            json_data={"redirect_to": "/"},
            set_cookies=["hatch_sess=new_sess; Max-Age=2592000; Path=/"],
        )
        session.post.side_effect = [r_restart, r_start, r_saved, r_login]

        merged = one_tap_relogin_http({"__Host-hatch_one_tap": "ot1"})
        self.assertEqual(merged["hatch_sess"], "new_sess")
        called_urls = [c.args[0] for c in session.post.call_args_list]
        self.assertEqual(
            called_urls,
            [
                "https://muse.ai/api/auth/native/restart",
                "https://muse.ai/api/auth/native/start",
                "https://muse.ai/api/auth/native/saved-accounts",
                "https://muse.ai/api/auth/native/one-tap-login",
            ],
        )

    @patch("muse_wss.requests.Session")
    def test_failure_modes_raise_muse_auth_error(self, mock_session_cls):
        cases = [
            _FakeResponse(403, json_data={"type": "checkpointRequired"}),
            _FakeResponse(200, json_data={"one_tap": "unavailable", "reason": "token_expired"}),
            _FakeResponse(200, json_data={"registration_state": "two_factor_required"}),
            _FakeResponse(200, json_data={"reactivation_required": True}),
            _FakeResponse(200, json_data={"redirect_to": "/"}, set_cookies=[]),
        ]
        for login_resp in cases:
            session = MagicMock()
            session.cookies = MagicMock()
            mock_session_cls.return_value = session
            session.post.side_effect = [
                _FakeResponse(201, json_data={"csrf_token": "c1", "flow_state": "started"}),
                _FakeResponse(200, json_data={"saved_accounts": [{"saved_account_id": "p1", "one_tap_available": True}]}),
                login_resp,
            ]
            with self.assertRaises(MuseAuthError):
                one_tap_relogin_http({"__Host-hatch_one_tap": "ot1"})


class TestCheckAuthSessionHttp(unittest.TestCase):
    @patch("muse_wss.requests.post")
    def test_200_rotates_hatch_sess_and_hatch_gw(self, mock_post):
        mock_post.return_value = _FakeResponse(
            200,
            json_data={"ok": True, "outcome": "validated"},
            set_cookies=[
                "hatch_sess=; Max-Age=0; Path=/",
                "hatch_sess=slid_sess; Max-Age=2592000; Path=/; Domain=.muse.ai",
                "hatch_gw=; Max-Age=0; Path=/",
                "hatch_gw=slid_gw; Max-Age=31536000; Path=/; Domain=.muse.ai",
            ],
        )
        data, merged, changed = check_auth_session_http({"hatch_sess": "old_s", "hatch_gw": "old_g", "datr": "d1"})
        self.assertTrue(data["ok"])
        self.assertTrue(changed)
        self.assertEqual(merged["hatch_sess"], "slid_sess")
        self.assertEqual(merged["hatch_gw"], "slid_gw")
        self.assertEqual(merged["datr"], "d1")

    @patch("muse_wss.requests.post")
    def test_error_statuses_raise_expected_exceptions(self, mock_post):
        mock_post.return_value = _FakeResponse(401)
        with self.assertRaises(MuseAuthError):
            check_auth_session_http({"hatch_sess": "s"})

        mock_post.return_value = _FakeResponse(403, json_data={"type": "checkpointRequired"})
        with self.assertRaises(MuseAuthError):
            check_auth_session_http({"hatch_sess": "s"})

        mock_post.return_value = _FakeResponse(502, text="bad gateway")
        with self.assertRaises(MuseWSSError):
            check_auth_session_http({"hatch_sess": "s"})

        mock_post.return_value = _FakeResponse(200, json_data={"ok": False, "outcome": "invalid"})
        with self.assertRaises(MuseAuthError):
            check_auth_session_http({"hatch_sess": "s"})


class TestKeepAliveAndIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=self.tmpdir.name)
        self.db = Database(self.cfg)
        self.wss_pool = WSSPool(self.cfg, self.db)
        self.keepalive = KeepAliveService(self.cfg, self.db, wss_pool=self.wss_pool)
        self.wss_pool.set_reauth_callback(lambda aid: self.keepalive.reauth_account(aid, close_wss=False))

        app.state.cfg = self.cfg
        app.state.db = self.db
        app.state.wss_pool = self.wss_pool
        app.state.keepalive = self.keepalive

    def tearDown(self):
        self.wss_pool.close_all()
        self.db.close()
        self.tmpdir.cleanup()

    def _create_acc(self, aid: str = "acc_1", status: str = "expired", with_one_tap: bool = True) -> dict:
        cookies = {"hatch_sess": "old_sess", "hatch_vml": "old_vml"}
        if with_one_tap:
            cookies["__Host-hatch_one_tap"] = "ot_secret"
        return self.db.create_account(
            account_id=aid,
            label="debraohagard2007@h4nabi.online",
            cookies=cookies,
            enabled=True,
            status=status,
        )

    @patch("services.keepalive.check_auth_session_http")
    @patch("services.keepalive.renew_session_http")
    def test_run_one_persists_rotated_cookies_on_200(self, mock_renew, mock_check):
        self._create_acc("acc_rot", status="healthy")

        def _fake_renew(cookies, proxy_url="", out_cookies=None):
            if out_cookies is not None:
                out_cookies.update({**cookies, "hatch_vml": "rotated_vml"})
            return {"status": "assigned", "vm_state": "RUNNING"}

        mock_renew.side_effect = _fake_renew
        mock_check.side_effect = lambda c, proxy_url="": (
            {"ok": True},
            {**c, "hatch_sess": "slid_sess", "hatch_gw": "slid_gw"},
            True,
        )
        res = self.keepalive.run_one("acc_rot")
        self.assertTrue(res["ok"])
        self.assertFalse(res["reauthenticated"])
        self.assertTrue(res["session_refreshed"])
        saved = json.loads(self.db.get_account("acc_rot")["cookies_json"])
        self.assertEqual(saved["hatch_vml"], "rotated_vml")
        self.assertEqual(saved["hatch_sess"], "slid_sess")
        self.assertEqual(saved["hatch_gw"], "slid_gw")

    @patch("services.keepalive.check_auth_session_http")
    @patch("services.keepalive.renew_session_http")
    def test_run_due_throttles_auth_check_by_interval(self, mock_renew, mock_check):
        self._create_acc("acc_th", status="healthy")
        mock_renew.return_value = {"status": "assigned", "vm_state": "RUNNING"}
        mock_check.side_effect = lambda c, proxy_url="": (
            {"ok": True},
            {**c, "hatch_sess": "slid_1"},
            True,
        )

        # First due run triggers proactive /api/auth/check
        res1 = self.keepalive.run_due()
        self.assertEqual(len(res1), 1)
        self.assertTrue(res1[0]["session_refreshed"])
        self.assertEqual(mock_check.call_count, 1)

        # Second due run within 6h skips /api/auth/check
        self.db.update_account("acc_th", last_keepalive_at=0.0)
        res2 = self.keepalive.run_due()
        self.assertEqual(len(res2), 1)
        self.assertFalse(res2[0]["session_refreshed"])
        self.assertEqual(mock_check.call_count, 1)

    @patch("services.keepalive.one_tap_relogin_http")
    @patch("services.keepalive.renew_session_http")
    def test_reauth_persists_one_tap_cookies_even_if_session_renew_fails(self, mock_renew, mock_one_tap):
        self._create_acc("acc_nonce", status="expired")
        mock_renew.side_effect = [
            MuseAuthError("Session expired (/api/session HTTP 401)"),
            RuntimeError("proxy timeout"),
        ]
        mock_one_tap.return_value = {
            "hatch_sess": "fresh_sess_saved",
            "__Host-hatch_one_tap": "fresh_ot_nonce_saved",
            "hatch_vml": "old_vml",
        }

        res = self.keepalive.run_one("acc_nonce")
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "cooldown")
        saved = json.loads(self.db.get_account("acc_nonce")["cookies_json"])
        self.assertEqual(saved["hatch_sess"], "fresh_sess_saved")
        self.assertEqual(saved["__Host-hatch_one_tap"], "fresh_ot_nonce_saved")

    @patch("services.keepalive.one_tap_relogin_http")
    @patch("services.keepalive.renew_session_http")
    def test_run_one_401_triggers_one_tap_and_recovers(self, mock_renew, mock_one_tap):
        self._create_acc("acc_rec", status="expired")
        self.wss_pool.close_account = MagicMock()

        def _renew_side(cookies, proxy_url="", out_cookies=None):
            if cookies.get("hatch_sess") == "old_sess":
                raise MuseAuthError("Session expired (/api/session HTTP 401)")
            if out_cookies is not None:
                out_cookies.update({**cookies, "hatch_vml": "new_vml"})
            return {"status": "assigned", "vm_state": "RUNNING"}

        mock_renew.side_effect = _renew_side
        mock_one_tap.return_value = {
            "hatch_sess": "fresh_sess",
            "__Host-hatch_one_tap": "fresh_ot",
            "hatch_vml": "old_vml",
        }

        res = self.keepalive.run_one("acc_rec")
        self.assertTrue(res["ok"])
        self.assertTrue(res["reauthenticated"])
        self.assertEqual(res["status"], "healthy")
        self.wss_pool.close_account.assert_called_once_with("acc_rec")

        acc = self.db.get_account("acc_rec")
        self.assertEqual(acc["status"], "healthy")
        saved = json.loads(acc["cookies_json"])
        self.assertEqual(saved["hatch_sess"], "fresh_sess")
        self.assertEqual(saved["__Host-hatch_one_tap"], "fresh_ot")
        self.assertEqual(saved["hatch_vml"], "new_vml")
        logs = self.db.list_keepalive_logs(limit=5)
        self.assertEqual(logs[0]["message"], "Session auto-reauthenticated via One-Tap")

    @patch("services.keepalive.one_tap_relogin_http", side_effect=MuseAuthError("One-Tap unavailable"))
    @patch("services.keepalive.renew_session_http", side_effect=MuseAuthError("Session expired (/api/session HTTP 401)"))
    def test_run_one_401_when_one_tap_fails_sets_expired_and_updates_timestamp(self, _mock_renew, _mock_ot):
        self._create_acc("acc_fail", status="healthy")
        res = self.keepalive.run_one("acc_fail")
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "expired")
        acc = self.db.get_account("acc_fail")
        self.assertEqual(acc["status"], "expired")
        self.assertGreater(float(acc["last_keepalive_at"] or 0), 0.0)
        saved = json.loads(acc["cookies_json"])
        self.assertEqual(saved["hatch_sess"], "old_sess")

    @patch("services.keepalive.check_auth_session_http")
    @patch("services.keepalive.renew_session_http")
    def test_run_due_skips_expired_accounts(self, mock_renew, mock_check):
        self._create_acc("acc_exp", status="expired")
        self._create_acc("acc_ok", status="healthy")
        mock_renew.return_value = {"status": "assigned", "vm_state": "RUNNING"}
        mock_check.side_effect = lambda c, proxy_url="": ({"ok": True}, c, False)

        results = self.keepalive.run_due()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["account_id"], "acc_ok")
        self.assertEqual(mock_renew.call_count, 1)

    @patch("routers.accounts.fetch_quota_http", return_value={"plan": "Muse Free", "weekly_pct": 10})
    @patch("services.keepalive.one_tap_relogin_http")
    @patch("services.keepalive.renew_session_http")
    @patch("services.wss_pool.MuseWSSClient")
    def test_refresh_endpoint_and_test_account_recover_via_one_tap(
        self, mock_wss_cls, mock_renew, mock_one_tap, mock_quota
    ):
        self._create_acc("acc_api", status="expired")

        def _renew_side(cookies, proxy_url="", out_cookies=None):
            if cookies.get("hatch_sess") == "old_sess":
                raise MuseAuthError("Session expired (/api/session HTTP 401)")
            return {"status": "assigned", "vm_state": "RUNNING"}

        mock_renew.side_effect = _renew_side
        mock_one_tap.return_value = {
            "hatch_sess": "fresh_sess_api",
            "__Host-hatch_one_tap": "fresh_ot_api",
            "hatch_vml": "new_vml_api",
        }

        wss_instance = MagicMock()
        wss_instance.vm_name = "vm_123"
        wss_instance.is_connected = True
        wss_instance.request.return_value = (200, b"ok")
        mock_wss_cls.return_value = wss_instance

        st, _, raw = asyncio.run(_call_asgi(app, "POST", "/admin/accounts/acc_api/refresh"))
        self.assertEqual(st, 200)
        body = json.loads(raw.decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertTrue(body["keepalive"]["reauthenticated"])
        self.assertEqual(body["account"]["status"], "healthy")
        mock_quota.assert_called_once()


if __name__ == "__main__":
    unittest.main()
