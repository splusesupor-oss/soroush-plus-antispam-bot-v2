"""ذخیرهٔ کاربران vip به تفکیک گروه (ID-based، الگوی admin_storage)."""
import json

from modules.runtime_paths import runtime_config_file
from modules.atomic_write import write_json
from modules.group_id import normalize_group_id
from modules import free_tier

FILE = runtime_config_file("vip_users.json")

_cache = None
_cache_mtime = None


def _load():
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


def _save(data):
    global _cache, _cache_mtime
    write_json(FILE, data, indent=2)
    _cache = data
    _cache_mtime = FILE.stat().st_mtime_ns


def add_vip(group_id, user_id):
    """ثبت vip؛ False اگر قبلاً vip باشد یا این قابلیت در پلن خاموش باشد."""
    if not free_tier.is_enabled("vip"):
        return False
    g = str(normalize_group_id(group_id))
    data = _load()
    ids = data.get(g)
    if not isinstance(ids, list):
        ids = []
    uid = str(user_id)
    if uid in ids:
        return False
    ids.append(uid)
    data[g] = ids
    _save(data)
    return True


def remove_vip(group_id, user_id):
    """لغو vip؛ False اگر vip نباشد یا این قابلیت در پلن خاموش باشد."""
    if not free_tier.is_enabled("vip"):
        return False
    g = str(normalize_group_id(group_id))
    data = _load()
    ids = data.get(g)
    if not isinstance(ids, list):
        return False
    uid = str(user_id)
    if uid not in ids:
        return False
    ids.remove(uid)
    data[g] = ids
    _save(data)
    return True


def is_vip(group_id, user_id):
    if not free_tier.is_enabled("vip"):
        return False
    try:
        data = _load()
        ids = data.get(str(normalize_group_id(group_id)))
        return isinstance(ids, list) and str(user_id) in ids
    except Exception:
        return False


def list_vips(group_id):
    if not free_tier.is_enabled("vip"):
        return []
    data = _load()
    ids = data.get(str(normalize_group_id(group_id)))
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, str) and i]
