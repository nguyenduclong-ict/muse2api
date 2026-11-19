"""SQLite persistence layer for muse2apiv2."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable, TypeVar

from config import Config, DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

_VALID_JOURNAL_MODES = frozenset({"DELETE", "TRUNCATE", "PERSIST", "WAL", "MEMORY", "OFF"})
_NON_WAL_FS_TYPES = frozenset({
    "9p",
    "cifs",
    "smb",
    "smb3",
    "smbfs",
    "nfs",
    "nfs4",
    "vboxsf",
    "fuse",
    "fuse.sshfs",
    "drvfs",
})
_TRANSIENT_SQLITE_ERRORS = (
    "unable to open database file",
    "disk i/o error",
    "database is locked",
    "database is busy",
)


def _detect_mount_fstype(path: str, mounts_file: str = "/proc/mounts") -> str | None:
    """Detect filesystem type for path from /proc/mounts using longest mount prefix."""
    if not mounts_file or not os.path.isfile(mounts_file):
        return None
    target = os.path.realpath(os.path.abspath(path))
    best_len = -1
    best_fstype: str | None = None
    try:
        with open(mounts_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1].replace("\\040", " ").replace("\\011", "\t")
                fstype = parts[2].strip().lower()
                mp_norm = mp.rstrip("/") or "/"
                matched = target == mp or mp_norm == "/" or target.startswith(mp_norm + "/")
                if matched and len(mp) > best_len:
                    best_len = len(mp)
                    best_fstype = fstype
    except OSError:
        return None
    return best_fstype


def resolve_journal_mode(
    db_path: str,
    env_override: str | None = None,
    mounts_file: str = "/proc/mounts",
) -> str:
    """Choose SQLite journal_mode based on explicit override or filesystem type."""
    raw_env = env_override if env_override is not None else os.environ.get("MUSE2API_SQLITE_JOURNAL_MODE", "")
    override = raw_env.strip().upper()
    if override in _VALID_JOURNAL_MODES:
        return override

    db_dir = os.path.dirname(os.path.abspath(db_path)) or "."
    fstype = _detect_mount_fstype(db_dir, mounts_file=mounts_file)
    if fstype in _NON_WAL_FS_TYPES:
        return "TRUNCATE"
    return "WAL"

MAX_INPUT_REQUEST_BYTES = 32 * 1024
_TRUNCATED_SUFFIX = "... [truncated]"
_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)
_RAW_B64_RE = re.compile(r"^[A-Za-z0-9+/=]{512,}$")
_BASE64_KEY_HINTS = frozenset({"b64_json", "image", "image_base64", "file", "data"})


def _sanitize_input_value(val: Any, key_hint: str = "") -> Any:
    """Recursively sanitize binary/base64 payloads into compact metadata strings."""
    if isinstance(val, dict):
        return {str(k): _sanitize_input_value(v, str(k)) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_sanitize_input_value(item, key_hint) for item in val]
    if isinstance(val, (bytes, bytearray)):
        return f"[binary {len(val)} bytes]"
    if isinstance(val, str):
        stripped = val.strip()
        m = _DATA_URI_RE.match(stripped)
        if m:
            mime, b64_part = m.group(1), m.group(2)
            kb = max(1, round(len(b64_part) * 3 / 4 / 1024))
            return f"[base64 {mime} ~{kb}KB]"
        if len(stripped) >= 512 and key_hint.lower() in _BASE64_KEY_HINTS and _RAW_B64_RE.match(stripped):
            kb = max(1, round(len(stripped) * 3 / 4 / 1024))
            return f"[base64 ~{kb}KB]"
        return val
    if isinstance(val, (int, float, bool)) or val is None:
        return val
    return str(val)


def _find_longest_str(node: Any) -> tuple[Any, Any, str] | None:
    """Return (container, key_or_index, string_value) for the longest string in node."""
    best: tuple[Any, Any, str] | None = None
    best_len = 0

    def walk(cur: Any) -> None:
        nonlocal best, best_len
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, str):
                    if len(v) > best_len:
                        best = (cur, k, v)
                        best_len = len(v)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(cur, list):
            for idx, v in enumerate(cur):
                if isinstance(v, str):
                    if len(v) > best_len:
                        best = (cur, idx, v)
                        best_len = len(v)
                elif isinstance(v, (dict, list)):
                    walk(v)

    walk(node)
    return best


def serialize_input_request(payload: Any, max_bytes: int = MAX_INPUT_REQUEST_BYTES) -> str:
    """Sanitize and serialize task input request JSON, capping at max_bytes UTF-8."""
    if payload is None or payload == "":
        return ""
    data = _sanitize_input_value(payload)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    while len(raw.encode("utf-8")) > max_bytes:
        longest = _find_longest_str(data)
        if not longest:
            break
        container, key, text = longest
        base = text[:-len(_TRUNCATED_SUFFIX)] if text.endswith(_TRUNCATED_SUFFIX) else text
        if len(base) <= 16:
            break
        new_len = max(16, len(base) // 2)
        container[key] = base[:new_len] + _TRUNCATED_SUFFIX
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > max_bytes:
        raw_preview = raw.encode("utf-8")[: max(64, max_bytes - 64)].decode("utf-8", errors="ignore")
        raw = json.dumps({"_truncated": True, "preview": raw_preview + _TRUNCATED_SUFFIX}, ensure_ascii=False, separators=(",", ":"))
    return raw

SUPPORTED_MODEL_TYPES: tuple[str, ...] = ("chat", "image", "video", "speech")
_SUPPORTED_MODEL_SET: frozenset[str] = frozenset(SUPPORTED_MODEL_TYPES)
DEFAULT_SUPPORTED_MODELS_JSON: str = json.dumps(list(SUPPORTED_MODEL_TYPES))


def normalize_supported_models(models: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    """Validate and normalize account supported_models into canonical order."""
    if not isinstance(models, (list, tuple, set)):
        raise ValueError("supported_models must contain at least one of: chat, image, video, speech")
    seen: set[str] = set()
    invalid: list[str] = []
    for item in models:
        if not isinstance(item, str):
            invalid.append(str(item))
            continue
        norm = item.strip().lower()
        if norm not in _SUPPORTED_MODEL_SET:
            invalid.append(item)
        else:
            seen.add(norm)
    if invalid:
        raise ValueError(
            f"Unsupported model type(s): {', '.join(invalid)}. Allowed values: {', '.join(SUPPORTED_MODEL_TYPES)}"
        )
    ordered = [m for m in SUPPORTED_MODEL_TYPES if m in seen]
    if not ordered:
        raise ValueError(f"supported_models must contain at least one of: {', '.join(SUPPORTED_MODEL_TYPES)}")
    return ordered


def parse_supported_models(raw: str | list[str] | None) -> list[str]:
    """Parse stored supported_models_json safely, defaulting to all 4 model types."""
    if raw is None or raw == "":
        return list(SUPPORTED_MODEL_TYPES)
    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return list(SUPPORTED_MODEL_TYPES)
    if not isinstance(data, list):
        return list(SUPPORTED_MODEL_TYPES)
    valid_set = {
        item.strip().lower()
        for item in data
        if isinstance(item, str) and item.strip().lower() in _SUPPORTED_MODEL_SET
    }
    ordered = [m for m in SUPPORTED_MODEL_TYPES if m in valid_set]
    return ordered or list(SUPPORTED_MODEL_TYPES)


def _remove_sqlite_sidecars(db_path: str) -> None:
    """Remove SQLite WAL/SHM/journal sidecar files for db_path if present."""
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = f"{db_path}{suffix}"
        try:
            if os.path.exists(sidecar):
                os.remove(sidecar)
        except OSError:
            pass


def _remove_file_and_sidecars(path: str) -> None:
    """Remove a SQLite file and its sidecar files if present."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    _remove_sqlite_sidecars(path)


