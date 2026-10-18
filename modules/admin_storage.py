"""ID-based registered group admin storage."""
import json
from pathlib import Path

from modules.runtime_paths import runtime_config_file
from modules.atomic_write import write_json

from modules.group_id import normalize_group_id

FILE = runtime_config_file("admins.json")

_cache = None
_cache_mtime = None


def load_admins():
    global _cache, _cache_mtime
    try:
        mtime = FILE.stat().st_mtime_ns
    except OSError:
        mtime = None
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    if mtime is None:
        _cache = {}
    else:
        try:
            _cache = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    _cache_mtime = mtime
    return _cache


def save_admins(data):
    global _cache, _cache_mtime
    write_json(FILE, data, indent=2)
    _cache = data
    _cache_mtime = FILE.stat().st_mtime_ns


def add_admin(group_id, user_id, username=None):
    data = load_admins()
    gid = normalize_group_id(group_id)
    entries = data.setdefault(gid, [])
    normalized_id = str(user_id)

    if any(
        isinstance(entry, dict) and str(entry.get("user_id")) == normalized_id
        for entry in entries
    ):
        return False

    entries.append({
        "user_id": normalized_id,
        "username": username or None,
    })
    save_admins(data)
    return True


def count_admins(group_id):
    """Number of admins currently registered for ``group_id``."""
    entries = load_admins().get(normalize_group_id(group_id), [])
    if not isinstance(entries, list):
        return 0
    return len(entries)


def is_admin(group_id, user_id, username=None):
    """رکوردهای جدید ID-based و رکوردهای قدیمی username-based را می‌پذیرد."""
    if user_id is None:
        return False
    normalized_id = str(user_id)
    normalized_username = (username or "").lstrip("@").lower()
    for entry in load_admins().get(normalize_group_id(group_id), []):
        if isinstance(entry, dict) and str(entry.get("user_id")) == normalized_id:
            return True
        if isinstance(entry, str) and normalized_username:
            if entry.lstrip("@").lower() == normalized_username:
                return True
    return False


def remove_admin(group_id, user_id):
    data = load_admins()
    gid = normalize_group_id(group_id)
    if gid not in data:
        return False

    normalized_id = str(user_id)
    original_length = len(data[gid])
    data[gid] = [
        entry for entry in data[gid]
        if not (
            isinstance(entry, dict)
            and str(entry.get("user_id")) == normalized_id
        )
    ]
    if len(data[gid]) == original_length:
        return False

    save_admins(data)
    return True
