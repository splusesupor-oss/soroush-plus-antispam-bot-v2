"""Central feature entitlement policy for the free edition.

The default plan is intentionally fail-closed: an unset or unknown plan gets
only the features explicitly marked ``free`` below.  To re-enable the paid
features later, configure ``SOROUSH_BOT_PLAN=premium`` (or extend
``PLAN_FEATURES``) rather than removing execution guards from handlers.

This module is deliberately independent of bot/client imports so command
routing, service-level guards, callbacks, and tests can share one policy.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Optional

PAYWALL_MESSAGE = "این قابلیت در نسخه رایگان فعال نمی‌باشد"

# Canonical entitlement registry.  Features not listed as free are premium.
FEATURES = {
    "game_list": {"free": True, "description": "نمایش فهرست بازی‌ها"},
    "games": {"free": False, "description": "شروع و اجرای بازی‌ها"},
    "warning_settings": {"free": False, "description": "تغییر آستانه اخطار"},
    "punishment_settings": {"free": False, "description": "تغییر حالت مجازات"},
    "notice_ttl_delete": {"free": False, "description": "حذف اعلان‌ها پس از ۶۰ ثانیه"},
    "clipboard": {"free": True, "description": "کپی‌بورد"},
    "ai": {"free": True, "description": "دستیار و دستورات هوش مصنوعی"},
    "admin_log_view": {"free": False, "description": "مشاهده لاگ مدیریتی"},
    "unban_by_username": {"free": False, "description": "آزادسازی با یوزرنیم"},
    "bulk_delete_over_500": {"free": False, "description": "پاک بیش از ۵۰۰ پیام"},
    "auto_cleanup": {"free": False, "description": "پاکسازی خودکار زمان‌بندی‌شده"},
    "vip": {"free": False, "description": "مدیریت VIP"},
    "search": {"free": True, "description": "جستجوی مطالب و آهنگ"},
    "font_creation": {"free": True, "description": "ساخت فونت"},
    # Explicitly preserved free routes.
    "bulk_delete_up_to_500": {"free": True, "description": "پاک ۱ تا ۵۰۰"},
    "unban_by_reply": {"free": True, "description": "آزادسازی با ریپلای"},
}

PREMIUM_PLANS = frozenset({"premium", "pro", "paid", "full"})
PLAN_FEATURES = {
    "free": frozenset(name for name, meta in FEATURES.items() if meta["free"]),
    "premium": frozenset(FEATURES),
}

# Unknown plan names deliberately behave as free.
PLAN = os.getenv("SOROUSH_BOT_PLAN", "free").strip().lower() or "free"

_NORMALIZE_MAP = str.maketrans({
    "\u200c": " ",  # ZWNJ → space, matching the runtime command router
    "\u200f": "",
    "\u200e": "",
    "\ufeff": "",
    "\u00a0": " ",
    "\u064a": "\u06cc",  # Arabic ي → Persian ی
    "\u0643": "\u06a9",  # Arabic ك → Persian ک
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})


def normalize(text: object) -> str:
    """Normalize text like the real command router, including Persian digits."""
    return " ".join(str(text or "").translate(_NORMALIZE_MAP).split())


def _strip_leading_decoration(text: str) -> str:
    """Allow visible button labels such as «🧹 پاکسازی خودکار» to match."""
    value = text.strip()
    while value:
        category = unicodedata.category(value[0])
        if value[0].isspace() or category[0] in {"S", "P"}:
            value = value[1:].lstrip()
            continue
        break
    return value


def current_plan() -> str:
    """Return the configured plan, treating unknown values as free."""
    value = str(PLAN or "free").strip().lower()
    return "premium" if value in PREMIUM_PLANS else "free"


def is_enabled(feature: str) -> bool:
    """Whether ``feature`` is available under the current plan."""
    if feature not in FEATURES:
        return False
    return feature in PLAN_FEATURES[current_plan()]


def parse_bulk_delete_count(text: object):
    """Return ``(status, count)`` for the real «پاک N» route.

    ``status`` is ``free`` for 1..500, ``premium`` above 500, and ``invalid``
    for zero, negatives, malformed input, or unsafe integer conversion.
    """
    command = _strip_leading_decoration(normalize(text))
    match = re.fullmatch(r"پاک\s+([+-]?[0-9]+)", command)
    if not match:
        return "invalid", None
    try:
        count = int(match.group(1))
    except (ValueError, OverflowError):
        return "invalid", None
    if count < 1:
        return "invalid", count
    if count > 500:
        return "premium", count
    return "free", count


def feature_for_text(text: object) -> Optional[str]:
    """Identify a listed paid command using names present in the live code.

    The game command set is sourced at call time from the existing game guard,
    not copied here, so new game aliases added there are licensed automatically.
    """
    command = _strip_leading_decoration(normalize(text))
    if not command:
        return None

    # The actual list handler has these aliases; none may be paywalled.
    if command in {"لیست بازی", "لیست بازی ها", "بازی ها"}:
        return None

    try:
        from modules.entertainment_control import is_game_command
        if is_game_command(command):
            return "games"
    except Exception:
        # A failure to import the game registry must not accidentally broaden
        # access; the specific game routes retain their own independent guard.
        pass

    if command in {"کپی بورد", "کپی"}:
        return "clipboard"

    if command in {"تغییر اخطار"}:
        return "warning_settings"
    if command == "تغییر مجازات":
        return "punishment_settings"

    if command == "پاکسازی خودکار":
        return "auto_cleanup"

    if command in {"vip", "لغو vip", "لیست vip"}:
        return "vip"

    if command == "لاگ مدیریتی":
        return "admin_log_view"

    if command.startswith("آزاد ") or command.startswith("آزاد@"):
        # The actual handler resolves every non-empty argument as a username;
        # exact «آزاد» (with reply) remains the free path.
        return "unban_by_username"

    delete_status, _delete_count = parse_bulk_delete_count(command)
    if delete_status == "premium":
        return "bulk_delete_over_500"

    if command == "جستجو" or command.startswith("جستجو "):
        return "search"

    if command == "فونت" or command.startswith("فونت "):
        return "font_creation"

    # These are the exact AI/admin command forms handled by
    # _handle_google_search_group_message in handlers/message_handler.py.
    if command in {
        "هوش مصنوعی فعال", "هوش مصنوعی خاموش", "لیست هوش مصنوعی",
        "مجاز", "غیرمجاز", "غیر مجاز",
    } or command.startswith(("مجاز @", "غیرمجاز @", "غیر مجاز @")):
        return "ai"

    return None


def _reply_id(event) -> Optional[int]:
    message = getattr(event, "message", None)
    nested = getattr(message, "reply_to", None)
    value = (
        getattr(message, "reply_to_msg_id", None)
        or getattr(nested, "reply_to_msg_id", None)
        or getattr(nested, "reply_to_top_id", None)
        or getattr(event, "reply_to_msg_id", None)
        or getattr(getattr(event, "reply_to", None), "reply_to_msg_id", None)
    )
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def feature_for_event(text: object, event, chat_id=None, user_id=None) -> Optional[str]:
    """Identify command and stateful follow-up routes before they execute."""
    feature = feature_for_text(text)
    if feature:
        return feature

    # A reply to the exact pending guide invokes the clipboard save operation
    # even though the reply text itself is arbitrary.
    if not getattr(event, "is_private", False) and not is_enabled("clipboard"):
        try:
            from modules.clipboard_storage import get_pending_guide
            pending_id = get_pending_guide(chat_id)
            reply_id = _reply_id(event)
            if pending_id is not None and reply_id == int(pending_id):
                return "clipboard"
        except (ImportError, TypeError, ValueError):
            pass

    # Stop stale in-memory multi-step conversations too. Durable settings are
    # deliberately untouched; only their transient, non-persistent prompts are
    # invalidated so a bare confirmation cannot mutate a paid setting.
    if not is_enabled("warning_settings"):
        try:
            from modules import warning_threshold
            if warning_threshold.has_pending(chat_id, user_id):
                return "warning_settings"
        except Exception:
            pass
    if not is_enabled("punishment_settings"):
        try:
            from modules import punishment_mode
            if punishment_mode.has_pending(chat_id, user_id):
                return "punishment_settings"
        except Exception:
            pass
    if not is_enabled("auto_cleanup"):
        try:
            from modules import admin_tools
            pending = admin_tools._PENDING_CLEANUP.get(chat_id)
            if pending and str(pending.get("user_id")) == str(user_id):
                return "auto_cleanup"
        except Exception:
            pass

    return None


def feature_for_callback(data: object) -> Optional[str]:
    """Classify a callback payload when a callback carries an actual command.

    There are currently no paid callback routes registered in the live source;
    comparing against real textual commands still future-proofs the shared
    callback dispatcher without inventing callback-data names.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="ignore")
    return feature_for_text(data)


def premium_feature_message(feature: str) -> str:
    """Consistent UI response. Kept centralized for future plan changes."""
    return PAYWALL_MESSAGE if feature in FEATURES else PAYWALL_MESSAGE
