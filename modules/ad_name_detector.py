"""تشخیص نام‌های تبلیغاتی؛ همان guard اصلی نام در مسیر moderation.

مقایسه عمداً در دو فرم انجام می‌شود: فرم کلمه‌ای برای الگوهای قدیمی و فرم
فشرده برای مقاومت در برابر فاصله/نیم‌فاصله/کشیده/علامت و تکرار حروف.
"""
import re
import unicodedata

from modules.user_display import format_user

# موارد تک‌نویسه‌ای پیش از حذف punctuation/symbol بررسی می‌شوند.
_EMOJI_TERMS = ("💦", "🌈", "👄", "💋", "🤤", "😰", "🥵", "🍑", "🔞")

# فرم canonical و بدون جداکننده. عبارت‌های کوتاه و بسیار عمومی عمداً اینجا
# نیستند تا شباهت جزئی یک نام عادی false-positive نسازد.
_COMPACT_TERMS = (
    "بیوچک", "چکبیو", "بیوگرافیچک", "بیوموچک", "بیوموببینید", "بیوموببین",
    "بیولینک", "بیوببین", "بیوفیلم", "بیوگرافی", "سکس", "سکسی", "پورن", "نود", "فیلم", "حالپی", "تمامسانسور",
    "حالمیدم", "حالمیذم", "فیلمپی", "پیوی", "خاله", "صیغه", "رایگان",
    "فیلترشکن", "شارژرایگان", "کانال", "گروه", "پکیج", "ارزدیجیتال",
    "تتر", "پهلوی", "شاهزاده", "پرچمامریکا", "دلباختهپهلوی", "رضاشاه",
    "محمدرضاشاه", "جانفدایمیهن", "فرزندایران", "یکیبیاد", "خانوم", "پسر",
    "دختر", "زوری",
)

# واژه‌های لاتین قدیمی فقط با مرز کلمه؛ حذف جداکننده برای pv/vpn می‌تواند
# نام‌های عادی لاتین را بیش از حد مسدود کند.
_WORD_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (r"\bpv\b", r"\bvpn\b"))

# همسان‌سازی حروف عربی/فارسی و چند نویسهٔ Unicode مشابه رایج.
_TRANSLATE = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ک": "ک",
    "ة": "ه", "ۀ": "ه", "ە": "ه", "ؤ": "و", "أ": "ا", "إ": "ا",
    "ٱ": "ا", "آ": "ا", "ء": "", "ھ": "ه",
})


def _norm(value):
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value)).lower().translate(_TRANSLATE)
    # کشیده، حرکات، variation selector و کنترل‌های نامرئی حذف شوند.
    value = re.sub(r"[\u0640\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\ufe00-\ufe0f\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", value)
    value = value.replace("_", " ")
    # هر separator یا punctuation به فاصله تبدیل شود، ولی emoji باقی بماند.
    value = "".join(" " if unicodedata.category(ch)[0] in {"P", "Z"} else ch for ch in value)
    return " ".join(value.split())


def _collapse(value):
    """تکرار متوالی grapheme ساده را جمع می‌کند (سکککس → سکس)."""
    return re.sub(r"(.)\1+", r"\1", value)


def _compact(value):
    # تمام فاصله‌ها، symbolها و نویسه‌های غیرحرفی حذف می‌شوند. در نتیجه
    # «بـ یـ ـو گِ‌ر‌ا.فــی» به «بیوگرافی» می‌رسد.
    return "".join(ch for ch in _collapse(_norm(value)) if unicodedata.category(ch).startswith("L"))


def display_name(user):
    return format_user(user)


def reason(user):
    raw_values = (
        getattr(user, "username", None) or "",
        " ".join(part for part in (
            getattr(user, "first_name", None), getattr(user, "last_name", None)
        ) if part),
    )
    for raw in raw_values:
        if not raw:
            continue
        normalized = _norm(raw)
        for emoji in _EMOJI_TERMS:
            if emoji in str(raw):
                return emoji
        for pattern in _WORD_PATTERNS:
            if pattern.search(normalized):
                return pattern.pattern
        compact = _compact(raw)
        for term in _COMPACT_TERMS:
            if term in compact:
                return term
    return None