def _check_db_integrity(db_path: str) -> tuple[bool, list[str]]:
    """Run PRAGMA integrity_check(10) and return (is_ok, messages)."""
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        rows = conn.execute("PRAGMA integrity_check(10);").fetchall()
        msgs = [str(r[0]) for r in rows] if rows else []
        is_ok = len(msgs) == 1 and msgs[0].lower() == "ok"
        return is_ok, msgs
    except sqlite3.OperationalError:
        # Lock / I/O errors are not structural DB corruption.
        raise
    except sqlite3.DatabaseError as exc:
        return False, [str(exc)]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _rebuild_sqlite_via_dump(src_path: str, dst_path: str) -> None:
    """Rebuild src_path into dst_path by replaying conn.iterdump() statements."""
    _remove_file_and_sidecars(dst_path)
    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    succeeded = False
    try:
        src_conn = sqlite3.connect(src_path, timeout=30.0)
        dst_conn = sqlite3.connect(dst_path, timeout=30.0, isolation_level=None)
        dst_conn.execute("PRAGMA foreign_keys=OFF;")
        for stmt in src_conn.iterdump():
            dst_conn.execute(stmt)
        succeeded = True
    finally:
        for conn in (dst_conn, src_conn):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        if not succeeded:
            _remove_file_and_sidecars(dst_path)

    ok, msgs = _check_db_integrity(dst_path)
    if not ok:
        _remove_file_and_sidecars(dst_path)
        raise sqlite3.DatabaseError(f"Rebuilt SQLite database still failed integrity_check: {msgs}")
    _remove_sqlite_sidecars(dst_path)


