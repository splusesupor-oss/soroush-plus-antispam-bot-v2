"""Shared SQLite infrastructure for bounded, indexed runtime state."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from modules.runtime_paths import (
    INSTANCE_NAME,
    USING_PRIVATE_DATA_DIR,
    runtime_backup_file,
    runtime_db_file,
)

DB_FILE = runtime_db_file("bot.sqlite3")
_REQUESTED = os.environ.get("RUNTIME_STATE_BACKEND", "").strip().lower()
SQLITE_ENABLED = (_REQUESTED == "sqlite" or
                  (_REQUESTED != "json" and USING_PRIVATE_DATA_DIR))
_LOCK = threading.RLock()
_CONN = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS banned_users (
    group_id TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    user_id TEXT,
    user_id_norm TEXT,
    username TEXT,
    username_norm TEXT,
    display_name TEXT,
    display_norm TEXT,
    reason TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, identity_key)
);
CREATE INDEX IF NOT EXISTS idx_banned_group_user
    ON banned_users(group_id, user_id);
CREATE INDEX IF NOT EXISTS idx_banned_group_username
    ON banned_users(group_id, username_norm);
CREATE INDEX IF NOT EXISTS idx_banned_user_global
    ON banned_users(user_id);
CREATE TABLE IF NOT EXISTS banned_aliases (
    group_id TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    alias_norm TEXT NOT NULL,
    alias_value TEXT,
    PRIMARY KEY(group_id, identity_key, alias_norm),
    FOREIGN KEY(group_id, identity_key)
      REFERENCES banned_users(group_id, identity_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_banned_alias
    ON banned_aliases(alias_norm);
CREATE TABLE IF NOT EXISTS user_activity (
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    gifs INTEGER NOT NULL DEFAULT 0 CHECK(gifs >= 0),
    videos INTEGER NOT NULL DEFAULT 0 CHECK(videos >= 0),
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY(group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_activity_last
    ON user_activity(last_seen);
CREATE TABLE IF NOT EXISTS admin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    actor_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    note TEXT NOT NULL DEFAULT '',
    event_time TEXT NOT NULL,
    event_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_events_group_time
    ON admin_events(group_id,event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_admin_events_time
    ON admin_events(event_ts);
CREATE TABLE IF NOT EXISTS runtime_kv (
    namespace TEXT NOT NULL,
    item_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(namespace, item_key)
);
CREATE TABLE IF NOT EXISTS storage_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connection():
    global _CONN
    if _CONN is not None:
        return _CONN
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_FILE), timeout=10.0, check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.executescript(_SCHEMA)
    # Additive schema upgrades keep databases created by earlier staged
    # versions readable; no table is dropped or rebuilt.
    banned_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(banned_users)")
    }
    if "user_id_norm" not in banned_columns:
        conn.execute("ALTER TABLE banned_users ADD COLUMN user_id_norm TEXT")
    alias_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(banned_aliases)")
    }
    if "alias_value" not in alias_columns:
        conn.execute("ALTER TABLE banned_aliases ADD COLUMN alias_value TEXT")
    conn.execute(
        "UPDATE banned_users SET user_id_norm="
        "LOWER(REPLACE(TRIM(user_id),'@','')) "
        "WHERE user_id IS NOT NULL AND user_id_norm IS NULL"
    )
    conn.execute(
        "UPDATE banned_aliases SET alias_value=alias_norm "
        "WHERE alias_value IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_banned_group_user_norm "
        "ON banned_users(group_id,user_id_norm)"
    )
    _CONN = conn
    return conn


@contextmanager
def transaction(immediate=True):
    with _LOCK:
        conn = connection()
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def execute(sql, params=()):
    with _LOCK:
        return connection().execute(sql, params)


def query_all(sql, params=()):
    with _LOCK:
        return connection().execute(sql, params).fetchall()


def query_one(sql, params=()):
    with _LOCK:
        return connection().execute(sql, params).fetchone()


def meta_get(key, default=None):
    row = query_one("SELECT value FROM storage_meta WHERE key=?", (str(key),))
    return row[0] if row else default


def meta_set(key, value):
    execute(
        "INSERT INTO storage_meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(key), str(value)),
    )


def kv_get(namespace, item_key, default=None):
    row = query_one(
        "SELECT payload FROM runtime_kv WHERE namespace=? AND item_key=?",
        (str(namespace), str(item_key)),
    )
    if not row:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return default


def kv_set(namespace, item_key, value):
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    execute(
        "INSERT INTO runtime_kv(namespace,item_key,payload,updated_at) "
        "VALUES(?,?,?,CURRENT_TIMESTAMP) "
        "ON CONFLICT(namespace,item_key) DO UPDATE SET "
        "payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
        (str(namespace), str(item_key), payload),
    )


def kv_delete(namespace, item_key):
    execute("DELETE FROM runtime_kv WHERE namespace=? AND item_key=?",
            (str(namespace), str(item_key)))


def integrity_check():
    with _LOCK:
        return str(connection().execute("PRAGMA integrity_check").fetchone()[0])


def maintenance(*, activity_retention_days=None):
    """Prune bounded state and refresh SQLite's planner/checkpoint state."""
    if activity_retention_days is None:
        activity_retention_days = int(
            os.environ.get("BOT_ACTIVITY_RETENTION_DAYS", "180")
        )
    cutoff = time.time() - max(1, int(activity_retention_days)) * 86400
    with _LOCK:
        conn = connection()
        cursor = conn.execute(
            "DELETE FROM user_activity WHERE last_seen < ?", (cutoff,)
        )
        admin_cursor = conn.execute(
            "DELETE FROM admin_events WHERE event_ts < ?", (time.time() - 86400,)
        )
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.execute("PRAGMA optimize")
        return {
            "activity_deleted": max(0, cursor.rowcount),
            "admin_events_deleted": max(0, admin_cursor.rowcount),
        }


def backup_to(path=None):
    """Create, verify, and atomically publish a consistent online backup."""
    target = Path(path) if path else runtime_backup_file(
        # شناسهٔ instance داخل نام فایل می‌آید تا مبدأ بکاپ‌های جابه‌جاشده روشن باشد.
        f"bot-{INSTANCE_NAME}-"
        + datetime.now().strftime("%Y%m%d-%H%M%S") + ".sqlite3"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("." + target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with _LOCK:
            destination = sqlite3.connect(str(temporary))
            try:
                connection().backup(destination)
                result = destination.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(
                        f"backup integrity_check failed: {result}"
                    )
            finally:
                destination.close()
            os.replace(temporary, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
        return target
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def stats():
    with _LOCK:
        conn = connection()
        tables = (
            "banned_users", "banned_aliases", "user_activity",
            "admin_events", "runtime_kv",
        )
        result = {
            "db_file": str(DB_FILE),
            "db_bytes": DB_FILE.stat().st_size if DB_FILE.exists() else 0,
            "wal_bytes": Path(str(DB_FILE) + "-wal").stat().st_size
            if Path(str(DB_FILE) + "-wal").exists() else 0,
        }
        for table in tables:
            result[table] = int(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        return result


def close():
    global _CONN
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            finally:
                _CONN = None
