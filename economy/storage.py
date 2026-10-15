"""Transactional economy storage with a scalable SQLite production backend.

Production/Termux uses SQLite rows instead of rewriting one growing JSON file.
The public dict-oriented API is intentionally unchanged, so games, profiles,
wallets and menus keep their existing behaviour.

Safety properties
-----------------
* SQLite WAL + transactional row updates.
* Automatic, verified import from the legacy ``economy.json``.
* The legacy JSON is never deleted automatically (instant rollback remains).
* A failed Python transaction restores only rows touched by that transaction.
* Deferred hot counters are batched and flushed as changed rows, never as one
  multi-megabyte document.
* Tests and emergency rollback can still select the legacy JSON backend.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.atomic_write import write_json as atomic_write_json
from modules.runtime_paths import (
    INSTANCE_NAME,
    USING_PRIVATE_DATA_DIR,
    runtime_backup_file,
    runtime_config_file,
    runtime_db_file,
)

DATA_FILE = runtime_config_file("economy.json")
LEGACY_COINS_FILE = runtime_config_file("coins.json")
DB_FILE = runtime_db_file("bot.sqlite3")

_requested_backend = os.environ.get("ECONOMY_BACKEND", "").strip().lower()
_BACKEND = _requested_backend or ("sqlite" if USING_PRIVATE_DATA_DIR else "json")
if _BACKEND not in {"sqlite", "json"}:
    _BACKEND = "sqlite" if USING_PRIVATE_DATA_DIR else "json"

_LOCK = threading.RLock()
_state = threading.local()
_cache = None
_cache_mtime = None
_dirty = False
_dirty_rows = set()
_conn = None
_tracking_suspended = False

EMPTY = {"users": {}, "meta": {"version": 2, "sequence": 0}}
_SHARDED_SECTIONS = {
    "users", "daily_messages", "usernames", "game_progress", "game_recent",
}
_MISSING = object()


def backend_name():
    return _BACKEND


def _mtime():
    try:
        return DATA_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return copy.deepcopy(value)


def _row_for_path(path):
    if not path:
        return ("__all__", "*")
    section = str(path[0])
    if section in _SHARDED_SECTIONS:
        return (section, str(path[1])) if len(path) >= 2 else (section, "*")
    return (section, "_")


def _current_row_value(row):
    section, key = row
    if section == "__all__":
        return _cache
    if not isinstance(_cache, dict):
        return _MISSING
    if key in {"_", "*"}:
        return _cache.get(section, _MISSING)
    section_data = _cache.get(section)
    if not isinstance(section_data, dict):
        return _MISSING
    return section_data.get(key, _MISSING)


def _mark(path):
    global _dirty
    if _tracking_suspended:
        return
    row = _row_for_path(path)
    depth = getattr(_state, "depth", 0)
    if depth > 0:
        backups = getattr(_state, "backups", None)
        if backups is not None and row not in backups:
            old = _current_row_value(row)
            backups[row] = _MISSING if old is _MISSING else _plain(old)
        getattr(_state, "touched", set()).add(row)
    _dirty_rows.add(row)
    _dirty = True


def _wrap(value, path=()):
    if isinstance(value, _TrackedDict) or isinstance(value, _TrackedList):
        return value
    if isinstance(value, dict):
        return _TrackedDict(value, path)
    if isinstance(value, list):
        return _TrackedList(value, path)
    return value


class _TrackedDict(dict):
    def __init__(self, source=None, path=()):
        dict.__init__(self)
        self._path = tuple(path)
        for key, value in dict(source or {}).items():
            dict.__setitem__(self, str(key), _wrap(value, self._path + (str(key),)))

    def __setitem__(self, key, value):
        key = str(key)
        _mark(self._path + (key,))
        # Keep the caller's object identity until commit. Existing economy
        # code often inserts a new dict and continues mutating that same local
        # reference. The changed row is recursively wrapped after persistence.
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        key = str(key)
        _mark(self._path + (key,))
        dict.__delitem__(self, key)

    def setdefault(self, key, default=None):
        key = str(key)
        if key not in self:
            self[key] = default
        return dict.__getitem__(self, key)

    def pop(self, key, default=_MISSING):
        key = str(key)
        if key in self:
            _mark(self._path + (key,))
            return dict.pop(self, key)
        if default is _MISSING:
            raise KeyError(key)
        return default

    def popitem(self):
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(reversed(self))
        return key, self.pop(key)

    def clear(self):
        if self:
            _mark(self._path)
            dict.clear(self)

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            self[key] = value


class _TrackedList(list):
    def __init__(self, source=None, path=()):
        self._path = tuple(path)
        list.__init__(self, [_wrap(v, self._path + (str(i),))
                             for i, v in enumerate(source or [])])

    def _changed(self):
        _mark(self._path)

    def append(self, value):
        self._changed(); list.append(self, value)

    def extend(self, values):
        values = list(values)
        if values:
            self._changed()
            list.extend(self, values)

    def insert(self, index, value):
        self._changed(); list.insert(self, index, value)

    def __setitem__(self, index, value):
        self._changed()
        list.__setitem__(self, index, value)

    def __delitem__(self, index):
        self._changed(); list.__delitem__(self, index)

    def pop(self, index=-1):
        self._changed(); return list.pop(self, index)

    def remove(self, value):
        self._changed(); list.remove(self, value)

    def clear(self):
        if self:
            self._changed(); list.clear(self)

    def sort(self, *args, **kwargs):
        self._changed(); list.sort(self, *args, **kwargs)

    def reverse(self):
        self._changed(); list.reverse(self)

    def __iadd__(self, values):
        self.extend(values); return self


def _json_read():
    global _cache, _cache_mtime
    mtime = _mtime()
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    if mtime is None:
        _cache = copy.deepcopy(EMPTY)
    else:
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("root is not a dict")
            raw.setdefault("users", {})
            raw.setdefault("meta", {"version": 1, "sequence": 0})
            raw["meta"].setdefault("sequence", 0)
            _cache = raw
        except (OSError, ValueError):
            _cache = copy.deepcopy(EMPTY)
    _cache_mtime = mtime
    return _cache


def _json_write(data):
    global _cache, _cache_mtime, _dirty
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(dir=str(DATA_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp_path, DATA_FILE)
    except BaseException:
        try: os.unlink(temp_path)
        except OSError: pass
        raise
    _cache = data
    _cache_mtime = _mtime()
    _dirty = False


def _connection():
    global _conn
    if _conn is not None:
        return _conn
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_FILE), timeout=10.0, check_same_thread=False,
        isolation_level=None,
    )
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS economy_state (
            section TEXT NOT NULL,
            item_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (section, item_key)
        );
        CREATE TABLE IF NOT EXISTS economy_daily_archive (
            day TEXT NOT NULL,
            group_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (day, group_id)
        );
        CREATE TABLE IF NOT EXISTS storage_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_economy_archive_day
            ON economy_daily_archive(day);
    """)
    _conn = conn
    return conn