def _ensure_db_integrity(db_path: str) -> bool:
    """Check db_path integrity and rebuild logically from dump if corrupted."""
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False
    ok, msgs = _check_db_integrity(db_path)
    if ok:
        return False

    logger.warning(
        "SQLite integrity check failed for %s (%s); attempting logical rebuild",
        db_path,
        "; ".join(msgs[:5]),
    )
    rebuilt_path = f"{db_path}.rebuilding"
    _rebuild_sqlite_via_dump(db_path, rebuilt_path)

    backup_base = f"{db_path}.corrupt.{int(time.time())}.bak"
    try:
        shutil.copy2(db_path, backup_base)
        wal_path = f"{db_path}-wal"
        if os.path.isfile(wal_path) and os.path.getsize(wal_path) > 0:
            shutil.copy2(wal_path, f"{backup_base}-wal")
    except OSError as exc:
        logger.warning("Failed to save corrupt DB backup to %s: %s", backup_base, exc)

    try:
        _remove_sqlite_sidecars(db_path)
        os.replace(rebuilt_path, db_path)
    except Exception:
        _remove_file_and_sidecars(rebuilt_path)
        raise

    logger.warning(
        "Successfully rebuilt corrupted SQLite database %s (backup saved to %s)",
        db_path,
        backup_base,
    )
    return True


