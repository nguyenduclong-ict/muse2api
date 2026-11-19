"""Unit and Integration tests for Task input_request_json storage and detail API."""
import asyncio
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database, MAX_INPUT_REQUEST_BYTES, serialize_input_request
from main import app


async def call_asgi(app_instance, method: str, path: str, headers: list[tuple[bytes, bytes]] = None, body: bytes = b""):
    status_code = None
    body_chunks = []
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
        "scheme": "http",
        "server": ("127.0.0.1", 18610),
        "client": ("127.0.0.1", 12345),
    }
    await app_instance(scope, receive, send)
    return status_code, b"".join(body_chunks)


class TestTaskInputRequestStorage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="muse_task_input_test_")
        self.cfg = Config(data_dir=self.tmpdir, initial_api_key="m2a_test_key")
        os.makedirs(self.cfg.media_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migration_adds_input_request_json_to_legacy_db(self):
        conn = sqlite3.connect(self.cfg.db_path)
        conn.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                account_id TEXT DEFAULT '',
                model TEXT DEFAULT '',
                prompt_preview TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                media_filename TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                latency_ms INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO tasks (id, type, status, created_at, updated_at) VALUES ('tsk_legacy', 'chat', 'completed', 1.0, 1.0)"
        )
        conn.commit()
        conn.close()

        db = Database(self.cfg)
        conn2 = sqlite3.connect(self.cfg.db_path)
        col_names = {r[1] for r in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
        conn2.close()
        self.assertIn("input_request_json", col_names)
        legacy = db.get_task("tsk_legacy")
        self.assertIsNotNone(legacy)
        self.assertIsNone(legacy["input_request"])

    def test_sanitize_base64_and_truncate_32kb(self):
        b64_bytes = base64.b64encode(b"\x89PNG\r\n" * 2000).decode("ascii")
        payload = {
            "model": "muse-image",
            "prompt": "A" * 50000,
            "image": f"data:image/png;base64,{b64_bytes}",
            "nested": [{"b64_json": b64_bytes}],
        }
        serialized = serialize_input_request(payload)
        self.assertLessEqual(len(serialized.encode("utf-8")), MAX_INPUT_REQUEST_BYTES)
        parsed = json.loads(serialized)
        self.assertTrue(parsed["image"].startswith("[base64 image/png ~"))
        self.assertTrue(parsed["nested"][0]["b64_json"].startswith("[base64 ~"))
        self.assertTrue(parsed["prompt"].endswith("... [truncated]"))

    def test_list_excludes_input_request_and_get_task_parses_it(self):
        db = Database(self.cfg)
        db.create_task(
            "tsk_001",
            "chat",
            status="completed",
            model="gpt-4o",
            prompt_preview="Hello world",
            input_request={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello world"}]},
        )
        rows = db.list_tasks()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("input_request_json", rows[0])

        detail = db.get_task("tsk_001")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["input_request"]["model"], "gpt-4o")
        self.assertEqual(detail["input_request"]["messages"][0]["content"], "Hello world")

    def test_admin_and_v1_endpoints_persist_and_serve_input_request(self):
        db = Database(self.cfg)
        pool = MagicMock()
        pool.ensure_capability.return_value = True
        pool.execute_chat.return_value = ("acc_1", "sess_1", "Hi there!")
        media_file = os.path.join(self.cfg.media_dir, "img_1.png")
        with open(media_file, "wb") as f:
            f.write(b"fake-media-bytes")
        pool.generate_media.return_value = {
            "account_id": "acc_1",
            "session_id": "sess_1",
            "filename": "img_1.png",
            "file_path": media_file,
            "size_bytes": 16,
        }

        app.state.cfg = self.cfg
        app.state.db = db
        app.state.wss_pool = pool

        auth_headers = [
            (b"authorization", b"Bearer m2a_test_key"),
            (b"content-type", b"application/json"),
        ]

        # 1. Chat completions
        chat_body = json.dumps({
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Explain quantum computing"}],
            "temperature": 0.7,
        }).encode("utf-8")
        status, _ = asyncio.run(call_asgi(app, "POST", "/v1/chat/completions", headers=auth_headers, body=chat_body))
        self.assertEqual(status, 200)

        # 2. Image generations
        img_body = json.dumps({
            "model": "muse-image",
            "prompt": "Sunset over Hanoi",
            "aspect_ratio": "16:9",
        }).encode("utf-8")
        status, _ = asyncio.run(call_asgi(app, "POST", "/v1/images/generations", headers=auth_headers, body=img_body))
        self.assertEqual(status, 200)

        # 3. Audio speech
        tts_body = json.dumps({
            "model": "muse-tts",
            "input": "Hello world from TTS",
            "voice": "alloy",
            "speed": 1.1,
            "response_format": "url",
        }).encode("utf-8")
        status, _ = asyncio.run(call_asgi(app, "POST", "/v1/audio/speech", headers=auth_headers, body=tts_body))
        self.assertEqual(status, 200)

        # Check /admin/tasks list omits input_request_json
        status, list_raw = asyncio.run(call_asgi(app, "GET", "/admin/tasks"))
        self.assertEqual(status, 200)
        list_data = json.loads(list_raw.decode("utf-8"))
        self.assertEqual(list_data["total"], 3)
        for item in list_data["tasks"]:
            self.assertNotIn("input_request_json", item)

        # Check /admin/tasks/{id} returns parsed input_request
        for item in list_data["tasks"]:
            status, detail_raw = asyncio.run(call_asgi(app, "GET", f"/admin/tasks/{item['id']}"))
            self.assertEqual(status, 200)
            detail = json.loads(detail_raw.decode("utf-8"))
            self.assertIsInstance(detail["input_request"], dict)
            self.assertEqual(detail["input_request"]["model"], item["model"])

        # Check 404 on unknown id
        status, _ = asyncio.run(call_asgi(app, "GET", "/admin/tasks/tsk_does_not_exist"))
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
