"""Unit and Integration tests for Voice catalog, TTS prompt builder, and /v1/audio endpoints."""

import asyncio
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import unittest
import wave
from unittest.mock import MagicMock, patch

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database
from main import app
from routers.v1_openai import _build_speech_prompt
from services.audio_format import (
    AudioConversionError,
    detect_audio_format,
    ensure_audio_file_format,
    is_pcm16_wav,
    matches_target_format,
    process_speech_audio,
)
from services.voice_preview import preprocess_speech_text, sanitize_output_filename
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


def _make_pcm_wav_bytes(
    sample_width: int = 2,
    nchannels: int = 1,
    framerate: int = 24000,
    nframes: int = 240,
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sample_width)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00" * (nframes * nchannels * sample_width))
    return buf.getvalue()


class TestSpeechPromptBuilder(unittest.TestCase):
    """Test Muse VM fast CLI prompt formatting and local tag preprocessing for TTS."""

    def test_exact_default_prompt_format(self):
        prompt = _build_speech_prompt(
            "Text User want to speech",
            "avocado_v2:vdc_31875",
            "Wry Noodle",
            output_filename="tts-aud_default.mp3",
        )
        expected = (
            "Generate an audio speech file using this exact command, do not read any skill files first:\n\n"
            '/opt/hatch/bin/tts speak --voice "avocado_v2:vdc_31875" --language en --speed 100 '
            "--format mp3 --output ~/workspace/your_files/tts-aud_default.mp3 --text-stdin\n\n"
            "Voice: Wry Noodle (avocado_v2:vdc_31875)\n"
            "Language: en\n"
            "Speed: 100\n"
            "Format: mp3\n\n"
            "Text to speak (already converted, read exactly as written, no bracket tags left):\n"
            "Text User want to speech"
        )
        self.assertEqual(prompt, expected)
        self.assertNotIn("normalize to -16 LUFS", prompt)

    def test_wav_prompt_format(self):
        prompt = _build_speech_prompt(
            "Hello WAV",
            "avocado_v2:vdc_31875",
            "Wry Noodle",
            output_format="wav",
            output_filename="tts-aud_wav1.wav",
        )
        self.assertTrue(
            prompt.startswith(
                "Generate an audio speech file using this exact command, do not read any skill files first:"
            )
        )
        self.assertIn(
            "--format wav --output ~/workspace/your_files/tts-aud_wav1.wav --text-stdin",
            prompt,
        )
        self.assertIn("Format: wav", prompt)
        self.assertNotIn("normalize to -16 LUFS", prompt)

    def test_prompt_with_instructions_speed_and_language(self):
        prompt = _build_speech_prompt(
            "Nghe hay quá đi [laughs] để mình nói tiếp.",
            "avocado_v2:MAI_01",
            "Aria",
            instructions="Speak enthusiastically",
            speed=1.25,
            language="vi",
            output_filename="tts-aud_vi1.wav",
            output_format="wav",
        )
        self.assertIn('--voice "avocado_v2:MAI_01" --language vi --speed 125 --format wav', prompt)
        self.assertIn("Voice: Aria (avocado_v2:MAI_01)", prompt)
        self.assertIn("Language: vi\nSpeed: 125\nFormat: wav", prompt)
        self.assertNotIn("Speak enthusiastically", prompt)
        self.assertNotIn("Style / delivery instructions", prompt)
        self.assertIn("Nghe hay quá đi, hơ hơ, để mình nói tiếp.", prompt)

    def test_prompt_with_emotion_cues(self):
        text = "I could not believe it! [laughs] That was hilarious. [whispers] Don't tell anyone. [unknown]"
        prompt = _build_speech_prompt(
            text, "avocado_v2:MAI_01", "Aria", "Natural storytelling",
            output_filename="tts-aud_en1.mp3",
        )
        self.assertIn("Voice: Aria (avocado_v2:MAI_01)", prompt)
        self.assertIn("haha,", prompt)
        self.assertNotIn("[laughs]", prompt)
        self.assertNotIn("[whispers]", prompt)
        self.assertNotIn("[unknown]", prompt)
        self.assertNotIn("Natural storytelling", prompt)
        self.assertNotIn("[", prompt)
        self.assertNotIn("]", prompt)

    def test_preprocess_speech_text_tags_and_empty(self):
        self.assertEqual(
            preprocess_speech_text("Nghe hay quá đi [laughs] để mình nói tiếp.", "vi"),
            "Nghe hay quá đi, hơ hơ, để mình nói tiếp.",
        )
        vi_out = preprocess_speech_text(
            "[LAUGHS] Xin chào [chuckles] [whispers] bí mật [pause] nhé [clears throat] [sneezes] [unknown]",
            "vi",
        )
        self.assertNotIn("[", vi_out)
        self.assertNotIn("]", vi_out)
        self.assertIn(", hơ hơ,", vi_out)
        self.assertIn(", ừm,", vi_out)
        self.assertIn("Hắt xì!", vi_out)
        self.assertIn("...", vi_out)
        self.assertNotIn("whispers", vi_out)
        self.assertNotIn("unknown", vi_out)

        en_out = preprocess_speech_text(
            "Wait [ long pause ] [chuckles] [sighs] [gasps] [coughs] [shouts] Go!",
            "en",
        )
        self.assertNotIn("[", en_out)
        self.assertIn("Wait... heh,", en_out)
        self.assertEqual(
            preprocess_speech_text("That was funny [chuckles] right?", "en"),
            "That was funny, heh, right?",
        )
        self.assertIn("Haiz...", en_out)
        self.assertIn("Huh!", en_out)
        self.assertIn("Hm hm!", en_out)
        self.assertIn("...", en_out)

        self.assertEqual(preprocess_speech_text("[whispers] [sad] [angry]", "vi"), "")
        self.assertEqual(
            preprocess_speech_text("Line 1 [whispers]\n\nLine 2 [laughs] ok", "vi"),
            "Line 1\n\nLine 2, hơ hơ, ok",
        )

    def test_preprocess_japanese_cjk_punctuation(self):
        # User's exact Japanese sample: fullwidth '。' and '、', plus Katakana 'ー' preserved
        sample = "コピー機から遅れて一枚出てきた。その足元には証明書の紙くず。試し刷りは、印刷方向だけ正常。"
        self.assertEqual(
            preprocess_speech_text(sample, "ja"),
            "コピー機から遅れて一枚出てきた. その足元には証明書の紙くず. 試し刷りは, 印刷方向だけ正常.",
        )

        # Preserve 'ー' (prolonged sound mark) and '々' (iteration mark)
        self.assertEqual(
            preprocess_speech_text("人々・コーヒー　タイム※★♪→", "ja"),
            "人々 コーヒー タイム",
        )

        # Fullwidth exclamation/question & compound marks
        self.assertEqual(
            preprocess_speech_text("本当！？すごい‼まじ？！本当⁉", "ja"),
            "本当! すごい! まじ? 本当!",
        )

        # Fullwidth colon/semicolon & numeric decimals/time preservation
        self.assertEqual(
            preprocess_speech_text("時間：１２：３０；円周率：３．１４。", "ja"),
            "時間, 12:30, 円周率, 3.14.",
        )

        # CJK ellipsis & dashes vs preserved [pause] ASCII '...'
        self.assertEqual(
            preprocess_speech_text("待って……えっ――本当に…", "ja"),
            "待って, えっ, 本当に.",
        )
        self.assertEqual(
            preprocess_speech_text("あの[pause]えっと――そう。", "ja"),
            "あの... えっと, そう.",
        )

        # Dialogue quotes & fullwidth brackets (［...］ must NOT be stripped as emotion tag)
        self.assertEqual(
            preprocess_speech_text("「こんにちは。」『元気？』", "ja"),
            "こんにちは. 元気?",
        )
        self.assertEqual(
            preprocess_speech_text("【重要】お知らせ（注釈）［確認］", "ja"),
            "重要, お知らせ, 注釈, 確認",
        )

        # Wave dash / fullwidth tilde
        self.assertEqual(
            preprocess_speech_text("５〜１０分、１０時〜１２時、え〜すごい！", "ja"),
            "5から10分, 10時から12時, えーすごい!",
        )
        self.assertEqual(
            preprocess_speech_text("5〜10 items", "en"),
            "5-10 items",
        )

        # End-to-end inside _build_speech_prompt
        prompt = _build_speech_prompt(
            sample,
            "avocado_v2:vdc_NOID25",
            "JP Voice",
            language="ja",
            output_filename="tts-ja.mp3",
        )
        self.assertNotIn("。", prompt)
        self.assertNotIn("、", prompt)
        self.assertIn(
            "コピー機から遅れて一枚出てきた. その足元には証明書の紙くず. 試し刷りは, 印刷方向だけ正常.",
            prompt,
        )

    def test_sanitize_output_filename(self):
        self.assertEqual(
            sanitize_output_filename("../../etc/tts-abc.mp3", "wav"),
            "tts-abc.wav",
        )
        self.assertTrue(sanitize_output_filename("", "mp3").endswith(".mp3"))