def _migrate_legacy_db_if_needed(cfg: Config) -> bool:
    """One-time copy (or logical rebuild) of data/muse2apiv2.db to custom db_path."""
    dst = os.path.abspath(cfg.db_path)
    legacy = os.path.abspath(os.path.join(cfg.data_dir, "muse2apiv2.db"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if dst == legacy or os.path.exists(dst) or not os.path.isfile(legacy):
        return False

    tmp_dst = f"{dst}.migrating"
    rebuilt_tmp = f"{dst}.migrating.rebuilt"
    _remove_file_and_sidecars(tmp_dst)
    _remove_file_and_sidecars(rebuilt_tmp)
    try:
        shutil.copy2(legacy, tmp_dst)
        legacy_wal = f"{legacy}-wal"
        if os.path.isfile(legacy_wal) and os.path.getsize(legacy_wal) > 0:
            shutil.copy2(legacy_wal, f"{tmp_dst}-wal")

        ok, msgs = _check_db_integrity(tmp_dst)
        if ok:
            if os.path.exists(f"{tmp_dst}-wal"):
                ckpt_conn: sqlite3.Connection | None = None
                try:
                    ckpt_conn = sqlite3.connect(tmp_dst, timeout=30.0)
                    ckpt_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchall()
                finally:
                    if ckpt_conn is not None:
                        try:
                            ckpt_conn.close()
                        except Exception:
                            pass
                _remove_sqlite_sidecars(tmp_dst)
            _remove_sqlite_sidecars(dst)
            os.replace(tmp_dst, dst)
            logger.info("Migrated legacy SQLite database from %s to %s", legacy, dst)
        else:
            logger.warning(
                "Legacy SQLite database %s failed integrity check (%s); rebuilding logically during migration to %s",
                legacy,
                "; ".join(msgs[:5]),
                dst,
            )
            _rebuild_sqlite_via_dump(tmp_dst, rebuilt_tmp)
            _remove_file_and_sidecars(tmp_dst)
            _remove_sqlite_sidecars(dst)
            os.replace(rebuilt_tmp, dst)
            logger.info("Migrated and logically rebuilt legacy SQLite database from %s to %s", legacy, dst)
    except Exception:
        _remove_file_and_sidecars(tmp_dst)
        _remove_file_and_sidecars(rebuilt_tmp)
        raise

    return True


class Database:
    """Thread-safe SQLite wrapper using a persistent connection and adaptive journal mode."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        os.makedirs(cfg.media_dir, exist_ok=True)
        _migrate_legacy_db_if_needed(cfg)
        _ensure_db_integrity(cfg.db_path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self.journal_mode: str = resolve_journal_mode(cfg.db_path)
        self.init_schema()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.cfg.db_path, timeout=30.0, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            jm_row = conn.execute(f"PRAGMA journal_mode={self.journal_mode};").fetchone()
            actual_jm = str(jm_row[0]).upper() if jm_row else ""
            if actual_jm and actual_jm != self.journal_mode:
                logger.warning(
                    "SQLite journal_mode requested=%s, actual=%s (path=%s)",
                    self.journal_mode,
                    actual_jm,
                    self.cfg.db_path,
                )
            conn.execute("PRAGMA synchronous=NORMAL;")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            raise

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open_connection()
        return self._conn

    def _reset_conn(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        """Close the persistent SQLite connection cleanly."""
        with self._lock:
            self._reset_conn()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _run(self, fn: Callable[[sqlite3.Connection], _T]) -> _T:
        with self._lock:
            for attempt in range(2):
                conn = self._get_conn()
                try:
                    return fn(conn)
                except sqlite3.OperationalError as exc:
                    self._reset_conn()
                    msg = str(exc).lower()
                    if attempt == 0 and any(tok in msg for tok in _TRANSIENT_SQLITE_ERRORS):
                        logger.warning(
                            "Transient SQLite error (%s); resetting connection and retrying once",
                            exc,
                        )
                        time.sleep(0.15)
                        continue
                    raise
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
            raise RuntimeError("Unreachable SQLite retry termination")

    def init_schema(self) -> None:
        def _op(conn: sqlite3.Connection) -> None:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proxies (
                    id TEXT PRIMARY KEY,
                    proxy_url TEXT NOT NULL UNIQUE,
                    scheme TEXT NOT NULL DEFAULT 'http',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    ip TEXT DEFAULT '',
                    country TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    org TEXT DEFAULT '',
                    latency_ms INTEGER DEFAULT 0,
                    last_checked_at REAL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    cookies_json TEXT NOT NULL,
                    proxy_id TEXT DEFAULT NULL REFERENCES proxies(id) ON DELETE SET NULL,
                    proxy_url TEXT DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    supported_models_json TEXT NOT NULL DEFAULT '["chat","image","video","speech"]',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    quota_json TEXT DEFAULT '{}',
                    last_used_at REAL DEFAULT 0,
                    last_keepalive_at REAL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS keepalive_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    vm_state TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    account_id TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    prompt_preview TEXT DEFAULT '',
                    input_request_json TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    media_filename TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    latency_ms INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    raw_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    rotated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            # Ensure proxy_id and supported_models_json exist on pre-existing DBs
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
            if "proxy_id" not in cols:
                conn.execute("ALTER TABLE accounts ADD COLUMN proxy_id TEXT DEFAULT NULL REFERENCES proxies(id) ON DELETE SET NULL")
            if "supported_models_json" not in cols:
                conn.execute(
                    "ALTER TABLE accounts ADD COLUMN supported_models_json TEXT NOT NULL DEFAULT '[\"chat\",\"image\",\"video\",\"speech\"]'"
                )
            task_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "input_request_json" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN input_request_json TEXT DEFAULT ''")
            now = time.time()
            row = conn.execute("SELECT raw_key FROM api_keys WHERE id = 1").fetchone()
            if not row:
                initial_key = self.cfg.initial_api_key or f"m2a_{secrets.token_urlsafe(24)}"
                conn.execute(
                    "INSERT INTO api_keys (id, raw_key, created_at, rotated_at) VALUES (1, ?, ?, ?)",
                    (initial_key, now, now),
                )

            defaults = {
                "system_prompt": {
                    "enabled": self.cfg.system_prompt_enabled,
                    "prompt": self.cfg.system_prompt or DEFAULT_SYSTEM_PROMPT,
                },
                "media_cleanup": {
                    "enabled": self.cfg.media_cleanup_enabled,
                    "retention_days": self.cfg.media_retention_days,
                    "max_gb": self.cfg.media_max_gb,
                    "interval_minutes": self.cfg.cleanup_interval_minutes,
                },
                "voice_languages": {
                    "enabled": False,
                    "languages": [],
                },
            }
            for k, val in defaults.items():
                exists = conn.execute("SELECT 1 FROM settings WHERE key = ?", (k,)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)",
                        (k, json.dumps(val), now),
                    )
            conn.commit()

        self._run(_op)

    # --- API Key ---
    def get_api_key(self) -> dict[str, Any]:
        def _op(conn: sqlite3.Connection) -> dict[str, Any]:
            row = conn.execute("SELECT raw_key, created_at, rotated_at FROM api_keys WHERE id = 1").fetchone()
            return dict(row) if row else {"raw_key": "", "created_at": 0, "rotated_at": 0}

        return self._run(_op)

    def rotate_api_key(self) -> dict[str, Any]:
        new_key = f"m2a_{secrets.token_urlsafe(24)}"
        now = time.time()

        def _op(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("UPDATE api_keys SET raw_key = ?, rotated_at = ? WHERE id = 1", (new_key, now))
            conn.commit()
            row = conn.execute("SELECT raw_key, created_at, rotated_at FROM api_keys WHERE id = 1").fetchone()
            return dict(row)

        return self._run(_op)

    # --- Settings ---
    def get_settings(self) -> dict[str, Any]:
        def _op(conn: sqlite3.Connection) -> dict[str, Any]:
            rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
            data = {r["key"]: json.loads(r["value_json"]) for r in rows}
            if "voice_languages" not in data:
                data["voice_languages"] = {"enabled": False, "languages": []}
            return data

        return self._run(_op)

    def update_setting(self, key: str, value: dict[str, Any]) -> None:
        now = time.time()

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                (key, json.dumps(value), now),
            )
            conn.commit()

        self._run(_op)

    # --- Proxies ---
    def list_proxies(self) -> list[dict[str, Any]]:
        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(a.id) as account_count
                FROM proxies p
                LEFT JOIN accounts a ON a.proxy_id = p.id
                GROUP BY p.id
                ORDER BY p.created_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

        return self._run(_op)

    def get_proxy(self, proxy_id: str) -> dict[str, Any] | None:
        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
            return dict(row) if row else None

        return self._run(_op)

    def create_proxy(self, proxy_id: str, proxy_url: str, scheme: str) -> dict[str, Any] | None:
        now = time.time()

        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            exists = conn.execute("SELECT 1 FROM proxies WHERE proxy_url = ?", (proxy_url,)).fetchone()
            if exists:
                return None
            conn.execute(
                "INSERT INTO proxies (id, proxy_url, scheme, created_at) VALUES (?, ?, ?, ?)",
                (proxy_id, proxy_url, scheme, now),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone())

        return self._run(_op)

    def update_proxy(self, proxy_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "ip", "country", "city", "org", "latency_ms", "last_checked_at", "last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_proxy(proxy_id)
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [proxy_id]

        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            conn.execute(f"UPDATE proxies SET {cols} WHERE id = ?", vals)
            conn.commit()
            row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
            return dict(row) if row else None

        return self._run(_op)

    def delete_proxy(self, proxy_id: str) -> tuple[bool, list[str]]:
        def _op(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
            affected = [
                r["id"] for r in conn.execute("SELECT id FROM accounts WHERE proxy_id = ?", (proxy_id,)).fetchall()
            ]
            conn.execute("UPDATE accounts SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
            cur = conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            conn.commit()
            return cur.rowcount > 0, affected

        return self._run(_op)

    # --- Accounts ---
    def list_accounts(self) -> list[dict[str, Any]]:
        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT a.*, p.proxy_url as joined_proxy_url, p.ip as proxy_ip, p.status as proxy_status
                FROM accounts a
                LEFT JOIN proxies p ON a.proxy_id = p.id
                ORDER BY a.created_at DESC
                """
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["effective_proxy_url"] = d.get("joined_proxy_url") or ""
                out.append(d)
            return out

        return self._run(_op)

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                """
                SELECT a.*, p.proxy_url as joined_proxy_url, p.ip as proxy_ip, p.status as proxy_status
                FROM accounts a
                LEFT JOIN proxies p ON a.proxy_id = p.id
                WHERE a.id = ?
                """,
                (account_id,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["effective_proxy_url"] = d.get("joined_proxy_url") or ""
            return d

        return self._run(_op)

    def create_account(self, account_id: str, label: str, cookies: dict[str, str],
                       proxy_id: str | None = None, enabled: bool = True, status: str = "unknown",
                       supported_models: list[str] | None = None) -> dict[str, Any]:
        now = time.time()
        models_list = list(SUPPORTED_MODEL_TYPES) if supported_models is None else normalize_supported_models(supported_models)

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO accounts (id, label, cookies_json, proxy_id, enabled, supported_models_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    label,
                    json.dumps(cookies),
                    proxy_id,
                    1 if enabled else 0,
                    json.dumps(models_list),
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()

        self._run(_op)
        return self.get_account(account_id)  # type: ignore[return-value]

    def update_account(self, account_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_account(account_id)
        allowed = {"label", "cookies_json", "proxy_id", "enabled", "supported_models_json", "status", "quota_json",
                   "last_used_at", "last_keepalive_at", "last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_account(account_id)
        updates["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [account_id]

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", vals)
            conn.commit()

        self._run(_op)
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        def _op(conn: sqlite3.Connection) -> bool:
            cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.commit()
            return cur.rowcount > 0

        return self._run(_op)

    def add_keepalive_log(self, account_id: str, status: str, vm_state: str = "", message: str = "") -> None:
        now = time.time()

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO keepalive_logs (account_id, status, vm_state, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (account_id, status, vm_state, message[:500], now),
            )
            # Retain only latest 20 logs per account
            conn.execute(
                """
                DELETE FROM keepalive_logs WHERE account_id = ? AND id NOT IN (
                    SELECT id FROM keepalive_logs WHERE account_id = ? ORDER BY id DESC LIMIT 20
                )
                """,
                (account_id, account_id),
            )
            conn.commit()

        self._run(_op)

    def list_keepalive_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                "SELECT k.*, a.label as account_label FROM keepalive_logs k "
                "LEFT JOIN accounts a ON k.account_id = a.id ORDER BY k.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

        return self._run(_op)

    # --- Tasks ---
    def create_task(self, task_id: str, task_type: str, status: str = "queued",
                    account_id: str = "", model: str = "", prompt_preview: str = "",
                    input_request: Any = None) -> dict[str, Any]:
        now = time.time()
        input_request_json = serialize_input_request(input_request) if input_request is not None else ""

        def _op(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute(
                """
                INSERT INTO tasks (id, type, status, account_id, model, prompt_preview, input_request_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, task_type, status, account_id, model, prompt_preview[:200], input_request_json, now, now),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

        return self._run(_op)

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "account_id", "session_id", "media_filename", "error_message", "latency_ms"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [task_id]

        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", vals)
            conn.commit()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

        return self._run(_op)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT t.*, a.label as account_label FROM tasks t "
                "LEFT JOIN accounts a ON t.account_id = a.id WHERE t.id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            raw = d.get("input_request_json") or ""
            if raw:
                try:
                    d["input_request"] = json.loads(raw)
                except json.JSONDecodeError:
                    d["input_request"] = {"raw": raw}
            else:
                d["input_request"] = None
            return d

        return self._run(_op)

    def fail_orphaned_tasks(self, reason: str = "Server restarted while task was in progress") -> int:
        """Mark any leftover queued/running tasks as failed on startup."""
        now = time.time()

        def _op(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'failed',
                    error_message = CASE WHEN error_message = '' THEN ? ELSE error_message END,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (reason, now),
            )
            conn.commit()
            return cur.rowcount

        return self._run(_op)

    @staticmethod
    def _task_filter_sql(task_type: str = "", status: str = "") -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []
        if task_type:
            clauses.append("t.type = ?")
            params.append(task_type)
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def count_tasks(self, task_type: str = "", status: str = "") -> int:
        where, params = self._task_filter_sql(task_type, status)

        def _op(conn: sqlite3.Connection) -> int:
            row = conn.execute(f"SELECT COUNT(*) FROM tasks t {where}", params).fetchone()
            return int(row[0]) if row else 0

        return self._run(_op)

    def list_tasks(self, task_type: str = "", status: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        where, params = self._task_filter_sql(task_type, status)
        params.extend([limit, offset])

        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                "SELECT t.id, t.type, t.status, t.account_id, t.model, t.prompt_preview, "
                "t.session_id, t.media_filename, t.error_message, t.latency_ms, "
                "t.created_at, t.updated_at, a.label as account_label FROM tasks t "
                f"LEFT JOIN accounts a ON t.account_id = a.id {where} "
                f"ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

        return self._run(_op)

    def delete_task(self, task_id: str) -> tuple[bool, list[str]]:
        def _op(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
            row = conn.execute("SELECT media_filename, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row or row["status"] == "running":
                return False, []
            fn = row["media_filename"] or ""
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            orphan_files: list[str] = []
            if fn:
                still = conn.execute("SELECT 1 FROM tasks WHERE media_filename = ? LIMIT 1", (fn,)).fetchone()
                if not still:
                    orphan_files.append(fn)
            conn.commit()
            return True, orphan_files

        return self._run(_op)

    def clear_completed_tasks(self) -> tuple[int, list[str]]:
        def _op(conn: sqlite3.Connection) -> tuple[int, list[str]]:
            rows = conn.execute(
                "SELECT DISTINCT media_filename FROM tasks WHERE status NOT IN ('running', 'queued') AND media_filename != ''"
            ).fetchall()
            candidates = [r["media_filename"] for r in rows]
            cur = conn.execute("DELETE FROM tasks WHERE status NOT IN ('running', 'queued')")
            orphan_files: list[str] = []
            for fn in candidates:
                still = conn.execute("SELECT 1 FROM tasks WHERE media_filename = ? LIMIT 1", (fn,)).fetchone()
                if not still:
                    orphan_files.append(fn)
            conn.commit()
            return cur.rowcount, orphan_files

        return self._run(_op)

    def task_stats_7days(self) -> list[dict[str, Any]]:
        cutoff = time.time() - 7 * 86400

        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT date(created_at, 'unixepoch', 'localtime') as day,
                       COUNT(*) as total,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM tasks
                WHERE created_at >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

        return self._run(_op)
