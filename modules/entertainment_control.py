"""🎮 کنترل سرگرمی به تفکیک گروه — روشن/خاموش کردن بازی‌های داخلی ربات.

این ماژول عمداً «فقط یک گارد» است: هیچ بازی، پاداش، storage یا پنل ادمین
را دست نمی‌زند و هیچ منطقی از منطق‌های موجود را بازنویسی نمی‌کند.

قوانینی که در این فایل تضمین شده‌اند:

* **دیتای مستقل.** وضعیت در فایل ``entertainment_mode.json`` و در پوشهٔ
  config رانتایم ذخیره می‌شود؛ نه داخل ``config.json``، نه ``group_rules.json``
  و نه هیچ فایل موجود دیگری. مسیر از ``runtime_config_file`` می‌آید، پس
  ``BOT_INSTANCE`` (main/bot2/bot3) هر کدام فایل خودشان را دارند و هیچ
  کلیدی بین instanceها تداخل نمی‌کند (کلیدها هم با ``normalize_group_id``
  یکسان می‌شوند تا ``-100…`` و شکل کوتاه یک گروه، دو رکورد نسازند).
* **fail-open.** نبود فایل، فایل خراب یا هر خطای دیسک یعنی «فعال».
  یک خطای خواندن نباید بازی‌ها را برای همیشه ببندد.
* **بی‌اثر بودنِ مسدودسازی.** ``blocks`` خالص و بدون I/O است و ``guard`` تنها
  یک پیام هشدار می‌فرستد؛ هیچ state، تایمر، سکه یا شمارنده‌ای ساخته نمی‌شود.
* **Bold واقعی.** Spanها بر حسب واحدهای UTF-16 محاسبه می‌شوند (نه ``len``)،
  وارونهٔ ایموجی‌ها entity را جابه‌جا می‌کند. ستارهٔ مارک‌داون تولید نمی‌شود.

دستورها: ``سرگرمی خاموش`` و ``سرگرمی فعال`` — فقط مالک اصلی ربات، مالک
ثبت‌شدهٔ گروه یا ادمین ثبت‌شدهٔ همان گروه (از ``admin_tools.has_admin_permission``
در هندلر استفاده می‌شود؛ این ماژول به هیچ‌روی دسترسی نمی‌سنجد تا خالص بماند).
"""
from __future__ import annotations

import json
import os

from modules.atomic_write import write_json
from modules.group_id import normalize_group_id
from modules.runtime_paths import runtime_config_file

# ---------------------------------------------------------------------------
# entity (در تست و روی کلاینت‌های بدون splusthon، کلاس جایگزین کافی است)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - بسته به نصب کتابخانهٔ کلاینت
    from splusthon.tl.types import MessageEntityBold
except ImportError:  # pragma: no cover
    class MessageEntityBold:
        """جایگزین سبک با همان امضای offset/length."""

        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length


# ---------------------------------------------------------------------------
# متن‌ها — این رشته‌ها عیناً (بدون کم و زیاد کردن کاراکتر) ارسال می‌شوند
# ---------------------------------------------------------------------------
DISABLED_NOTICE = "🎮 بازی های روباه غیر فعال شد"
ENABLED_NOTICE = "🍬 : بازی های روباه فعال شد میتوانید با دستور لیست بازی از بازی ها استفاده کنید"
BLOCKED_NOTICE = ("بازی های روباه عموم غیر فعال می\u200cباشند ؛ برای فعال سازی باید ادمین یا "
                  "مالک با دستور سرگرمی فعال بازی هارو فعال کند تا بتوانید از بازی ها استفاده "
                  "کنید ☑️")
PERMISSION_DENIED = "❌ فقط مالک یا ادمین\u200cهای گروه اجازه تغییر وضعیت سرگرمی را دارند"
PRIVATE_CHAT_NOTICE = "❌ این دستور فقط داخل گروه کار می\u200cکند."

# تنها عبارتِ Bold‌شده در پیام مسدودسازی.
BOLD_TARGET = "سرگرمی فعال"

COMMAND_DISABLE = "سرگرمی خاموش"
COMMAND_ENABLE = "سرگرمی فعال"
COMMANDS = frozenset({COMMAND_DISABLE, COMMAND_ENABLE})

