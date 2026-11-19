"""SQLite (WAL mode) persistence layer for muse2apiv2."""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Any

from config import Config, DEFAULT_SYSTEM_PROMPT

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


class Database:
    """Thread-safe SQLite wrapper using WAL mode."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        os.makedirs(cfg.media_dir, exist_ok=True)
        self._lock = threading.Lock()
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.cfg.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    # --- API Key ---
    def get_api_key(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT raw_key, created_at, rotated_at FROM api_keys WHERE id = 1").fetchone()
                return dict(row) if row else {"raw_key": "", "created_at": 0, "rotated_at": 0}
            finally:
                conn.close()

    def rotate_api_key(self) -> dict[str, Any]:
        new_key = f"m2a_{secrets.token_urlsafe(24)}"
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE api_keys SET raw_key = ?, rotated_at = ? WHERE id = 1", (new_key, now))
                conn.commit()
                row = conn.execute("SELECT raw_key, created_at, rotated_at FROM api_keys WHERE id = 1").fetchone()
                return dict(row)
            finally:
                conn.close()

    # --- Settings ---
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
                data = {r["key"]: json.loads(r["value_json"]) for r in rows}
                if "voice_languages" not in data:
                    data["voice_languages"] = {"enabled": False, "languages": []}
                return data
            finally:
                conn.close()

    def update_setting(self, key: str, value: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                    (key, json.dumps(value), now),
                )
                conn.commit()
            finally:
                conn.close()

    # --- Proxies ---
    def list_proxies(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def get_proxy(self, proxy_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def create_proxy(self, proxy_id: str, proxy_url: str, scheme: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                exists = conn.execute("SELECT 1 FROM proxies WHERE proxy_url = ?", (proxy_url,)).fetchone()
                if exists:
                    return None
                conn.execute(
                    "INSERT INTO proxies (id, proxy_url, scheme, created_at) VALUES (?, ?, ?, ?)",
                    (proxy_id, proxy_url, scheme, now),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone())
            finally:
                conn.close()

    def update_proxy(self, proxy_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "ip", "country", "city", "org", "latency_ms", "last_checked_at", "last_error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_proxy(proxy_id)
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [proxy_id]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE proxies SET {cols} WHERE id = ?", vals)
                conn.commit()
                row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def delete_proxy(self, proxy_id: str) -> tuple[bool, list[str]]:
        with self._lock:
            conn = self._connect()
            try:
                affected = [
                    r["id"] for r in conn.execute("SELECT id FROM accounts WHERE proxy_id = ?", (proxy_id,)).fetchall()
                ]
                conn.execute("UPDATE accounts SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
                cur = conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
                conn.commit()
                return cur.rowcount > 0, affected
            finally:
                conn.close()

    # --- Accounts ---
    def list_accounts(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def create_account(self, account_id: str, label: str, cookies: dict[str, str],
                       proxy_id: str | None = None, enabled: bool = True, status: str = "unknown",
                       supported_models: list[str] | None = None) -> dict[str, Any]:
        now = time.time()
        models_list = list(SUPPORTED_MODEL_TYPES) if supported_models is None else normalize_supported_models(supported_models)
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()
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
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", vals)
                conn.commit()
            finally:
                conn.close()
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def add_keepalive_log(self, account_id: str, status: str, vm_state: str = "", message: str = "") -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def list_keepalive_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT k.*, a.label as account_label FROM keepalive_logs k "
                    "LEFT JOIN accounts a ON k.account_id = a.id ORDER BY k.id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # --- Tasks ---
    def create_task(self, task_id: str, task_type: str, status: str = "queued",
                    account_id: str = "", model: str = "", prompt_preview: str = "",
                    input_request: Any = None) -> dict[str, Any]:
        now = time.time()
        input_request_json = serialize_input_request(input_request) if input_request is not None else ""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO tasks (id, type, status, account_id, model, prompt_preview, input_request_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, task_type, status, account_id, model, prompt_preview[:200], input_request_json, now, now),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
            finally:
                conn.close()

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "account_id", "session_id", "media_filename", "error_message", "latency_ms"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [task_id]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", vals)
                conn.commit()
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def fail_orphaned_tasks(self, reason: str = "Server restarted while task was in progress") -> int:
        """Mark any leftover queued/running tasks as failed on startup."""
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

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
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM tasks t {where}", params).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def list_tasks(self, task_type: str = "", status: str = "", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        where, params = self._task_filter_sql(task_type, status)
        params.extend([limit, offset])
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT t.id, t.type, t.status, t.account_id, t.model, t.prompt_preview, "
                    "t.session_id, t.media_filename, t.error_message, t.latency_ms, "
                    "t.created_at, t.updated_at, a.label as account_label FROM tasks t "
                    f"LEFT JOIN accounts a ON t.account_id = a.id {where} "
                    f"ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def delete_task(self, task_id: str) -> tuple[bool, list[str]]:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def clear_completed_tasks(self) -> tuple[int, list[str]]:
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()

    def task_stats_7days(self) -> list[dict[str, Any]]:
        cutoff = time.time() - 7 * 86400
        with self._lock:
            conn = self._connect()
            try:
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
            finally:
                conn.close()
