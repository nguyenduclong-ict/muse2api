"""Unit and Integration tests for per-account supported_models and capability routing."""
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
from db import (
    Database,
    SUPPORTED_MODEL_TYPES,
    normalize_supported_models,
    parse_supported_models,
)
from main import app
from services.wss_pool import NoCandidateAccountError, WSSPool


async def call_asgi(
    app_instance,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    query_string: bytes = b"",
):
    """Lightweight ASGI caller without external httpx dependency."""
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
        await asyncio.wait_for(task, timeout=10.0)
    except asyncio.TimeoutError:
        task.cancel()
        raise TimeoutError(f"ASGI request timed out: {method} {path}")

    resp_headers_dict = {k.decode("latin1").lower(): v.decode("latin1") for k, v in response_headers}
    return status_code, resp_headers_dict, b"".join(body_chunks)


def _make_temp_cfg(tmpdir: str) -> Config:
    return Config(
        project_root=tmpdir,
        data_dir=tmpdir,
        initial_api_key="m2a_test_models_key",
    )


class TestSupportedModelsHelpersAndMigration(unittest.TestCase):
    def test_normalize_supported_models(self):
        self.assertEqual(
            normalize_supported_models(["speech", "CHAT", "chat", " image "]),
            ["chat", "image", "speech"],
        )
        self.assertEqual(
            normalize_supported_models(["video"]),
            ["video"],
        )
        with self.assertRaises(ValueError):
            normalize_supported_models([])
        with self.assertRaises(ValueError):
            normalize_supported_models(["audio"])
        with self.assertRaises(ValueError):
            normalize_supported_models(["chat", "unknown"])
        with self.assertRaises(ValueError):
            normalize_supported_models(None)

    def test_parse_supported_models_fallback(self):
        self.assertEqual(parse_supported_models(None), list(SUPPORTED_MODEL_TYPES))
        self.assertEqual(parse_supported_models(""), list(SUPPORTED_MODEL_TYPES))
        self.assertEqual(parse_supported_models("not-json"), list(SUPPORTED_MODEL_TYPES))
        self.assertEqual(parse_supported_models("[]"), list(SUPPORTED_MODEL_TYPES))
        self.assertEqual(parse_supported_models('["speech","chat"]'), ["chat", "speech"])

    def test_sqlite_migration_adds_column_for_legacy_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_temp_cfg(tmp)
            os.makedirs(cfg.media_dir, exist_ok=True)
            # Create a legacy accounts table without supported_models_json
            conn = sqlite3.connect(cfg.db_path)
            conn.executescript(
                """
                CREATE TABLE accounts (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    cookies_json TEXT NOT NULL,
                    proxy_url TEXT DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'healthy',
                    quota_json TEXT DEFAULT '{}',
                    last_used_at REAL DEFAULT 0,
                    last_keepalive_at REAL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            now = time.time()
            conn.execute(
                "INSERT INTO accounts (id, label, cookies_json, enabled, status, created_at, updated_at) "
                "VALUES ('acc_legacy', 'legacy-1', '{\"hatch_sess\":\"abc\"}', 1, 'healthy', ?, ?)",
                (now, now),
            )
            conn.commit()
            conn.close()

            db = Database(cfg)
            try:
                acc = db.get_account("acc_legacy")
                self.assertIsNotNone(acc)
                self.assertEqual(
                    parse_supported_models(acc.get("supported_models_json")),
                    ["chat", "image", "video", "speech"],
                )
            finally:
                db.close()


class TestAdminAccountsSupportedModelsAPI(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cfg = _make_temp_cfg(self._tmpdir.name)
        self.db = Database(self.cfg)
        self.pool = WSSPool(self.cfg, self.db)

        self._orig_cfg = getattr(app.state, "cfg", None)
        self._orig_db = getattr(app.state, "db", None)
        self._orig_pool = getattr(app.state, "wss_pool", None)

        app.state.cfg = self.cfg
        app.state.db = self.db
        app.state.wss_pool = self.pool

    def tearDown(self):
        app.state.cfg = self._orig_cfg
        app.state.db = self._orig_db
        app.state.wss_pool = self._orig_pool
        self.db.close()
        self._tmpdir.cleanup()

    def _json_headers(self):
        return [(b"content-type", b"application/json")]

    def test_create_patch_list_export_supported_models(self):
        async def _run():
            with patch.object(self.pool, "test_account", return_value={"ok": False, "status": "unknown"}):
                # 1. Default creates with all 4 models
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    "/admin/accounts",
                    headers=self._json_headers(),
                    body=json.dumps({
                        "label": "acc-default",
                        "cookies_raw": "hatch_sess=session_1; hatch_vml=vml_1",
                    }).encode(),
                )
                self.assertEqual(st, 201)
                acc1 = json.loads(raw)["account"]
                self.assertEqual(acc1["supported_models"], ["chat", "image", "video", "speech"])

                # 2. Custom subset normalized & deduplicated
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    "/admin/accounts",
                    headers=self._json_headers(),
                    body=json.dumps({
                        "label": "acc-no-video",
                        "cookies_raw": "hatch_sess=session_2",
                        "supported_models": ["speech", "CHAT", "image", "chat"],
                    }).encode(),
                )
                self.assertEqual(st, 201)
                acc2 = json.loads(raw)["account"]
                self.assertEqual(acc2["supported_models"], ["chat", "image", "speech"])

                # 3. Empty list -> 400
                st, _, _ = await call_asgi(
                    app,
                    "POST",
                    "/admin/accounts",
                    headers=self._json_headers(),
                    body=json.dumps({
                        "label": "acc-empty",
                        "cookies_raw": "hatch_sess=session_3",
                        "supported_models": [],
                    }).encode(),
                )
                self.assertEqual(st, 400)

                # 4. Invalid value -> 400
                st, _, _ = await call_asgi(
                    app,
                    "POST",
                    "/admin/accounts",
                    headers=self._json_headers(),
                    body=json.dumps({
                        "label": "acc-bad",
                        "cookies_raw": "hatch_sess=session_4",
                        "supported_models": ["chat", "audio"],
                    }).encode(),
                )
                self.assertEqual(st, 400)

            # 5. PATCH supported_models does NOT close WSS tunnel
            with patch.object(self.pool, "close_account") as mock_close:
                st, _, raw = await call_asgi(
                    app,
                    "PATCH",
                    f"/admin/accounts/{acc1['id']}",
                    headers=self._json_headers(),
                    body=json.dumps({"supported_models": ["video"]}).encode(),
                )
                self.assertEqual(st, 200)
                self.assertEqual(json.loads(raw)["account"]["supported_models"], ["video"])
                mock_close.assert_not_called()

            # 6. PATCH empty list -> 400
            st, _, _ = await call_asgi(
                app,
                "PATCH",
                f"/admin/accounts/{acc1['id']}",
                headers=self._json_headers(),
                body=json.dumps({"supported_models": []}).encode(),
            )
            self.assertEqual(st, 400)

            # 7. Export includes supported_models
            st, _, raw = await call_asgi(app, "GET", "/admin/accounts/export")
            self.assertEqual(st, 200)
            exported = {a["label"]: a["supported_models"] for a in json.loads(raw)["accounts"]}
            self.assertEqual(exported["acc-default"], ["video"])
            self.assertEqual(exported["acc-no-video"], ["chat", "image", "speech"])

        asyncio.run(_run())


class TestCapabilityRoutingAndFailFast503(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cfg = _make_temp_cfg(self._tmpdir.name)
        self.db = Database(self.cfg)
        self.pool = WSSPool(self.cfg, self.db)

        self._orig_cfg = getattr(app.state, "cfg", None)
        self._orig_db = getattr(app.state, "db", None)
        self._orig_pool = getattr(app.state, "wss_pool", None)

        app.state.cfg = self.cfg
        app.state.db = self.db
        app.state.wss_pool = self.pool

        # Account A: chat, image, speech (NO video)
        self.db.create_account(
            account_id="acc_a",
            label="acc-a",
            cookies={"hatch_sess": "s_a"},
            enabled=True,
            status="healthy",
            supported_models=["chat", "image", "speech"],
        )
        # Account B: video ONLY
        self.db.create_account(
            account_id="acc_b",
            label="acc-b",
            cookies={"hatch_sess": "s_b"},
            enabled=True,
            status="healthy",
            supported_models=["video"],
        )

    def tearDown(self):
        app.state.cfg = self._orig_cfg
        app.state.db = self._orig_db
        app.state.wss_pool = self._orig_pool
        self.db.close()
        self._tmpdir.cleanup()

    def _v1_headers(self):
        return [
            (b"authorization", f"Bearer {self.cfg.initial_api_key}".encode()),
            (b"content-type", b"application/json"),
        ]

    def test_pool_candidate_filtering_and_error_reasons(self):
        self.assertEqual([a["id"] for a in self.pool._candidate_accounts("video")], ["acc_b"])
        self.assertEqual([a["id"] for a in self.pool._candidate_accounts("chat")], ["acc_a"])
        self.assertEqual([a["id"] for a in self.pool._candidate_accounts("image")], ["acc_a"])
        self.assertEqual([a["id"] for a in self.pool._candidate_accounts("speech")], ["acc_a"])

        # Exhaust acc_b quota -> quota specific error for video
        self.db.update_account("acc_b", quota_json=json.dumps({"weekly_pct": 100}))
        with self.assertRaises(NoCandidateAccountError) as ctx:
            self.pool.ensure_candidate("video")
        self.assertIn("exhausted their quota", str(ctx.exception))
        self.assertIn("video", str(ctx.exception))

        # Disable acc_b -> no enabled accounts support 'video'
        self.db.update_account("acc_b", enabled=0, quota_json="{}")
        with self.assertRaises(NoCandidateAccountError) as ctx:
            self.pool.ensure_candidate("video")
        self.assertIn("No enabled accounts support 'video'", str(ctx.exception))

        # Mark acc_b expired & enabled -> no healthy enabled accounts available for 'video'
        self.db.update_account("acc_b", enabled=1, status="expired")
        with self.assertRaises(NoCandidateAccountError) as ctx:
            self.pool.ensure_candidate("video")
        self.assertIn("No healthy enabled accounts available for 'video'", str(ctx.exception))

    def test_v1_routing_selects_only_capable_account(self):
        chosen_ids: list[str] = []

        class _FakeClient:
            def request(self, method, path, payload=None, timeout=30.0):
                if path == "/chat/stream":
                    return 200, b"{}"
                if path.startswith("/chat/history"):
                    return 200, json.dumps({
                        "result": {
                            "chat_events": [
                                {
                                    "role": "assistant",
                                    "event_name": "message.assistant",
                                    "display_text": "hello",
                                    "resources": [
                                        {
                                            "kind": "image",
                                            "mime_type": "image/png",
                                            "metadata": {"path": "/workspace/img.png"},
                                        },
                                        {
                                            "kind": "video",
                                            "mime_type": "video/mp4",
                                            "metadata": {"path": "/workspace/vid.mp4"},
                                        },
                                        {
                                            "kind": "audio",
                                            "mime_type": "audio/mpeg",
                                            "metadata": {"path": "/workspace/aud.mp3"},
                                        },
                                    ],
                                }
                            ]
                        }
                    }).encode()
                if path.startswith("/media/raw/"):
                    return 200, b"FAKE_BINARY_PAYLOAD"
                return 200, b"{}"

            def stream_rpc(self, method, path, payload=None, timeout=30.0, idle_timeout=None):
                yield 200, json.dumps({"event": "task.status", "payload": {"status": "completed"}}).encode()

        def fake_get_client(aid: str):
            chosen_ids.append(aid)
            return _FakeClient()

        with patch.object(self.pool, "get_client", side_effect=fake_get_client):
            aid, _, txt = self.pool.execute_chat("hi")
            self.assertEqual(aid, "acc_a")
            self.assertEqual(txt, "hello")

            res_img = self.pool.generate_media("draw cat", expect_kind="image")
            self.assertEqual(res_img["account_id"], "acc_a")

            res_aud = self.pool.generate_media("say hi", expect_kind="audio", skip_system_prompt=True)
            self.assertEqual(res_aud["account_id"], "acc_a")

            selected_events: list[tuple[str, str]] = []
            res_vid = self.pool.generate_media(
                "animate cat",
                expect_kind="video",
                on_account_selected=lambda aid, sid: selected_events.append((aid, sid)),
            )
            self.assertEqual(res_vid["account_id"], "acc_b")
            self.assertEqual(len(selected_events), 1)
            self.assertEqual(selected_events[0][0], "acc_b")
            self.assertTrue(bool(selected_events[0][1]))

        self.assertEqual(chosen_ids, ["acc_a", "acc_a", "acc_a", "acc_b"])

        # Verify orphaned queued/running tasks are marked failed on startup cleanup
        self.db.create_task("vid_orphan_1", "video", status="running", model="muse-video")
        self.db.create_task("vid_orphan_2", "video", status="queued", model="muse-video")
        self.db.create_task("vid_done_1", "video", status="completed", model="muse-video")
        cleaned = self.db.fail_orphaned_tasks()
        self.assertEqual(cleaned, 2)
        self.assertEqual(self.db.get_task("vid_orphan_1")["status"], "failed")
        self.assertEqual(self.db.get_task("vid_orphan_2")["status"], "failed")
        self.assertEqual(self.db.get_task("vid_done_1")["status"], "completed")

    def test_v1_endpoints_fail_fast_503_without_creating_orphan_tasks(self):
        # Disable acc_b so NO account supports 'video'
        self.db.update_account("acc_b", enabled=0)

        async def _run():
            # Video endpoints -> 503 and 0 tasks created
            for vpath in ("/v1/videos", "/v1/videos/generations"):
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    vpath,
                    headers=self._v1_headers(),
                    body=json.dumps({"prompt": "a flying car"}).encode(),
                )
                self.assertEqual(st, 503, f"Expected 503 on {vpath}, got {st}: {raw}")
                data = json.loads(raw)
                err = data.get("detail", data).get("error", {})
                self.assertEqual(err.get("type"), "service_unavailable_error")
                self.assertIn("video", err.get("message", ""))

            self.assertEqual(self.db.count_tasks(), 0)

            # Now restrict acc_a to video-only so chat/image/speech have no candidates
            self.db.update_account("acc_a", supported_models_json=json.dumps(["video"]))

            # Chat sync & stream -> 503 before creating task or SSE
            for stream_flag in (False, True):
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    "/v1/chat/completions",
                    headers=self._v1_headers(),
                    body=json.dumps({
                        "model": "muse-spark",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": stream_flag,
                    }).encode(),
                )
                self.assertEqual(st, 503)
                self.assertIn("chat", raw.decode())

            # Responses sync & stream -> 503
            for stream_flag in (False, True):
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    "/v1/responses",
                    headers=self._v1_headers(),
                    body=json.dumps({"input": "hello", "stream": stream_flag}).encode(),
                )
                self.assertEqual(st, 503)
                self.assertIn("chat", raw.decode())

            # Images sync, async & tasks -> 503
            for body_payload, path in (
                ({"prompt": "sunset", "async": False}, "/v1/images/generations"),
                ({"prompt": "sunset", "async": True}, "/v1/images/generations"),
                ({"prompt": "sunset"}, "/v1/images/tasks"),
            ):
                st, _, raw = await call_asgi(
                    app,
                    "POST",
                    path,
                    headers=self._v1_headers(),
                    body=json.dumps(body_payload).encode(),
                )
                self.assertEqual(st, 503)
                self.assertIn("image", raw.decode())

            # Speech -> 503
            st, _, raw = await call_asgi(
                app,
                "POST",
                "/v1/audio/speech",
                headers=self._v1_headers(),
                body=json.dumps({"input": "Hello world", "voice": "Timid Marshmallow"}).encode(),
            )
            self.assertEqual(st, 503)
            self.assertIn("speech", raw.decode())

            # No orphan tasks were created for any failed-fast request
            self.assertEqual(self.db.count_tasks(), 0)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
