"""Audio format verification, ffmpeg conversion, and 2-pass loudness normalization."""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import wave
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_SPEECH_FORMATS = {"mp3", "wav", "url", "json"}
BINARY_SPEECH_FORMATS = {"mp3", "wav"}
AUDIO_MEDIA_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
}

DEFAULT_TARGET_LUFS = -16.0
DEFAULT_TRUE_PEAK = -1.5
DEFAULT_LRA = 11.0

_LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
_LOUDNORM_JSON_RE = re.compile(r'\{[^{}]*"input_i"[^{}]*\}', re.DOTALL)
_AUDIO_SR_RE = re.compile(r"Audio:.*?(\d+)\s*Hz")
_FALLBACK_SR_RE = re.compile(r"\b(\d{4,6})\s*Hz\b")


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


def _remove_old_source(src_path: str, dst_path: str) -> None:
    if os.path.abspath(dst_path) != os.path.abspath(src_path) and os.path.isfile(src_path):
        try:
            os.remove(src_path)
        except OSError:
            pass


def _rename_if_needed(src_path: str, dst_path: str) -> str:
    if os.path.abspath(dst_path) != os.path.abspath(src_path):
        os.replace(src_path, dst_path)
        return dst_path
    return src_path


def _get_wav_sample_rate(data: bytes) -> int | None:
    """Extract sample rate from a WAV header without spawning ffprobe."""
    if detect_audio_format(data) != "wav":
        return None
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            sr = int(wf.getframerate())
            return sr if sr > 0 else None
    except (wave.Error, EOFError, ValueError):
        return None


def _parse_sample_rate_from_ffmpeg_stderr(stderr: str) -> int | None:
    """Parse input audio stream sample rate from ffmpeg stderr output."""
    if not stderr:
        return None
    m = _AUDIO_SR_RE.search(stderr) or _FALLBACK_SR_RE.search(stderr)
    if not m:
        return None
    try:
        sr = int(m.group(1))
    except ValueError:
        return None
    return sr if 8000 <= sr <= 192000 else None


def _parse_loudnorm_stats(stderr: str) -> dict[str, str] | None:
    """Parse the final JSON stats block emitted by ffmpeg loudnorm pass 1."""
    if not stderr:
        return None
    matches = _LOUDNORM_JSON_RE.findall(stderr)
    for raw_json in reversed(matches):
        try:
            parsed = json.loads(raw_json)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and all(k in parsed for k in _LOUDNORM_KEYS):
            return {k: str(parsed[k]).strip() for k in _LOUDNORM_KEYS}
    return None


def _is_finite_metric(val: Any) -> bool:
    try:
        return math.isfinite(float(val))
    except (TypeError, ValueError):
        return False


def _is_silent_loudnorm(stats: dict[str, Any]) -> bool:
    raw = str(stats.get("input_i") or "").strip().lower()
    if raw in ("-inf", "-infinity"):
        return True
    try:
        return float(raw) == float("-inf")
    except ValueError:
        return False


def _measure_loudnorm(
    ffmpeg_bin: str,
    src_path: str,
    target_lufs: float,
    true_peak: float,
    lra: float,
) -> tuple[dict[str, str] | None, int | None]:
    """Run pass 1 of ffmpeg loudnorm to measure loudness metrics and sample rate."""
    af = f"loudnorm=I={target_lufs:g}:TP={true_peak:g}:LRA={lra:g}:print_format=json"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-nostats",
        "-i",
        src_path,
        "-af",
        af,
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        raise AudioConversionError(f"ffmpeg loudnorm measurement failed: {exc}") from exc

    if proc.returncode != 0:
        err_detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        raise AudioConversionError(f"ffmpeg loudnorm measurement failed: {err_detail}")

    stderr = proc.stderr or ""
    return _parse_loudnorm_stats(stderr), _parse_sample_rate_from_ffmpeg_stderr(stderr)


def _encode_audio_file(
    ffmpeg_bin: str,
    src_path: str,
    dst_path: str,
    target_format: str,
    *,
    audio_filter: str | None = None,
    sample_rate: int | None = None,
) -> None:
    """Encode src_path atomically into dst_path with optional audio filter and sample rate."""
    fmt = (target_format or "").strip().lower()
    if fmt not in BINARY_SPEECH_FORMATS:
        raise AudioConversionError(f"Unsupported target audio format '{target_format}'")

    tmp_path = f"{dst_path}.{secrets.token_hex(4)}.tmp"
    cmd = [ffmpeg_bin, "-y", "-v", "error", "-i", src_path]
    if audio_filter:
        cmd.extend(["-af", audio_filter])
    if sample_rate and sample_rate > 0:
        cmd.extend(["-ar", str(int(sample_rate))])
    if fmt == "wav":
        cmd.extend(["-acodec", "pcm_s16le", "-f", "wav", tmp_path])
    else:
        cmd.extend(["-codec:a", "libmp3lame", "-qscale:a", "2", "-f", "mp3", tmp_path])

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

    _encode_audio_file(ffmpeg_bin, src_path, dst_path, fmt)


