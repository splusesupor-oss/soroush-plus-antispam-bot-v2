"""Command and reply flow for the Fox clipboard feature.

Only this module knows the clipboard UX. Authorization is deliberately delegated
to the project's existing ``admin_tools.has_admin_permission`` helper, so the
feature cannot create a second admin system.
"""
from __future__ import annotations

from typing import Optional

from modules import clipboard_storage
from modules import admin_tools

try:
    from splusthon.tl.types import MessageEntityBlockquote, MessageEntityBold
except Exception:  # pragma: no cover - test/offline fallback
    class MessageEntityBold:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length

    class MessageEntityBlockquote:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length


COPYBOARD_COMMAND = "کپی بورد"
COPY_COMMAND = "کپی"
COMMANDS = frozenset({COPYBOARD_COMMAND, COPY_COMMAND})

GUIDE_TITLE = "🔖راهنما و توضیحات کپی بورد"
GUIDE_DESCRIPTION = (
    "قابلیت کپی بورد به این صورت می‌باشد که میتوانید یک متن به هم به صورت ساده و هم ب صورت bold شده و یا نقل قول شده به ربات بدهید و بعدا با دستور کپی بورد اون متن رو ارسال میکنه اما چه استفاده ای می‌تونه داشته باشه مثلا در مواردی مثل وقتی که گروه میبندید میخایین بعد از قفل شدن لینکی رو برای سین زدن یا برای دیده شدن فواورد کنید ربات مستقیم نشان میده یا موقع چت گروهی میتوانید بدون نیاز به فواورد از کانالی یا پیام شخصی لینک کانال گروه دوم یا پیوی خصوصی و یا تکست و اعلان های مهم گروه رو با هر شکل و توضیحی به ربات بدهید و با همون دستور ربات سریع نمایش خواهد داد"
)
GUIDE_FOOTER = "📌روی همین پیام ریپلای کنید و متن یا تکست و لینک خودتون رو بفرستید"
GUIDE_TEXT = f"{GUIDE_TITLE}\n\n{GUIDE_DESCRIPTION}\n\n{GUIDE_FOOTER}"

# This exact block is also embedded in the admin-only Fox help menu.
HELP_BLOCK = (
    "📮کپی بورد حافظه روباهی\n\n"
    "برای ایجاد بنویسید کپی بورد\n\n"
    "برای نمایش پیام بنویس کپی"
)


def _u16(value: str) -> int:
    return len((value or "").encode("utf-16-le")) // 2


def build_guide_entities():
    """Build real SPlusthon formatting entities; no Markdown markers."""
    title_start = 0
    description_start = _u16(GUIDE_TITLE + "\n\n")
    return [
        MessageEntityBlockquote(offset=title_start, length=_u16(GUIDE_TITLE)),
        MessageEntityBold(offset=title_start, length=_u16(GUIDE_TITLE)),
        MessageEntityBold(
            offset=description_start,
            length=_u16(GUIDE_DESCRIPTION),
        ),
    ]


def build_help_entities(text: str):
    """Return one Bold + one Quote span covering the complete help block."""
    start = text.find(HELP_BLOCK)
    if start < 0:
        return []
    offset = _u16(text[:start])
    length = _u16(HELP_BLOCK)
    return [
        MessageEntityBold(offset=offset, length=length),
        MessageEntityBlockquote(offset=offset, length=length),
    ]


def is_command(text: str) -> bool:
    return str(text or "").strip() in COMMANDS


def _sender_username(sender) -> Optional[str]:
    return getattr(sender, "username", None)


def _authorized(chat_id, user_id, sender) -> bool:
    return admin_tools.has_admin_permission(
        chat_id, user_id, _sender_username(sender)
    )


def _reply_id(event):
    message = getattr(event, "message", None)
    nested = getattr(message, "reply_to", None)
    return (
        getattr(message, "reply_to_msg_id", None)
        or getattr(nested, "reply_to_msg_id", None)
        or getattr(nested, "reply_to_top_id", None)
        or getattr(event, "reply_to_msg_id", None)
        or getattr(getattr(event, "reply_to", None), "reply_to_msg_id", None)
    )


def _message_entities(event):
    entities = getattr(getattr(event, "message", None), "entities", None)
    return list(entities) if entities else []


async def _reply(event, text: str, entities=None):
    return await event.reply(
        text,
        formatting_entities=entities or None,
    )


async def _send_clipboard(bot, event, chat_id, record):
    """Send the stored body through the existing SPlusthon formatting API."""
    text = record["text"]
    entities = record.get("entities") or None
    respond = getattr(event, "respond", None)
    if callable(respond):
        return await respond(text, formatting_entities=entities)
    # Fake/minimal events in the test suite may only implement reply().
    reply = getattr(event, "reply", None)
    if callable(reply):
        return await reply(text, formatting_entities=entities)
    return await bot.client.send_message(
        chat_id,
        text,
        formatting_entities=entities,
    )


async def handle_command(bot, event, chat_id, user_id, sender, text: str) -> bool:
    """Handle ``کپی بورد`` or ``کپی``. Return True when consumed."""
    command = str(text or "").strip()
    if command not in COMMANDS:
        return False

    if getattr(event, "is_private", False):
        await _reply(event, "❌ قابلیت کپی بورد فقط داخل گروه فعال است.")
        return True

    if not _authorized(chat_id, user_id, sender):
        await _reply(
            event,
            "❌ فقط مالک ثبت‌شده یا ادمین ربات اجازه استفاده از کپی بورد را دارد.",
        )
        return True

    if command == COPYBOARD_COMMAND:
        sent = await _reply(event, GUIDE_TEXT, build_guide_entities())
        sent_id = getattr(sent, "id", None) if sent is not None else None
        # The exact message ID is the security boundary: a later message must
        # reply to this guide, not merely to any bot message.
        if sent_id is not None:
            clipboard_storage.set_pending_guide(chat_id, sent_id)
        else:
            bot.logger.log_error(
                "CLIPBOARD GUIDE SENT WITHOUT MESSAGE ID "
                f"chat_id={chat_id} user_id={user_id}"
            )
        return True

    record = clipboard_storage.get(chat_id)
    if record is None:
        await _reply(event, "❌ هنوز متنی برای کپی ذخیره نشده است.")
        return True

    try:
        await _send_clipboard(bot, event, chat_id, record)
    except Exception as error:
        bot.logger.log_error(
            "CLIPBOARD SEND FAILED "
            f"chat_id={chat_id} user_id={user_id} error={error!r}"
        )
        await _reply(event, "❌ ارسال متن کپی بورد ناموفق بود.")
    return True


async def handle_reply_save(bot, event, chat_id, user_id, sender, text: str) -> bool:
    """Save only a valid authorized reply to the latest guide message."""
    if getattr(event, "is_private", False):
        return False
    pending_id = clipboard_storage.get_pending_guide(chat_id)
    if pending_id is None or _reply_id(event) != pending_id:
        return False
    if not _authorized(chat_id, user_id, sender):
        # A normal user replying to the guide must never alter the group
        # clipboard; leave the guide pending for an authorized operator.
        return False

    ok, reason = clipboard_storage.save(
        chat_id,
        text,
        _message_entities(event),
    )
    if not ok:
        await _reply(event, reason or "❌ این متن قابل ذخیره نیست.")
        return True

    clipboard_storage.clear_pending_guide(chat_id)
    await _reply(event, "✅ متن کپی بورد با موفقیت ذخیره شد.")
    return True
