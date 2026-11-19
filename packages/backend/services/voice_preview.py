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
from services.voices import get_voice_language_code, get_voice_language_group

logger = logging.getLogger(__name__)

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

DEFAULT_SAMPLE_TEXT = "Hello! This is a quick voice preview so you can hear how I sound."


def safe_preview_filename(voice_id: str) -> str:
    """Convert arbitrary voice ID into a safe filesystem filename."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "__", voice_id.strip())
    return f"{safe}.mp3"


def get_sample_text_for_group(group: str) -> str:
    """Retrieve the designated preview sample sentence for a language group."""
    return SAMPLE_TEXTS.get(group, DEFAULT_SAMPLE_TEXT)


def build_speech_prompt(
    text: str,
    voice_id: str,
    voice_name: str,
    instructions: str | None = None,
    speed: float | None = None,
    language: str | None = None,
) -> str:
    """Format user prompt instructions for Muse WSS speech generation."""
    lang = (language or "en").strip() or "en"
    if speed is None or speed <= 0:
        speed_pct = 100
    elif speed <= 10:
        speed_pct = round(speed * 100)
    else:
        speed_pct = round(speed)

    header_lines = [
        f'Generate an MP3 audio speech file using voice "{voice_id}" ({voice_name}).',
        f"Language: {lang}. Speed: {speed_pct}.",
    ]
    if instructions and instructions.strip():
        header_lines.append(f"Style / delivery instructions: {instructions.strip()}")

    emotion_guide = (
        "Do NOT read any bracket tags literally. Convert them to spoken sounds or delivery cues first:\n"
        '- [laughs] → "Ha ha ha!"\n'
        '- [chuckles], [giggles] → "He he he!"\n'
        '- [sighs] → "Haa..."\n'
        '- [gasps] → "Huh!"\n'
        '- [coughs] → "Hm hm!"\n'
        '- [sneezes] → "Achoo!" (or "Hắt xì!" in Vietnamese)\n'
        '- [clears throat] → "Hmm!"\n'
        '- [pause], [long pause] → "..." (brief / longer pause)\n'
        "- [whispers] → read the following words slowly and quietly\n"
        "- [shouts] → read faster and louder with emphasis\n"
        "- [angry], [sad], [happy], [excited] → adjust pacing and tone to match the mood\n"
        "- Any other [tag] → omit the tag, do not speak it literally"
    )

    speak_block = (
        "Then speak this text, with the converted sounds in place:\n"
        f'"{text}"'
    )

    return "\n\n".join(["\n".join(header_lines), emotion_guide, speak_block])


class VoicePreviewService:
    """Manages disk-cached voice sample previews with in-flight deduplication."""

    def __init__(self, cfg: Config, db: Database, pool: Any):
        self.cfg = cfg
        self.db = db
        self.pool = pool
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        os.makedirs(self.cfg.voice_preview_dir, exist_ok=True)

    def get_preview_filename(self, voice_id: str) -> str:
        return safe_preview_filename(voice_id)

    def get_preview_path(self, voice_id: str) -> str:
        return os.path.join(self.cfg.voice_preview_dir, self.get_preview_filename(voice_id))

    def is_cached(self, voice_id: str) -> bool:
        p = self.get_preview_path(voice_id)
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

    def delete_one(self, voice_id: str) -> bool:
        """Delete preview cache for a specific voice ID."""
        p = self.get_preview_path(voice_id)
        if os.path.isfile(p):
            try:
                os.remove(p)
                return True
            except OSError:
                return False
        return False

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
        filename = self.get_preview_filename(voice_id)
        dst_path = self.get_preview_path(voice_id)

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

        # In-flight lock per voice_id to prevent redundant generation
        with self._locks_guard:
            if voice_id not in self._locks:
                self._locks[voice_id] = threading.Lock()
            vlock = self._locks[voice_id]

        with vlock:
            # Double check inside lock
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
            )
            t0 = time.time()

            prompt = build_speech_prompt(
                text=sample_text,
                voice_id=voice_id,
                voice_name=voice_name,
                instructions=None,
                speed=None,
                language=get_voice_language_code(voice_info),
            )

            try:
                res = self.pool.generate_media(
                    prompt,
                    "audio",
                    None,
                    timeout,
                    skip_system_prompt=True,
                )
                src_path = os.path.join(self.cfg.media_dir, res["filename"])
                tmp_path = dst_path + ".tmp"
                shutil.copyfile(src_path, tmp_path)
                os.replace(tmp_path, dst_path)

                # Clean up duplicate media file from media_dir
                try:
                    if os.path.isfile(src_path):
                        os.remove(src_path)
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
