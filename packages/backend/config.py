"""Configuration loader for muse2apiv2."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv() -> None:
    env_path = os.path.join(_PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

DEFAULT_SYSTEM_PROMPT = (
    "Session isolation\n"
    "Everything in this chat session is independent. Do not use memory or materials from other sessions.\n"
    "Do not save anything from this session to memory. Do not update MEMORY.md, preferences, or goals from this chat. Treat everything here as temporary and session-only."
)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        val = int(float(_env(key, str(default))))
    except (TypeError, ValueError):
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def _env_float(key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        val = float(_env(key, str(default)))
    except (TypeError, ValueError):
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def _default_data_dir() -> str:
    return os.path.join(_PROJECT_ROOT, _env("MUSE2API_DATA_DIR", "data"))


@dataclass
class Config:
    project_root: str = _PROJECT_ROOT
    host: str = field(default_factory=lambda: _env("MUSE2API_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("MUSE2API_PORT", 18610, 1, 65535))
    initial_api_key: str = field(default_factory=lambda: _env("MUSE2API_KEY", "").strip())
    data_dir: str = field(default_factory=_default_data_dir)
    db_path_override: str | None = None
    _default_data_dir_snapshot: str = field(default_factory=_default_data_dir, init=False, repr=False)
    keepalive_interval_minutes: int = field(
        default_factory=lambda: _env_int("MUSE2API_KEEPALIVE_INTERVAL_MINUTES", 20, 5)
    )
    system_prompt_enabled: bool = field(
        default_factory=lambda: _env("MUSE2API_SYSTEM_PROMPT_ENABLED", "0") in ("1", "true", "True")
    )
    system_prompt: str = field(
        default_factory=lambda: _env("MUSE2API_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
    )
    media_cleanup_enabled: bool = field(
        default_factory=lambda: _env("MUSE2API_MEDIA_CLEANUP_ENABLED", "1") in ("1", "true", "True")
    )
    media_retention_days: int = field(
        default_factory=lambda: _env_int("MUSE2API_MEDIA_RETENTION_DAYS", 1, 0)
    )
    media_max_gb: float = field(
        default_factory=lambda: _env_float("MUSE2API_MEDIA_MAX_GB", 1.0, 0.0)
    )
    cleanup_interval_minutes: int = field(
        default_factory=lambda: _env_int("MUSE2API_CLEANUP_INTERVAL_MINUTES", 60, 5)
    )
    ref_image_local_files: bool = field(
        default_factory=lambda: _env("MUSE2API_REF_IMAGE_LOCAL_FILES", "0") in ("1", "true", "True")
    )
    ref_image_private_fetch: bool = field(
        default_factory=lambda: _env("MUSE2API_REF_IMAGE_PRIVATE_FETCH", "0") in ("1", "true", "True")
    )
    tool_protocol: bool = field(
        default_factory=lambda: _env("MUSE2API_TOOL_PROTOCOL", "0") in ("1", "true", "True")
    )
    log_level: str = field(
        default_factory=lambda: (_env("MUSE2API_LOG_LEVEL", "INFO").strip().upper() or "INFO")
    )
    audio_normalize: bool = field(
        default_factory=lambda: _env("MUSE2API_AUDIO_NORMALIZE", "1").strip().lower() in ("1", "true", "yes", "on")
    )
    audio_target_lufs: float = field(
        default_factory=lambda: _env_float("MUSE2API_AUDIO_TARGET_LUFS", -16.0, -70.0, -5.0)
    )
    audio_true_peak: float = field(
        default_factory=lambda: _env_float("MUSE2API_AUDIO_TRUE_PEAK", -1.5, -9.0, 0.0)
    )
    audio_lra: float = field(
        default_factory=lambda: _env_float("MUSE2API_AUDIO_LRA", 11.0, 1.0, 50.0)
    )
    reset_wait_timeout_seconds: float = field(
        default_factory=lambda: _env_float("MUSE2API_RESET_WAIT_TIMEOUT_SECONDS", 150.0, 0.0)
    )
    reset_max_waiters: int = field(
        default_factory=lambda: _env_int("MUSE2API_RESET_MAX_WAITERS", 50, 1)
    )

    @property
    def db_path(self) -> str:
        override = (self.db_path_override or "").strip()
        if not override and self.db_path_override is None:
            if os.path.abspath(self.data_dir) == os.path.abspath(self._default_data_dir_snapshot):
                override = _env("MUSE2API_DB_PATH", "").strip()
        if override:
            if os.path.isabs(override):
                return override
            return os.path.join(self.project_root, override)
        return os.path.join(self.data_dir, "muse2apiv2.db")

    @property
    def media_dir(self) -> str:
        return os.path.join(self.data_dir, "media")

    @property
    def voice_preview_dir(self) -> str:
        return os.path.join(self.data_dir, "voice_previews")

    @property
    def frontend_dist_dir(self) -> str:
        return os.path.join(_PROJECT_ROOT, "packages", "frontend", "dist")
