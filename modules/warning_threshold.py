"""آستانهٔ اخطار به تفکیک گروه — دستور «تغییر اخطار».

پیش‌فرض ۵ اخطار تا بن؛ مالک اصلی ربات یا مالک ثبت‌شدهٔ گروه می‌تواند با
دستور «تغییر اخطار» عددی بین ۱ تا ۱۲ برای همان گروه تعیین کند.

ذخیره در ``config/warning_threshold.json`` با نوشتن اتمیک (temp + os.replace).
نوشتن بسیار کم‌تکرار است (فقط هنگام تغییر توسط مالک)، بنابراین نوشتن همگام
هیچ فشاری روی مسیر پیام‌ها ندارد؛ خواندن با کش mtime انجام می‌شود.
"""
import json
import os
import tempfile
import time
from pathlib import Path

from modules.runtime_paths import CONFIG_DIR

from modules.group_id import normalize_group_id
from modules import free_tier

_BASE = CONFIG_DIR
_FILE = _BASE / "warning_threshold.json"

DEFAULT_THRESHOLD = 5
MIN_THRESHOLD = 1
MAX_THRESHOLD = 12

# انتظار برای عدد بعد از دستور «تغییر اخطار»: (chat_key, user_key) → زمان شروع
_PENDING_TTL = 120
_pending = {}

_cache = None
_cache_mtime = None

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _key(chat_id):
    return str(normalize_group_id(chat_id))


def _load():
    """خواندن با کش mtime؛ فایل خراب/غایب → دیکشنری خالی."""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(_FILE)
    except OSError:
        _cache, _cache_mtime = {}, None
        return _cache
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    try:
        with open(_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        _cache = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        _cache = {}
    _cache_mtime = mtime
    return _cache


def get_threshold(chat_id, default=DEFAULT_THRESHOLD):
    """آستانهٔ اخطار این گروه؛ اگر ثبت نشده باشد همان پیش‌فرض."""
    try:
        value = _load().get(_key(chat_id))
        value = int(value)
    except (TypeError, ValueError):
        return int(default)
    if MIN_THRESHOLD <= value <= MAX_THRESHOLD:
        return value
    return int(default)


def set_threshold(chat_id, value):
    """ثبت آستانهٔ ۱ تا ۱۲ برای گروه؛ نوشتن اتمیک."""
    global _cache, _cache_mtime
    if not free_tier.is_enabled("warning_settings"):
        return None
    value = int(value)
    if not (MIN_THRESHOLD <= value <= MAX_THRESHOLD):
        raise ValueError(f"threshold out of range: {value}")
    data = dict(_load())
    data[_key(chat_id)] = value
    _BASE.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(_BASE), prefix="warning_threshold.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _cache = data
    try:
        _cache_mtime = os.path.getmtime(_FILE)
    except OSError:
        _cache_mtime = None
    return value


def begin_change(chat_id, user_id):
    """شروع انتظار برای عدد از همین کاربر در همین گروه."""
    if not free_tier.is_enabled("warning_settings"):
        return False
    _prune_pending()
    _pending[(_key(chat_id), str(user_id))] = time.time()
    return True


def has_pending(chat_id, user_id):
    _prune_pending()
    return (_key(chat_id), str(user_id)) in _pending


def clear_pending(chat_id, user_id):
    _pending.pop((_key(chat_id), str(user_id)), None)


def _prune_pending(now=None):
    now = time.time() if now is None else now
    for key in [k for k, ts in _pending.items() if now - ts > _PENDING_TTL]:
        _pending.pop(key, None)


def parse_choice(text):
    """تبدیل جواب کاربر به عدد.

    خروجی ``(value, valid)``: اگر متن اصلاً عدد نبود ``(None, False)``؛
    اگر عدد بود ولی خارج از ۱ تا ۱۲ بود ``(value, False)``.
    ارقام فارسی/عربی و گیومه « » هم پذیرفته می‌شوند.
    """
    cleaned = str(text or "").translate(_DIGIT_MAP)
    cleaned = cleaned.replace("«", " ").replace("»", " ").strip()
    if not cleaned.isdigit() or len(cleaned) > 2:
        return None, False
    value = int(cleaned)
    return value, MIN_THRESHOLD <= value <= MAX_THRESHOLD
