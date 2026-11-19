"""Unit and Integration tests for Voice catalog, TTS prompt builder, and /v1/audio endpoints."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from main import app
from routers.v1_openai import _build_speech_prompt
from services.voices import (
    get_voice_language_group,
    is_voice_allowed,
    list_available_voice_languages,
    list_voices,
    normalize_voice_languages,
    resolve_voice,
)
from services.wss_pool import WSSPool


async def call_asgi(
    app_instance,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] = None,
    body: bytes = b"",
    query_string: bytes = b"",
):
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

    task = asyncio.create_task(app_instance(scope, receive, send))
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except asyncio.TimeoutError:
        task.cancel()
        raise TimeoutError(f"ASGI request timed out: {method} {path}")

    resp_headers_dict = {
        k.decode("latin1").lower(): v.decode("latin1") for k, v in response_headers
    }
    return status_code, resp_headers_dict, b"".join(body_chunks)


class TestVoiceCatalog(unittest.TestCase):
    """Test voices.json catalog parsing and filtering logic."""

    def test_total_voices_and_exclusions(self):
        voices = list_voices()
        self.assertGreaterEqual(len(voices), 100)

        # Check internal voice excluded
        all_ids = {v["id"] for v in voices}
        self.assertNotIn("avocado_v2:p1a1_short", all_ids)
        self.assertIn("avocado_v2:vdc_NOID25", all_ids)

        # Check no internal metrics leaked and long_description is always present
        for v in voices:
            self.assertNotIn("aesthetics_mean", v)
            self.assertNotIn("aesthetics_mean_normalized", v)
            self.assertNotIn("adherence_mean", v)
            self.assertIn("id", v)
            self.assertIn("name", v)
            self.assertIn("description", v)
            self.assertIn("long_description", v)
            self.assertTrue(bool(v["long_description"].strip()))

    def test_filters(self):
        # Gender filter
        female = list_voices(gender="F")
        self.assertTrue(all(v.get("gender") == "F" for v in female))
        self.assertGreater(len(female), 0)

        male = list_voices(gender="M")
        self.assertTrue(all(v.get("gender") == "M" for v in male))
        self.assertGreater(len(male), 0)

        # Accent filter
        british = list_voices(accent="British")
        self.assertTrue(all(v.get("accent") == "British" for v in british))
        self.assertGreater(len(british), 0)

        # Query filter on name / description / long_description
        marshmallow_search = list_voices(q="marshmallow")
        self.assertGreater(len(marshmallow_search), 0)
        self.assertTrue(
            any(v["name"] == "Timid Marshmallow" for v in marshmallow_search)
        )

        long_desc_search = list_voices(q="cautious")
        self.assertGreater(len(long_desc_search), 0)

    def test_resolve_voice(self):
        # Exact id
        v1 = resolve_voice("avocado_v2:vdc_NOID25")
        self.assertIsNotNone(v1)
        self.assertEqual(v1["id"], "avocado_v2:vdc_NOID25")
        self.assertEqual(v1["name"], "Timid Marshmallow")
        self.assertTrue(bool(v1.get("long_description")))

        # Name case-insensitive
        v2 = resolve_voice("timid marshmallow")
        self.assertIsNotNone(v2)
        self.assertEqual(v2["id"], "avocado_v2:vdc_NOID25")

        # OpenAI aliases
        self.assertEqual(resolve_voice("fable")["id"], "avocado_v2:isabella")
        self.assertEqual(resolve_voice("onyx")["id"], "avocado_v2:magnus")
        self.assertEqual(resolve_voice("nova")["id"], "avocado_v2:paloma")
        self.assertEqual(resolve_voice("shimmer")["id"], "avocado_v2:lumi")

        # Default voice
        v_def = resolve_voice(None)
        self.assertIsNotNone(v_def)
        self.assertEqual(v_def["id"], "avocado_v2:vdc_NOID25")
        self.assertTrue(bool(v_def.get("long_description")))

        # Invalid voice returns None
        self.assertIsNone(resolve_voice("non_existent_voice_12345"))

    def test_language_groups_distribution(self):
        available = list_available_voice_languages()
        self.assertEqual(len(available), 31)
        total_count = sum(x["count"] for x in available)
        self.assertEqual(total_count, len(list_voices()))

        counts_map = {x["name"]: x["count"] for x in available}
        self.assertGreaterEqual(counts_map["English (US)"], 10)
        self.assertGreaterEqual(counts_map["English (UK)"], 10)
        self.assertGreaterEqual(counts_map["French"], 10)
        self.assertGreaterEqual(counts_map["Vietnamese"], 7)
        self.assertGreaterEqual(counts_map["Japanese"], 6)
        self.assertGreaterEqual(counts_map["Korean"], 4)
        self.assertGreaterEqual(counts_map["Other"], 1)

    def test_normalize_voice_languages(self):
        # Legacy "English" should expand to all 13 English country groups
        norm = normalize_voice_languages(
            ["vietnamese", "ENGLISH", "invalid_group", "japanese", "vietnamese"]
        )
        self.assertIn("English (US)", norm)
        self.assertIn("English (UK)", norm)
        self.assertIn("English (Canada)", norm)
        self.assertIn("Vietnamese", norm)
        self.assertIn("Japanese", norm)
        self.assertEqual(len(norm), 15)  # 13 English + Vietnamese + Japanese
        self.assertEqual(normalize_voice_languages(None), [])
        self.assertEqual(normalize_voice_languages([]), [])

    def test_is_voice_allowed_and_filter(self):
        us_voice = resolve_voice("avocado_v2:vdc_NOID25")  # English (US)
        satchel = resolve_voice("Questioning Satchel")  # Vietnamese

        self.assertTrue(is_voice_allowed(us_voice, None))
        self.assertTrue(is_voice_allowed(us_voice, []))
        self.assertTrue(is_voice_allowed(us_voice, ["English (US)"]))
        self.assertFalse(is_voice_allowed(us_voice, ["English (UK)", "Vietnamese"]))

        self.assertTrue(is_voice_allowed(satchel, ["Vietnamese"]))
        self.assertFalse(is_voice_allowed(satchel, ["English (US)"]))

        # list_voices with allowed_languages
        allowed = list_voices(allowed_languages=["Vietnamese", "Japanese"])
        self.assertEqual(len(allowed), 13)
        self.assertTrue(
            all(
                get_voice_language_group(v) in {"Vietnamese", "Japanese"}
                for v in allowed
            )
        )

        # Query by canonical group name
        vn_only = list_voices(
            language="Vietnamese", allowed_languages=["English (US)", "Vietnamese"]
        )
        self.assertEqual(len(vn_only), 7)

        # Query by legacy group name "English"
        expected_eng = len(
            list_voices(
                language="English", allowed_languages=["English (US)", "Vietnamese"]
            )
        )
        eng_us_only = list_voices(
            language="English", allowed_languages=["English (US)", "Vietnamese"]
        )
        self.assertEqual(len(eng_us_only), expected_eng)


class TestSpeechPromptBuilder(unittest.TestCase):
    """Test Muse VM prompt formatting for TTS."""

    def test_exact_default_prompt_format(self):
        prompt = _build_speech_prompt(
            "Text User want to speech",
            "avocado_v2:vdc_31875",
            "Wry Noodle",
        )
        expected = (
            'Generate an MP3 audio speech file using voice "avocado_v2:vdc_31875" (Wry Noodle).\n'
            "Language: en. Speed: 100.\n"
            "\n"
            "Do NOT read any bracket tags literally. Convert them to spoken sounds or delivery cues first "
            "(keep sounds lowercase and comma-separated, without exclamation marks, so delivery stays soft and natural):\n"
            '- [laughs] → ", haha,"\n'
            '- [chuckles], [giggles] → ", heh,"\n'
            '- [clears throat] → ", hmm,"\n'
            '- [sneezes] → "Achoo!"\n'
            '- [sighs] → "Haiz..."\n'
            '- [gasps] → "Huh!"\n'
            '- [coughs] → "Hm hm!"\n'
            '- [pause], [long pause] → "..." (brief / longer pause)\n'
            "- [whispers] → read the following words slowly and quietly\n"
            "- [shouts] → read faster and louder with emphasis\n"
            "- [angry], [sad], [happy], [excited] → adjust pacing and tone to match the mood\n"
            "- Any other [tag] → omit the tag, do not speak it literally\n"
            "\n"
            "Then speak this text with the converted sounds in place, don't ask any more questions:\n"
            '"Text User want to speech"'
        )
        self.assertEqual(prompt, expected)

    def test_prompt_with_instructions_speed_and_language(self):
        prompt = _build_speech_prompt(
            "Hello world",
            "avocado_v2:MAI_01",
            "Aria",
            instructions="Speak enthusiastically",
            speed=1.25,
            language="vi",
        )
        self.assertIn('using voice "avocado_v2:MAI_01" (Aria)', prompt)
        self.assertIn("Language: vi. Speed: 125.", prompt)
        self.assertIn("Style / delivery instructions: Speak enthusiastically", prompt)
        self.assertIn('- [laughs] → ", hơ hơ,"', prompt)
        self.assertIn('- [chuckles], [giggles] → ", hơ hơ,"', prompt)
        self.assertIn('- [clears throat] → ", ừm,"', prompt)
        self.assertIn('- [sneezes] → "Hắt xì!"', prompt)
        self.assertIn('"Hello world"', prompt)

    def test_prompt_with_emotion_cues(self):
        text = "I could not believe it! [laughs] That was hilarious. [whispers] Don't tell anyone."
        prompt = _build_speech_prompt(
            text, "avocado_v2:MAI_01", "Aria", "Natural storytelling"
        )
        self.assertIn('using voice "avocado_v2:MAI_01" (Aria)', prompt)
        self.assertIn("Do NOT read any bracket tags literally.", prompt)
        self.assertIn("Style / delivery instructions: Natural storytelling", prompt)
        self.assertIn(f'"{text}"', prompt)


class TestAudioEndpoints(unittest.IsolatedAsyncioTestCase):
    """Integration tests for FastAPI endpoints: /v1/models, /v1/audio/voices, /v1/audio/speech."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.cfg = Config()
        cls.cfg.data_dir = cls.temp_dir
        cls.db = Database(cls.cfg)
        cls.api_key_data = cls.db.get_api_key()
        cls.api_key = cls.api_key_data["raw_key"]
        cls.auth_headers = [(b"authorization", f"Bearer {cls.api_key}".encode("utf-8"))]

        # Attach minimal state to app for testing
        app.state.cfg = cls.cfg
        app.state.db = cls.db
        cls.pool = WSSPool(cls.cfg, cls.db)
        app.state.wss_pool = cls.pool

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        # Reset settings to disabled before each test
        self.db.update_setting("voice_languages", {"enabled": False, "languages": []})

    def tearDown(self):
        self.db.update_setting("voice_languages", {"enabled": False, "languages": []})

    async def test_get_models_includes_tts(self):
        status, headers, body = await call_asgi(
            app, "GET", "/v1/models", headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        model_ids = {m["id"] for m in data.get("data", [])}
        for alias in ["muse-tts", "tts-1", "tts-1-hd", "gpt-4o-mini-tts"]:
            self.assertIn(alias, model_ids)

    async def test_get_voices_unauthorized(self):
        status, headers, body = await call_asgi(app, "GET", "/v1/audio/voices")
        self.assertEqual(status, 401)

    async def test_get_voices_success(self):
        status, headers, body = await call_asgi(
            app, "GET", "/v1/audio/voices", headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["object"], "list")
        self.assertEqual(data["total"], len(list_voices()))
        self.assertGreater(len(data["data"]), 0)

        # Ensure long_description is returned in public API item payload
        first_item = data["data"][0]
        self.assertIn("long_description", first_item)
        self.assertTrue(bool(first_item["long_description"].strip()))

        # Test filter params via query string
        status, headers, body = await call_asgi(
            app,
            "GET",
            "/v1/audio/voices",
            headers=self.auth_headers,
            query_string=b"gender=F&q=marshmallow",
        )
        self.assertEqual(status, 200)
        filtered = json.loads(body.decode("utf-8"))
        self.assertGreater(filtered["total"], 0)
        self.assertTrue(all(v["gender"] == "F" for v in filtered["data"]))

        # Test alias /v1/voices
        status, headers, body = await call_asgi(
            app, "GET", "/v1/voices", headers=self.auth_headers
        )
        self.assertEqual(status, 200)

    async def test_admin_settings_voice_languages(self):
        # GET /admin/settings returns available_voice_languages & voice_languages
        status, _, body = await call_asgi(app, "GET", "/admin/settings")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("available_voice_languages", data)
        self.assertEqual(len(data["available_voice_languages"]), 31)
        self.assertIn("voice_languages", data)

        # Test legacy "English" expansion in GET /admin/settings
        self.db.update_setting(
            "voice_languages", {"enabled": True, "languages": ["English"]}
        )
        status, _, body = await call_asgi(app, "GET", "/admin/settings")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("English (US)", data["voice_languages"]["languages"])
        self.assertIn("English (UK)", data["voice_languages"]["languages"])
        self.assertEqual(len(data["voice_languages"]["languages"]), 13)

        # POST /admin/settings updates voice_languages
        payload = json.dumps(
            {
                "voice_languages": {
                    "enabled": True,
                    "languages": ["vietnamese", "JAPANESE", "invalid_group"],
                }
            }
        ).encode("utf-8")
        status, _, body = await call_asgi(
            app,
            "POST",
            "/admin/settings",
            headers=[(b"content-type", b"application/json")],
            body=payload,
        )
        self.assertEqual(status, 200)
        updated = json.loads(body.decode("utf-8"))
        self.assertTrue(updated["voice_languages"]["enabled"])
        self.assertEqual(
            updated["voice_languages"]["languages"], ["Vietnamese", "Japanese"]
        )

    async def test_voices_filtered_by_settings_languages(self):
        expected_total = len(
            list_voices(allowed_languages=["English (US)", "Vietnamese", "Japanese"])
        )
        expected_us = len(
            list_voices(
                language="English",
                allowed_languages=["English (US)", "Vietnamese", "Japanese"],
            )
        )
        expected_vn = len(
            list_voices(
                language="Vietnamese",
                allowed_languages=["English (US)", "Vietnamese", "Japanese"],
            )
        )

        # Enable 3 groups: English (US), Vietnamese, Japanese
        self.db.update_setting(
            "voice_languages",
            {
                "enabled": True,
                "languages": ["English (US)", "Vietnamese", "Japanese"],
            },
        )

        status, _, body = await call_asgi(
            app, "GET", "/v1/audio/voices", headers=self.auth_headers
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["total"], expected_total)

        # AND filter with legacy query: ?language=English
        status, _, body = await call_asgi(
            app,
            "GET",
            "/v1/audio/voices",
            headers=self.auth_headers,
            query_string=b"language=English",
        )
        self.assertEqual(status, 200)
        eng_data = json.loads(body.decode("utf-8"))
        self.assertEqual(eng_data["total"], expected_us)

        # AND filter with disabled country: ?language=English%20(UK) -> 0 voices
        status, _, body = await call_asgi(
            app,
            "GET",
            "/v1/audio/voices",
            headers=self.auth_headers,
            query_string=b"language=English%20(UK)",
        )
        self.assertEqual(status, 200)
        uk_data = json.loads(body.decode("utf-8"))
        self.assertEqual(uk_data["total"], 0)

        # AND filter with query: ?language=Vietnamese
        status, _, body = await call_asgi(
            app,
            "GET",
            "/v1/audio/voices",
            headers=self.auth_headers,
            query_string=b"language=Vietnamese",
        )
        self.assertEqual(status, 200)
        vn_data = json.loads(body.decode("utf-8"))
        self.assertEqual(vn_data["total"], expected_vn)

        # AND filter with disabled language: ?language=French -> 0 voices
        status, _, body = await call_asgi(
            app,
            "GET",
            "/v1/audio/voices",
            headers=self.auth_headers,
            query_string=b"language=French",
        )
        self.assertEqual(status, 200)
        fr_data = json.loads(body.decode("utf-8"))
        self.assertEqual(fr_data["total"], 0)

    async def test_speech_validations(self):
        # Empty input -> 400
        req_body = json.dumps({"input": "   "}).encode("utf-8")
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_body,
        )
        self.assertEqual(status, 400)
        self.assertIn("input must be non-empty", body.decode("utf-8"))

        # Input too long -> 400
        req_body = json.dumps({"input": "a" * 4097}).encode("utf-8")
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_body,
        )
        self.assertEqual(status, 400)
        self.assertIn("input must be non-empty", body.decode("utf-8"))

        # Unsupported format -> 400
        req_body = json.dumps({"input": "Hello", "response_format": "wav"}).encode(
            "utf-8"
        )
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_body,
        )
        self.assertEqual(status, 400)
        self.assertIn("Unsupported response_format", body.decode("utf-8"))

        # Unknown voice -> 400
        req_body = json.dumps({"input": "Hello", "voice": "unknown_voice_xyz"}).encode(
            "utf-8"
        )
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_body,
        )
        self.assertEqual(status, 400)
        self.assertIn("Voice 'unknown_voice_xyz' not found", body.decode("utf-8"))

    async def test_speech_rejects_disabled_language_and_no_fallback(self):
        # 1. Test when neither English nor English (US) is enabled (only Vietnamese & Japanese)
        self.db.update_setting(
            "voice_languages",
            {
                "enabled": True,
                "languages": ["Vietnamese", "Japanese"],
            },
        )

        # Calling with Timid Marshmallow (English (US)) -> 400
        req_us = json.dumps({"input": "Hello", "voice": "Timid Marshmallow"}).encode(
            "utf-8"
        )
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_us,
        )
        self.assertEqual(status, 400)
        self.assertIn("not currently enabled in settings", body.decode("utf-8"))

        # Calling with alloy (alias falling back to default English (US) voice) -> 400
        req_alloy = json.dumps({"input": "Hello", "voice": "alloy"}).encode("utf-8")
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_alloy,
        )
        self.assertEqual(status, 400)
        self.assertIn("not currently enabled in settings", body.decode("utf-8"))

        # Omitting voice (system defaults to English (US) voice) -> 400 (NO FALLBACK)
        req_empty = json.dumps({"input": "Hello"}).encode("utf-8")
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_empty,
        )
        self.assertEqual(status, 400)
        self.assertIn("not currently enabled in settings", body.decode("utf-8"))

        # 2. Test when English (UK) is enabled, but English (US) is NOT enabled
        self.db.update_setting(
            "voice_languages",
            {
                "enabled": True,
                "languages": ["English (UK)", "Vietnamese", "Japanese"],
            },
        )

        # Timid Marshmallow belongs to English (US) -> must be rejected even though English (UK) is enabled
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_us,
        )
        self.assertEqual(status, 400)
        self.assertIn("not currently enabled in settings", body.decode("utf-8"))

        # Omitting voice (defaults to English (US) voice) -> must also be rejected
        status, _, body = await call_asgi(
            app,
            "POST",
            "/v1/audio/speech",
            headers=self.auth_headers + [(b"content-type", b"application/json")],
            body=req_empty,
        )
        self.assertEqual(status, 400)
        self.assertIn("not currently enabled in settings", body.decode("utf-8"))

    async def test_speech_generation_mp3_and_url_mocked(self):
        # Create a fake audio file in data/media
        media_dir = self.cfg.media_dir
        os.makedirs(media_dir, exist_ok=True)
        fake_filename = "aud_test_sample.mp3"
        fake_path = os.path.join(media_dir, fake_filename)
        fake_audio_bytes = b"ID3\x03\x00\x00\x00\x00\x00#MOCK_MP3_AUDIO_STREAM_DATA#"
        with open(fake_path, "wb") as f:
            f.write(fake_audio_bytes)

        fake_media_result = {
            "account_id": "acc_test",
            "session_id": "sess_test",
            "filename": fake_filename,
            "path": fake_path,
            "url": f"http://testserver/v1/media/{fake_filename}",
            "mime_type": "audio/mpeg",
            "bytes": len(fake_audio_bytes),
            "size_bytes": len(fake_audio_bytes),
            "kind": "audio",
        }

        # Mock pool.ensure_candidate and pool.generate_media
        with patch.object(
            self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
        ), patch.object(
            self.pool, "generate_media", return_value=fake_media_result
        ) as mock_gen:
            # 1. Test binary response (response_format="mp3")
            payload_mp3 = json.dumps(
                {
                    "model": "muse-tts",
                    "input": "Xin chào! [laughs] Thật tuyệt vời.",
                    "voice": "alloy",
                    "instructions": "Be lively",
                    "response_format": "mp3",
                }
            ).encode("utf-8")

            status, headers, body = await call_asgi(
                app,
                "POST",
                "/v1/audio/speech",
                headers=self.auth_headers + [(b"content-type", b"application/json")],
                body=payload_mp3,
            )
            self.assertEqual(status, 200)
            self.assertIn("audio/mpeg", headers.get("content-type", ""))
            self.assertEqual(body, fake_audio_bytes)

            # Check that generate_media was called with expect_kind="audio" and skip_system_prompt=True
            mock_gen.assert_called_once()
            call_args = mock_gen.call_args
            self.assertEqual(call_args.args[1], "audio")
            self.assertEqual(call_args.kwargs.get("skip_system_prompt"), True)
            sent_prompt = call_args.args[0]
            self.assertIn(
                'using voice "avocado_v2:vdc_NOID25" (Timid Marshmallow)', sent_prompt
            )
            self.assertIn("Style / delivery instructions: Be lively", sent_prompt)
            self.assertIn("Xin chào! [laughs] Thật tuyệt vời.", sent_prompt)

            # Check DB recorded task with type="audio"
            tasks = self.db.list_tasks(task_type="audio", limit=5)
            self.assertGreater(len(tasks), 0)
            self.assertEqual(tasks[0]["type"], "audio")
            self.assertEqual(tasks[0]["status"], "completed")
            self.assertEqual(tasks[0]["media_filename"], fake_filename)

            # 2. Test JSON/URL response (response_format="url")
            mock_gen.reset_mock()
            payload_url = json.dumps(
                {
                    "model": "tts-1",
                    "input": "Testing url format",
                    "voice": "avocado_v2:vdc_NOID25",
                    "response_format": "url",
                }
            ).encode("utf-8")

            status, headers, body = await call_asgi(
                app,
                "POST",
                "/v1/audio/speech",
                headers=self.auth_headers + [(b"content-type", b"application/json")],
                body=payload_url,
            )
            self.assertEqual(status, 200)
            self.assertIn("application/json", headers.get("content-type", ""))
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data["kind"], "audio")
            self.assertEqual(data["voice"], "avocado_v2:vdc_NOID25")
            self.assertIn("/v1/media/aud_test_sample.mp3", data["url"])
            self.assertEqual(data["bytes"], len(fake_audio_bytes))

        # Clean up fake file
        if os.path.exists(fake_path):
            os.remove(fake_path)

        # Clean up fake file
        if os.path.exists(fake_path):
            os.remove(fake_path)

    def test_fetch_media_from_history_handles_string_fields(self):
        pool = WSSPool(self.cfg, self.db)
        mock_client = MagicMock()
        history_payload = {
            "result": {
                "chat_events": [
                    {
                        "resources": ["not-a-dict"],
                        "payload": json.dumps(
                            {"data": {"audio": "sandbox:///tmp/speech_out.mp3"}}
                        ),
                    }
                ]
            }
        }
        mock_client.request.side_effect = [
            (200, json.dumps(history_payload).encode("utf-8")),
            (200, b"ID3fake-mp3-bytes"),
        ]
        res = pool._fetch_media_from_history(mock_client, "acc_1", "sess_1", "audio")
        self.assertTrue(res["filename"].startswith("aud_"))
        self.assertTrue(res["filename"].endswith(".mp3"))
        self.assertEqual(res["mime_type"], "audio/mpeg")
        out_path = os.path.join(self.cfg.media_dir, res["filename"])
        if os.path.exists(out_path):
            os.remove(out_path)


if __name__ == "__main__":
    unittest.main()
