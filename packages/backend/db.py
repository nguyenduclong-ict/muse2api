"""SQLite (WAL mode) persistence layer for muse2apiv2."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from typing import Any

from config import Config, DEFAULT_SYSTEM_PROMPT


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
                # Ensure proxy_id exists on pre-existing DBs
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
                if "proxy_id" not in cols:
                    conn.execute("ALTER TABLE accounts ADD COLUMN proxy_id TEXT DEFAULT NULL REFERENCES proxies(id) ON DELETE SET NULL")
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
                return {r["key"]: json.loads(r["value_json"]) for r in rows}
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
                       proxy_id: str | None = None, enabled: bool = True, status: str = "unknown") -> dict[str, Any]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO accounts (id, label, cookies_json, proxy_id, enabled, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (account_id, label, json.dumps(cookies), proxy_id, 1 if enabled else 0, status, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_account(account_id)  # type: ignore[return-value]

    def update_account(self, account_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_account(account_id)
        allowed = {"label", "cookies_json", "proxy_id", "enabled", "status", "quota_json",
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
                    account_id: str = "", model: str = "", prompt_preview: str = "") -> dict[str, Any]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO tasks (id, type, status, account_id, model, prompt_preview, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, task_type, status, account_id, model, prompt_preview[:200], now, now),
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
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                return dict(row) if row else None
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
                    f"SELECT t.*, a.label as account_label FROM tasks t "
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
