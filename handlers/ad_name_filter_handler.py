"""گفت‌وگوی مدیریت فیلتر نام‌های تبلیغاتی.

این handler فقط storage و permission را به مسیر فعلی وصل می‌کند؛ تشخیص نام
و enforcement همچنان در ``modules.ad_name_detector`` و مسیر موجود
``message_handler`` انجام می‌شود.
"""
from __future__ import annotations

from modules import ad_name_detector
from modules import admin_tools

try:
    from splusthon.tl.types import MessageEntityBlockquote, MessageEntityBold
except Exception:  # pragma: no cover - offline/unit-test fallback
    class MessageEntityBold:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length

    class MessageEntityBlockquote:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length


ADD_PREFIX = "فیلتر اسم"
REMOVE_PREFIXES = ("حذف فیلتر اسم", "لغو اسم")
LIST_COMMAND = "لیست فیلتر اسم"
COMMAND_PREFIXES = (ADD_PREFIX, *REMOVE_PREFIXES)

# این متن بدون Markdown فرستاده می‌شود؛ formatting_entities در راهنمای اصلی
# هر دو خط را با entity واقعی Bold و Blockquote پوشش می‌دهد.
HELP_BLOCK = (
    "برای فیلتر اسم یک کاربر بنویسید فیلتر اسم بعد نام را بنویسید\n"
    "برای لغو بنویسید لغو اسم بعد اسم را بنویسید\n"
    "برای دیدن لیست اسم ها\n"
    "لیست فیلتر اسم"
)


def _u16(value):
    return len((value or "").encode("utf-16-le")) // 2


def _success_entities(text):
    length = _u16(text)
    return [
        MessageEntityBold(offset=0, length=length),
        MessageEntityBlockquote(offset=0, length=length),
    ]


def _authorized(chat_id, user_id, sender):
    return admin_tools.has_admin_permission(
        chat_id,
        user_id,
        getattr(sender, "username", None),
    )


def _match(text):
    value = str(text or "").strip()
    if value == LIST_COMMAND:
        return "list", ""
    if value == ADD_PREFIX:
        return "add", ""
    if value.startswith(ADD_PREFIX + " "):
        return "add", value[len(ADD_PREFIX):].strip()
    for prefix in REMOVE_PREFIXES:
        if value == prefix:
            return "remove", ""
        if value.startswith(prefix + " "):
            return "remove", value[len(prefix):].strip()
    return None, ""


def is_command(text):
    action, _value = _match(text)
    return action is not None


async def handle(bot, event, chat_id, user_id, sender, text):
    """Handle management commands; return True only for this feature."""
    action, value = _match(text)
    if action is None:
        return False

    if getattr(event, "is_private", False):
        await event.reply("❌ فیلتر اسم فقط داخل گروه قابل استفاده است.")
        return True

    if not _authorized(chat_id, user_id, sender):
        await event.reply(
            "❌ فقط مالک ثبت‌شده یا ادمین ثبت‌شده اجازه مدیریت فیلتر اسم را دارد."
        )
        return True

    if action == "list":
        values = ad_name_detector.list_name_filters(chat_id)
        if not values:
            await event.reply("❌ برای این گروه هیچ فیلتر اسمی ثبت نشده است.")
        else:
            lines = ["📋 فیلترهای اسم این گروه:"]
            lines.extend(f"{index}. {item}" for index, item in enumerate(values, 1))
            await event.reply("\n".join(lines))
        return True

    if not value:
        if action == "add":
            await event.reply("❌ استفاده صحیح: فیلتر اسم بعد نام را بنویسید.")
        else:
            await event.reply("❌ استفاده صحیح: لغو اسم بعد نام را بنویسید.")
        return True

    if action == "add":
        added = ad_name_detector.add_name_filter(chat_id, value)
        if not added:
            await event.reply("⚠️ این نام از قبل در فیلترهای همین گروه وجود دارد.")
            return True
        response = f"نام : {value} فیلتر شد"
        await event.reply(response, formatting_entities=_success_entities(response))
        return True

    removed = ad_name_detector.remove_name_filter(chat_id, value)
    if not removed:
        await event.reply("⚠️ این نام در فیلترهای همین گروه پیدا نشد.")
        return True
    response = f"نام : {value} از فیلتر خارج شد"
    await event.reply(response, formatting_entities=_success_entities(response))
    return True
