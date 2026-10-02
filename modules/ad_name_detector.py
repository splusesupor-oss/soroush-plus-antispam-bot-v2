"""تشخیص و فیلتر مستقل نام‌های تبلیغاتی، به تفکیک گروه."""
import json
import re
import threading
from pathlib import Path

from modules.atomic_write import write_json
from modules.group_id import normalize_group_id
from modules.runtime_paths import runtime_config_file
from modules.user_display import format_user

_TERMS = (
    r"بیو\s*چک", r"چک\s*بیو", r"بیوگرافی\s*چک", r"بیومو\s*(?:چک|ببینید|ببین)",
    r"بیو.*(?:فیلم|لینک|چک|ببین)",
    r"فیلم",
    r"حال\s*پی",
    r"تمام\s*سانسور",
    r"حال\s*می(?:د|ذ)م",
    r"فیلم\s*پی",
    r"🔞",
    r"پی\s*وی",
    r"پیوی",
    r"\bpv\b",
    r"خاله",
    r"صیغه",
    r"رایگان",
    r"سکس",
    r"سکسی",
    r"پورن",
    r"نود",
    r"فیلتر\s*شکن",
    r"فیلترشکن",
    r"\bvpn\b",
    r"شارژ\s*رایگان",
    r"کانال",
    r"پکیج",
    r"ارز\s*دیجیتال",
    r"تتر",
    r"پهلوی",
    r"شاهزاده",
    r"شاه\s*زاده",
    r"پرچم\s*آمریکا",
    r"دلباخته\s*پهلوی",
    r"رضا\s*شاه",
    r"رضاشاه",
    r"محمدرضا\s*شاه",
    r"جان\s*فدای\s*میهن",
    r"جانفدای\s*میهن",
    r"فرزند\s*ایران",
)
_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in _TERMS)

# فیلترهای دستیِ نام به‌صورت مستقل از config.json و به تفکیک گروه ذخیره
# می‌شوند؛ runtime_config_file باعث جداسازی main/bot2/bot3 نیز می‌شود.
FILTER_FILE = Path(runtime_config_file("ad_name_filters.json"))
_FILTER_LOCK = threading.RLock()
_FILTER_CACHE = None
_FILTER_CACHE_MTIME = None


def _norm(value):
    if not value:
        return ""
    value = str(value).lower().replace("ي", "ی").replace("ك", "ک").replace("_", " ")
    # حذف «کشیده» (ـ tatweel) و علائم حرکات
    value = re.sub(r"[\u0640\u064b-\u065f]", "", value)
    # تبدیل نیم‌فاصله، نشانه‌های جهت، فاصله‌های خاص، ایموجی‌ها، علائم نگارشی و نمادها به فاصله
    value = re.sub(r"[\u200c\u200d\u200f\u200e\ufeff\u00a0\-_.,/\\;:!؟،؛|()\[\]{}<>+=*&^%$#@~\"\'`«»…]+", " ", value)
    return " ".join(value.split())


def _collapse(value):
    """جمع کردن حروف تکراری: «بیوچکک» و «بییییو چک» → «بیوچک» و «بیو چک»."""
    return re.sub(r"(.)\1+", r"\1", value)


def _filter_key(value):
    """کلید تطبیق فیلتر، با همان نرمال‌سازی نام تبلیغاتی."""
    return _collapse(_norm(value))


def _filter_file_mtime():
    try:
        return FILTER_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _load_filters():
    global _FILTER_CACHE, _FILTER_CACHE_MTIME
    mtime = _filter_file_mtime()
    if _FILTER_CACHE is not None and mtime == _FILTER_CACHE_MTIME:
        return _FILTER_CACHE
    if mtime is None:
        data = {}
    else:
        try:
            data = json.loads(FILTER_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, TypeError, ValueError):
            data = {}
    # فایل خراب یا دادهٔ قدیمی نباید مسیر پیام را بشکند.
    cleaned = {}
    for group_id, values in data.items():
        if not isinstance(values, list):
            continue
        items = []
        seen = set()
        for value in values:
            raw = str(value or "").strip()
            key = _filter_key(raw)
            if key and key not in seen:
                seen.add(key)
                items.append(raw)
        if items:
            cleaned[str(group_id)] = items
    _FILTER_CACHE = cleaned
    _FILTER_CACHE_MTIME = mtime
    return cleaned


def _save_filters(data):
    global _FILTER_CACHE, _FILTER_CACHE_MTIME
    FILTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(FILTER_FILE, data, indent=2)
    _FILTER_CACHE = data
    _FILTER_CACHE_MTIME = _filter_file_mtime()


def list_name_filters(chat_id):
    """فهرست فیلترهای نام همین گروه؛ خروجی کپی‌شده برای جلوگیری از mutation."""
    with _FILTER_LOCK:
        return list(_load_filters().get(str(normalize_group_id(chat_id)), []))


def add_name_filter(chat_id, value):
    """افزودن یک عبارت فیلتر به همان گروه؛ مقدار False یعنی تکراری/خالی."""
    raw = str(value or "").strip()
    key = _filter_key(raw)
    if not key:
        return False
    group_key = str(normalize_group_id(chat_id))
    with _FILTER_LOCK:
        data = _load_filters()
        values = data.setdefault(group_key, [])
        if any(_filter_key(item) == key for item in values):
            return False
        values.append(raw)
        _save_filters(data)
    return True


def remove_name_filter(chat_id, value):
    """حذف فقط همان عبارت از فیلترهای نام گروه."""
    key = _filter_key(value)
    if not key:
        return False
    group_key = str(normalize_group_id(chat_id))
    with _FILTER_LOCK:
        data = _load_filters()
        values = data.get(group_key, [])
        kept = [item for item in values if _filter_key(item) != key]
        if len(kept) == len(values):
            return False
        if kept:
            data[group_key] = kept
        else:
            data.pop(group_key, None)
        _save_filters(data)
    return True


def _custom_name_reason(user, chat_id):
    if chat_id is None:
        return None
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    display = _norm(f"{first} {last}".strip())
    if not display:
        return None
    candidates = (display, _collapse(display))
    for raw_filter in list_name_filters(chat_id):
        key = _filter_key(raw_filter)
        if key and any(key in candidate for candidate in candidates):
            return f"فیلتر اسم ({raw_filter})"
    return None


def reset_filter_cache():
    """Test hook; persistent filters are not deleted."""
    global _FILTER_CACHE, _FILTER_CACHE_MTIME
    with _FILTER_LOCK:
        _FILTER_CACHE = None
        _FILTER_CACHE_MTIME = None


def display_name(user):
    return format_user(user)


def reason(user, chat_id=None):
    """بررسی نام تبلیغاتی فعلی و فیلتر دستی همان گروه.

    مسیر مجازات عمداً بیرون از این ماژول و همان مسیر قدیمی handler باقی
    می‌ماند؛ این تابع فقط دلیل match را برمی‌گرداند.
    """
    custom_reason = _custom_name_reason(user, chat_id)
    if custom_reason:
        return custom_reason

    username = _norm(getattr(user, "username", None))
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    name = _norm(f"{first} {last}".strip())
    for value in (username, name):
        if not value:
            continue
        # هم متن عادی و هم نسخهٔ بدون حروف تکراری بررسی می‌شود تا
        # نوشتار کشیده (بیوچکک، بیــو چک، بییییو چک) هم گرفته شود.
        for candidate in (value, _collapse(value)):
            for pattern in _PATTERNS:
                if pattern.search(candidate):
                    return pattern.pattern
    return None