def process_speech_audio(
    file_path: str,
    target_format: str,
    *,
    normalize: bool = True,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    true_peak: float = DEFAULT_TRUE_PEAK,
    lra: float = DEFAULT_LRA,
) -> tuple[str, bool, bool]:
    """Verify/convert audio format and optionally apply 2-pass loudnorm locally.

    Returns (final_path, was_converted, was_normalized).
    """
    fmt = (target_format or "").strip().lower()
    if fmt not in BINARY_SPEECH_FORMATS:
        raise AudioConversionError(f"Unsupported target audio format '{target_format}'")
    if not os.path.isfile(file_path):
        raise AudioConversionError(f"Audio file not found: {file_path}")

    with open(file_path, "rb") as f:
        data = f.read()

    dst_path = os.path.splitext(file_path)[0] + f".{fmt}"
    needs_convert = not matches_target_format(data, fmt)

    if not normalize:
        if not needs_convert:
            return _rename_if_needed(file_path, dst_path), False, False
        logger.info(
            "Audio format mismatch for %s: expected=%s, detected=%s; converting with ffmpeg",
            os.path.basename(file_path),
            fmt,
            detect_audio_format(data) or "unknown",
        )
        convert_audio_file(file_path, dst_path, fmt)
        _remove_old_source(file_path, dst_path)
        return dst_path, True, False

    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        if needs_convert:
            logger.info(
                "Audio format mismatch for %s: expected=%s, detected=%s; converting with ffmpeg",
                os.path.basename(file_path),
                fmt,
                detect_audio_format(data) or "unknown",
            )
            convert_audio_file(file_path, dst_path, fmt)
            _remove_old_source(file_path, dst_path)
            return dst_path, True, False
        logger.warning(
            "ffmpeg not found in PATH; skipping local loudness normalization for %s",
            os.path.basename(file_path),
        )
        return _rename_if_needed(file_path, dst_path), False, False

    orig_sr = _get_wav_sample_rate(data)
    try:
        stats, stderr_sr = _measure_loudnorm(
            ffmpeg_bin, file_path, target_lufs, true_peak, lra
        )
        effective_sr = orig_sr or stderr_sr

        if stats is not None and _is_silent_loudnorm(stats):
            logger.info(
                "Skipping loudness normalization for silent audio %s",
                os.path.basename(file_path),
            )
            if needs_convert:
                convert_audio_file(file_path, dst_path, fmt)
                _remove_old_source(file_path, dst_path)
                return dst_path, True, False
            return _rename_if_needed(file_path, dst_path), False, False

        if stats is not None and all(_is_finite_metric(stats.get(k)) for k in _LOUDNORM_KEYS):
            loudnorm_filter = (
                f"loudnorm=I={target_lufs:g}:TP={true_peak:g}:LRA={lra:g}"
                f":measured_I={stats['input_i']}"
                f":measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}"
                f":measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}"
                ":linear=true:print_format=summary"
            )
        else:
            logger.warning(
                "Could not parse 2-pass loudnorm metrics for %s; falling back to 1-pass loudnorm",
                os.path.basename(file_path),
            )
            loudnorm_filter = f"loudnorm=I={target_lufs:g}:TP={true_peak:g}:LRA={lra:g}"

        _encode_audio_file(
            ffmpeg_bin,
            file_path,
            dst_path,
            fmt,
            audio_filter=loudnorm_filter,
            sample_rate=effective_sr,
        )
        _remove_old_source(file_path, dst_path)
        return dst_path, needs_convert, True
    except AudioConversionError as exc:
        if needs_convert:
            raise
        logger.warning(
            "Local loudness normalization failed for %s (%s); returning original audio",
            os.path.basename(file_path),
            exc,
        )
        return _rename_if_needed(file_path, dst_path), False, False


def ensure_audio_file_format(file_path: str, target_format: str) -> tuple[str, bool]:
    """Ensure file_path matches target_format, converting with ffmpeg if needed.

    Returns (final_path, was_converted).
    """
    final_path, was_converted, _ = process_speech_audio(
        file_path, target_format, normalize=False
    )
    return final_path, was_converted