# ---------------------------------------------------------------------------
# دستورهایی که یک بازیِ داخلی را شروع/ملحق می‌کنند.
# «لیست بازی» عمداً اینجا نیست: پیام فعال‌سازی کاربر را به همان ارجاع
# می‌دهد، پس باید همیشه کار کند. «دانستنی»، «بیوگرافی»، «فونت»، «جستجو»
# و «ترجمه» ابزارند نه بازی، پس گارد نمی‌شوند.
# همه در شکل نرمال‌شده (نیم‌فاصله → فاصله) نوشته شده‌اند.
# ---------------------------------------------------------------------------
GAME_COMMANDS = frozenset({
    # روتر بازی‌های Fox AI
    "بخند یا بباز",
    "بقا",
    "جعبه شانسی",
    "خون آشام",
    "معما",
    "حدس جمله",
    "ساخت جمله",
    "مین یاب",
    "بهترین جواب",
    "نبرد",
    "کارگاه",
    "شرکت",
    # بازی‌های هندلر اصلی
    "اسم فامیل",
    "حدس ایموجی",
    "حدس پرچم",
    "تصحیح کلمات",
    "چهار گزینه ای",
    "کی بیشتر بلده",
    "دروغ یا حقیقت",
    "جای خالی",
    "چیستان",
    "جرعت",
    "جرات",
    "جرئت",
    "حقیقت",
    "حقیقت بگو",
    "جک",
})

# ---------------------------------------------------------------------------
# نرمال‌سازی — همان قواعد normalize_command هندلر، ولی مستقل و بدون import
# حلقوی، تا گارد در هر نقطه‌ای (حتی تست خالص) یکسان رفتار کند.
# ---------------------------------------------------------------------------
_NORMALIZE_MAP = {
    "\u200c": " ",   # نیم‌فاصله → فاصله
    "\u200f": "",    # نویسهٔ جهت‌دهای راست‌به‌چپ
    "\u200e": "",    # نویسهٔ جهت‌دهای چپ‌به‌راست
    "\ufeff": "",    # BOM / ZWNBSP
    "\u00a0": " ",   # فاصلهٔ نشکن
    "\u064a": "\u06cc",  # «ي» عربی → «ی» فارسی
    "\u0643": "\u06a9",  # «ك» عربی → «ک» فارسی
}


def normalize(text):
    """شکل مقایسه‌پذیر دستور.

    «چهار گزینه‌ای»، «چهار گزینه  ای» و «حدس ايموجي» همگی به یک رشتهٔ قابل
    تطبیق تبدیل می‌شوند.
    """
    if not text:
        return ""
    normalized = str(text)
    for source, target in _NORMALIZE_MAP.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def is_game_command(text):
    """آیا این متن، دستور شروع/الحاق یکی از بازی‌های داخلی است."""
    return normalize(text) in GAME_COMMANDS


# ---------------------------------------------------------------------------
# Bold واقعی: واحدهای UTF-16
# ---------------------------------------------------------------------------
def u16_length(text):
    """طول رشته بر حسب واحدهای UTF-16 (واحدی که entityها می‌شناسند)."""
    return len(str(text).encode("utf-16-le")) // 2


def full_bold_span(text):
    """(offset, length) کل پیام."""
    return 0, u16_length(text)


def blocked_bold_span(text=None):
    """(offset, length) عبارت «سرگرمی فعال» داخل پیام مسدودسازی."""
    text = BLOCKED_NOTICE if text is None else text
    index = text.find(BOLD_TARGET)
    if index < 0:
        return None
    return u16_length(text[:index]), u16_length(BOLD_TARGET)


# ---------------------------------------------------------------------------
# ذخیره‌سازی: فایل مستقل + نوشتن اتمیک + کش بر پایهٔ mtime
# ---------------------------------------------------------------------------
FILE = runtime_config_file("entertainment_mode.json")

_cache = None
_cache_mtime = None


def _file_mtime():
    try:
        return os.stat(FILE).st_mtime_ns
    except OSError:
        return None


