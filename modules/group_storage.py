import json
from pathlib import Path

from modules.runtime_paths import runtime_config_file
from modules.atomic_write import write_json

from modules.group_id import normalize_group_id

FILE = runtime_config_file("groups.json")

_cache = None
_cache_mtime = None


def _group_key(data, group_id):
    """کلید موجود را بدون ساختن رکورد تکراری پیدا می‌کند."""
    raw_key = str(group_id)
    canonical_key = normalize_group_id(group_id)
    if raw_key in data:
        return raw_key
    if canonical_key in data:
        return canonical_key
    return canonical_key


def _file_mtime():
    try:
        return FILE.stat().st_mtime_ns
    except OSError:
        return None

def load_groups():
    global _cache, _cache_mtime
    mtime = _file_mtime()
    if _cache is not None and mtime == _cache_mtime:
        return _cache

    if mtime is None:
        _cache = {}
    else:
        try:
            _cache = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception as _corrupt:
            # دلیل خرابی باید در ترمینال دیده شود: تا این فایل سالم
            # نشود، همه گروه‌ها inactive و ربات در همه جا بی‌صداست.
            print(
                "⛔ GROUPS FILE CORRUPT/UNREADABLE (%s) — all groups "
                "treated as INACTIVE until the file is fixed: %s"
                % (_corrupt, FILE)
            )
            _cache = {}

    _cache_mtime = mtime
    return _cache

def save_groups(data):
    global _cache, _cache_mtime
    write_json(FILE, data, indent=2)
    _cache = data
    _cache_mtime = _file_mtime()

def activate_group(group_id, title):
    data = load_groups()
    key = _group_key(data, group_id)
    group = data.get(key, {})

    group.update({
        "title": title,
        "active": True
    })
    data[key] = group

    save_groups(data)
    try:
        from modules.cache_manager import PermissionCircuitBreaker
        PermissionCircuitBreaker.get_default().reset(group_id)
    except Exception:
        pass


def deactivate_group(group_id, title):
    data = load_groups()
    key = _group_key(data, group_id)
    group = data.get(key, {})

    group.update({
        "title": title,
        "active": False
    })
    data[key] = group

    save_groups(data)
    try:
        from modules import fox_game_tokens
        fox_game_tokens.revoke_group_tokens(group_id)
    except Exception:
        pass


def update_group_title(group_id, title):
    """🔄 همگام‌سازی خودکار نام گروه پس از تغییر آن در سروش.

    فقط عنوانِ گروهی که قبلاً ثبت شده به‌روز می‌شود؛ برای گروه‌های
    ثبت‌نشده هیچ رکوردی ساخته نمی‌شود و به هیچ فیلد دیگری (active،
    owner_id و...) دست نمی‌زند. خروجی: True اگر عنوان واقعاً تغییر کرد.
    """
    title = str(title or "").strip()
    if not title:
        return False
    data = load_groups()
    raw_key = str(group_id)
    canonical_key = normalize_group_id(group_id)
    key = raw_key if raw_key in data else (
        canonical_key if canonical_key in data else None
    )
    if key is None:
        return False
    group = data.get(key)
    if not isinstance(group, dict):
        return False
    if str(group.get("title") or "").strip() == title:
        return False
    group["title"] = title
    save_groups(data)
    return True


def set_group_owner(group_id, owner_id):
    data = load_groups()
    key = _group_key(data, group_id)
    group = data.get(key, {})
    group["owner_id"] = int(owner_id)
    data[key] = group
    save_groups(data)


def get_group_owner(group_id):
    data = load_groups()
    return data.get(_group_key(data, group_id), {}).get("owner_id")


def remove_group_owner(group_id):
    data = load_groups()
    key = _group_key(data, group_id)
    group = data.get(key)
    if not group or "owner_id" not in group:
        return False

    del group["owner_id"]
    save_groups(data)
    return True


def is_active(group_id):
    data = load_groups()
    return data.get(_group_key(data, group_id), {}).get("active", False)
