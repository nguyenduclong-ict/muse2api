"""Media retention and storage cap cleanup service."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from config import Config
from db import Database


class CleanupService:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run_at: float = 0.0
        self.last_freed_bytes: int = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            settings = self.db.get_settings().get("media_cleanup", {})
            interval_m = max(5, int(settings.get("interval_minutes", 60)))
            if self._stop.wait(interval_m * 60):
                break
            if settings.get("enabled", True):
                try:
                    self.run_now()
                except Exception:
                    pass

    def storage_usage_bytes(self) -> int:
        total = 0
        if not os.path.isdir(self.cfg.media_dir):
            return 0
        for name in os.listdir(self.cfg.media_dir):
            p = os.path.join(self.cfg.media_dir, name)
            if os.path.isfile(p):
                total += os.path.getsize(p)
        return total

    def run_now(self) -> dict[str, Any]:
        settings = self.db.get_settings().get("media_cleanup", {})
        retention_days = int(settings.get("retention_days", 1))
        max_gb = float(settings.get("max_gb", 1.0))

        deleted = 0
        freed = 0
        now = time.time()
        files: list[tuple[str, int, float]] = []

        if os.path.isdir(self.cfg.media_dir):
            for name in os.listdir(self.cfg.media_dir):
                p = os.path.join(self.cfg.media_dir, name)
                if not os.path.isfile(p):
                    continue
                st = os.stat(p)
                if retention_days > 0 and (now - st.st_mtime) > retention_days * 86400:
                    os.remove(p)
                    deleted += 1
                    freed += st.st_size
                else:
                    files.append((p, st.st_size, st.st_mtime))

        if max_gb > 0:
            cap_bytes = int(max_gb * (1024 ** 3))
            total = sum(sz for _, sz, _ in files)
            if total > cap_bytes:
                files.sort(key=lambda x: x[2])  # oldest first
                for p, sz, _ in files:
                    if total <= cap_bytes:
                        break
                    try:
                        os.remove(p)
                        deleted += 1
                        freed += sz
                        total -= sz
                    except OSError:
                        pass

        self.last_run_at = now
        self.last_freed_bytes = freed
        return {
            "deleted_files": deleted,
            "freed_bytes": freed,
            "current_usage_bytes": self.storage_usage_bytes(),
        }