def _split_plain(data):
    rows = []
    for section, value in dict(data or {}).items():
        section = str(section)
        if section in _SHARDED_SECTIONS and isinstance(value, dict):
            rows.extend((section, str(key), item) for key, item in value.items())
        else:
            rows.append((section, "_", value))
    return rows


def _legacy_chat_key(chat_id):
    """Local copy of account group normalization (avoids an import cycle)."""
    try:
        value = int(chat_id)
    except (TypeError, ValueError):
        return str(chat_id)
    if value <= -1_000_000_000_000:
        value = abs(value) - 1_000_000_000_000
    elif value <= -1_000_000_000 and str(value).startswith("-100"):
        value = abs(value) - 10_000_000_000
    elif value < 0:
        value = abs(value)
    return str(value)


def _convert_legacy_coins(raw):
    """Convert nested ``coins.json`` wallets to current group:user rows."""
    now = datetime.now(timezone.utc).isoformat()
    users = {}
    sequence = 0
    for group_id, members in (raw.get("users") or {}).items():
        if not isinstance(members, dict):
            continue
        group = _legacy_chat_key(group_id)
        for user_id, legacy in members.items():
            if not isinstance(legacy, dict):
                continue
            key = f"{group}:{user_id}"
            try:
                amount = max(0, int(legacy.get("coins", 0) or 0))
                wins = max(0, int(legacy.get("wins", 0) or 0))
            except (TypeError, ValueError):
                continue
            user = users.get(key)
            if user is None:
                sequence += 1
                reference = f"legacy_coins_import:v1:{key}"
                user = {
                    "bronze": 0, "silver": 0, "gold": 0,
                    "total_coin_value": 0,
                    "transactions": [{
                        "id": sequence, "kind": "receive", "at": now,
                        "changes": {"bronze": amount} if amount else {},
                        "reference": reference,
                        "note": "انتقال خودکار سکه‌های سیستم قدیمی",
                        "balance_after": {
                            "bronze": amount, "silver": 0, "gold": 0,
                            "total_coin_value": amount,
                        },
                        "total_value": amount,
                    }],
                    "references": [reference],
                    "wins": 0, "name": None, "created_at": now,
                    "value_reached_seq": sequence,
                    "value_reached_at": now,
                }
                users[key] = user
            else:
                # Canonical group aliases can collapse to one wallet. Merge
                # rather than overwrite so no legacy value disappears.
                user["transactions"][0]["changes"]["bronze"] = (
                    int(user["transactions"][0]["changes"].get("bronze", 0))
                    + amount
                )
            user["bronze"] += amount
            user["wins"] += wins
            user["total_coin_value"] = user["bronze"]
            tx = user["transactions"][0]
            tx["balance_after"]["bronze"] = user["bronze"]
            tx["balance_after"]["total_coin_value"] = user["bronze"]
            tx["total_value"] = user["bronze"]
            if legacy.get("name"):
                user["name"] = str(legacy["name"])

    daily = {}
    for day, groups in (raw.get("daily_messages") or {}).items():
        if not isinstance(groups, dict):
            continue
        day_bucket = daily.setdefault(str(day), {})
        for group_id, members in groups.items():
            if not isinstance(members, dict):
                continue
            group_bucket = day_bucket.setdefault(_legacy_chat_key(group_id), {})
            for user_id, legacy in members.items():
                if not isinstance(legacy, dict):
                    continue
                try:
                    count = max(0, int(legacy.get("messages", 0) or 0))
                except (TypeError, ValueError):
                    continue
                entry = group_bucket.setdefault(str(user_id), {"messages": 0})
                entry["messages"] += count
                if legacy.get("name"):
                    entry["name"] = str(legacy["name"])

    return {
        "users": users,
        "daily_messages": daily,
        "paid_days": sorted({str(day) for day in (raw.get("paid_days") or [])}),
        "meta": {
            "version": 2,
            "sequence": sequence,
            "legacy_coins_imported_at": now,
        },
    }


