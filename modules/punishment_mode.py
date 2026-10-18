"""حالت مجازات به تفکیک گروه — دستور «تغییر مجازات».

پیش‌فرض «بن» است؛ مالک اصلی ربات یا مالک ثبت‌شدهٔ گروه می‌تواند با دستور
«تغییر مجازات» و سپس «تایید»، مجازاتِ همهٔ مسیرهای خودکار (پر شدن اخطار،
اسپم‌ها، نام تبلیغاتی، موج اسپم) را در همان گروه به سکوت دائمی تبدیل کند
و دوباره با همان دستور به بن برگرداند.

نقطهٔ اعمال مرکزی: ``AdminActions.ban_user`` — تا سیستم پاکسازی، صف‌ها و
callback های موفقیت دقیقاً مثل قبل کار کنند (فقط RPC نهایی عوض می‌شود).
دستورهای دستی («اخراج») از این مسیر نمی‌گذرند و دست‌نخورده می‌مانند.

ذخیره در ``config/punishment_mode.json`` اتمیک؛ خواندن با کش mtime.
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
_FILE = _BASE / "punishment_mode.json"

MODE_BAN = "ban"
MODE_MUTE = "mute"
DEFAULT_MODE = MODE_BAN

# انتظار برای «تایید/لغو» بعد از دستور: (chat_key, user_key) → زمان شروع
_PENDING_TTL = 120
_PENDING_MAX = 2000
_pending = {}

_cache = None
_cache_mtime = None

CONFIRM_WORDS = frozenset({"تایید", "تأیید", "✅ تایید", "✅ تأیید"})
CANCEL_WORDS = frozenset({"لغو", "❌ لغو"})


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


def get_mode(chat_id):
    value = _load().get(_key(chat_id))
    return MODE_MUTE if value == MODE_MUTE else MODE_BAN


def is_mute(chat_id):
    """True یعنی در این گروه به جای بن، سکوت دائمی اعمال شود."""
    try:
        return get_mode(chat_id) == MODE_MUTE
    except Exception:
        # هر خطای غیرمنتظره نباید مسیر مجازات را بشکند؛ پیش‌فرض بن.
        return False


def set_mode(chat_id, mode):
    """ثبت حالت مجازات گروه؛ نوشتن اتمیک."""
    global _cache, _cache_mtime
    if not free_tier.is_enabled("punishment_settings"):
        return get_mode(chat_id)
    if mode not in (MODE_BAN, MODE_MUTE):
        raise ValueError(f"invalid punishment mode: {mode!r}")
    data = dict(_load())
    data[_key(chat_id)] = mode
    _BASE.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(_BASE), prefix="punishment_mode.", suffix=".tmp")
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
    return mode


def toggle(chat_id):
    """جابجایی بن ↔ سکوت؛ حالت جدید را برمی‌گرداند."""
    new_mode = MODE_BAN if is_mute(chat_id) else MODE_MUTE
    return set_mode(chat_id, new_mode)


def mode_label(mode):
    """برچسب فارسی برای پیام تأیید: بن → «اخراج»، سکوت → «سکوت»."""
    return "سکوت" if mode == MODE_MUTE else "اخراج"


def begin_change(chat_id, user_id):
    if not free_tier.is_enabled("punishment_settings"):
        return False
    _prune_pending()
    _pending[(_key(chat_id), str(user_id))] = time.time()
    _prune_pending()
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
    while len(_pending) > _PENDING_MAX:
        _pending.pop(next(iter(_pending)), None)
