"""Audio format verification and ffmpeg-based fallback conversion for TTS speech output."""
from __future__ import annotations

import io
import logging
import os
import secrets
import shutil
import subprocess
import wave

logger = logging.getLogger(__name__)

SUPPORTED_SPEECH_FORMATS = {"mp3", "wav", "url", "json"}
BINARY_SPEECH_FORMATS = {"mp3", "wav"}
AUDIO_MEDIA_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
}


class AudioConversionError(RuntimeError):
    """Raised when audio format verification or ffmpeg conversion fails."""


def detect_audio_format(data: bytes) -> str | None:
    """Detect whether raw audio bytes are WAV or MP3 from container/frame headers."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3"):
        return "mp3"
    if (
        len(data) >= 2
        and data[0] == 0xFF
        and (data[1] & 0xE0) == 0xE0
        and (data[1] & 0x18) != 0x08
        and (data[1] & 0x06) != 0x00
    ):
        return "mp3"
    return None


def is_pcm16_wav(data: bytes) -> bool:
    """Verify that bytes are a valid uncompressed 16-bit PCM RIFF/WAVE file."""
    if detect_audio_format(data) != "wav":
        return False
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            return (
                wf.getcomptype() == "NONE"
                and wf.getsampwidth() == 2
                and wf.getnchannels() >= 1
                and wf.getframerate() > 0
            )
    except (wave.Error, EOFError, ValueError):
        return False


def matches_target_format(data: bytes, target_format: str) -> bool:
    """Return True if raw audio bytes match the exact required target format."""
    fmt = (target_format or "").strip().lower()
    if fmt == "wav":
        return is_pcm16_wav(data)
    if fmt == "mp3":
        return detect_audio_format(data) == "mp3"
    return False


def find_ffmpeg() -> str | None:
    """Locate ffmpeg binary from FFMPEG_PATH env var or system PATH."""
    env_bin = os.environ.get("FFMPEG_PATH", "").strip()
    if env_bin:
        if os.path.isfile(env_bin):
            return env_bin
        resolved = shutil.which(env_bin)
        if resolved:
            return resolved
    return shutil.which("ffmpeg")


def _cleanup_tmp(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def convert_audio_file(src_path: str, dst_path: str, target_format: str) -> None:
    """Transcode src_path into target_format ('mp3' or 'wav' PCM16) atomically at dst_path."""
    fmt = (target_format or "").strip().lower()
    if fmt not in BINARY_SPEECH_FORMATS:
        raise AudioConversionError(f"Unsupported target audio format '{target_format}'")

    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        raise AudioConversionError(
            f"ffmpeg is not installed or not found in PATH; cannot convert audio to '{fmt}'"
        )

    tmp_path = f"{dst_path}.{secrets.token_hex(4)}.tmp"
    if fmt == "wav":
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            src_path,
            "-acodec",
            "pcm_s16le",
            "-f",
            "wav",
            tmp_path,
        ]
    else:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            src_path,
            "-codec:a",
            "libmp3lame",
            "-qscale:a",
            "2",
            "-f",
            "mp3",
            tmp_path,
        ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        _cleanup_tmp(tmp_path)
        raise AudioConversionError(f"ffmpeg execution failed converting to '{fmt}': {exc}") from exc

    if proc.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
        err_detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        _cleanup_tmp(tmp_path)
        raise AudioConversionError(f"ffmpeg failed converting to '{fmt}': {err_detail}")

    os.replace(tmp_path, dst_path)


def ensure_audio_file_format(file_path: str, target_format: str) -> tuple[str, bool]:
    """Ensure file_path matches target_format, converting with ffmpeg if needed.

    Returns (final_path, was_converted).
    """
    fmt = (target_format or "").strip().lower()
    if fmt not in BINARY_SPEECH_FORMATS:
        raise AudioConversionError(f"Unsupported target audio format '{target_format}'")
    if not os.path.isfile(file_path):
        raise AudioConversionError(f"Audio file not found: {file_path}")

    with open(file_path, "rb") as f:
        data = f.read()

    dst_path = os.path.splitext(file_path)[0] + f".{fmt}"
    if matches_target_format(data, fmt):
        if os.path.abspath(dst_path) != os.path.abspath(file_path):
            os.replace(file_path, dst_path)
            return dst_path, False
        return file_path, False

    detected = detect_audio_format(data) or "unknown"
    logger.info(
        "Audio format mismatch for %s: expected=%s, detected=%s; converting with ffmpeg",
        os.path.basename(file_path),
        fmt,
        detected,
    )
    convert_audio_file(file_path, dst_path, fmt)
    if os.path.abspath(dst_path) != os.path.abspath(file_path) and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    return dst_path, True
