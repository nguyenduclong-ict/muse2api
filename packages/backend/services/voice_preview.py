"""Voice preview cache and generation service."""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import threading
import time
from typing import Any

from config import Config
from db import Database
from services.audio_format import process_speech_audio
from services.voices import (
    get_voice_language_code,
    get_voice_language_group,
    has_multiple_language_groups,
)

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"\[([^\[\]]*)\]")

_JA_LANGS = {"ja", "jp", "jpn", "japanese"}

_FULLWIDTH_ALNUM_TRANS = str.maketrans(
    {
        **{chr(0xFF10 + i): chr(0x30 + i) for i in range(10)},
        **{chr(0xFF21 + i): chr(0x41 + i) for i in range(26)},
        **{chr(0xFF41 + i): chr(0x61 + i) for i in range(26)},
    }
)

_CJK_SPACE_OR_DECOR_RE = re.compile(r"[\u3000\u30FB\uFF65※★☆♪♫→←⇒■●◆▼／]+")
_CJK_QUOTE_RE = re.compile(r"[「」『』＂＇]+")
_CJK_LEADING_OPEN_BRACKET_RE = re.compile(r"^\s*[（【［｛〈《〔≪]+\s*")
_CJK_TRAILING_CLOSE_BRACKET_RE = re.compile(r"\s*[）】］｝〉》〕≫]+\s*$")
_CJK_OPEN_BRACKET_RE = re.compile(r"[（【［｛〈《〔≪]+")
_CJK_CLOSE_BRACKET_RE = re.compile(r"[）】］｝〉》〕≫]+")
_CJK_WAVE_RANGE_RE = re.compile(r"(?<=[\d時分秒日月年円人個回])\s*[〜～]+\s*(?=\d)")
_CJK_WAVE_KANA_RE = re.compile(r"(?<=[\u3040-\u309F\u30A0-\u30FF])[〜～]+")
_CJK_WAVE_REST_RE = re.compile(r"[〜～]+")
_CJK_ELLIPSIS_END_RE = re.compile(r"[…⋯︙‥]+\s*$")
_CJK_ELLIPSIS_RE = re.compile(r"[…⋯︙‥]+")
_CJK_DASH_START_RE = re.compile(r"^\s*[―—─–－]+\s*")
_CJK_DASH_END_RE = re.compile(r"\s*[―—─–－]+\s*$")
_CJK_DASH_RE = re.compile(r"[―—─–－]+")

_COMMON_TAG_MAP: dict[str, str] = {
    "sighs": "Haiz...",
    "gasps": "Huh!",
    "coughs": "Hm hm!",
    "pause": "...",
    "long pause": "...",
}

_VI_TAG_MAP: dict[str, str] = {
    **_COMMON_TAG_MAP,
    "laughs": ", hơ hơ,",
    "chuckles": ", hơ hơ,",
    "giggles": ", hơ hơ,",
    "clears throat": ", ừm,",
    "sneezes": "Hắt xì!",
}

_DEFAULT_TAG_MAP: dict[str, str] = {
    **_COMMON_TAG_MAP,
    "laughs": ", haha,",
    "chuckles": ", heh,",
    "giggles": ", heh,",
    "clears throat": ", hmm,",
    "sneezes": "Achoo!",
}

SAMPLE_TEXTS: dict[str, str] = {
    "Vietnamese": "Xin chào, đây là bản nghe thử giọng đọc để bạn kiểm tra chất lượng âm thanh.",
    "Japanese": "こんにちは、こちらは音声の品質を確認するためのサンプルボイスです。",
    "Korean": "안녕하세요, 음성 품질을 확인하기 위한 샘플 미리듣기입니다.",
    "Chinese": "你好，这是一段用于试听音质和语气的语音样本。",
    "French": "Bonjour, ceci est un court extrait vocal pour vous permettre d'écouter ma voix.",
    "Spanish": "Hola, esta es una breve muestra de voz para que puedas escuchar cómo sueno.",
    "German": "Hallo, dies ist eine kurze Stimmprobe, damit du hören kannst, wie ich klinge.",
    "Italian": "Ciao, questo è un breve campione vocale per farti ascoltare la mia voce.",
    "Portuguese": "Olá, esta é uma breve amostra de voz para você ouvir como eu soo.",
    "Russian": "Привет, это короткий образец голоса, чтобы вы могли оценить его звучание.",
    "Thai": "สวัสดีครับ นี่คือตัวอย่างเสียงพูดสั้นๆ เพื่อให้คุณทดลองฟังคุณภาพเสียง",
    "Indonesian": "Halo, ini adalah contoh suara singkat agar Anda dapat mendengar kualitas suara saya.",
    "Arabic": "مرحباً، هذه عينة صوتية قصيرة لتتمكن من سماع نبرة وجودة الصوت.",
}