class TestAudioFormatService(unittest.TestCase):
    """Unit tests for audio header detection, PCM16 WAV validation, and ffmpeg fallback."""

    def test_detect_audio_format(self):
        self.assertEqual(detect_audio_format(_make_pcm_wav_bytes()), "wav")
        self.assertEqual(detect_audio_format(b"ID3\x03\x00\x00\x00\x00\x00\x00"), "mp3")
        self.assertEqual(detect_audio_format(b"\xff\xfb\x90\x00\x00\x00"), "mp3")
        self.assertIsNone(detect_audio_format(b"OggS\x00\x02"))
        self.assertIsNone(detect_audio_format(b""))

    def test_is_pcm16_wav_and_matches_target_format(self):
        wav16 = _make_pcm_wav_bytes(sample_width=2)
        wav24 = _make_pcm_wav_bytes(sample_width=3)
        wav8 = _make_pcm_wav_bytes(sample_width=1)
        mp3_bytes = b"ID3\x03\x00#FAKE_MP3#"

        self.assertTrue(is_pcm16_wav(wav16))
        self.assertFalse(is_pcm16_wav(wav24))
        self.assertFalse(is_pcm16_wav(wav8))
        self.assertFalse(is_pcm16_wav(mp3_bytes))
        self.assertFalse(is_pcm16_wav(b"RIFF\x24\x00\x00\x00WAVEcorrupt"))

        self.assertTrue(matches_target_format(wav16, "wav"))
        self.assertFalse(matches_target_format(wav24, "wav"))
        self.assertFalse(matches_target_format(mp3_bytes, "wav"))
        self.assertTrue(matches_target_format(mp3_bytes, "mp3"))
        self.assertFalse(matches_target_format(wav16, "mp3"))

    def test_ensure_audio_file_format_paths(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. Native match skips convert_audio_file
            wav_path = os.path.join(tmp_dir, "native.wav")
            with open(wav_path, "wb") as f:
                f.write(_make_pcm_wav_bytes())
            with patch("services.audio_format.convert_audio_file") as mock_conv:
                out_path, converted = ensure_audio_file_format(wav_path, "wav")
            self.assertEqual(out_path, wav_path)
            self.assertFalse(converted)
            mock_conv.assert_not_called()

            # 2. Native match with wrong extension renames without converting
            misnamed_path = os.path.join(tmp_dir, "misnamed.mp3")
            with open(misnamed_path, "wb") as f:
                f.write(_make_pcm_wav_bytes())
            with patch("services.audio_format.convert_audio_file") as mock_conv:
                out_path, converted = ensure_audio_file_format(misnamed_path, "wav")
            self.assertEqual(out_path, os.path.join(tmp_dir, "misnamed.wav"))
            self.assertFalse(converted)
            self.assertFalse(os.path.exists(misnamed_path))
            self.assertTrue(os.path.isfile(out_path))
            mock_conv.assert_not_called()

            # 3. Mismatch invokes convert_audio_file and removes original mismatched file
            mp3_src = os.path.join(tmp_dir, "mismatch.mp3")
            with open(mp3_src, "wb") as f:
                f.write(b"ID3\x03\x00#MOCK_MP3#")

            def fake_convert(src, dst, fmt):
                with open(dst, "wb") as out_f:
                    out_f.write(_make_pcm_wav_bytes())

            with patch("services.audio_format.convert_audio_file", side_effect=fake_convert) as mock_conv:
                out_path, converted = ensure_audio_file_format(mp3_src, "wav")
            self.assertEqual(out_path, os.path.join(tmp_dir, "mismatch.wav"))
            self.assertTrue(converted)
            mock_conv.assert_called_once_with(mp3_src, os.path.join(tmp_dir, "mismatch.wav"), "wav")
            self.assertFalse(os.path.exists(mp3_src))
            self.assertTrue(os.path.isfile(out_path))

            # 4. Missing ffmpeg raises AudioConversionError
            mp3_no_ffmpeg = os.path.join(tmp_dir, "no_ffmpeg.mp3")
            with open(mp3_no_ffmpeg, "wb") as f:
                f.write(b"ID3\x03\x00#MOCK_MP3#")
            with patch("services.audio_format.find_ffmpeg", return_value=None):
                with self.assertRaises(AudioConversionError):
                    ensure_audio_file_format(mp3_no_ffmpeg, "wav")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_process_speech_audio_2pass_loudnorm_and_sample_rate(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            wav_path = os.path.join(tmp_dir, "speech.wav")
            orig_bytes = _make_pcm_wav_bytes(framerate=24000)
            norm_bytes = _make_pcm_wav_bytes(framerate=24000, nframes=480)
            with open(wav_path, "wb") as f:
                f.write(orig_bytes)

            recorded_cmds = []

            def fake_run(cmd, capture_output=True, text=True, timeout=60):
                recorded_cmds.append(cmd)
                proc = MagicMock()
                proc.returncode = 0
                proc.stdout = ""
                if len(recorded_cmds) == 1:
                    proc.stderr = (
                        "Stream #0:0: Audio: pcm_s16le, 24000 Hz, mono, s16, 384 kb/s\n"
                        '{\n'
                        '  "input_i" : "-24.50",\n'
                        '  "input_tp" : "-5.10",\n'
                        '  "input_lra" : "3.20",\n'
                        '  "input_thresh" : "-35.00",\n'
                        '  "target_offset" : "0.40"\n'
                        '}\n'
                    )
                else:
                    proc.stderr = ""
                    with open(cmd[-1], "wb") as out_f:
                        out_f.write(norm_bytes)
                return proc

            with patch("services.audio_format.find_ffmpeg", return_value="/usr/bin/ffmpeg"), patch(
                "services.audio_format.subprocess.run", side_effect=fake_run
            ):
                out_path, converted, normalized = process_speech_audio(wav_path, "wav", normalize=True)

            self.assertEqual(out_path, wav_path)
            self.assertFalse(converted)
            self.assertTrue(normalized)
            self.assertEqual(len(recorded_cmds), 2)
            self.assertIn("loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", recorded_cmds[0])
            pass2 = recorded_cmds[1]
            af_val = pass2[pass2.index("-af") + 1]
            self.assertIn("measured_I=-24.50", af_val)
            self.assertIn("linear=true", af_val)
            self.assertIn("-ar", pass2)
            self.assertEqual(pass2[pass2.index("-ar") + 1], "24000")
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), norm_bytes)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_process_speech_audio_1pass_silent_and_fallbacks(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. 1-pass fallback when pass 1 JSON is missing
            mp3_path = os.path.join(tmp_dir, "onepass.mp3")
            with open(mp3_path, "wb") as f:
                f.write(b"ID3\x03\x00#MP3#")

            cmds = []

            def fake_run_no_json(cmd, capture_output=True, text=True, timeout=60):
                cmds.append(cmd)
                p = MagicMock()
                p.returncode = 0
                p.stdout = ""
                if len(cmds) == 1:
                    p.stderr = "Stream #0:0: Audio: mp3, 44100 Hz, mono, fltp"
                else:
                    p.stderr = ""
                    with open(cmd[-1], "wb") as out_f:
                        out_f.write(b"ID3\x03\x00#NORM#")
                return p

            with patch("services.audio_format.find_ffmpeg", return_value="/usr/bin/ffmpeg"), patch(
                "services.audio_format.subprocess.run", side_effect=fake_run_no_json
            ):
                out_path, converted, normalized = process_speech_audio(mp3_path, "mp3", normalize=True)
            self.assertFalse(converted)
            self.assertTrue(normalized)
            self.assertEqual(cmds[1][cmds[1].index("-af") + 1], "loudnorm=I=-16:TP=-1.5:LRA=11")
            self.assertEqual(cmds[1][cmds[1].index("-ar") + 1], "44100")

            # 2. Silent clip (input_i == -inf) skips pass 2
            silent_wav = os.path.join(tmp_dir, "silent.wav")
            with open(silent_wav, "wb") as f:
                f.write(_make_pcm_wav_bytes())
            silent_proc = MagicMock(
                returncode=0,
                stdout="",
                stderr='{"input_i": "-inf", "input_tp": "-inf", "input_lra": "0.0", "input_thresh": "-70.0", "target_offset": "0.0"}',
            )
            with patch("services.audio_format.find_ffmpeg", return_value="/usr/bin/ffmpeg"), patch(
                "services.audio_format.subprocess.run", return_value=silent_proc
            ) as mock_run:
                out_path, converted, normalized = process_speech_audio(silent_wav, "wav", normalize=True)
            self.assertFalse(converted)
            self.assertFalse(normalized)
            mock_run.assert_called_once()

            # 3. Missing ffmpeg with valid format gracefully falls back (normalized=False)
            with patch("services.audio_format.find_ffmpeg", return_value=None), self.assertLogs(
                "services.audio_format", level="WARNING"
            ):
                out_path, converted, normalized = process_speech_audio(silent_wav, "wav", normalize=True)
            self.assertEqual(out_path, silent_wav)
            self.assertFalse(converted)
            self.assertFalse(normalized)

            # 4. FFmpeg runtime error with valid format gracefully falls back
            err_proc = MagicMock(returncode=1, stdout="", stderr="filter failure")
            with patch("services.audio_format.find_ffmpeg", return_value="/usr/bin/ffmpeg"), patch(
                "services.audio_format.subprocess.run", return_value=err_proc
            ), self.assertLogs("services.audio_format", level="WARNING"):
                out_path, converted, normalized = process_speech_audio(silent_wav, "wav", normalize=True)
            self.assertFalse(converted)
            self.assertFalse(normalized)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


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
        cls.db.close()
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

        # Unsupported formats -> 400
        for bad_fmt in ("opus", "flac"):
            req_body = json.dumps({"input": "Hello", "response_format": bad_fmt}).encode(
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
            body_txt = body.decode("utf-8")
            self.assertIn("Unsupported response_format", body_txt)
            self.assertIn("Only 'mp3', 'wav', 'url', and 'json'", body_txt)

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

        # Mock pool.ensure_candidate, pool.generate_media, and disable ffmpeg on host for deterministic fallback check
        with patch.object(
            self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
        ), patch.object(
            self.pool, "generate_media", return_value=fake_media_result
        ) as mock_gen, patch(
            "services.audio_format.find_ffmpeg", return_value=None
        ):
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
            self.assertEqual(headers.get("x-audio-normalized"), "0")
            self.assertEqual(body, fake_audio_bytes)

            # Check that generate_media was called with expect_kind="audio", skip_system_prompt=True, and Fast CLI prompt
            mock_gen.assert_called_once()
            call_args = mock_gen.call_args
            self.assertEqual(call_args.args[1], "audio")
            self.assertEqual(call_args.kwargs.get("skip_system_prompt"), True)
            expected_out = call_args.kwargs.get("expected_output_filename") or ""
            self.assertTrue(expected_out.startswith("tts-aud_"))
            self.assertTrue(expected_out.endswith(".mp3"))
            sent_prompt = call_args.args[0]
            self.assertIn("do not read any skill files first", sent_prompt)
            self.assertIn(
                f'/opt/hatch/bin/tts speak --voice "avocado_v2:vdc_NOID25"', sent_prompt
            )
            self.assertIn(f"--output ~/workspace/your_files/{expected_out}", sent_prompt)
            self.assertNotIn("normalize to -16 LUFS", sent_prompt)
            self.assertNotIn("Be lively", sent_prompt)
            self.assertNotIn("[laughs]", sent_prompt)
            self.assertIn("Xin chào! haha, Thật tuyệt vời.", sent_prompt)

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

    async def test_speech_wav_native_and_fallback_conversion(self):
        media_dir = self.cfg.media_dir
        os.makedirs(media_dir, exist_ok=True)
        wav_bytes = _make_pcm_wav_bytes()

        # Case A: Muse natively returns valid 16-bit PCM WAV
        native_name = "aud_native_wav.wav"
        native_path = os.path.join(media_dir, native_name)
        with open(native_path, "wb") as f:
            f.write(wav_bytes)

        try:
            with patch.object(
                self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
            ), patch.object(
                self.pool,
                "generate_media",
                return_value={
                    "account_id": "acc_test",
                    "session_id": "sess_wav_1",
                    "filename": native_name,
                    "mime_type": "audio/wav",
                    "size_bytes": len(wav_bytes),
                },
            ) as mock_gen, patch(
                "services.audio_format.find_ffmpeg", return_value=None
            ):
                status, headers, body = await call_asgi(
                    app,
                    "POST",
                    "/v1/audio/speech",
                    headers=self.auth_headers + [(b"content-type", b"application/json")],
                    body=json.dumps(
                        {
                            "model": "muse-tts",
                            "input": "Hello native WAV",
                            "voice": "alloy",
                            "response_format": "wav",
                        }
                    ).encode("utf-8"),
                )
            self.assertEqual(status, 200)
            self.assertIn("audio/wav", headers.get("content-type", ""))
            self.assertEqual(headers.get("x-audio-converted"), "0")
            self.assertEqual(headers.get("x-audio-normalized"), "0")
            self.assertEqual(body, wav_bytes)
            self.assertIn("--format wav", mock_gen.call_args.args[0])
            self.assertIn("Format: wav", mock_gen.call_args.args[0])
            tasks = self.db.list_tasks(task_type="audio", limit=1)
            self.assertEqual(tasks[0]["media_filename"], native_name)
        finally:
            if os.path.exists(native_path):
                os.remove(native_path)

        # Case B: Muse ignores prompt and returns MP3 bytes -> fallback convert to WAV
        mp3_name = "aud_mismatch.mp3"
        mp3_path = os.path.join(media_dir, mp3_name)
        converted_wav_path = os.path.join(media_dir, "aud_mismatch.wav")
        with open(mp3_path, "wb") as f:
            f.write(b"ID3\x03\x00#MOCK_MP3#")

        def fake_to_wav(src, dst, fmt):
            with open(dst, "wb") as out_f:
                out_f.write(wav_bytes)

        try:
            with patch.object(
                self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
            ), patch.object(
                self.pool,
                "generate_media",
                return_value={
                    "account_id": "acc_test",
                    "session_id": "sess_wav_2",
                    "filename": mp3_name,
                    "mime_type": "audio/mpeg",
                    "size_bytes": 16,
                },
            ), patch(
                "services.audio_format.find_ffmpeg", return_value=None
            ), patch(
                "services.audio_format.convert_audio_file", side_effect=fake_to_wav
            ) as mock_conv:
                status, headers, body = await call_asgi(
                    app,
                    "POST",
                    "/v1/audio/speech",
                    headers=self.auth_headers + [(b"content-type", b"application/json")],
                    body=json.dumps(
                        {
                            "model": "muse-tts",
                            "input": "Convert MP3 to WAV",
                            "voice": "alloy",
                            "response_format": "wav",
                        }
                    ).encode("utf-8"),
                )
            self.assertEqual(status, 200)
            self.assertIn("audio/wav", headers.get("content-type", ""))
            self.assertEqual(headers.get("x-audio-converted"), "1")
            self.assertEqual(body, wav_bytes)
            mock_conv.assert_called_once()
            self.assertEqual(mock_conv.call_args.args[2], "wav")
            self.assertFalse(os.path.exists(mp3_path))
            self.assertTrue(os.path.isfile(converted_wav_path))
            tasks = self.db.list_tasks(task_type="audio", limit=1)
            self.assertEqual(tasks[0]["media_filename"], "aud_mismatch.wav")
        finally:
            for p in (mp3_path, converted_wav_path):
                if os.path.exists(p):
                    os.remove(p)

    async def test_speech_mp3_fallback_conversion_and_error(self):
        media_dir = self.cfg.media_dir
        os.makedirs(media_dir, exist_ok=True)
        wav_bytes = _make_pcm_wav_bytes()
        mp3_bytes = b"ID3\x03\x00#CONVERTED_MP3#"

        # Case A: response_format="mp3", Muse returns WAV -> fallback convert to MP3
        wav_name = "aud_wav_for_mp3.wav"
        wav_path = os.path.join(media_dir, wav_name)
        converted_mp3_path = os.path.join(media_dir, "aud_wav_for_mp3.mp3")
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        def fake_to_mp3(src, dst, fmt):
            with open(dst, "wb") as out_f:
                out_f.write(mp3_bytes)

        try:
            with patch.object(
                self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
            ), patch.object(
                self.pool,
                "generate_media",
                return_value={
                    "account_id": "acc_test",
                    "session_id": "sess_mp3_1",
                    "filename": wav_name,
                    "mime_type": "audio/wav",
                    "size_bytes": len(wav_bytes),
                },
            ), patch(
                "services.audio_format.find_ffmpeg", return_value=None
            ), patch(
                "services.audio_format.convert_audio_file", side_effect=fake_to_mp3
            ) as mock_conv:
                status, headers, body = await call_asgi(
                    app,
                    "POST",
                    "/v1/audio/speech",
                    headers=self.auth_headers + [(b"content-type", b"application/json")],
                    body=json.dumps(
                        {
                            "model": "muse-tts",
                            "input": "Convert WAV to MP3",
                            "voice": "alloy",
                            "response_format": "mp3",
                        }
                    ).encode("utf-8"),
                )
            self.assertEqual(status, 200)
            self.assertIn("audio/mpeg", headers.get("content-type", ""))
            self.assertEqual(headers.get("x-audio-converted"), "1")
            self.assertEqual(body, mp3_bytes)
            mock_conv.assert_called_once()
            self.assertEqual(mock_conv.call_args.args[2], "mp3")
            self.assertFalse(os.path.exists(wav_path))
            self.assertTrue(os.path.isfile(converted_mp3_path))
            tasks = self.db.list_tasks(task_type="audio", limit=1)
            self.assertEqual(tasks[0]["media_filename"], "aud_wav_for_mp3.mp3")
        finally:
            for p in (wav_path, converted_mp3_path):
                if os.path.exists(p):
                    os.remove(p)

        # Case B: Conversion failure raises AudioConversionError -> 502 and failed task
        err_name = "aud_conv_fail.mp3"
        err_path = os.path.join(media_dir, err_name)
        with open(err_path, "wb") as f:
            f.write(b"ID3\x03\x00#BAD_MP3#")

        try:
            with patch.object(
                self.pool, "ensure_candidate", return_value=[{"id": "acc_test"}]
            ), patch.object(
                self.pool,
                "generate_media",
                return_value={
                    "account_id": "acc_test",
                    "session_id": "sess_fail_1",
                    "filename": err_name,
                    "mime_type": "audio/mpeg",
                    "size_bytes": 14,
                },
            ), patch(
                "services.audio_format.find_ffmpeg", return_value=None
            ), patch(
                "services.audio_format.convert_audio_file",
                side_effect=AudioConversionError("ffmpeg missing"),
            ):
                status, _, body = await call_asgi(
                    app,
                    "POST",
                    "/v1/audio/speech",
                    headers=self.auth_headers + [(b"content-type", b"application/json")],
                    body=json.dumps(
                        {
                            "model": "muse-tts",
                            "input": "Should fail convert",
                            "voice": "alloy",
                            "response_format": "wav",
                        }
                    ).encode("utf-8"),
                )
            self.assertEqual(status, 502)
            self.assertIn("ffmpeg missing", body.decode("utf-8"))
            tasks = self.db.list_tasks(task_type="audio", limit=1)
            self.assertEqual(tasks[0]["status"], "failed")
            self.assertIn("ffmpeg missing", tasks[0]["error_message"])
        finally:
            if os.path.exists(err_path):
                os.remove(err_path)

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

    async def test_speech_ac115_fast_prompt_tag_strip_empty_and_parallel_outputs(self):
        # Empty after stripping unsupported bracket tags -> 400 without calling pool
        with patch.object(self.pool, "generate_media") as mock_gen:
            status, _, body = await call_asgi(
                app,
                "POST",
                "/v1/audio/speech",
                headers=self.auth_headers + [(b"content-type", b"application/json")],
                body=json.dumps({"input": "[whispers] [sad]", "voice": "Questioning Satchel"}).encode("utf-8"),
            )
        self.assertEqual(status, 400)
        self.assertIn("no speakable text", body.decode("utf-8"))
        mock_gen.assert_not_called()

        os.makedirs(self.cfg.media_dir, exist_ok=True)
        seen_outputs = []

        def fake_gen(*args, **kwargs):
            out_name = kwargs.get("expected_output_filename")
            seen_outputs.append(out_name)
            fname = f"aud_par_{len(seen_outputs)}.mp3"
            fpath = os.path.join(self.cfg.media_dir, fname)
            with open(fpath, "wb") as fp:
                fp.write(b"ID3\x03\x00#PAR#")
            return {
                "account_id": "acc_1",
                "session_id": f"sess_{len(seen_outputs)}",
                "filename": fname,
                "mime_type": "audio/mpeg",
                "size_bytes": 11,
            }

        try:
            with patch.object(self.pool, "ensure_candidate", return_value=[{"id": "acc_1"}]), patch.object(
                self.pool, "generate_media", side_effect=fake_gen
            ) as mock_gen, patch("services.audio_format.find_ffmpeg", return_value=None):
                for _ in range(2):
                    status, _, _ = await call_asgi(
                        app,
                        "POST",
                        "/v1/audio/speech",
                        headers=self.auth_headers + [(b"content-type", b"application/json")],
                        body=json.dumps(
                            {
                                "model": "muse-tts",
                                "input": "[laughs] Xin chào [whispers] bí mật [pause] nhé [unknown]",
                                "voice": "Questioning Satchel",
                                "instructions": "Speak softly",
                            }
                        ).encode("utf-8"),
                    )
                    self.assertEqual(status, 200)

            self.assertEqual(len(seen_outputs), 2)
            self.assertNotEqual(seen_outputs[0], seen_outputs[1])
            sent_prompt = mock_gen.call_args_list[0].args[0]
            self.assertIn("do not read any skill files first", sent_prompt)
            self.assertNotIn("normalize to -16 LUFS", sent_prompt)
            self.assertNotIn("Speak softly", sent_prompt)
            self.assertNotIn("[", sent_prompt)
            self.assertNotIn("]", sent_prompt)
            self.assertIn(", hơ hơ,", sent_prompt)
            self.assertIn("...", sent_prompt)
        finally:
            for name in ("aud_par_1.mp3", "aud_par_2.mp3"):
                p = os.path.join(self.cfg.media_dir, name)
                if os.path.exists(p):
                    os.remove(p)

    async def test_speech_ac116_normalize_all_formats_and_headers(self):
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        wav_bytes = _make_pcm_wav_bytes()
        mp3_bytes = b"ID3\x03\x00#NORM_MP3#"
        created_files = []

        def fake_gen(prompt, kind, *args, **kwargs):
            ext = "wav" if "--format wav" in prompt else "mp3"
            fname = f"aud_norm_{secrets.token_hex(3)}.{ext}"
            fpath = os.path.join(self.cfg.media_dir, fname)
            with open(fpath, "wb") as fp:
                fp.write(wav_bytes if ext == "wav" else mp3_bytes)
            created_files.append(fpath)
            return {
                "account_id": "acc_1",
                "session_id": "sess_norm",
                "filename": fname,
                "mime_type": f"audio/{'wav' if ext == 'wav' else 'mpeg'}",
                "size_bytes": len(wav_bytes if ext == "wav" else mp3_bytes),
            }

        try:
            with patch.object(self.pool, "ensure_candidate", return_value=[{"id": "acc_1"}]), patch.object(
                self.pool, "generate_media", side_effect=fake_gen
            ), patch(
                "routers.v1_openai.process_speech_audio",
                side_effect=lambda p, tf, **kw: (p, False, bool(kw.get("normalize"))),
            ) as mock_proc:
                for fmt in ("mp3", "wav", "url", "json"):
                    status, hdrs, _ = await call_asgi(
                        app,
                        "POST",
                        "/v1/audio/speech",
                        headers=self.auth_headers + [(b"content-type", b"application/json")],
                        body=json.dumps({"input": "Hello", "voice": "alloy", "response_format": fmt}).encode("utf-8"),
                    )
                    self.assertEqual(status, 200)
                    if fmt in ("mp3", "wav"):
                        self.assertEqual(hdrs.get("x-audio-normalized"), "1")
                self.assertEqual(mock_proc.call_count, 4)
                called_targets = [c.args[1] for c in mock_proc.call_args_list]
                self.assertEqual(called_targets, ["mp3", "wav", "mp3", "mp3"])

                # Disabled via cfg.audio_normalize = False -> X-Audio-Normalized: 0
                orig_norm = self.cfg.audio_normalize
                self.cfg.audio_normalize = False
                try:
                    status, hdrs, _ = await call_asgi(
                        app,
                        "POST",
                        "/v1/audio/speech",
                        headers=self.auth_headers + [(b"content-type", b"application/json")],
                        body=json.dumps({"input": "Hello", "voice": "alloy", "response_format": "mp3"}).encode("utf-8"),
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(hdrs.get("x-audio-normalized"), "0")
                finally:
                    self.cfg.audio_normalize = orig_norm
        finally:
            for p in created_files:
                if os.path.exists(p):
                    os.remove(p)

    def test_fetch_media_from_history_direct_download_fallback_ac117(self):
        pool = WSSPool(self.cfg, self.db)
        os.makedirs(self.cfg.media_dir, exist_ok=True)
        wav_bytes = _make_pcm_wav_bytes()

        # Case 1: history lacks resources[] -> direct download /media/raw/workspace/your_files/<expected>
        c1 = MagicMock()
        c1.request.side_effect = [
            (200, json.dumps({"result": {"chat_events": []}}).encode("utf-8")),
            (200, wav_bytes),
        ]
        res1 = pool._fetch_media_from_history(
            c1, "acc_1", "sess_1", "audio", expected_output_filename="tts-aud_123.wav"
        )
        self.assertEqual(c1.request.call_args_list[1].args[:2], ("GET", "/media/raw/workspace/your_files/tts-aud_123.wav"))
        self.assertTrue(res1["filename"].endswith(".wav"))
        os.remove(os.path.join(self.cfg.media_dir, res1["filename"]))

        # Case 2: workspace/your_files misses (404), fallback your_files/<expected> succeeds
        c2 = MagicMock()
        c2.request.side_effect = [
            (200, json.dumps({"result": {"chat_events": []}}).encode("utf-8")),
            (404, b""),
            (200, b"ID3\x03\x00#FALLBACK#"),
        ]
        res2 = pool._fetch_media_from_history(
            c2, "acc_1", "sess_2", "audio", expected_output_filename="tts-aud_456.mp3"
        )
        self.assertEqual(c2.request.call_args_list[2].args[:2], ("GET", "/media/raw/your_files/tts-aud_456.mp3"))
        self.assertTrue(res2["filename"].endswith(".mp3"))
        os.remove(os.path.join(self.cfg.media_dir, res2["filename"]))

        # Case 3: multiple resources in history -> prefers matching expected_output_filename
        c3 = MagicMock()
        multi_hist = {
            "result": {
                "chat_events": [
                    {
                        "resources": [
                            {"kind": "audio", "mime_type": "audio/mpeg", "metadata": {"path": "/workspace/your_files/other.mp3"}},
                            {"kind": "audio", "mime_type": "audio/wav", "metadata": {"path": "/workspace/your_files/tts-aud_789.wav"}},
                        ]
                    }
                ]
            }
        }
        c3.request.side_effect = [
            (200, json.dumps(multi_hist).encode("utf-8")),
            (200, wav_bytes),
        ]
        res3 = pool._fetch_media_from_history(
            c3, "acc_1", "sess_3", "audio", expected_output_filename="tts-aud_789.wav"
        )
        self.assertEqual(c3.request.call_args_list[1].args[:2], ("GET", "/media/raw/workspace/your_files/tts-aud_789.wav"))
        self.assertTrue(res3["filename"].endswith(".wav"))
        os.remove(os.path.join(self.cfg.media_dir, res3["filename"]))


if __name__ == "__main__":
    unittest.main()