def _verified_backup_copy(source, backup):
    backup.parent.mkdir(parents=True, exist_ok=True)
    def digest(path):
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        return value.hexdigest()
    if not backup.exists():
        handle, temp_name = tempfile.mkstemp(
            dir=str(backup.parent), prefix=f".{backup.name}.", suffix=".tmp"
        )
        temporary = Path(temp_name)
        try:
            with source.open("rb") as src, os.fdopen(handle, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush(); os.fsync(dst.fileno())
            if digest(source) != digest(temporary):
                raise OSError(
                    f"legacy economy backup verification failed: {source}"
                )
            os.replace(temporary, backup)
        except BaseException:
            try: os.close(handle)
            except OSError: pass
            temporary.unlink(missing_ok=True)
            raise
    if digest(source) != digest(backup):
        raise OSError(f"legacy economy backup verification failed: {source}")


def _sqlite_import_legacy_if_needed(conn):
    count = conn.execute("SELECT COUNT(*) FROM economy_state").fetchone()[0]
    if count:
        return False

    source_file = None
    source_kind = None
    source = None
    for candidate, kind in ((DATA_FILE, "economy"),
                            (LEGACY_COINS_FILE, "coins")):
        if not candidate.exists():
            continue
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict):
            source_file, source_kind, source = candidate, kind, loaded
            break
    if source is None:
        return False
    if source_kind == "coins":
        source = _convert_legacy_coins(source)
    else:
        source.setdefault("users", {})
        source.setdefault("meta", {"version": 2, "sequence": 0})

    backup = runtime_backup_file(
        f"{source_kind}-before-sqlite-" +
        datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
    )
    _verified_backup_copy(source_file, backup)
    rows = _split_plain(source)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO economy_state(section,item_key,payload) VALUES(?,?,?)",
            [(s, k, json.dumps(v, ensure_ascii=False, separators=(",", ":")))
             for s, k, v in rows],
        )
        conn.execute(
            "INSERT OR REPLACE INTO storage_meta(key,value) VALUES('legacy_backup',?)",
            (str(backup),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO storage_meta(key,value) "
            "VALUES('legacy_economy_source',?)", (source_kind,),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise sqlite3.DatabaseError("SQLite integrity_check failed after import")
    return True


def _sqlite_load_plain():
    conn = _connection()
    _sqlite_import_legacy_if_needed(conn)
    data = {}
    for section, key, payload in conn.execute(
        "SELECT section,item_key,payload FROM economy_state"
    ):
        try:
            value = json.loads(payload)
        except ValueError:
            continue
        if key == "_":
            data[section] = value
        else:
            data.setdefault(section, {})[key] = value
    data.setdefault("users", {})
    data.setdefault("meta", {"version": 2, "sequence": 0})
    data["meta"].setdefault("sequence", 0)
    return data


def _sqlite_read():
    global _cache
    if _cache is None:
        _cache = _wrap(_sqlite_load_plain(), ())
    return _cache


def _delete_section_rows(conn, section):
    conn.execute("DELETE FROM economy_state WHERE section=?", (section,))


def _persist_rows(rows):
    if not rows:
        return False
    conn = _connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for section, key in sorted(rows):
            if section == "__all__":
                conn.execute("DELETE FROM economy_state")
                for sec, item_key, value in _split_plain(_plain(_cache)):
                    conn.execute(
                        "INSERT INTO economy_state(section,item_key,payload,updated_at) "
                        "VALUES(?,?,?,CURRENT_TIMESTAMP)",
                        (sec, item_key, json.dumps(value, ensure_ascii=False,
                                                   separators=(",", ":"))),
                    )
                continue
            if key == "*":
                _delete_section_rows(conn, section)
                value = _current_row_value((section, key))
                if value is _MISSING:
                    continue
                plain_value = _plain(value)
                if section in _SHARDED_SECTIONS and isinstance(plain_value, dict):
                    for item_key, item in plain_value.items():
                        conn.execute(
                            "INSERT INTO economy_state(section,item_key,payload,updated_at) "
                            "VALUES(?,?,?,CURRENT_TIMESTAMP)",
                            (section, str(item_key), json.dumps(
                                item, ensure_ascii=False, separators=(",", ":"))),
                        )
                else:
                    conn.execute(
                        "INSERT INTO economy_state(section,item_key,payload,updated_at) "
                        "VALUES(?,?,?,CURRENT_TIMESTAMP)",
                        (section, "_", json.dumps(plain_value,
                                                   ensure_ascii=False,
                                                   separators=(",", ":"))),
                    )
                continue
            value = _current_row_value((section, key))
            if value is _MISSING:
                conn.execute(
                    "DELETE FROM economy_state WHERE section=? AND item_key=?",
                    (section, key),
                )
            else:
                conn.execute(
                    "INSERT INTO economy_state(section,item_key,payload,updated_at) "
                    "VALUES(?,?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(section,item_key) DO UPDATE SET "
                    "payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
                    (section, key, json.dumps(_plain(value), ensure_ascii=False,
                                               separators=(",", ":"))),
                )
        conn.execute("COMMIT")
        return True
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _read():
    return _sqlite_read() if _BACKEND == "sqlite" else _json_read()


def _restore_row(row, previous):
    global _tracking_suspended, _cache
    _tracking_suspended = True
    try:
        section, key = row
        if section == "__all__":
            _cache = _wrap(copy.deepcopy(EMPTY) if previous is _MISSING else previous, ())
            return
        if key in {"_", "*"}:
            if previous is _MISSING:
                dict.pop(_cache, section, None)
            else:
                dict.__setitem__(_cache, section, _wrap(previous, (section,)))
            return
        section_data = dict.get(_cache, section)
        if not isinstance(section_data, dict):
            if previous is _MISSING:
                return
            section_data = _TrackedDict({}, (section,))
            dict.__setitem__(_cache, section, section_data)
        if previous is _MISSING:
            dict.pop(section_data, key, None)
        else:
            dict.__setitem__(section_data, key,
                             _wrap(previous, (section, key)))
    finally:
        _tracking_suspended = False


def _rewrap_rows(rows):
    """Install recursive trackers after callers finish mutating new objects."""
    for row in rows:
        current = _current_row_value(row)
        if current is not _MISSING:
            _restore_row(row, _plain(current))


class _Transaction:
    def __init__(self, defer=False):
        self._defer = bool(defer)

    def __enter__(self):
        _LOCK.acquire()
        depth = getattr(_state, "depth", 0)
        if depth == 0:
            _state.deferred = self._defer
            _state.preexisting_dirty = set(_dirty_rows)
            _state.backups = {}
            _state.touched = set()
            if _BACKEND == "json":
                _state.data = _json_read() if self._defer else copy.deepcopy(_json_read())
            else:
                _state.data = _sqlite_read()
        _state.depth = depth + 1
        return _state.data

    def __exit__(self, exc_type, exc, tb):
        global _dirty, _cache
        try:
            _state.depth -= 1
            if _state.depth != 0:
                return False
            if _BACKEND == "json":
                if exc_type is None:
                    if _state.deferred:
                        _cache = _state.data
                        _dirty = True
                    else:
                        _json_write(_state.data)
                return False

            if exc_type is not None:
                for row, previous in reversed(list(_state.backups.items())):
                    _restore_row(row, previous)
                _dirty_rows.clear()
                _dirty_rows.update(_state.preexisting_dirty)
                _dirty = bool(_dirty_rows)
                return False

            if not _state.deferred:
                committed_rows = set(_dirty_rows)
                try:
                    _persist_rows(committed_rows)
                except BaseException:
                    for row, previous in reversed(list(_state.backups.items())):
                        _restore_row(row, previous)
                    _dirty_rows.clear()
                    _dirty_rows.update(_state.preexisting_dirty)
                    _dirty = bool(_dirty_rows)
                    raise
                _rewrap_rows(committed_rows)
                _dirty_rows.clear()
                _dirty = False
            return False
        finally:
            if getattr(_state, "depth", 0) == 0:
                _state.data = None
                _state.deferred = False
                _state.backups = {}
                _state.touched = set()
            _LOCK.release()


def transaction(defer=False):
    return _Transaction(defer)


def flush():
    global _dirty
    with _LOCK:
        if not _dirty:
            return False
        if getattr(_state, "depth", 0) > 0:
            return False
        if _BACKEND == "sqlite":
            committed_rows = set(_dirty_rows)
            changed = _persist_rows(committed_rows)
            _rewrap_rows(committed_rows)
            _dirty_rows.clear(); _dirty = False
            return changed
        _json_write(_cache if _cache is not None else copy.deepcopy(EMPTY))
        _dirty = False
        return True


def is_dirty():
    return bool(_dirty)


def snapshot():
    with _LOCK:
        data = _state.data if getattr(_state, "depth", 0) > 0 else _read()
        return _plain(data)


def user_fields(user_key, fields):
    with _LOCK:
        # Cold SQLite reads stay row-local and do not hydrate every wallet.
        if (_BACKEND == "sqlite" and _cache is None and
                getattr(_state, "depth", 0) == 0):
            conn = _connection()
            _sqlite_import_legacy_if_needed(conn)
            row = conn.execute(
                "SELECT payload FROM economy_state "
                "WHERE section='users' AND item_key=?", (str(user_key),)
            ).fetchone()
            if not row:
                return None
            try:
                user = json.loads(row[0])
            except (TypeError, ValueError):
                return None
        else:
            data = _state.data if getattr(_state, "depth", 0) > 0 else _read()
            user = data.get("users", {}).get(str(user_key))
        if not isinstance(user, dict):
            return None
        return {field: copy.deepcopy(user.get(field)) for field in fields}


def user_records(fields):
    with _LOCK:
        data = _state.data if getattr(_state, "depth", 0) > 0 else _read()
        return [(key, {field: copy.deepcopy(user.get(field)) for field in fields})
                for key, user in data.get("users", {}).items()
                if isinstance(user, dict)]


def read_path(*keys, default=None):
    with _LOCK:
        normalized = tuple(str(key) for key in keys)
        if (_BACKEND == "sqlite" and _cache is None and
                getattr(_state, "depth", 0) == 0 and len(normalized) >= 2 and
                normalized[0] in _SHARDED_SECTIONS):
            conn = _connection()
            _sqlite_import_legacy_if_needed(conn)
            row = conn.execute(
                "SELECT payload FROM economy_state WHERE section=? AND item_key=?",
                (normalized[0], normalized[1]),
            ).fetchone()
            if not row:
                return copy.deepcopy(default)
            try:
                node = json.loads(row[0])
            except (TypeError, ValueError):
                return copy.deepcopy(default)
            remaining = normalized[2:]
        else:
            node = _state.data if getattr(_state, "depth", 0) > 0 else _read()
            remaining = normalized
        for key in remaining:
            if not isinstance(node, dict):
                return copy.deepcopy(default)
            node = node.get(key, _MISSING)
            if node is _MISSING:
                return copy.deepcopy(default)
        return _plain(node)


def next_sequence(data):
    meta = data.setdefault("meta", {"version": 2, "sequence": 0})
    meta["sequence"] = int(meta.get("sequence", 0)) + 1
    return meta["sequence"]


def archive_daily_days(stale_days):
    """Archive daily rankings inside SQLite instead of a growing JSON file."""
    if not stale_days:
        return 0
    if _BACKEND != "sqlite":
        return 0
    conn = _connection()
    rows = [(str(day), str(group), json.dumps(payload, ensure_ascii=False,
                                               separators=(",", ":")))
            for day, groups in stale_days.items()
            for group, payload in groups.items()]
    with _LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO economy_daily_archive(day,group_id,payload) "
                "VALUES(?,?,?)", rows,
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK"); raise
    return len(rows)


def maintenance(*, archive_days=365):
    """Bound cold data and keep SQLite planner/WAL healthy."""
    if _BACKEND != "sqlite":
        return {"backend": _BACKEND, "archive_deleted": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=archive_days)).date().isoformat()
    with _LOCK:
        conn = _connection()
        cur = conn.execute("DELETE FROM economy_daily_archive WHERE day < ?", (cutoff,))
        deleted = max(0, cur.rowcount)
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.execute("PRAGMA optimize")
    return {"backend": "sqlite", "archive_deleted": deleted}


def integrity_check():
    if _BACKEND != "sqlite":
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
            return "ok" if isinstance(data, dict) else "invalid-json-root"
        except Exception as error:
            return f"error:{error}"
    with _LOCK:
        return str(_connection().execute("PRAGMA integrity_check").fetchone()[0])


def export_json(path=None):
    """Export the current canonical economy state for verified JSON rollback."""
    target = Path(path) if path else DATA_FILE
    payload = snapshot()
    atomic_write_json(target, payload)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    if loaded != payload:
        raise OSError(f"economy JSON rollback export verification failed: {target}")
    return target


def backup_to(path=None):
    """Create a consistent online backup. Returns the backup path."""
    target = Path(path) if path else runtime_backup_file(
        # شناسهٔ instance داخل نام می‌آید تا مبدأ فایل‌های بکاپ جابه‌جاشده روشن باشد.
        f"bot-{INSTANCE_NAME}-"
        + datetime.now().strftime("%Y%m%d-%H%M%S")
        + (".sqlite3" if _BACKEND == "sqlite" else ".json")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        flush()
        if _BACKEND == "sqlite":
            destination = sqlite3.connect(str(target))
            try:
                _connection().backup(destination)
            finally:
                destination.close()
        else:
            if DATA_FILE.exists():
                shutil.copy2(DATA_FILE, target)
            else:
                target.write_text("{}", encoding="utf-8")
    return target


def stats():
    with _LOCK:
        data = _read()
        result = {
            "backend": _BACKEND,
            "users": len(data.get("users", {})),
            "dirty_rows": len(_dirty_rows),
            "data_file": str(DATA_FILE),
            "db_file": str(DB_FILE),
        }
        if _BACKEND == "sqlite" and DB_FILE.exists():
            result["db_bytes"] = DB_FILE.stat().st_size
            result["state_rows"] = _connection().execute(
                "SELECT COUNT(*) FROM economy_state"
            ).fetchone()[0]
        return result


def reset_all():
    global _cache, _cache_mtime, _dirty
    with _LOCK:
        _cache = None; _cache_mtime = None; _dirty = False; _dirty_rows.clear()
        _state.depth = 0; _state.data = None
        if _BACKEND == "sqlite":
            conn = _connection()
            conn.execute("DELETE FROM economy_state")
            conn.execute("DELETE FROM economy_daily_archive")
            conn.execute("DELETE FROM storage_meta")
        else:
            try: DATA_FILE.unlink()
            except OSError: pass


def _close_connection():
    global _conn
    if _conn is not None:
        try: _conn.close()
        except Exception: pass
        _conn = None


def use_file(path):
    """Select legacy JSON storage (tests and emergency rollback)."""
    global DATA_FILE, _cache, _cache_mtime, _dirty, _BACKEND
    with _LOCK:
        _close_connection()
        DATA_FILE = Path(path)
        _BACKEND = "json"
        _cache = None; _cache_mtime = None; _dirty = False; _dirty_rows.clear()
        _state.depth = 0; _state.data = None


def use_sqlite(path):
    """Select an isolated SQLite database (tests/migration verification)."""
    global DB_FILE, _cache, _cache_mtime, _dirty, _BACKEND
    with _LOCK:
        _close_connection()
        DB_FILE = Path(path)
        _BACKEND = "sqlite"
        _cache = None; _cache_mtime = None; _dirty = False; _dirty_rows.clear()
        _state.depth = 0; _state.data = None
