"""Unit tests for SQLite persistence resilience (journal mode detection, connection reuse, retries, concurrency)."""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config import Config
from db import Database, resolve_journal_mode
from routers.v1_openai import _safe_fail_task


class TestSQLiteResilience(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="muse_db_resilience_")
        self.cfg = Config(data_dir=self.tmpdir, initial_api_key="m2a_resilience_key")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resolve_journal_mode_from_mounts_and_env(self):
        mounts_path = os.path.join(self.tmpdir, "mounts")
        data_9p = os.path.join(self.tmpdir, "mnt_9p")
        data_cifs = os.path.join(self.tmpdir, "mnt_cifs")
        data_ext4 = os.path.join(self.tmpdir, "mnt_ext4")
        os.makedirs(data_9p, exist_ok=True)
        os.makedirs(data_cifs, exist_ok=True)
        os.makedirs(data_ext4, exist_ok=True)

        real_9p = os.path.realpath(data_9p)
        real_cifs = os.path.realpath(data_cifs)
        real_ext4 = os.path.realpath(data_ext4)

        with open(mounts_path, "w", encoding="utf-8") as f:
            f.write(
                f"/dev/sda1 / ext4 rw 0 0\n"
                f"C:\\134 {real_9p} 9p rw,noatime,aname=drvfs 0 0\n"
                f"//nas/share {real_cifs} cifs rw 0 0\n"
                f"/dev/nvme0n1 {real_ext4} ext4 rw 0 0\n"
            )

        self.assertEqual(
            resolve_journal_mode(os.path.join(data_9p, "muse2apiv2.db"), env_override="", mounts_file=mounts_path),
            "TRUNCATE",
        )
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_cifs, "muse2apiv2.db"), env_override="", mounts_file=mounts_path),
            "TRUNCATE",
        )
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_ext4, "muse2apiv2.db"), env_override="", mounts_file=mounts_path),
            "WAL",
        )

        # Env override takes precedence for valid modes; invalid modes fall back to FS detection
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_9p, "muse2apiv2.db"), env_override="delete", mounts_file=mounts_path),
            "DELETE",
        )
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_9p, "muse2apiv2.db"), env_override="wal", mounts_file=mounts_path),
            "WAL",
        )
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_ext4, "muse2apiv2.db"), env_override="truncate", mounts_file=mounts_path),
            "TRUNCATE",
        )
        self.assertEqual(
            resolve_journal_mode(os.path.join(data_9p, "muse2apiv2.db"), env_override="invalid_mode", mounts_file=mounts_path),
            "TRUNCATE",
        )

    def test_persistent_connection_reused_across_operations(self):
        db = Database(self.cfg)
        self.addCleanup(db.close)

        initial_conn = db._conn
        self.assertIsNotNone(initial_conn)
        conn_id = id(initial_conn)

        db.create_account(
            account_id="acc_1",
            label="acc-one",
            cookies={"hatch_sess": "abc"},
            enabled=True,
            status="healthy",
        )
        db.update_account("acc_1", status="healthy", last_error="")
        acc = db.get_account("acc_1")
        self.assertIsNotNone(acc)
        db.create_task("tsk_1", "audio", status="running", model="tts-1")
        db.update_task("tsk_1", status="completed", media_filename="aud_1.mp3")
        key_info = db.get_api_key()
        self.assertEqual(key_info["raw_key"], "m2a_resilience_key")

        # Exact same connection object was reused across all reads & writes
        self.assertIs(db._conn, initial_conn)
        self.assertEqual(id(db._conn), conn_id)

    def test_open_connection_closes_raw_handle_on_pragma_failure(self):
        db = Database(self.cfg)
        self.addCleanup(db.close)

        fake_conn = MagicMock()
        fake_conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")
        with patch("db.sqlite3.connect", return_value=fake_conn):
            with self.assertRaises(sqlite3.OperationalError):
                db._open_connection()
        fake_conn.close.assert_called_once()

    def test_transient_operational_error_resets_connection_and_retries_once(self):
        db = Database(self.cfg)
        self.addCleanup(db.close)

        db.create_account("acc_retry", "acc-retry", {"s": "1"}, enabled=True, status="healthy")

        for err_msg in ("unable to open database file", "disk I/O error"):
            db.close()
            failing_conn = MagicMock()
            failing_conn.execute.side_effect = sqlite3.OperationalError(err_msg)
            db._conn = failing_conn

            with patch("db.time.sleep") as mock_sleep:
                acc = db.get_account("acc_retry")

            self.assertIsNotNone(acc)
            self.assertEqual(acc["label"], "acc-retry")
            mock_sleep.assert_called_once_with(0.15)
            failing_conn.close.assert_called_once()
            self.assertIsNotNone(db._conn)
            self.assertIsNot(db._conn, failing_conn)

    def test_concurrent_multithread_reads_and_writes(self):
        db = Database(self.cfg)
        self.addCleanup(db.close)
        db.create_account("acc_conc", "conc", {"s": "1"}, enabled=True, status="healthy")

        def worker(worker_id: int) -> None:
            for step in range(25):
                tid = f"tsk_{worker_id}_{step}"
                db.create_task(tid, "audio", status="running", account_id="acc_conc", model="tts-1")
                db.update_account("acc_conc", last_used_at=float(step))
                db.update_task(tid, status="completed", media_filename=f"{tid}.mp3", latency_ms=step)
                fetched = db.get_task(tid)
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched["status"], "completed")
                self.assertTrue(bool(db.get_api_key()["raw_key"]))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker, wid) for wid in range(8)]
            for fut in futures:
                fut.result()

        self.assertEqual(db.count_tasks(task_type="audio", status="completed"), 200)

    def test_safe_fail_task_swallows_secondary_db_error(self):
        bad_db = MagicMock()
        bad_db.update_task.side_effect = sqlite3.OperationalError("unable to open database file")
        _safe_fail_task(bad_db, "tsk_err", "original error", 123)
        bad_db.update_task.assert_called_once_with(
            "tsk_err",
            status="failed",
            error_message="original error",
            latency_ms=123,
        )

    def test_custom_db_path_migrates_legacy_db_once(self):
        data_dir = os.path.join(self.tmpdir, "data_dir")
        db_dir = os.path.join(self.tmpdir, "db_dir")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(db_dir, exist_ok=True)

        legacy_cfg = Config(data_dir=data_dir, initial_api_key="m2a_legacy_key")
        legacy_db = Database(legacy_cfg)
        legacy_db.create_account(
            account_id="acc_mig",
            label="migrated-account",
            cookies={"hatch_sess": "mig"},
            enabled=True,
            status="healthy",
        )
        legacy_db.close()

        custom_db_path = os.path.join(db_dir, "muse2apiv2.db")
        cfg2 = Config(data_dir=data_dir, db_path_override=custom_db_path)
        db2 = Database(cfg2)
        try:
            self.assertTrue(os.path.isfile(custom_db_path))
            self.assertTrue(os.path.isfile(os.path.join(data_dir, "muse2apiv2.db")))
            self.assertEqual(db2.get_api_key()["raw_key"], "m2a_legacy_key")
            mig_acc = db2.get_account("acc_mig")
            self.assertIsNotNone(mig_acc)
            self.assertEqual(mig_acc["label"], "migrated-account")

            db2.create_account(
                account_id="acc_new",
                label="new-account",
                cookies={"hatch_sess": "new"},
                enabled=True,
                status="healthy",
            )
        finally:
            db2.close()

        # Reopening must NOT overwrite custom_db_path with legacy DB
        db3 = Database(cfg2)
        try:
            self.assertIsNotNone(db3.get_account("acc_new"))
            self.assertIsNotNone(db3.get_account("acc_mig"))
        finally:
            db3.close()

    def test_config_db_path_respects_data_dir_override_even_when_env_set(self):
        env_db = os.path.join(self.tmpdir, "prod", "muse2apiv2.db")
        custom_db = os.path.join(self.tmpdir, "custom.db")
        with patch.dict(os.environ, {"MUSE2API_DB_PATH": env_db}):
            # Default data_dir picks up MUSE2API_DB_PATH
            self.assertEqual(Config().db_path, env_db)

            # Explicit data_dir in constructor isolates db_path inside data_dir
            self.assertEqual(
                Config(data_dir=self.tmpdir).db_path,
                os.path.join(self.tmpdir, "muse2apiv2.db"),
            )

            # Post-init mutation of data_dir (used by several test suites) also isolates db_path
            cfg_mut = Config()
            cfg_mut.data_dir = self.tmpdir
            self.assertEqual(cfg_mut.db_path, os.path.join(self.tmpdir, "muse2apiv2.db"))

            # Explicit db_path_override takes priority even alongside custom data_dir
            self.assertEqual(
                Config(data_dir=self.tmpdir, db_path_override=custom_db).db_path,
                custom_db,
            )


if __name__ == "__main__":
    unittest.main()
