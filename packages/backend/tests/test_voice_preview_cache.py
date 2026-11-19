"""Unit and Integration tests for Voice Preview Cache service and endpoints."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from main import app
from services.cleanup import CleanupService
from services.voice_preview import (
    DEFAULT_SAMPLE_TEXT,
    SAMPLE_TEXTS,
    VoicePreviewService,
    build_speech_prompt,
    get_sample_text_for_group,
    safe_preview_filename,
)
from services.voices import resolve_voice
from services.wss_pool import WSSPool


async def call_asgi(app_instance, method: str, path: str, headers: list[tuple[bytes, bytes]] = None, body: bytes = b"", query_string: bytes = b""):
    """Lightweight ASGI caller without external httpx dependency."""
    status_code = None
    response_headers = []
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

    await app_instance(scope, receive, send)
    hdrs = {k.decode("latin1").lower(): v.decode("latin1") for k, v in response_headers}
    return status_code, hdrs, b"".join(body_chunks)


class TestVoicePreviewServiceUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cfg = Config()
        self.cfg.data_dir = self.temp_dir
        self.db = Database(self.cfg)
        self.pool = MagicMock()
        self.svc = VoicePreviewService(self.cfg, self.db, self.pool)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safe_preview_filename(self):
        self.assertEqual(safe_preview_filename("avocado_v2:MAI_01"), "avocado_v2__MAI_01.mp3")
        self.assertEqual(safe_preview_filename("alloy"), "alloy.mp3")
        self.assertEqual(safe_preview_filename("voice/with/slash:test"), "voice__with__slash__test.mp3")

    def test_sample_texts(self):
        self.assertIn("Xin chào", get_sample_text_for_group("Vietnamese"))
        self.assertIn("こんにちは", get_sample_text_for_group("Japanese"))
        self.assertIn("Bonjour", get_sample_text_for_group("French"))
        self.assertEqual(get_sample_text_for_group("English (US)"), DEFAULT_SAMPLE_TEXT)
        self.assertEqual(get_sample_text_for_group("Other"), DEFAULT_SAMPLE_TEXT)

    def test_cache_hit_and_miss(self):
        voice_info = resolve_voice("avocado_v2:vdc_NOID25")
        self.assertIsNotNone(voice_info)
        self.assertFalse(self.svc.is_cached(voice_info["id"]))

        # Mock pool generate_media
        dummy_mp3 = os.path.join(self.cfg.media_dir, "aud_test_generated.mp3")
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        with open(dummy_mp3, "wb") as f:
            f.write(b"ID3_DUMMY_AUDIO_BYTES_TEST")

        self.pool.generate_media.return_value = {
            "filename": "aud_test_generated.mp3",
            "account_id": "acc_1",
            "session_id": "sess_1",
            "size_bytes": 26,
            "bytes": 26,
        }

        # Cache miss: calls pool
        res = self.svc.get_or_generate_preview(voice_info, refresh=False)
        self.assertFalse(res["cached"])
        self.assertEqual(res["filename"], "avocado_v2__vdc_NOID25.mp3")
        self.assertTrue(self.svc.is_cached(voice_info["id"]))
        self.pool.generate_media.assert_called_once()

        # Cache hit: does not call pool again
        self.pool.generate_media.reset_mock()
        res2 = self.svc.get_or_generate_preview(voice_info, refresh=False)
        self.assertTrue(res2["cached"])
        self.pool.generate_media.assert_not_called()

        # Check stats
        stats = self.svc.get_stats()
        self.assertEqual(stats["count"], 1)
        self.assertGreater(stats["total_bytes"], 0)

        # Delete single
        self.assertTrue(self.svc.delete_one(voice_info["id"]))
        self.assertFalse(self.svc.is_cached(voice_info["id"]))
        self.assertEqual(self.svc.get_stats()["count"], 0)

    def test_cleanup_service_isolation(self):
        """CleanupService must not touch voice_previews directory."""
        # Create file in media_dir and file in voice_preview_dir
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        os.makedirs(self.cfg.voice_preview_dir, exist_ok=True)

        media_file = os.path.join(self.cfg.media_dir, "old_media.mp3")
        with open(media_file, "wb") as f:
            f.write(b"OLD_MEDIA")
        # set mtime to 10 days ago
        old_time = time.time() - (10 * 86400)
        os.utime(media_file, (old_time, old_time))

        preview_file = os.path.join(self.cfg.voice_preview_dir, "voice_test.mp3")
        with open(preview_file, "wb") as f:
            f.write(b"PREVIEW_TEST")
        os.utime(preview_file, (old_time, old_time))

        cleanup = CleanupService(self.cfg, self.db)
        # Run cleanup with retention_days = 1
        cleanup.run_now()

        self.assertFalse(os.path.exists(media_file), "Media file should have been cleaned up")
        self.assertTrue(os.path.exists(preview_file), "Voice preview MUST NOT be deleted by cleanup")


class TestVoicePreviewEndpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cfg = Config()
        self.cfg.data_dir = self.temp_dir
        self.db = Database(self.cfg)
        self.pool = MagicMock()
        self.cleanup = CleanupService(self.cfg, self.db)
        self.voice_preview = VoicePreviewService(self.cfg, self.db, self.pool)

        # Setup API Key
        raw_key = self.db.get_api_key()["raw_key"]
        self.auth_headers = [(b"authorization", f"Bearer {raw_key}".encode("latin1"))]

        app.state.cfg = self.cfg
        app.state.db = self.db
        app.state.wss_pool = self.pool
        app.state.cleanup = self.cleanup
        app.state.voice_preview = self.voice_preview

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_get_voices_includes_preview_metadata(self):
        # Seed 1 cached preview
        p = self.voice_preview.get_preview_path("avocado_v2:vdc_NOID25")
        with open(p, "wb") as f:
            f.write(b"AUDIO_DATA")

        status, _, body = await call_asgi(app, "GET", "/v1/audio/voices", headers=self.auth_headers, query_string=b"q=marshmallow")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertGreater(data["total"], 0)
        target = next(v for v in data["data"] if v["id"] == "avocado_v2:vdc_NOID25")
        self.assertEqual(target["language_group"], "English (US)")
        self.assertTrue(target["cached"])
        self.assertIn("long_description", target)
        self.assertIn("/v1/audio/voices/avocado_v2:vdc_NOID25/preview", target["preview_url"])

    async def test_preview_cache_miss_hit_and_refresh(self):
        dummy_mp3 = os.path.join(self.cfg.media_dir, "aud_preview_gen.mp3")
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        with open(dummy_mp3, "wb") as f:
            f.write(b"MP3_BINARY_STREAM_CONTENT")

        self.pool.generate_media.return_value = {
            "filename": "aud_preview_gen.mp3",
            "account_id": "acc_sample",
            "session_id": "sess_sample",
            "size_bytes": 25,
            "bytes": 25,
        }

        # 1. First call: MISS -> binary audio/mpeg, creates task
        status, hdrs, body = await call_asgi(
            app, "GET", "/v1/audio/voices/avocado_v2:vdc_NOID25/preview", headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("content-type"), "audio/mpeg")
        self.assertEqual(hdrs.get("x-voice-preview-cache"), "MISS")
        self.assertEqual(body, b"MP3_BINARY_STREAM_CONTENT")

        tasks = self.db.list_tasks(task_type="audio")
        self.assertEqual(len(tasks), 1)
        self.assertIn("[Voice Preview]", tasks[0]["prompt_preview"])

        # 2. Second call: HIT -> binary audio/mpeg, no new task
        status, hdrs, body = await call_asgi(
            app, "GET", "/v1/audio/voices/avocado_v2:vdc_NOID25/preview", headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("x-voice-preview-cache"), "HIT")
        self.assertEqual(body, b"MP3_BINARY_STREAM_CONTENT")
        self.assertEqual(len(self.db.list_tasks(task_type="audio")), 1)

        # 3. Third call with response_format=url
        status, hdrs, body = await call_asgi(
            app, "GET", "/v1/audio/voices/avocado_v2:vdc_NOID25/preview", headers=self.auth_headers, query_string=b"response_format=url"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["cached"])
        self.assertIn("/v1/voice-previews/avocado_v2__vdc_NOID25.mp3", payload["url"])

        # Fetch served preview
        status, hdrs, p_body = await call_asgi(app, "GET", "/v1/voice-previews/avocado_v2__vdc_NOID25.mp3")
        self.assertEqual(status, 200)
        self.assertEqual(p_body, b"MP3_BINARY_STREAM_CONTENT")

        # 4. Refresh call: refresh=true -> MISS
        with open(dummy_mp3, "wb") as f:
            f.write(b"NEW_REFRESHED_CONTENT")

        status, hdrs, body = await call_asgi(
            app, "GET", "/v1/audio/voices/avocado_v2:vdc_NOID25/preview", headers=self.auth_headers, query_string=b"refresh=true"
        )
        self.assertEqual(status, 200)
        self.assertEqual(hdrs.get("x-voice-preview-cache"), "MISS")
        self.assertEqual(body, b"NEW_REFRESHED_CONTENT")

    async def test_preview_admin_routes(self):
        # Seed 2 previews
        p1 = self.voice_preview.get_preview_path("avocado_v2:MAI_01")
        with open(p1, "wb") as f:
            f.write(b"A1")
        p2 = self.voice_preview.get_preview_path("avocado_v2:MAI_02")
        with open(p2, "wb") as f:
            f.write(b"A22")

        # Stats
        status, _, body = await call_asgi(app, "GET", "/admin/voices/preview/stats")
        self.assertEqual(status, 200)
        stats = json.loads(body.decode("utf-8"))
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["total_bytes"], 5)

        # Delete single
        status, _, body = await call_asgi(app, "DELETE", "/admin/voices/preview/avocado_v2:MAI_01")
        self.assertEqual(status, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertTrue(res["ok"])
        self.assertTrue(res["deleted"])
        self.assertFalse(self.voice_preview.is_cached("avocado_v2:MAI_01"))
        self.assertTrue(self.voice_preview.is_cached("avocado_v2:MAI_02"))

        # Clear all
        status, _, body = await call_asgi(app, "DELETE", "/admin/voices/preview")
        self.assertEqual(status, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertTrue(res["ok"])
        self.assertEqual(res["deleted_files"], 1)
        self.assertEqual(self.voice_preview.get_stats()["count"], 0)

    async def test_duplicate_voice_id_preview_by_language(self):
        """Duplicate voice IDs across languages must resolve & cache independently per language."""
        dup_id = "avocado_v2:vd3_qvd_00052"
        v_ja = resolve_voice(dup_id, language="Japanese")
        v_vi = resolve_voice(dup_id, language="Vietnamese")
        self.assertIsNotNone(v_ja)
        self.assertIsNotNone(v_vi)
        self.assertEqual(v_ja["accent"], "Japanese")
        self.assertEqual(v_vi["accent"], "Vietnamese")

        os.makedirs(self.cfg.media_dir, exist_ok=True)
        dummy_mp3 = os.path.join(self.cfg.media_dir, "dup_preview.mp3")

        def fake_generate(prompt, kind, *args, **kwargs):
            with open(dummy_mp3, "wb") as f:
                f.write(b"JP_AUDIO" if "Language: ja" in prompt else b"VI_AUDIO")
            return {
                "filename": "dup_preview.mp3",
                "account_id": "acc_1",
                "session_id": "sess_1",
                "size_bytes": 8,
                "bytes": 8,
            }

        self.pool.generate_media.side_effect = fake_generate

        # Request Japanese preview
        status, _, body = await call_asgi(
            app,
            "GET",
            f"/v1/audio/voices/{dup_id}/preview",
            headers=self.auth_headers,
            query_string=b"language=Japanese&response_format=json",
        )
        self.assertEqual(status, 200)
        data_ja = json.loads(body.decode("utf-8"))
        self.assertEqual(data_ja["language_group"], "Japanese")
        self.assertEqual(data_ja["sample_text"], SAMPLE_TEXTS["Japanese"])
        self.assertFalse(data_ja["cached"])
        self.assertIn("avocado_v2__vd3_qvd_00052__Japanese.mp3", data_ja["url"])

        # Request Vietnamese preview for the same ID: must NOT hit Japanese cache
        status, _, body = await call_asgi(
            app,
            "GET",
            f"/v1/audio/voices/{dup_id}/preview",
            headers=self.auth_headers,
            query_string=b"language=Vietnamese&response_format=json",
        )
        self.assertEqual(status, 200)
        data_vi = json.loads(body.decode("utf-8"))
        self.assertEqual(data_vi["language_group"], "Vietnamese")
        self.assertEqual(data_vi["sample_text"], SAMPLE_TEXTS["Vietnamese"])
        self.assertFalse(data_vi["cached"])
        self.assertIn("avocado_v2__vd3_qvd_00052__Vietnamese.mp3", data_vi["url"])

        # Verify audio bytes are isolated per language
        status, _, ja_bytes = await call_asgi(
            app,
            "GET",
            f"/v1/audio/voices/{dup_id}/preview",
            headers=self.auth_headers,
            query_string=b"language=Japanese",
        )
        self.assertEqual(status, 200)
        self.assertEqual(ja_bytes, b"JP_AUDIO")

        status, _, vi_bytes = await call_asgi(
            app,
            "GET",
            f"/v1/audio/voices/{dup_id}/preview",
            headers=self.auth_headers,
            query_string=b"language=Vietnamese",
        )
        self.assertEqual(status, 200)
        self.assertEqual(vi_bytes, b"VI_AUDIO")


if __name__ == "__main__":
    unittest.main()
