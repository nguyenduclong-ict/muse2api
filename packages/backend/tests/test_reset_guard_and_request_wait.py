"""Tests for Reset Guard, Request Wait/Wakeup, and Async Task Queueing (AC-118, AC-119, AC-120)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from main import app
from services.wss_pool import AccountResettingError, NoCandidateAccountError, WSSPool


async def call_asgi(
    app_instance,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    query_string: bytes = b"",
    timeout: float = 10.0,
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
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        task.cancel()
        raise TimeoutError(f"ASGI request timed out: {method} {path}")

    resp_headers_dict = {k.decode("latin1").lower(): v.decode("latin1") for k, v in response_headers}
    return status_code, resp_headers_dict, b"".join(body_chunks)


def _make_cfg(tmpdir: str, **overrides) -> Config:
    kwargs = dict(
        project_root=tmpdir,
        data_dir=tmpdir,
        initial_api_key="m2a_test_reset_wait_key",
        reset_wait_timeout_seconds=10.0,
        reset_max_waiters=50,
    )
    kwargs.update(overrides)
    return Config(**kwargs)


def _auth_headers() -> list[tuple[bytes, bytes]]:
    return [
        (b"authorization", b"Bearer m2a_test_reset_wait_key"),
        (b"content-type", b"application/json"),
    ]


class _FakeWSSClient:
    """Minimal fake WSS client for execute_chat / stream_chat_events / generate_media."""

    def __init__(self, reply_text: str = "hello after reset", media_bytes: bytes = b"ID3fake_mp3_data"):
        self.reply_text = reply_text
        self.media_bytes = media_bytes

    def request(self, method: str, path: str, payload=None, timeout: float = 30.0):
        if path == "/chat/stream":
            return 200, b"{}"
        if path.startswith("/chat/history"):
            return 200, json.dumps({
                "result": {
                    "chat_events": [
                        {
                            "role": "assistant",
                            "event_name": "message.assistant",
                            "display_text": self.reply_text,
                            "resources": [
                                {
                                    "kind": "audio",
                                    "mime_type": "audio/mpeg",
                                    "metadata": {"path": "/workspace/your_files/out.mp3"},
                                },
                                {
                                    "kind": "image",
                                    "mime_type": "image/png",
                                    "metadata": {"path": "/workspace/your_files/out.png"},
                                },
                            ],
                        }
                    ]
                }
            }).encode()
        if path.startswith("/media/raw/"):
            return 200, self.media_bytes
        return 200, b"{}"

    def stream_rpc(self, method: str, path: str, payload=None, timeout: float = 30.0, idle_timeout=None):
        yield 200, json.dumps({
            "event": "chat.delta",
            "payload": {"delta": self.reply_text},
        }).encode()
        yield 200, json.dumps({
            "event": "task.status",
            "payload": {"status": "completed"},
        }).encode()


class TestResetGuardAndRequestWait(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = _make_cfg(self._tmp.name)
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        os.makedirs(self.cfg.voice_preview_dir, exist_ok=True)
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
        if hasattr(self.pool, "stop_all"):
            self.pool.stop_all()
        self.db.close()
        self._tmp.cleanup()

    def _add_account(self, aid: str = "acc_1", status: str = "healthy",
                     supported_models: list[str] | None = None,
                     quota_json: str = "") -> None:
        self.db.create_account(
            account_id=aid,
            label=aid,
            cookies={"hatch_sess": f"s_{aid}"},
            enabled=True,
            status=status,
            supported_models=supported_models or ["chat", "image", "video", "speech"],
        )
        if quota_json:
            self.db.update_account(aid, quota_json=quota_json)

    # ------------------------------------------------------------------
    # AC-118: Sync / SSE / Speech Wait & Instant Wakeup + Fail-fast 503
    # ------------------------------------------------------------------

    def test_ac118_chat_completions_sync_waits_for_reset_then_200(self):
        self._add_account("acc_chat", status="resetting", supported_models=["chat"])
        self.pool.begin_reset("acc_chat")

        fake_client = _FakeWSSClient(reply_text="ok-sync-chat")

        def finish_reset_soon():
            time.sleep(0.15)
            self.db.update_account("acc_chat", status="healthy")
            self.pool.end_reset("acc_chat")

        t = threading.Thread(target=finish_reset_soon, daemon=True)
        t.start()

        with patch.object(self.pool, "get_client", return_value=fake_client):
            t0 = time.monotonic()
            status, _, raw = asyncio.run(
                call_asgi(
                    app,
                    "POST",
                    "/v1/chat/completions",
                    headers=_auth_headers(),
                    body=json.dumps({
                        "model": "muse-spark",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": False,
                    }).encode(),
                )
            )
            elapsed = time.monotonic() - t0

        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(data["choices"][0]["message"]["content"], "ok-sync-chat")
        self.assertGreaterEqual(elapsed, 0.1)
        self.assertLess(elapsed, 3.0)

    def test_ac118_chat_completions_stream_waits_for_reset_then_sse(self):
        self._add_account("acc_stream", status="resetting", supported_models=["chat"])
        self.pool.begin_reset("acc_stream")

        fake_client = _FakeWSSClient(reply_text="ok-sse-chat")

        def finish_reset_soon():
            time.sleep(0.15)
            self.db.update_account("acc_stream", status="healthy")
            self.pool.end_reset("acc_stream")

        threading.Thread(target=finish_reset_soon, daemon=True).start()

        with patch.object(self.pool, "get_client", return_value=fake_client):
            status, headers, raw = asyncio.run(
                call_asgi(
                    app,
                    "POST",
                    "/v1/chat/completions",
                    headers=_auth_headers(),
                    body=json.dumps({
                        "model": "muse-spark",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    }).encode(),
                )
            )

        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers.get("content-type", ""))
        text = raw.decode("utf-8")
        self.assertIn("ok-sse-chat", text)
        self.assertIn("data: [DONE]", text)

    def test_ac118_audio_speech_waits_without_blocking_event_loop(self):
        self._add_account("acc_speech", status="resetting", supported_models=["speech"])
        self.pool.begin_reset("acc_speech")

        async def run_concurrent():
            speech_task = asyncio.create_task(
                call_asgi(
                    app,
                    "POST",
                    "/v1/audio/speech",
                    headers=_auth_headers(),
                    body=json.dumps({
                        "model": "muse-tts",
                        "voice": "alloy",
                        "input": "Hello world",
                        "response_format": "mp3",
                    }).encode(),
                )
            )
            # Yield briefly so speech_task enters run_in_threadpool wait
            await asyncio.sleep(0.05)

            # Event loop must remain responsive while /v1/audio/speech waits
            models_status, _, _ = await call_asgi(
                app,
                "GET",
                "/v1/models",
                headers=[(b"authorization", b"Bearer m2a_test_reset_wait_key")],
            )
            self.assertEqual(models_status, 200)

            # Now complete reset
            self.db.update_account("acc_speech", status="healthy")
            self.pool.end_reset("acc_speech")

            return await speech_task

        fake_client = _FakeWSSClient(media_bytes=b"ID3" + b"\x00" * 64)
        with patch.object(self.pool, "get_client", return_value=fake_client), \
             patch("routers.v1_openai.process_speech_audio", side_effect=lambda p, *a, **kw: (p, False, False)):
            status, headers, raw = asyncio.run(run_concurrent())

        self.assertEqual(status, 200)
        self.assertIn("audio/mpeg", headers.get("content-type", ""))
        self.assertTrue(raw.startswith(b"ID3"))

    def test_ac118_fail_fast_503_when_expired_or_quota_exhausted(self):
        self._add_account("acc_exp", status="expired", supported_models=["chat", "speech"])
        self._add_account(
            "acc_quota",
            status="healthy",
            supported_models=["chat", "speech"],
            quota_json=json.dumps({"weekly_pct": 100}),
        )

        for stream_flag in (False, True):
            t0 = time.monotonic()
            status, _, raw = asyncio.run(
                call_asgi(
                    app,
                    "POST",
                    "/v1/chat/completions",
                    headers=_auth_headers(),
                    body=json.dumps({
                        "model": "muse-spark",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": stream_flag,
                    }).encode(),
                )
            )
            self.assertEqual(status, 503)
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertEqual(json.loads(raw)["detail"]["error"]["type"], "service_unavailable_error")

        status_sp, _, _ = asyncio.run(
            call_asgi(
                app,
                "POST",
                "/v1/audio/speech",
                headers=_auth_headers(),
                body=json.dumps({
                    "model": "muse-tts",
                    "voice": "alloy",
                    "input": "Hello",
                }).encode(),
            )
        )
        self.assertEqual(status_sp, 503)

    # ------------------------------------------------------------------
    # AC-119: Async Tasks return queued immediately & wait in worker
    # ------------------------------------------------------------------

    def test_ac119_async_tasks_return_queued_and_complete_after_reset(self):
        self._add_account("acc_media", status="resetting", supported_models=["image", "video"])
        self.pool.begin_reset("acc_media")

        # Keep track of generate_media calls
        def fake_generate_media(prompt, expect_kind="image", images=None, timeout=120,
                                on_account_selected=None, **kwargs):
            # Inside real WSSPool.generate_media, wait_for_candidate blocks until reset ends
            self.pool.wait_for_candidate(expect_kind, timeout=timeout)
            if on_account_selected:
                on_account_selected("acc_media", "sess_media_1")
            fname = f"test_{expect_kind}.bin"
            with open(os.path.join(self.cfg.media_dir, fname), "wb") as f:
                f.write(b"media_payload")
            return {
                "filename": fname,
                "account_id": "acc_media",
                "session_id": "sess_media_1",
                "size_bytes": 13,
            }

        endpoints = [
            ("/v1/videos", {"model": "muse-video", "prompt": "a cat"}),
            ("/v1/images/tasks", {"model": "muse-image", "prompt": "a dog"}),
            ("/v1/images/generations", {"model": "muse-image", "prompt": "a bird", "async": True}),
        ]

        task_ids: list[str] = []
        with patch.object(self.pool, "generate_media", side_effect=fake_generate_media):
            for path, payload in endpoints:
                status, _, raw = asyncio.run(
                    call_asgi(
                        app,
                        "POST",
                        path,
                        headers=_auth_headers(),
                        body=json.dumps(payload).encode(),
                    )
                )
                self.assertEqual(status, 200, f"{path} failed: {raw}")
                data = json.loads(raw)
                self.assertEqual(data["status"], "queued")
                task_ids.append(data["id"])

            # While still resetting, tasks must remain "queued" (not "running")
            time.sleep(0.1)
            for tid in task_ids:
                t = self.db.get_task(tid)
                self.assertIsNotNone(t)
                self.assertEqual(t["status"], "queued")

            # Finish reset -> workers wake up and complete tasks
            self.db.update_account("acc_media", status="healthy")
            self.pool.end_reset("acc_media")

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if all(self.db.get_task(tid)["status"] == "completed" for tid in task_ids):
                    break
                time.sleep(0.05)

        for tid in task_ids:
            t = self.db.get_task(tid)
            self.assertEqual(t["status"], "completed")
            self.assertEqual(t["account_id"], "acc_media")

    def test_ac119_async_worker_marks_failed_when_reset_fails(self):
        self._add_account("acc_vid_fail", status="resetting", supported_models=["video"])
        self.pool.begin_reset("acc_vid_fail")

        def fake_generate_media(prompt, expect_kind="video", images=None, timeout=120,
                                on_account_selected=None, **kwargs):
            self.pool.wait_for_candidate(expect_kind, timeout=timeout)
            raise AssertionError("Should not reach here")

        with patch.object(self.pool, "generate_media", side_effect=fake_generate_media):
            status, _, raw = asyncio.run(
                call_asgi(
                    app,
                    "POST",
                    "/v1/videos",
                    headers=_auth_headers(),
                    body=json.dumps({"model": "muse-video", "prompt": "fail test"}).encode(),
                )
            )
            self.assertEqual(status, 200)
            task_id = json.loads(raw)["id"]

            time.sleep(0.05)
            # Reset fails -> account becomes expired and end_reset is called
            self.db.update_account("acc_vid_fail", status="expired")
            self.pool.end_reset("acc_vid_fail")

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if self.db.get_task(task_id)["status"] == "failed":
                    break
                time.sleep(0.05)

        t = self.db.get_task(task_id)
        self.assertEqual(t["status"], "failed")

    # ------------------------------------------------------------------
    # AC-120: Early Exit 503, Timeout=0 / Timeout, and Max Waiters Guard
    # ------------------------------------------------------------------

    def test_ac120_early_exit_503_when_reset_fails(self):
        self._add_account("acc_early", status="resetting", supported_models=["chat"])
        self.pool.begin_reset("acc_early")

        def fail_reset_soon():
            time.sleep(0.15)
            self.db.update_account("acc_early", status="expired")
            self.pool.end_reset("acc_early")

        threading.Thread(target=fail_reset_soon, daemon=True).start()

        t0 = time.monotonic()
        status, _, raw = asyncio.run(
            call_asgi(
                app,
                "POST",
                "/v1/chat/completions",
                headers=_auth_headers(),
                body=json.dumps({
                    "model": "muse-spark",
                    "messages": [{"role": "user", "content": "hi"}],
                    "timeout": 30,
                }).encode(),
            )
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertLess(elapsed, 2.0)

    def test_ac120_zero_wait_timeout_returns_503_immediately(self):
        self.cfg.reset_wait_timeout_seconds = 0.0
        self._add_account("acc_zero", status="resetting", supported_models=["chat"])
        self.pool.begin_reset("acc_zero")

        t0 = time.monotonic()
        status, _, _ = asyncio.run(
            call_asgi(
                app,
                "POST",
                "/v1/chat/completions",
                headers=_auth_headers(),
                body=json.dumps({
                    "model": "muse-spark",
                    "messages": [{"role": "user", "content": "hi"}],
                }).encode(),
            )
        )
        self.assertEqual(status, 503)
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_ac120_max_waiters_guard_returns_503(self):
        self.cfg.reset_max_waiters = 1
        self.cfg.reset_wait_timeout_seconds = 5.0
        self._add_account("acc_maxw", status="resetting", supported_models=["chat"])
        self.pool.begin_reset("acc_maxw")

        # Start 1st waiter in background thread
        first_result: list[Exception | None] = []

        def first_waiter():
            try:
                self.pool.wait_for_candidate("chat", timeout=5.0)
                first_result.append(None)
            except Exception as exc:
                first_result.append(exc)

        t = threading.Thread(target=first_waiter, daemon=True)
        t.start()

        # Wait until _waiters_count == 1
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self.pool._waiters_count >= 1:
                break
            time.sleep(0.02)
        self.assertEqual(self.pool._waiters_count, 1)

        # 2nd request must be rejected immediately with 503 & specific message
        status, _, raw = asyncio.run(
            call_asgi(
                app,
                "POST",
                "/v1/chat/completions",
                headers=_auth_headers(),
                body=json.dumps({
                    "model": "muse-spark",
                    "messages": [{"role": "user", "content": "hi"}],
                }).encode(),
            )
        )
        self.assertEqual(status, 503)
        self.assertIn("Too many requests waiting for account reset", raw.decode("utf-8"))

        # Clean up 1st waiter
        self.db.update_account("acc_maxw", status="healthy")
        self.pool.end_reset("acc_maxw")
        t.join(timeout=2.0)
        self.assertEqual(first_result, [None])

    # ------------------------------------------------------------------
    # Race: AccountResettingError in execute_chat / generate_media
    # ------------------------------------------------------------------

    def test_race_account_resetting_error_does_not_cooldown_and_recovers(self):
        self._add_account("acc_r1", status="healthy", supported_models=["chat", "image"])
        fake_client = _FakeWSSClient(reply_text="recovered-after-race", media_bytes=b"PNG_DATA")

        # Simulate race: acc_r1 starts resetting right as get_client / _track_in_flight runs
        calls = {"count": 0}

        def racy_get_client(aid: str):
            calls["count"] += 1
            if calls["count"] == 1:
                self.db.update_account(aid, status="resetting")
                self.pool.begin_reset(aid)
                # Finish reset shortly after so wait_for_candidate wakes up
                def finish():
                    time.sleep(0.1)
                    self.db.update_account(aid, status="healthy")
                    self.pool.end_reset(aid)
                threading.Thread(target=finish, daemon=True).start()
                raise AccountResettingError(f"Account {aid} is currently resetting")
            return fake_client

        with patch.object(self.pool, "get_client", side_effect=racy_get_client):
            aid, sid, text = self.pool.execute_chat("hello race", timeout=5.0)

        self.assertEqual(aid, "acc_r1")
        self.assertEqual(text, "recovered-after-race")
        acc = self.db.get_account("acc_r1")
        self.assertNotEqual(acc["status"], "cooldown")

        # Also test generate_media race
        calls["count"] = 0
        with patch.object(self.pool, "get_client", side_effect=racy_get_client):
            res = self.pool.generate_media("draw race", expect_kind="image", timeout=5.0)
        self.assertEqual(res["account_id"], "acc_r1")
        acc2 = self.db.get_account("acc_r1")
        self.assertNotEqual(acc2["status"], "cooldown")


if __name__ == "__main__":
    unittest.main()