DEFAULT_SAMPLE_TEXT = (
    "Hello! This is a quick voice preview so you can hear how I sound."
)


def safe_preview_filename(voice_id: str, language_group: str | None = None) -> str:
    """Convert arbitrary voice ID (and optional language group) into a safe filesystem filename."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "__", voice_id.strip())
    if language_group and language_group.strip():
        safe_lang = re.sub(r"[^a-zA-Z0-9_-]+", "_", language_group.strip()).strip("_")
        if safe_lang:
            return f"{safe}__{safe_lang}.mp3"
    return f"{safe}.mp3"


def get_sample_text_for_group(group: str) -> str:
    """Retrieve the designated preview sample sentence for a language group."""
    return SAMPLE_TEXTS.get(group, DEFAULT_SAMPLE_TEXT)


def _normalize_cjk_line(line: str, lang: str) -> str:
    """Normalize Japanese/CJK fullwidth punctuation and symbols into TTS-safe forms."""
    line = line.translate(_FULLWIDTH_ALNUM_TRANS)
    line = _CJK_SPACE_OR_DECOR_RE.sub(" ", line)

    range_rep = "から" if lang in _JA_LANGS else "-"
    line = _CJK_WAVE_RANGE_RE.sub(range_rep, line)
    line = _CJK_WAVE_KANA_RE.sub("ー", line)
    line = _CJK_WAVE_REST_RE.sub(" ", line)

    line = re.sub(r"(?<=\d)．(?=\d)", ".", line)
    line = re.sub(r"(?<=\d)：(?=\d)", ":", line)
    line = re.sub(r"[：；]+", ", ", line)

    line = _CJK_QUOTE_RE.sub(" ", line)
    line = _CJK_LEADING_OPEN_BRACKET_RE.sub("", line)
    line = _CJK_TRAILING_CLOSE_BRACKET_RE.sub("", line)
    line = _CJK_OPEN_BRACKET_RE.sub(", ", line)
    line = _CJK_CLOSE_BRACKET_RE.sub(", ", line)

    line = re.sub(r"(?:！？|⁉|‼)+", "! ", line)
    line = re.sub(r"(?:？！|[⁈⁇])+", "? ", line)
    line = re.sub(r"[。｡．]+", ". ", line)
    line = re.sub(r"！+", "! ", line)
    line = re.sub(r"？+", "? ", line)
    line = re.sub(r"[、､，]+", ", ", line)

    line = _CJK_ELLIPSIS_END_RE.sub(".", line)
    line = _CJK_ELLIPSIS_RE.sub(", ", line)

    line = _CJK_DASH_START_RE.sub("", line)
    line = _CJK_DASH_END_RE.sub(".", line)
    line = _CJK_DASH_RE.sub(", ", line)
    return line


def preprocess_speech_text(text: str, language: str | None = None) -> str:
    """Convert supported bracket emotion tags locally and normalize CJK punctuation."""
    lang = (language or "en").strip().lower()
    tag_map = _VI_TAG_MAP if lang == "vi" else _DEFAULT_TAG_MAP

    def _replace_tag(match: re.Match[str]) -> str:
        key = re.sub(r"\s+", " ", match.group(1).strip().lower())
        mapped = tag_map.get(key)
        return f" {mapped} " if mapped else " "

    cleaned_lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line
        while _TAG_RE.search(line):
            line = _TAG_RE.sub(_replace_tag, line)
        line = _normalize_cjk_line(line, lang)
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"\s+([,;!?])", r"\1", line)
        line = re.sub(r"(?<!\.)\s+\.(?!\.)", ".", line)
        line = re.sub(r"\s+(\.{3})", r"\1", line)
        line = re.sub(r",\s*,+", ",", line)
        line = re.sub(r",\s*([.!?])", r"\1", line)
        line = re.sub(r"([.!?]),+", r"\1", line)
        line = re.sub(r"([!?])\.+", r"\1", line)
        line = re.sub(r",([^\s,.;!?])", r", \1", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(line)

    joined = "\n".join(cleaned_lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def sanitize_output_filename(filename: str | None, output_format: str = "mp3") -> str:
    """Sanitize an audio output filename and ensure it has the expected extension."""
    fmt = "wav" if (output_format or "").strip().lower() == "wav" else "mp3"
    base = os.path.basename((filename or "").strip())
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", base).strip("._-")
    if not safe:
        return f"tts-{secrets.token_hex(6)}.{fmt}"
    stem, ext = os.path.splitext(safe)
    if ext.lower() in (".mp3", ".wav"):
        safe_stem = stem.strip("._-") or f"tts-{secrets.token_hex(6)}"
        return f"{safe_stem}.{fmt}"
    return f"{safe}.{fmt}"


def build_speech_prompt(
    text: str,
    voice_id: str,
    voice_name: str,
    instructions: str | None = None,
    speed: float | None = None,
    language: str | None = None,
    output_format: str = "mp3",
    output_filename: str | None = None,
    already_preprocessed: bool = False,
) -> str:
    """Format fast CLI prompt for Muse WSS speech generation (no skill reading, no VM normalization)."""
    lang = re.sub(r"[^a-zA-Z0-9_-]+", "", (language or "en").strip().lower()) or "en"
    fmt = "wav" if (output_format or "mp3").strip().lower() == "wav" else "mp3"
    if speed is None or speed <= 0:
        speed_pct = 100
    elif speed <= 10:
        speed_pct = round(speed * 100)
    else:
        speed_pct = round(speed)

    safe_out = sanitize_output_filename(output_filename, fmt)
    safe_voice_id = (
        (voice_id or "").replace('"', "").replace("\n", "").replace("\r", "").strip()
    )
    safe_voice_name = (
        (voice_name or safe_voice_id).replace("\n", " ").replace("\r", " ").strip()
    )
    spoken_text = (
        (text or "").strip()
        if already_preprocessed
        else preprocess_speech_text(text, lang)
    )

    return (
        "Generate an audio speech file using this exact command, do not read any skill files first:\n\n"
        f'/opt/hatch/bin/tts speak --voice "{safe_voice_id}" --language {lang} --speed {speed_pct} '
        f"--format {fmt} --output ~/workspace/your_files/{safe_out} --text-stdin\n\n"
        f"Voice: {safe_voice_name} ({safe_voice_id})\n"
        f"Language: {lang}\n"
        f"Speed: {speed_pct}\n"
        f"Format: {fmt}\n\n"
        "Text to speak (already converted, read exactly as written, no bracket tags left):\n"
        f"{spoken_text}"
    )


class VoicePreviewService:
    """Manages disk-cached voice sample previews with in-flight deduplication."""

    def __init__(self, cfg: Config, db: Database, pool: Any):
        self.cfg = cfg
        self.db = db
        self.pool = pool
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        os.makedirs(self.cfg.voice_preview_dir, exist_ok=True)

    def _cache_lang_suffix(
        self, voice_id: str, language_group: str | None
    ) -> str | None:
        if language_group and has_multiple_language_groups(voice_id):
            return language_group
        return None

    def get_preview_filename(
        self, voice_id: str, language_group: str | None = None
    ) -> str:
        return safe_preview_filename(
            voice_id, self._cache_lang_suffix(voice_id, language_group)
        )

    def get_preview_path(self, voice_id: str, language_group: str | None = None) -> str:
        return os.path.join(
            self.cfg.voice_preview_dir,
            self.get_preview_filename(voice_id, language_group),
        )

    def is_cached(self, voice_id: str, language_group: str | None = None) -> bool:
        p = self.get_preview_path(voice_id, language_group)
        return os.path.isfile(p) and os.path.getsize(p) > 0

    def get_stats(self) -> dict[str, Any]:
        """Return total cached files and aggregated size in bytes."""
        count = 0
        total_bytes = 0
        if os.path.isdir(self.cfg.voice_preview_dir):
            for name in os.listdir(self.cfg.voice_preview_dir):
                if name.endswith(".mp3"):
                    p = os.path.join(self.cfg.voice_preview_dir, name)
                    if os.path.isfile(p):
                        count += 1
                        total_bytes += os.path.getsize(p)
        return {"count": count, "total_bytes": total_bytes}

    def clear_all(self) -> int:
        """Purge all cached preview MP3 files."""
        deleted = 0
        if os.path.isdir(self.cfg.voice_preview_dir):
            for name in os.listdir(self.cfg.voice_preview_dir):
                if name.endswith(".mp3"):
                    p = os.path.join(self.cfg.voice_preview_dir, name)
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                            deleted += 1
                    except OSError:
                        pass
        return deleted

    def delete_one(self, voice_id: str, language_group: str | None = None) -> bool:
        """Delete preview cache for a specific voice ID (and optional language group)."""
        if language_group is not None:
            p = self.get_preview_path(voice_id, language_group)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    return True
                except OSError:
                    return False
            return False

        deleted_any = False
        base_path = self.get_preview_path(voice_id)
        if os.path.isfile(base_path):
            try:
                os.remove(base_path)
                deleted_any = True
            except OSError:
                pass
        if has_multiple_language_groups(voice_id) and os.path.isdir(
            self.cfg.voice_preview_dir
        ):
            prefix = safe_preview_filename(voice_id)[:-4] + "__"
            for name in os.listdir(self.cfg.voice_preview_dir):
                if name.startswith(prefix) and name.endswith(".mp3"):
                    try:
                        os.remove(os.path.join(self.cfg.voice_preview_dir, name))
                        deleted_any = True
                    except OSError:
                        pass
        return deleted_any

    def get_or_generate_preview(
        self,
        voice_info: dict[str, Any],
        refresh: bool = False,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Fetch cached preview or synchronously generate a new sample from Muse WSS."""
        voice_id = voice_info["id"]
        voice_name = voice_info.get("name") or voice_id
        lang_group = get_voice_language_group(voice_info)
        sample_text = get_sample_text_for_group(lang_group)
        filename = self.get_preview_filename(voice_id, lang_group)
        dst_path = self.get_preview_path(voice_id, lang_group)

        # Fast path: cache hit without lock
        if not refresh and os.path.isfile(dst_path) and os.path.getsize(dst_path) > 0:
            return {
                "voice_id": voice_id,
                "voice_name": voice_name,
                "language_group": lang_group,
                "sample_text": sample_text,
                "filename": filename,
                "file_path": dst_path,
                "cached": True,
                "bytes": os.path.getsize(dst_path),
            }

        # In-flight lock per cache filename to prevent redundant generation
        lock_key = filename
        with self._locks_guard:
            if lock_key not in self._locks:
                self._locks[lock_key] = threading.Lock()
            vlock = self._locks[lock_key]

        with vlock:
            # Double check inside lock
            if (
                not refresh
                and os.path.isfile(dst_path)
                and os.path.getsize(dst_path) > 0
            ):
                return {
                    "voice_id": voice_id,
                    "voice_name": voice_name,
                    "language_group": lang_group,
                    "sample_text": sample_text,
                    "filename": filename,
                    "file_path": dst_path,
                    "cached": True,
                    "bytes": os.path.getsize(dst_path),
                }

            if hasattr(self.pool, "ensure_candidate"):
                self.pool.ensure_candidate("speech")

            task_id = f"aud_prev_{secrets.token_hex(4)}"
            prompt_preview = f"[Voice Preview] {voice_name}: {sample_text[:140]}"
            self.db.create_task(
                task_id,
                "audio",
                status="running",
                model="muse-tts",
                prompt_preview=prompt_preview,
                input_request={
                    "source": "voice_preview",
                    "voice_id": voice_id,
                    "voice_name": voice_name,
                    "language": lang_group,
                    "sample_text": sample_text,
                },
            )
            t0 = time.time()

            output_filename = f"tts-{task_id}.mp3"
            prompt = build_speech_prompt(
                text=sample_text,
                voice_id=voice_id,
                voice_name=voice_name,
                instructions=None,
                speed=None,
                language=get_voice_language_code(voice_info),
                output_format="mp3",
                output_filename=output_filename,
            )

            try:
                res = self.pool.generate_media(
                    prompt,
                    "audio",
                    None,
                    timeout,
                    skip_system_prompt=True,
                    expected_output_filename=output_filename,
                )
                src_path = os.path.join(self.cfg.media_dir, res["filename"])
                processed_path, _, _ = process_speech_audio(
                    src_path,
                    "mp3",
                    normalize=self.cfg.audio_normalize,
                    target_lufs=self.cfg.audio_target_lufs,
                    true_peak=self.cfg.audio_true_peak,
                    lra=self.cfg.audio_lra,
                )
                tmp_path = dst_path + ".tmp"
                shutil.copyfile(processed_path, tmp_path)
                os.replace(tmp_path, dst_path)

                # Clean up duplicate media file(s) from media_dir
                for cleanup_path in {src_path, processed_path}:
                    try:
                        if cleanup_path and os.path.isfile(cleanup_path):
                            os.remove(cleanup_path)
                    except OSError:
                        pass

                latency_ms = int((time.time() - t0) * 1000)
                self.db.update_task(
                    task_id,
                    status="completed",
                    account_id=res.get("account_id"),
                    session_id=res.get("session_id"),
                    media_filename=filename,
                    latency_ms=latency_ms,
                )
                return {
                    "voice_id": voice_id,
                    "voice_name": voice_name,
                    "language_group": lang_group,
                    "sample_text": sample_text,
                    "filename": filename,
                    "file_path": dst_path,
                    "cached": False,
                    "bytes": os.path.getsize(dst_path),
                }
            except Exception as exc:
                latency_ms = int((time.time() - t0) * 1000)
                self.db.update_task(
                    task_id,
                    status="failed",
                    error_message=str(exc),
                    latency_ms=latency_ms,
                )
                raise