def load():
    """فایل وضعیت را با کش mtime می‌خواند. هیچ خطایی به بیرون راه نمی‌یابد."""
    global _cache, _cache_mtime
    mtime = _file_mtime()
    if _cache is not None and mtime == _cache_mtime:
        return _cache

    if mtime is None:
        data = {}
    else:
        try:
            with open(FILE, "r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            data = loaded if isinstance(loaded, dict) else {}
        except BaseException:
            # فایل نیمه‌نوشته، خراب یا غیرقابل‌خواندن → حالت امنِ «همه چیز فعال».
            data = {}

    _cache = data
    _cache_mtime = mtime
    return _cache


def save(data):
    """نوشتن اتمیک (فایل موقت + fsync + replace) و به‌روزرسانی کش."""
    global _cache, _cache_mtime
    write_json(FILE, data, indent=2)
    _cache = data
    _cache_mtime = _file_mtime()
    return data


def _key(chat_id):
    return normalize_group_id(chat_id)


def set_enabled(chat_id, enabled):
    """وضعیت یک گروه را ثبت می‌کند و همان مقدار را برمی‌گرداند."""
    data = dict(load())
    value = bool(enabled)
    data[_key(chat_id)] = value
    save(data)
    return value


def is_enabled(chat_id):
    """پیش‌فرض هر گروه تنظیم\u200cنشده = فعال."""
    try:
        data = load()
    except BaseException:
        return True
    return bool(data.get(_key(chat_id), True))


def enable(chat_id):
    return set_enabled(chat_id, True)


def disable(chat_id):
    return set_enabled(chat_id, False)


def reset(chat_id):
    """کلید گروه پاک می‌شود تا به پیش‌فرض (فعال) برگردد."""
    data = dict(load())
    removed = data.pop(_key(chat_id), None) is not None
    if removed:
        save(data)
    return removed


def all_states():
    """نمای خوانا از وضعیت ثبت‌شدهٔ گروه‌ها (فقط برای گزارش/عیب‌یابی)."""
    return dict(load())


# ---------------------------------------------------------------------------
# ارسال پیام‌ها
# ---------------------------------------------------------------------------
async def _reply_bold(event, text, span):
    """یک پاسخ با Bold entity می‌فرستد؛ در نبود پشتیبانی، متن ساده.

    اگر ارسال با entity با ``TypeError`` (یا هر خطای دیگرِ ناشی از نسخهٔ
    کلاینت/سرور) رد شود، همان متن بدون قالب‌بندی فرستاده می‌شود تا کاربر
    هرگز پیامی نبیند که غیب شده باشد. متن ارسالی هیچ‌وقت ستارهٔ مارک‌داون
    ندارد؛ Bold فقط entity است.
    """
    entities = None
    if span is not None:
        offset, length = span
        try:
            entities = [MessageEntityBold(offset=offset, length=length)]
        except BaseException:      # کلاسی که entity را پشتیبانی نمی‌کند
            entities = None
    if entities is not None:
        try:
            return await event.reply(text, formatting_entities=entities)
        except BaseException:
            pass
    return await event.reply(text)


async def send_disabled_notice(event):
    return await _reply_bold(event, DISABLED_NOTICE, full_bold_span(DISABLED_NOTICE))


async def send_enabled_notice(event):
    return await _reply_bold(event, ENABLED_NOTICE, full_bold_span(ENABLED_NOTICE))


async def send_blocked_notice(event):
    return await _reply_bold(event, BLOCKED_NOTICE, blocked_bold_span(BLOCKED_NOTICE))


async def send_permission_denied(event):
    return await event.reply(PERMISSION_DENIED)


# ---------------------------------------------------------------------------
# گارد
# ---------------------------------------------------------------------------
def blocks(chat_id, text):
    """گارد خالص، بدون I/O شبکه — برای تست آسان.

    True یعنی این دستور بازی نباید اجرا شود.
    """
    return is_game_command(text) and not is_enabled(chat_id)


async def guard(event, chat_id, text):
    """True یعنی بازی مسدود شد و هندلر باید همان‌جا return کند.

    فقط یک پیام هشدار ارسال می‌شود؛ هیچ state، تایمر، پرداخت سکه یا
    شمارنده‌ای در این مسیر ساخته نمی‌شود.
    """
    if not blocks(chat_id, text):
        return False
    await send_blocked_notice(event)
    return True
