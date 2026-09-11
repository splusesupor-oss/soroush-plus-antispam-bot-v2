import asyncio as _asyncio
from collections import Counter, deque
from datetime import date
import os
import time

from modules.fill_blank import check_fill, get_token as get_fill_token
from modules.riddles import check_answer
from modules.group_stats import add_message, get_stats
from modules.group_storage import activate_group, deactivate_group, is_active
from modules.owner_check import get_owner, is_global_owner
from modules.spam_history import save_history_message
from modules.spam_history import is_repeat
from modules.fill_blank import (
    TIMEOUT as FILL_TIMEOUT,
    clear as clear_fill,
    get_fill_answer,
    get_token as get_fill_token,
    new_fill,
)
from modules.riddles import (
    RIDDLE_TIMEOUT,
    clear as clear_riddle,
    get_answer,
    get_token as get_riddle_token,
    new_riddle,
)
from modules.multiple_choice import (
    ANSWER_SECONDS as QUIZ_SECONDS,
    EXHAUSTED_MESSAGE as QUIZ_EXHAUSTED_MESSAGE,
    answer_question,
    clear_question,
    get_active_question,
    is_exhausted as quiz_exhausted,
    start_question,
)
from modules.user_original_storage import (
    begin_registration,
    is_waiting_for_original,
    save_original,
    get_original,
)
from modules.jokes import get_joke
from modules.biographies import get_biography
from modules.simple_replies import SIMPLE_REPLIES, INSULTS, INSULT_REPLY
from modules.word_correction import start as start_correction, answer as answer_correction, get as get_correction, clear as clear_correction
from handlers.fox_games_router import (
    FOX_GAME_COMMANDS,
    any_active as fox_game_active,
    handle as handle_fox_games,
)
from modules import who_knows as _who_knows
from modules import truth_or_lie as _truth_lie
# 📥 قابلیت مستقل «دانلود عکس».
from handlers.photo_download_handler import handle as handle_photo_download
# ⏳ تاریخ انقضای گروه — قابلیتی کاملاً مستقل با مسیر پردازش جدا.
from handlers.group_expiry_handler import (
    EXPIRED_NOTICE as GROUP_EXPIRED_NOTICE,
    blocks_message as group_expiry_blocks,
    handle as handle_group_expiry,
)
from modules.expiry_report import build_group_list
from modules.name_family import (
    cancel_round as cancel_name_family_round,
    finish as finish_name_family,
    is_active as name_family_active,
    schedule_round as schedule_name_family_round,
    start as start_name_family,
    submit as submit_name_family,
)
from modules.emoji_guess import (
    ANSWER_SECONDS as EMOJI_GUESS_SECONDS,
    REWARD_BRONZE as EMOJI_REWARD_BRONZE,
    EXHAUSTED_MESSAGE as EMOJI_GUESS_EXHAUSTED_MESSAGE,
    total_stages as _emoji_total_stages,
    answer as answer_emoji_guess,
    finish as finish_emoji_guess,
    is_active as emoji_guess_active,
    is_exhausted as emoji_guess_exhausted,
    reset_user as emoji_guess_reset,
    start as start_emoji_guess,
)
from modules.flag_guess import (
    get_active as get_flag_guess,
    EXHAUSTED_MESSAGE as FLAG_GUESS_EXHAUSTED_MESSAGE,
    answer as answer_flag_guess,
    finish as finish_flag_guess,
    is_active as flag_guess_active,
    is_exhausted as flag_guess_exhausted,
    start as start_flag_guess,
)
from economy import name_filter
from modules.group_memory import extract_name, friendly_reply, get_name as get_memory_name, remove_name as remove_memory_name, set_name as set_memory_name
from modules.group_rules import begin as begin_rules, cancel as cancel_rules, format_rules, remove as remove_rules, save as save_rules, waiting as waiting_rules
from modules.name_insights import report as name_personality_report
from modules.did_you_know import get_fact
from modules.user_activity import record as record_activity, get as get_activity
from modules.reminders import begin as begin_reminder, waiting as waiting_reminder, capture as capture_reminder
from modules.translation import begin as begin_translation, waiting as waiting_translation, clear as clear_translation, translate_to_persian
# 💰 اقتصاد: تنها از راه API عمومی. هیچ دسترسی مستقیمی به دیتابیس نیست.
import economy
from economy import directory as username_directory
from economy import (
    get_profile as get_coin_profile,
    get_rank as coin_rank,
    leaderboard as coin_leaderboard,
    record_message as record_coin_message,
)
from handlers.economy_handler import handle as handle_economy
from modules.gif_spam_detector import (
    handle_gif as handle_gif_message,
    flush_deletes as flush_gif_deletes,
    is_gif_message,
    pending_count as gif_pending_count,
    reset_gif_history,
    track_gif,
)
from modules.group_stats import add_kick, add_mute, make_report, add_deleted_count
from modules.spam_history import get_message_ids, get_user_history, clear_user
from modules.web_search import can_search, search_web
from modules.jorat_haghighat import get_jorat, get_haghighat
from modules.font_converter import make_fonts
from modules.admin_storage import add_admin, remove_admin, is_admin, load_admins
from modules.banned_storage import add_banned, load_banned, save_banned, is_banned
from modules.removed_users_reset import reset_system_removed_users
from modules.group_storage import set_group_owner, get_group_owner, remove_group_owner
from modules.owner_greetings import registered_owner_greeting_response
from modules.group_id import normalize_group_id
from modules.pinned_messages import save as save_pinned_message, get as get_pinned_message
from modules.performance import MessagePerformance
from modules.outgoing_profiler import (
    begin_response_measurement,
    end_response_measurement,
    response_rpc_ms,
)
from handlers.admin_handler import handle_admin_commands
from modules import admin_tools
# 🎮 روشن/خاموش کردن بازی‌های داخلی به تفکیک گروه (storage و گارد خالص).
from modules import entertainment_control
from modules.group_dispatch import PRIORITY_ADMIN, classify_priority
# 🗂 سیستم سابقه‌ها و 🏆 سطح گروه — دو قابلیتِ مستقل با فایل و ماژولِ جدا.
from modules import user_history
from modules import group_level
from modules import bot_detector
from modules import ad_name_detector
from modules import warning_threshold
from modules import punishment_mode
from modules.user_display import format_user
from modules import message_tracker
from modules import big_spam
from modules import search_access
from modules import web_search, wiki_search_service
from modules.notice_cleanup import capture_sent
try:
    from splusthon.tl.types import MessageEntityBold, MessageEntityBlockquote
    from splusthon.tl import functions
    from splusthon import Button, types
except ImportError:
    class MessageEntityBold:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length
    class MessageEntityBlockquote:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length
    class Button:
        pass
    from types import SimpleNamespace
    types = SimpleNamespace()
    functions = SimpleNamespace()


def _resolved_event_peer(event):
    """Read an already-resolved InputPeer from an event without any RPC."""
    message = getattr(event, "message", None)
    for owner in (message, event):
        if owner is None:
            continue
        for attr in ("_input_chat", "input_chat"):
            try:
                peer = getattr(owner, attr, None)
            except Exception:
                peer = None
            if peer is not None:
                return peer
    return None


def _warm_reply_input_chat(bot, event, chat=None):
    """Retain an event's resolved InputPeer for replies and later RPCs.

    A cached InputPeer makes ``Message.reply`` skip SPlusthon's expensive
    ``iter_dialogs(100)`` fallback. Delete workers also reuse it so a positive
    Soroush group ID is not misclassified as a user and resolved through a
    failing ``GetUsersRequest``. The cache stays bounded for long runtimes.
    """
    message = getattr(event, "message", None)
    if message is None:
        return False
    chat_id = getattr(event, "chat_id", None)
    cache = getattr(bot, "reply_input_peer_cache", None)
    if cache is None:
        cache = bot.reply_input_peer_cache = {}

    # Many SPlusthon events already contain the best access-hash-bearing peer.
    # The former early return left that peer on the message only, so background
    # delete/notice workers later fell back to an ambiguous positive integer.
    input_chat = _resolved_event_peer(event)
    if input_chat is None:
        input_chat = cache.get(chat_id)
    if input_chat is None:
        wanted = normalize_group_id(chat_id)
        for cached_id, peer in list(cache.items()):
            if peer is not None and normalize_group_id(cached_id) == wanted:
                input_chat = peer
                break
    if input_chat is None and chat is not None:
        try:
            from splusthon import utils
            input_chat = utils.get_input_peer(chat)
        except Exception:
            input_chat = None
    if input_chat is None:
        return False

    message._input_chat = input_chat
    cache[chat_id] = input_chat
    while len(cache) > 500:
        cache.pop(next(iter(cache)), None)
    return True


def _message_debug_enabled(bot):
    cfg = getattr(bot, "config_manager", None)
    if cfg is None:
        return False
    return bool(cfg.get("debug_message_pipeline", False))


def _debug_log(bot, message):
    """Keep detailed per-message diagnostics opt-in, not hot-path INFO."""
    if _message_debug_enabled(bot):
        bot.logger.log_info(message)


def _send_spam_cleanup_notice(trigger):
    """Only genuine anti-spam detections may show the spam cleanup notice.

    Content filters intentionally share deletion/moderation plumbing with spam,
    but their own warning is the only user-facing notice they should produce.
    """
    return trigger == "spam"


def _detector_moderation_trigger(reason):
    """Separate content/link filters from genuine spam-wave notifications."""
    value = str(reason or "")
    if "spam_banned_word" in value:
        return "spam"
    if (
        value.startswith("banned_word")
        or value.startswith("کلمه ممنوعه (")
        or "کلمه ممنوعه (" in value
        or value.startswith("لینک مشکوک (")
    ):
        return "filter_group"
    return "spam"


def _math_digits(value):
    """نمایش عدد فقط برای متن اعلان‌ها، بدون تغییر مقدار منطقی."""
    return str(value).translate(str.maketrans("0123456789", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"))


def _fullwidth_digits(value):
    """فونت شمارندهٔ پیام‌های پاک‌شده، فقط برای پیام‌های cleanup."""
    return str(value).translate(str.maketrans("0123456789", "０１２３４５６７８９"))


def _jalali_today():
    """تاریخ امروز ایران در تقویم جلالی، بدون وابستگی خارجی."""
    gy, gm, gd = date.today().year, date.today().month, date.today().day
    g_days = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
        + (gy2 + 399) // 400 + gd + g_days[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def _format_group_member(user):
    return format_user(user)


async def _group_main_owner_display(bot, chat, fallback_user=None, chat_id=None):
    """نام نمایشی مالک اصلیِ خودِ گروه (سازندهٔ گروه در سروش).

    در این نسخهٔ SPlusthon entityِ Chat فاقد fieldِ owner_id است؛ سازندهٔ
    گروه اولین itemِ get_participants است (TL: chatParticipantCreator) و
    به‌عنوان User کامل برمی‌گردد. اگر شناسایی/دریافت نشد، به فرستندهٔ
    دستور (fallback_user) برمی‌گردد تا خطِ «مالک اصلی» هرگز خالی نماند.
    هر دو شاخه در لاگ ثبت می‌شود (GROUP OWNER IDENTIFIED / FALLBACK).
    """
    _logger = getattr(bot, "logger", None)

    def _log(message):
        try:
            if _logger is not None:
                _logger.log_info(message)
        except Exception:
            pass

    try:
        participants = await bot.client.get_participants(chat, limit=1)
        if participants:
            owner_user = participants[0]
            if owner_user is not None:
                _log(
                    "GROUP OWNER IDENTIFIED "
                    f"chat_id={chat_id} owner_id={getattr(owner_user, 'id', None)} "
                    f"username={getattr(owner_user, 'username', None)!r}")
                return format_user(owner_user)
        _log(f"GROUP OWNER FALLBACK chat_id={chat_id} reason=participants_empty")
    except Exception as error:
        _log(f"GROUP OWNER FALLBACK chat_id={chat_id} reason={error!r}")
    return format_user(fallback_user)


def _format_admin_display(user):
    return format_user(user)


async def _reward_game_reply(event, chat_id, user_id, user, game,
                             reference=None, amount=None):
    """جایزهٔ بازی را با نوع سکهٔ درست پرداخت و موجودی را اعلام می‌کند.

    نوع سکه از ``economy.rewards`` می‌آید: بازی عادی برنز، بازی سخت نقره.
    """
    from economy import rewards as _rewards
    coin_type = _rewards.coin_for(game)
    paid = _rewards.amount_for(game) if amount is None else int(amount)

    # موجودی «قبل» را می‌خوانیم تا بتوانیم بفهمیم پرداخت واقعاً انجام
    # شده یا دفتر تراکنش آن را تکراری دیده است.
    before = economy.get_balance(chat_id, user_id)[coin_type]
    economy.award_game(
        chat_id, user_id, game, reference=reference, amount=amount,
        name=_format_admin_display(user),
    )
    # موجودی از دیتابیس دوباره خوانده می‌شود، نه از مقدار کش‌شده.
    balance = economy.get_balance(chat_id, user_id)
    gained = balance[coin_type] - before

    coin_label = _rewards.coin_name(coin_type)
    icon = "🥈" if coin_type == economy.SILVER else "🥉"

    if gained <= 0:
        # هرگز نباید «+n سکه» بگوییم وقتی چیزی اضافه نشده. اگر اینجا
        # رسیدیم یعنی مرجع تکراری بوده و جایزهٔ این دور قبلاً پرداخت شده.
        bot_logger = getattr(event, "_bot_logger", None)
        if bot_logger is not None:
            bot_logger.log_error(
                f"REWARD NOT APPLIED game={game} chat_id={chat_id} "
                f"user_id={user_id} reference={reference!r}"
            )
        await event.reply(
            "🎉 پاسخ صحیح بود.\n\n"
            "🪙 جایزهٔ این دور قبلاً به حساب شما اضافه شده است.\n\n"
            f"💰 موجودی {coin_label}:\n{icon} "
            f"{_math_digits(balance[coin_type])}\n\n"
            f"💎 ارزش کل:\n{_math_digits(balance['total_coin_value'])}"
        )
        return balance

    await event.reply(
        "🎉 پاسخ صحیح بود.\n\n"
        f"🪙 شما +{_math_digits(gained)} سکه {coin_label} دریافت کردید.\n\n"
        f"💰 موجودی {coin_label}:\n{icon} {_math_digits(balance[coin_type])}\n\n"
        f"💎 ارزش کل:\n{_math_digits(balance['total_coin_value'])}"
    )
    return balance


def _format_banned_user(user, user_id):
    # ``user_id`` is intentionally not a display fallback.
    return format_user(user)


_FORWARD_HEADER_FIELDS = (
    "fwd_from",
    "forward",
    "forward_from",
    "forward_chat",
    "forward_from_chat",
    "forward_sender_name",
    "fwd_from_id",
    "forward_from_id",
    "forward_date",
)
_FORWARD_FLAG_FIELDS = ("is_forward", "forwarded")
_FORWARD_ALBUM_TTL = 30


def _forward_header_present(value):
    """True for a real header object. False for None / False / empty."""
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return False
    if isinstance(value, (str, bytes)) and not value:
        return False
    return True


def _get_forward_metadata(message, event=None):
    """Detect a forwarded message across SPlusthon / Soroush field names.

    ``fwd_from`` is the official header, but some Soroush updates only fill
    ``forward`` or a Pyrogram-style name.  Use ``is not None`` for headers
    so an empty-looking MessageFwdHeader still counts.  Never treat the
    integer ``forwards`` view-count as a forward.
    """
    fields = {}
    sources = []
    if message is not None:
        sources.append(message)
    if event is not None and event is not message:
        sources.append(event)
    for obj in sources:
        for field in _FORWARD_HEADER_FIELDS:
            value = getattr(obj, field, None)
            fields.setdefault(field, value)
            if _forward_header_present(value):
                return True, field, fields
        for field in _FORWARD_FLAG_FIELDS:
            value = getattr(obj, field, None)
            fields.setdefault(field, value)
            if value is True:
                return True, field, fields
    return False, None, fields


def _album_forward_ids(bot, chat_id, message, is_forward):
    """Collect IDs for this item and any earlier album siblings.

    Soroush sometimes puts ``fwd_from`` on only one item of a grouped
    album.  Remember the group briefly so a later tagged item can delete
    the siblings that already arrived, and later untagged items are
    still treated as the same forward.
    """
    message_id = getattr(message, "id", None)
    grouped_id = getattr(message, "grouped_id", None)
    if not isinstance(message_id, int) or message_id <= 0:
        return set()
    if grouped_id is None:
        return {message_id} if is_forward else set()
    cache = getattr(bot, "_forward_albums", None)
    if cache is None:
        cache = bot._forward_albums = {}
    now = time.monotonic()
    key = (normalize_group_id(chat_id), grouped_id)
    row = cache.get(key)
    if row is None or row["expires"] <= now:
        row = {"ids": set(), "is_forward": False, "expires": now + _FORWARD_ALBUM_TTL}
        cache[key] = row
    row["ids"].add(message_id)
    if is_forward:
        row["is_forward"] = True
    row["expires"] = now + _FORWARD_ALBUM_TTL
    if len(cache) > 500:
        cache.pop(next(iter(cache)), None)
    if row["is_forward"]:
        return set(row["ids"])
    return set()


def _handle_forwarded_group_message(
    bot, event, chat_id, user_id, sender, sender_username, *,
    is_forwarded, forward_field, forward_fields, delete_ids,
):
    """Queue delete for a single forward / album wave. Mute after three."""
    bot.logger.log_info(
        "FORWARD DETECTED "
        f"user_id={user_id} username={sender_username} "
        f"forward_field={forward_field} fields={forward_fields}"
    )
    deleted = False
    forward_key = (chat_id, user_id)
    forward_count = getattr(bot, "forward_spam_counts", {}).get(
        forward_key, 0
    ) + 1
    bot.forward_spam_counts[forward_key] = forward_count
    bot.touch_temporary_state("forward", forward_key)
    try:
        ids = {
            message_id for message_id in (delete_ids or ())
            if isinstance(message_id, int) and message_id > 0
        }
        current_id = getattr(getattr(event, "message", None), "id", None)
        if isinstance(current_id, int) and current_id > 0:
            ids.add(current_id)
        if ids:
            _queue_message_deletes(bot, chat_id, ids)
            deleted = True
        if forward_count >= 3:
            processing = getattr(bot, "forward_spam_processing", set())
            if forward_key not in processing:
                if not hasattr(bot, "forward_spam_processing"):
                    bot.forward_spam_processing = set()
                bot.forward_spam_processing.add(forward_key)

                async def forward_mute_finished(_result):
                    try:
                        await _send_moderation_notification_once(
                            bot, chat_id, user_id, "forward_spam_mute",
                            getattr(event.message, "id", None),
                            "🔸کاربر ← "
                            f"{_format_banned_user(sender, user_id)}\n\n"
                            "به دلیل ارسال فوروارد تکراری 𝟮𝟰 ساعت سکوت شد",
                        )
                    finally:
                        bot.forward_spam_counts.pop(forward_key, None)
                        bot.forward_spam_processing.discard(forward_key)

                async def forward_mute_failed(_error):
                    bot.forward_spam_counts.pop(forward_key, None)
                    bot.forward_spam_processing.discard(forward_key)

                bot.moderation_queue.enqueue(
                    chat_id,
                    "auto_mute",
                    user_id=user_id,
                    timeout_seconds=15,
                    operation=lambda: bot.admin_actions.mute_user(
                        chat_id, user_id, 24 * 60 * 60, user=sender,
                    ),
                    on_success=forward_mute_finished,
                    on_failure=forward_mute_failed,
                )
    finally:
        bot.logger.log_info(
            "FORWARD DETECTED "
            f"user_id={user_id} username={sender_username} "
            f"forward_field={forward_field} deleted={deleted} "
            f"forward_count={forward_count}"
        )
    return True


def _log_ban_execution(bot, chat_id, user_id, reason):
    punish_key = _punishment_key(chat_id, user_id)
    _debug_log(
        bot,
        "BAN EXECUTION DEBUG\n"
        f"chat_id={chat_id}\n"
        f"user_id={user_id}\n"
        f"reason={reason}\n"
        f"already_punished={punish_key in bot.punished_users}\n"
        f"will_ban={punish_key not in bot.punished_users}",
    )


async def _send_moderation_notification_once(
    bot, chat_id, user_id, action, source_message_id, text,
    formatting_entities=None,
):
    key = (chat_id, user_id, action, source_message_id)
    if not hasattr(bot, "moderation_notification_guard"):
        bot.moderation_notification_guard = set()
        bot.moderation_notification_order = deque(maxlen=1000)
    if key in bot.moderation_notification_guard:
        return False

    if len(bot.moderation_notification_order) == bot.moderation_notification_order.maxlen:
        expired_key = bot.moderation_notification_order.popleft()
        bot.moderation_notification_guard.discard(expired_key)
    bot.moderation_notification_guard.add(key)
    bot.moderation_notification_order.append(key)
    try:
        # Use outgoing sender queue so this moderation notice does not block
        # the caller's worker (especially GroupDispatcher normal lane).
        sender = getattr(bot, "outgoing_sender", None)
        if sender is not None:
            def _factory1():
                return bot.client.send_message(chat_id, text, formatting_entities=formatting_entities)
            # Capture after real send completes, still via sender's worker
            def _on_done1(sent):
                capture_sent(bot, chat_id, sent)
            sender.enqueue(chat_id, _factory1, priority=1, on_done=_on_done1)
            return True
        sent = await bot.client.send_message(
            chat_id, text, formatting_entities=formatting_entities
        )
        capture_sent(bot, chat_id, sent)
        return True
    except Exception:
        bot.moderation_notification_guard.discard(key)
        raise


def _run_background(bot, name, callback, *args):
    """کارهای غیرامنیتیِ پس از پاسخ را از مسیر پیام جدا می‌کند."""
    async def run():
        try:
            callback(*args)
        except Exception as error:
            bot.logger.log_error(f"BACKGROUND {name} FAILED: {error}")
    return _asyncio.create_task(run(), name=f"bg:{name}")


def _schedule_reply(bot, event, *args, **kwargs):
    """Send a reply without holding this group's dispatcher worker on RPC RTT."""
    async def run():
        try:
            await event.reply(*args, **kwargs)
        except Exception as error:
            logger = getattr(bot, "logger", None)
            if logger is not None:
                logger.log_error(f"SCHEDULED REPLY FAILED error={error!r}")
    return _asyncio.create_task(
        run(), name=f"reply:{getattr(event, 'chat_id', None)}")


def is_game_answer_active(chat_id, user_id):
    """Cheap in-memory guard for answers that must bypass generic flood rules."""
    return bool(
        name_family_active(chat_id)
        or fox_game_active(chat_id)
        or emoji_guess_active(chat_id, user_id)
        or flag_guess_active(chat_id)
        or get_correction(chat_id) is not None
        or get_active_question(chat_id) is not None
        or get_fill_token(chat_id, user_id) is not None
        or get_riddle_token(chat_id, user_id) is not None
        or _who_knows.is_active(chat_id)
        or _truth_lie.is_active(chat_id)
    )


def _chat_game_busy(chat_id):
    """آیا یکی از بازی‌های «چت‌محور» همین حالا در این گروه فعال است.

    این بازی‌ها state خود را با کلید chat_id نگه می‌دارند، پس اجرای دوبارهٔ
    دستور، دور قبلی را بازنویسی و خراب می‌کرد. بازی‌های کاربرمحور (چیستان،
    جای خالی و حدس ایموجی) عمداً در این فهرست نیستند؛ آن‌ها با کلید
    (chat_id, user_id) کار می‌کنند و چند کاربر می‌توانند هم‌زمان بازی کنند.
    """
    return (
        name_family_active(chat_id)
        or flag_guess_active(chat_id)
        or get_correction(chat_id) is not None
        or get_active_question(chat_id) is not None
        or _who_knows.is_active(chat_id)
        or _truth_lie.is_active(chat_id)
    )


GAME_BUSY_MESSAGE = "⏳ یک بازی دیگر در این گروه در جریان است؛ لطفاً تا پایان آن صبر کنید."


EMOJI_GUESS_TOTAL = _emoji_total_stages()

# فقط این دستورها اجازهٔ ریست کردن پیشرفت را دارند.
EMOJI_RESET_COMMANDS = {
    "شروع دوباره حدس ایموجی",
    "ریست حدس ایموجی",
}


def puzzle_token_for(chat_id, user_id=None):
    """توکن معمای فعال همین کاربر (برای لاگ و مرجع)."""
    import modules.emoji_guess as _eg
    state = _eg.active_state(chat_id, user_id) if user_id is not None else None
    return state["token"] if state else 0


def _track_group_timer(bot, chat_id, task):
    if not hasattr(bot, "group_timer_tasks"):
        bot.group_timer_tasks = {}
    tasks = bot.group_timer_tasks.setdefault(chat_id, set())
    tasks.add(task)

    def discard_finished_task(completed_task):
        tasks.discard(completed_task)
        if not tasks:
            bot.group_timer_tasks.pop(chat_id, None)

    task.add_done_callback(discard_finished_task)
    return task


def _spam_runtime_key(chat_id, user_id):
    """Canonical in-memory key across full and short SPlus channel IDs."""
    return normalize_group_id(chat_id), str(user_id)


def _punishment_key(chat_id, user_id):
    group_id, member_id = _spam_runtime_key(chat_id, user_id)
    return f"{group_id}:{member_id}"


def finalize_spam_wave(chat_id, user_id, requested, deleted, remaining):
    """Clear both spam histories only after complete cleanup."""
    if remaining or deleted != requested:
        return False
    message_tracker.clear_user_history(chat_id, user_id)
    clear_user(chat_id, user_id)
    return True


def _is_true_auto_spam_text(bot, chat_id, text):
    """Keep content-filter deletions out of the automatic spam sweep."""
    if not str(text or "").strip():
        return False
    is_spam, reason = bot.detector.is_spam(str(text), chat_id)
    return is_spam and _detector_moderation_trigger(reason) == "spam"


_BIG_SPAM_MIN_CHARS = big_spam.LARGE_PAYLOAD_CHARS
_BIG_SPAM_REPEAT_WINDOW_SECONDS = big_spam.REPEAT_WINDOW_SECONDS
_BIG_SPAM_REPEAT_MESSAGES = big_spam.SIMILAR_MESSAGE_THRESHOLD


def _big_repeated_spam(chat_id, user_id, text):
    """Detect a promotional wave on the second similar message, or one packed box."""
    rows = message_tracker.get_user_recent_messages(chat_id, user_id)
    return big_spam.detect_big_spam(
        text, rows,
        allow_generic=not is_game_answer_active(chat_id, user_id),
    )


def _big_spam_incident(bot, key, seed_ids=()):
    """Create the bounded ID registry used only after big-spam detection."""
    try:
        key = _spam_runtime_key(key[0], key[1])
    except (TypeError, IndexError):
        pass
    incidents = getattr(bot, "_big_spam_incidents", None)
    if incidents is None:
        incidents = bot._big_spam_incidents = {}
    incident = incidents.get(key)
    if incident is None:
        sequence = getattr(bot, "_big_spam_incident_sequence", 0) + 1
        bot._big_spam_incident_sequence = sequence
        incident = incidents[key] = {
            "id": sequence,
            "ids": set(),
            "deleted_ids": set(),
            "retry_ids": set(),
            "retry_rounds": 0,
            "abandoned_ids": set(),
            "cleanup_task": None,
            "_touched_at": time.monotonic(),
            # Reopened incidents for an already-punished user can drain at
            # once. A newly queued ban changes this to ``pending`` below and
            # keeps the incident open until SPlus confirms the restriction.
            "ban_state": "confirmed",
        }
    else:
        incident["_touched_at"] = time.monotonic()
    incident["ids"].update(
        message_id for message_id in seed_ids
        if isinstance(message_id, int) and message_id > 0
    )
    # This registry exists only from fast detection until cleanup finishes.
    # Do not truncate its IDs: every captured message belongs to the wave.
    return incident


def _capture_big_spam_message(bot, chat_id, user_id, message_id):
    """Add every post-detection message ID before any later handler branch."""
    incidents = getattr(bot, "_big_spam_incidents", {})
    incident = incidents.get(_spam_runtime_key(chat_id, user_id))
    if incident is not None and isinstance(message_id, int) and message_id > 0:
        incident["ids"].add(message_id)


def _record_spam_ban_deletes(bot, event, chat_id, user_id, deleted_ids):
    """Accumulate unique deleted IDs for the one final ban notice."""
    key = _spam_runtime_key(chat_id, user_id)
    shared = _spam_cleanup_incident(bot, key, event)
    counted = shared.setdefault("counted_ids", set())
    counted.update(
        message_id for message_id in (deleted_ids or ())
        if isinstance(message_id, int) and message_id > 0
    )
    shared["deleted"] = len(counted)
    shared["ban_confirmed"] = True
    if event is not None:
        shared["event"] = event
    return shared


def _schedule_spam_ban_notice(bot, event, chat_id, user_id):
    """Send the ban notice once, after every in-flight cleanup stage finishes."""
    key = _spam_runtime_key(chat_id, user_id)
    shared = _spam_cleanup_incident(bot, key, event)
    shared["generation"] = shared.get("generation", 0) + 1
    my_gen = shared["generation"]

    async def run():
        try:
            await _asyncio.sleep(0)
            if shared.get("generation") != my_gen:
                return
            for _ in range(40):
                if shared.get("generation") != my_gen:
                    return
                big = getattr(bot, "_big_spam_incidents", {}).get(key)
                big_task = None if big is None else big.get("cleanup_task")
                auto_task = getattr(bot, "_auto_spam_cleanup_tasks", {}).get(key)
                me = _asyncio.current_task()
                big_busy = big_task is not None and not big_task.done()
                auto_busy = (
                    auto_task is not None
                    and not auto_task.done()
                    and auto_task is not me
                )
                if not big_busy and not auto_busy:
                    break
                await _asyncio.sleep(0)
            if shared.get("generation") != my_gen:
                return
            count = len(shared.get("counted_ids") or ())
            if count <= 0:
                return
            notice_event = shared.get("event") or event
            await _send_spam_ban_cleanup_notification(
                bot, notice_event, chat_id, user_id, count, "wave",
            )
        finally:
            if (
                shared.get("notice_task") is _asyncio.current_task()
                and shared.get("generation") == my_gen
            ):
                getattr(bot, "_spam_cleanup_incidents", {}).pop(key, None)

    task = _asyncio.create_task(run())
    shared["notice_task"] = task
    return task


async def _send_spam_ban_cleanup_notification(
        bot, event, chat_id, user_id, deleted_count, notice_id):
    """Send the one existing final ban/cleanup template for a completed wave."""
    ban_header = (
        "⚠️ کاربر ⏌ "
        f"{format_user(getattr(event, 'sender', None))}"
        " ⎾"
    )
    if punishment_mode.is_mute(chat_id):
        ban_action_line = "به دلیل هرزنامه سکوت دائم شد.\n"
    else:
        ban_action_line = "به دلیل هرزنامه از گروه اخراج شد.\n"
    ban_text = (
        f"{ban_header}\n\n"
        f"{ban_action_line}"
        f"🗑 {_fullwidth_digits(deleted_count)} پیام تکراری پاک شد"
    )
    return await _send_moderation_notification_once(
        bot, chat_id, user_id, "spam_ban_cleanup", "wave", ban_text,
        formatting_entities=[
            MessageEntityBlockquote(
                offset=0,
                length=len(ban_header.encode("utf-16-le")) // 2,
            )
        ],
    )


def _collect_big_spam_ids(chat_id, user_id, seed_ids=(), current_id=None):
    """Return only detector-selected/current IDs for this spam incident.

    The tracker intentionally retains up to 30 minutes for detection. Pulling
    its entire snapshot here made one new spam hit delete old, unrelated chat
    from the same user and inflated small incidents into dozens of delete RPCs.
    The detector supplies the initial wave; after creation, light ingest adds
    every later message directly to ``incident['ids']``.
    """
    collected = {
        message_id for message_id in (seed_ids or ())
        if isinstance(message_id, int) and message_id > 0
    }
    if isinstance(current_id, int) and current_id > 0:
        collected.add(current_id)
    return collected


async def _drain_big_spam_incident(bot, event, chat_id, user_id, incident):
    """Keep draining IDs added during cleanup; retain failed IDs for retry."""
    key = _spam_runtime_key(chat_id, user_id)
    while True:
        incident["ids"].update(_collect_big_spam_ids(chat_id, user_id))
        pending = (
            set(incident["ids"])
            - set(incident["deleted_ids"])
            - set(incident.get("abandoned_ids", ()))
        )
        if pending:
            remaining = set()
            # Any pending count is deleted now. 100 is only the RPC max.
            for chunk in big_spam.chunk_ids(pending, big_spam.DELETE_BATCH_MAX):
                queue = getattr(bot, "message_delete_queue", None)
                rpc_peer = incident.get("rpc_peer")
                if queue is not None and rpc_peer is not None:
                    _deleted, leftover = await queue.enqueue(
                        chat_id, chunk, rpc_peer=rpc_peer,
                    )
                else:
                    _deleted, leftover = await cleanup_spam_messages(
                        bot, chat_id, user_id, chunk
                    )
                leftover = set(leftover)
                incident["deleted_ids"].update(set(chunk) - leftover)
                remaining.update(leftover)
            incident["retry_ids"] = remaining
            if remaining:
                incident["retry_rounds"] = int(incident.get("retry_rounds", 0)) + 1
                if incident["retry_rounds"] <= 3:
                    # Bounded incident-level retries. The queue itself already
                    # handles transient RPC retries, so an entity failure must
                    # never spin forever once per second.
                    await _asyncio.sleep(min(incident["retry_rounds"], 3))
                    continue
                incident.setdefault("abandoned_ids", set()).update(remaining)
                bot.logger.log_error(
                    "BIG SPAM DELETE UNRESOLVED "
                    f"chat_id={chat_id} user_id={user_id} "
                    f"remaining={len(remaining)} retries={incident['retry_rounds']}"
                )
            else:
                incident["retry_rounds"] = 0
            continue

        # Keep capturing/deleting while the permanent-ban RPC is in flight.
        # Previously a fast first delete could close the incident before a
        # slow (1–5s) ban completed; later burst messages then escaped the
        # light path and accumulated in the heavy handler queue.
        ban_state = incident.get("ban_state", "confirmed")
        if ban_state == "pending":
            deadline = incident.get("ban_deadline")
            now = _asyncio.get_running_loop().time()
            if deadline is not None and now >= deadline:
                # A per-chat moderation worker can legitimately queue several
                # different spammers. Do not expire this incident while its ban
                # job is still queued/running, but retain a hard five-minute
                # bound for a wedged worker or lost callback.
                moderation = getattr(bot, "moderation_queue", None)
                pending_key = (key[0], user_id, "ban")
                still_pending = pending_key in getattr(
                    moderation, "_pending_keys", set()
                )
                absolute = float(incident.get("ban_absolute_deadline", deadline))
                if still_pending and now < absolute:
                    incident["ban_deadline"] = min(now + 50.0, absolute)
                    await _asyncio.sleep(0.05)
                    continue
                incident["ban_state"] = "failed"
                bot.punished_users.discard(_punishment_key(chat_id, user_id))
                bot.clear_spam_lock(key)
                bot.logger.log_error(
                    "BIG SPAM BAN CALLBACK TIMEOUT "
                    f"chat_id={chat_id} user_id={user_id} "
                    f"still_pending={still_pending}"
                )
                continue
            await _asyncio.sleep(0.05)
            continue
        if ban_state == "failed":
            message_tracker.remove_message_ids(
                chat_id, user_id,
                set(incident["deleted_ids"]) | set(incident.get("abandoned_ids", ()))
            )
            getattr(bot, "_big_spam_incidents", {}).pop(key, None)
            return

        # Two event-loop turns close the race with received messages that had
        # already entered the handler when the ban succeeded.
        await _asyncio.sleep(0)
        incident["ids"].update(_collect_big_spam_ids(chat_id, user_id))
        if (
            set(incident["ids"])
            - set(incident["deleted_ids"])
            - set(incident.get("abandoned_ids", ()))
        ):
            continue
        await _asyncio.sleep(0)
        incident["ids"].update(_collect_big_spam_ids(chat_id, user_id))
        if (
            set(incident["ids"])
            - set(incident["deleted_ids"])
            - set(incident.get("abandoned_ids", ()))
        ):
            continue

        _record_spam_ban_deletes(
            bot, event, chat_id, user_id, incident["deleted_ids"],
        )
        # Do not leave completed or permanently-unresolvable IDs in the
        # 30-minute tracker. Reopening an incident used to retry every old ID,
        # turning one new spam message into a long batch of stale requests.
        message_tracker.remove_message_ids(
            chat_id, user_id,
            set(incident["deleted_ids"]) | set(incident.get("abandoned_ids", ()))
        )
        getattr(bot, "_big_spam_incidents", {}).pop(key, None)
        _schedule_spam_ban_notice(bot, event, chat_id, user_id)
        return


def _start_big_spam_cleanup(bot, event, chat_id, user_id, incident):
    """Drain recorded IDs immediately; do not wait for the ban RPC."""
    task = incident.get("cleanup_task")
    if task is not None and not task.done():
        return task
    task = _asyncio.create_task(
        _drain_big_spam_incident(bot, event, chat_id, user_id, incident)
    )
    incident["cleanup_task"] = task
    return task


def _queue_big_spam_ban(bot, event, chat_id, user_id, sender, seed_ids, reason):
    """Ban at once and start deleting whatever IDs are already recorded."""
    if sender is None:
        sender = (
            getattr(event, "sender", None)
            or getattr(getattr(event, "message", None), "sender", None)
        )
    key = _spam_runtime_key(chat_id, user_id)
    punish_key = _punishment_key(chat_id, user_id)
    current_id = getattr(getattr(event, "message", None), "id", None)
    collected = _collect_big_spam_ids(chat_id, user_id, seed_ids, current_id)
    if punish_key in bot.punished_users:
        # The first drain may have finished before the rest of the wave
        # arrived. Re-open the same chat+user incident with every ID the
        # tracker still has so messages 3..N are not dropped.
        incident = _big_spam_incident(bot, key, collected)
        resolved_peer = _resolved_event_peer(event)
        if resolved_peer is not None:
            incident["rpc_peer"] = resolved_peer
        _start_big_spam_cleanup(bot, event, chat_id, user_id, incident)
        return False

    incident = _big_spam_incident(bot, key, collected)
    resolved_peer = _resolved_event_peer(event)
    if resolved_peer is not None:
        incident["rpc_peer"] = resolved_peer
    incident["ban_state"] = "pending"
    queued_at = _asyncio.get_running_loop().time()
    incident["ban_deadline"] = queued_at + 50.0
    incident["ban_absolute_deadline"] = queued_at + 300.0
    bot.punished_users.add(punish_key)
    bot.set_spam_lock(key)
    _start_big_spam_cleanup(bot, event, chat_id, user_id, incident)

    async def succeeded(_result):
        incident["ban_state"] = "confirmed"
        bot.punished_users.add(punish_key)
        await _asyncio.sleep(0)
        # A success arriving after the hard callback deadline still proves the
        # user is banned, but must not resurrect a detached old incident that
        # could pop a newer incident with the same key.
        if getattr(bot, "_big_spam_incidents", {}).get(key) is not incident:
            bot.logger.log_info(
                "BIG SPAM BAN CONFIRMED LATE "
                f"chat_id={chat_id} user_id={user_id}"
            )
            return
        incident["ids"].update(_collect_big_spam_ids(
            chat_id, user_id, (), getattr(event.message, "id", None)
        ))
        _start_big_spam_cleanup(bot, event, chat_id, user_id, incident)
        bot.logger.log_info(
            "BIG SPAM BAN CONFIRMED "
            f"chat_id={chat_id} user_id={user_id} cleanup_ids={len(incident['ids'])}"
        )

    async def failed(error):
        incident["ban_state"] = "failed"
        bot.punished_users.discard(punish_key)
        bot.clear_spam_lock(key)
        bot.logger.log_error(
            "BIG SPAM BAN FAILED "
            f"chat_id={chat_id} user_id={user_id} reason={reason} error={error!r}"
        )

    queued = bot.moderation_queue.enqueue(
        chat_id, "ban", user_id=user_id, timeout_seconds=45,
        operation=lambda: bot.admin_actions.ban_user(
            chat_id, user_id, reason="اسپم بزرگ تکراری", user=sender,
        ),
        on_success=succeeded, on_failure=failed,
    )
    if not queued:
        incident["ban_state"] = "failed"
        bot.punished_users.discard(punish_key)
        bot.clear_spam_lock(key)
        bot.logger.log_info(
            "BIG SPAM BAN QUEUE DUPLICATE "
            f"chat_id={chat_id} user_id={user_id} reason={reason}"
        )
        return False
    bot.logger.log_info(
        "BIG SPAM BAN QUEUED "
        f"chat_id={chat_id} user_id={user_id} reason={reason} "
        f"seed_ids={len(incident['ids'])}"
    )
    return True


# Negative results (KeyError miss or confirmed non-admin) stay cached long
# enough that a later management command does not retry get_permissions.
# A newly promoted native admin is still re-checked after this window.
_NATIVE_ADMIN_FAIL_TTL = 180
_NATIVE_ADMIN_NEGATIVE_TTL = 90
_NATIVE_ADMIN_LIST_TTL = 60


async def _bot_status_text(bot):
    """🩺 گزارش لحظه‌ای سلامت — برای تشخیص «حافظه/CPU یا سرور» هنگام کندی.

    فقط خواندنی است؛ هیچ state ای را تغییر نمی‌دهد.
    """
    import time as _time

    # ۱) تاخیر حلقهٔ رویداد: نزدیک صفر = سالم؛ عدد بزرگ = فشار CPU/GIL داخلی
    t0 = _time.perf_counter()
    await _asyncio.sleep(0.05)
    loop_lag_ms = max(0.0, (_time.perf_counter() - t0 - 0.05) * 1000)

    # ۲) حافظهٔ واقعی پروسه (RSS)
    rss_mb = 0.0
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS"):
                    rss_mb = float(line.split()[1]) / 1024.0
                    break
    except OSError:
        pass

    # ۳) صف معلق اتصال (sender_pending)
    sender_pending = 0
    try:
        from modules.outgoing_profiler import pending_rpc_snapshot
        snap = pending_rpc_snapshot(getattr(bot.client, "_sender", None))
        sender_pending = int(snap.get("sender_pending", 0) or 0)
    except Exception:
        pass

    governor_snapshot = {}
    governor = getattr(bot, "rpc_governor", None)
    if governor is not None:
        try:
            governor_snapshot = governor.snapshot()
        except Exception:
            governor_snapshot = {}

    # ۴) صف‌ها و کش‌های داخلی
    dispatcher = getattr(bot, "group_dispatcher", None)
    workers = dispatcher.worker_count() if dispatcher is not None else 0
    stats = dict(getattr(dispatcher, "stats", {}) or {})
    delete_pending = 0
    delete_queue = getattr(bot, "message_delete_queue", None)
    if delete_queue is not None:
        try:
            delete_pending = sum(
                q.qsize() for q in delete_queue._queues.values())
        except Exception:
            pass
    tracker_rows = history_rows = 0
    try:
        tracker_rows = sum(len(v) for v in message_tracker._HISTORY.values())
    except Exception:
        pass
    try:
        from modules import spam_history as _sh
        history_rows = sum(len(v) for v in _sh.MESSAGE_HISTORY.values())
    except Exception:
        pass

    uptime_s = int(_time.time() - getattr(bot, "started_at", _time.time()))
    up_h, rem = divmod(max(0, uptime_s), 3600)
    up_m = rem // 60

    # ۵) سرعت واقعی سرور: یک RPC سبک همین حالا
    rpc_ms = -1.0
    try:
        t1 = _time.perf_counter()
        await _asyncio.wait_for(bot.client.get_me(), timeout=10)
        rpc_ms = (_time.perf_counter() - t1) * 1000
    except Exception:
        pass

    verdict = []
    if loop_lag_ms >= 100:
        verdict.append("⚠️ فشار داخلی CPU/حلقه — مشکل از خود ربات/گوشی است")
    if rss_mb >= 500:
        verdict.append("⚠️ مصرف حافظه بالا — احتمال swap شدن پروسه")
    if sender_pending >= 300:
        verdict.append("⚠️ انباشت صف اتصال — sender_pending غیرعادی")
    if int(governor_snapshot.get("waiting", 0) or 0) >= 20:
        verdict.append("⚠️ فشار RPC چندگروهی — بودجه اتصال در حال backpressure است")
    if rpc_ms >= 1000 and loop_lag_ms < 100:
        verdict.append("🌐 کندی از شبکه/سرور سروش است، نه از ربات")
    if not verdict:
        verdict.append("✅ همه چیز سالم است")

    rpc_display = "خطا/مهلت" if rpc_ms < 0 else f"{rpc_ms:.0f} ms"
    if governor_snapshot:
        governor_mode = (
            "shadow" if governor_snapshot.get("shadow")
            else ("فعال" if governor_snapshot.get("enabled") else "خاموش")
        )
        governor_display = (
            f"{governor_mode} | فعال: {governor_snapshot.get('active', 0)}/"
            f"{governor_snapshot.get('total_limit', 0)} | "
            f"منتظر: {governor_snapshot.get('waiting', 0)}"
        )
    else:
        governor_display = "نصب نشده"
    cb_display = "سالم"
    try:
        from modules.cache_manager import PermissionCircuitBreaker, STATE_OPEN
        cb_inst = PermissionCircuitBreaker.get_default()
        if cb_inst:
            open_count = sum(1 for r in getattr(cb_inst, "_breakers", {}).values() if r.state == STATE_OPEN)
            total_cb = len(getattr(cb_inst, "_breakers", {}))
            cb_display = f"قطع: {open_count} | کل: {total_cb}" if open_count > 0 else f"سالم ({total_cb} گروه)"
    except Exception:
        pass

    return (
        "🩺 وضعیت ربات\n\n"
        f"⏳ مدت اجرا: {up_h} ساعت و {up_m} دقیقه\n"
        f"🧠 حافظه (RSS): {rss_mb:.0f} MB\n"
        f"🌀 تاخیر حلقه رویداد: {loop_lag_ms:.0f} ms\n"
        f"🌐 پاسخ سرور (RPC تست): {rpc_display}\n"
        f"📡 صف معلق اتصال: {sender_pending}\n"
        f"🚦 بودجه RPC: {governor_display}\n"
        f"🔌 مدارشکن (Circuit Breaker): {cb_display}\n"
        f"👷 ورکرها: {workers} | پردازش: {stats.get('processed', 0)} | "
        f"خطا: {stats.get('failed', 0)} | حذف از صف: {stats.get('dropped', 0)}\n"
        f"🗑 صف حذف: {delete_pending} پیام\n"
        f"🧾 ردیاب پیام: {tracker_rows} | تاریخچه اسپم: {history_rows}\n\n"
        + "\n".join(verdict)
    )


def _is_management_command(text):
    """True only for a recognized owner/moderation command.

    Group dispatch keeps any ``.``, ``/`` or ``!`` prefix in the fast admin
    lane, but decorative spam such as ``.....`` is not a command and must not
    trigger a native-role RPC. Strip prefixes and classify the actual command.
    """
    value = normalize_command(text)
    if value[:1] in {".", "/", "!"}:
        value = value.lstrip("./!").strip()
        if not value:
            return False
    priority, _kind = classify_priority(value)
    return int(priority) <= PRIORITY_ADMIN


# Owner-only commands authorize with is_global_owner. A native
# get_permissions RTT (~1.7s) cannot change that decision.
_OWNER_ONLY_NATIVE_SKIP = frozenset({
    "فعال", "غیر فعال", "فعال سازی",
    "ثبت گروه", "حذف گروه",
    "ثبت مالک", "لغو مالک", "برکناری مالک",
})


def _should_check_native_admin(is_private, registered_admin, text):
    """Native role RPC is only for management commands, never filters."""
    if is_private or registered_admin:
        return False
    if normalize_command(text) in _OWNER_ONLY_NATIVE_SKIP:
        return False
    return _is_management_command(text)


def _store_native_admin_cache(cache, key, value, expires_at):
    cache[key] = (value, expires_at)
    if len(cache) > 5000:
        cache.pop(next(iter(cache)), None)


def _native_participant_is_admin(participant):
    """Read Soroush TL participant role without Telegram-specific imports."""
    name = type(participant).__name__
    return name in {
        "ChannelParticipantAdmin", "ChannelParticipantCreator",
        "ChatParticipantAdmin", "ChatParticipantCreator",
    }


async def _native_admin_from_resolved_peer(
    bot, resolved_chat, sender, user_id
):
    """Query the Soroush participant directly, bypassing entity re-resolution.

    Returns ``None`` only when the event did not provide enough resolved peer
    data, so the compatibility ``get_permissions`` fallback may be used. Once
    a direct request is constructed, its server errors are deliberately raised
    to the caller instead of causing a second duplicate RPC.
    """
    if resolved_chat is None:
        return None
    try:
        from splusthon import utils as _sutils
        chat_peer = _sutils.get_input_peer(resolved_chat)
    except Exception:
        return None
    if chat_peer is None:
        return None

    chat_peer_name = type(chat_peer).__name__
    if (
        chat_peer_name in {"InputPeerChannel", "InputChannel"}
        or getattr(chat_peer, "channel_id", None) is not None
    ):
        # Soroush returns NOT_SUPPORTED for channels.GetParticipant even
        # though SPlusthon's get_permissions uses it. Fetch the supported
        # filtered admin list once and reuse it for all users of this chat.
        channel_id = getattr(chat_peer, "channel_id", None)
        list_key = normalize_group_id(channel_id)
        list_cache = getattr(bot, "native_group_admin_ids_cache", None)
        if list_cache is None:
            list_cache = bot.native_group_admin_ids_cache = {}
        now = _asyncio.get_running_loop().time()
        cached = list_cache.get(list_key)
        if cached and cached[1] > now:
            return str(user_id) in cached[0]

        request = functions.channels.GetParticipantsRequest(
            channel=chat_peer,
            filter=types.ChannelParticipantsAdmins(),
            offset=0,
            limit=200,
            hash=0,
        )
        response = await bot.client(request)
        admin_ids = {
            str(getattr(user, "id", ""))
            for user in (getattr(response, "users", ()) or ())
            if getattr(user, "id", None) is not None
        }
        for participant in getattr(response, "participants", ()) or ():
            participant_id = getattr(participant, "user_id", None)
            if participant_id is None:
                participant_id = getattr(
                    getattr(participant, "peer", None), "user_id", None
                )
            if participant_id is not None and _native_participant_is_admin(
                participant
            ):
                admin_ids.add(str(participant_id))
        list_cache[list_key] = (
            frozenset(admin_ids), now + _NATIVE_ADMIN_LIST_TTL
        )
        if len(list_cache) > 1000:
            list_cache.pop(next(iter(list_cache)), None)
        return str(user_id) in admin_ids

    if (
        chat_peer_name in {"InputPeerChat", "InputChat"}
        or getattr(chat_peer, "chat_id", None) is not None
    ):
        short_chat_id = getattr(chat_peer, "chat_id", None)
        response = await bot.client(
            functions.messages.GetFullChatRequest(chat_id=short_chat_id)
        )
        container = getattr(
            getattr(response, "full_chat", None), "participants", None
        )
        participants = getattr(container, "participants", ()) or ()
        target_id = str(user_id)
        for participant in participants:
            participant_id = getattr(participant, "user_id", None)
            if participant_id is None:
                participant_id = getattr(
                    getattr(participant, "peer", None), "user_id", None
                )
            if str(participant_id) == target_id:
                return _native_participant_is_admin(participant)
        return False

    return None


async def _is_native_group_admin(
    bot, chat_id, user_id, sender, resolved_chat=None
):
    """Read the actual Soroush group role for a management command only.

    Regular chat and content-filter paths must never call this.  The result
    is short-lived cached so a later management command does not repeat the
    RPC, while role changes are still seen after the TTL.

    ``get_permissions`` first resolves its chat argument. Passing only the
    short numeric Soroush id can miss SPlusthon's entity cache and raise a
    ``KeyError`` before GetParticipant is sent. Reuse the event's already
    resolved chat/InputPeer whenever available; the numeric id remains only
    a compatibility fallback.
    """
    cache = getattr(bot, "native_group_admin_cache", None)
    if cache is None:
        cache = bot.native_group_admin_cache = {}
    key = (normalize_group_id(chat_id), str(user_id))
    now = _asyncio.get_running_loop().time()
    cached = cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        is_admin = await _native_admin_from_resolved_peer(
            bot, resolved_chat, sender, user_id
        )
        if is_admin is None:
            permissions = await bot.client.get_permissions(
                resolved_chat or chat_id, sender or user_id
            )
            is_admin = bool(getattr(permissions, "is_admin", False))
        # Admin status stays short-lived so a demotion is seen soon.
        # A confirmed non-admin uses the longer negative TTL to avoid
        # repeating get_permissions on every ordinary group message.
        _store_native_admin_cache(
            cache, key, is_admin,
            now + (60 if is_admin else _NATIVE_ADMIN_NEGATIVE_TTL),
        )
        return is_admin
    except Exception as error:
        _store_native_admin_cache(cache, key, False, now + _NATIVE_ADMIN_FAIL_TTL)
        last = getattr(bot, "_native_admin_fail_logged", None)
        if last is None:
            last = bot._native_admin_fail_logged = {}
        if _message_debug_enabled(bot) or last.get(key, 0) <= now:
            last[key] = now + 300
            if len(last) > 5000:
                last.pop(next(iter(last)), None)
            bot.logger.log_error(
                "NATIVE ADMIN CHECK FAILED "
                f"chat_id={chat_id} user_id={user_id} error={error!r}"
            )
        return False


def _clear_native_admin_moderation_state(bot, chat_id, user_id, *, force=False):
    """Remove stale punishment/delete state for a real group administrator."""
    cleared = getattr(bot, "native_admin_state_cleared", None)
    if cleared is None:
        cleared = bot.native_admin_state_cleared = set()
    key = (normalize_group_id(chat_id), str(user_id))
    if key in cleared and not force:
        return False
    clear_state = getattr(bot, "clear_released_user_state", None)
    if callable(clear_state):
        clear_state(chat_id, user_id)
    else:
        # Compatibility fallback for a minimal bot object/test double.
        bot.tracker.reset_count(chat_id, user_id)
        bot.clear_spam_lock((chat_id, user_id))
    cleared.add(key)
    if len(cleared) > 5000:
        cleared.pop()
    return True


async def _same_sender(message, user_id):
    sender_id = getattr(message, "sender_id", None)
    if sender_id is None:
        from_id = getattr(message, "from_id", None)
        sender_id = getattr(from_id, "user_id", None)
    if sender_id is None:
        get_sender = getattr(message, "get_sender", None)
        if callable(get_sender):
            sender = await get_sender()
            sender_id = getattr(sender, "id", None)
    return sender_id is not None and str(sender_id) == str(user_id)


SPAM_HISTORY_SWEEP_LIMIT = 300


async def collect_accessible_spam_ids(bot, chat_id, user_id, seed_ids):
    """Use tracked IDs first; history sweep is bounded and background-only.

    ⚠️ آی‌دی‌های ردیابِ حافظه‌ای همیشه ادغام می‌شوند. پیش‌تر با وجود
    حتی یک seed، فقط همان seed حذف می‌شد و بقیهٔ موج (که ingest همه
    را در message_tracker ثبت کرده) جا می‌ماند — همان باگ «بعد از بن
    فقط ۲-۳ پیام پاک می‌شود». ادغام ردیاب هیچ RPC ای ندارد؛ فقط
    خواندن حافظه است. جاروی تاریخچه (GetHistory) همچنان فقط برای
    بازیابیِ بدون seed و بدون ردیاب استفاده می‌شود.
    """
    ids = {message_id for message_id in seed_ids
           if isinstance(message_id, int) and message_id > 0}
    tracked = message_tracker.spam_snapshot(chat_id, user_id)
    tracked_ids = {
        message_id for message_id in tracked
        if isinstance(message_id, int) and message_id > 0
    }
    ids.update(tracked_ids)
    if ids:
        bot.logger.log_info(
            "SPAM HISTORY SWEEP SKIPPED "
            f"chat_id={chat_id} user_id={user_id} "
            f"seed_ids={len(seed_ids or ())} tracked_ids={len(tracked_ids)} "
            f"total={len(ids)}"
        )
        return ids

    iterator_factory = getattr(bot.client, "iter_messages", None)
    if not callable(iterator_factory):
        bot.logger.log_error(
            "SPAM HISTORY SWEEP UNAVAILABLE "
            f"chat_id={chat_id} user_id={user_id}"
        )
        return ids

    for attempt in range(2):
        scanned = matched = 0
        try:
            # SPlusthon throttles history pages; cap recovery to a recent
            # window and use its page wait_time rather than flooding RPCs.
            async for message in iterator_factory(
                    chat_id, limit=SPAM_HISTORY_SWEEP_LIMIT, wait_time=1):
                scanned += 1
                if not await _same_sender(message, user_id):
                    continue
                text = (getattr(message, "message", None)
                        or getattr(message, "caption", None) or "")
                if not _is_true_auto_spam_text(bot, chat_id, text):
                    continue
                message_id = getattr(message, "id", None)
                if isinstance(message_id, int) and message_id > 0:
                    before = len(ids)
                    ids.add(message_id)
                    matched += len(ids) - before
        except _asyncio.CancelledError:
            raise
        except Exception as error:
            wait = getattr(error, "seconds", None)
            if wait and attempt == 0:
                delay = min(max(float(wait), 1.0), 30.0)
                bot.logger.log_error(
                    "SPAM HISTORY SWEEP FLOODWAIT "
                    f"chat_id={chat_id} user_id={user_id} wait_s={delay:.1f}"
                )
                await _asyncio.sleep(delay)
                continue
            bot.logger.log_error(
                "SPAM HISTORY SWEEP FAILED "
                f"chat_id={chat_id} user_id={user_id} scanned={scanned} "
                f"matched={matched} error={error!r}"
            )
            return ids
        else:
            bot.logger.log_info(
                "SPAM HISTORY SWEEP COMPLETE "
                f"chat_id={chat_id} user_id={user_id} scanned={scanned} "
                f"spam_ids={len(ids)}"
            )
            return ids
    return ids


def _queue_message_deletes(bot, chat_id, message_ids, *, priority=1):
    """Queue deletion immediately; never await a delete RPC in this handler.

    ``priority=0`` is reserved for owner/admin «پاک» so a spam-wave cleanup
    in the same group cannot delay a manual delete.
    """
    queue = getattr(bot, "message_delete_queue", None)
    if queue is not None:
        return queue.enqueue(chat_id, message_ids, priority=priority)

    async def fallback():
        ids = list(message_ids)
        try:
            await bot.client.delete_messages(chat_id, ids)
            return len(ids), []
        except Exception as error:
            bot.logger.log_error(
                f"DELETE BACKGROUND FALLBACK FAILED chat_id={chat_id} error={error!r}"
            )
            return 0, ids
    return _asyncio.create_task(fallback(), name="delete:fallback")


def _spam_cleanup_incident(bot, key, event):
    """Return the one aggregate cleanup incident for a user/group spam wave."""
    incidents = getattr(bot, "_spam_cleanup_incidents", None)
    if incidents is None:
        incidents = bot._spam_cleanup_incidents = {}
    incident = incidents.get(key)
    if incident is None:
        sequence = getattr(bot, "_spam_cleanup_incident_sequence", 0) + 1
        bot._spam_cleanup_incident_sequence = sequence
        incident = incidents[key] = {
            "id": sequence,
            "deleted": 0,
            "ban_confirmed": False,
            "event": event,
            "_touched_at": time.monotonic(),
        }
    else:
        incident["_touched_at"] = time.monotonic()
        if event is not None:
            # Keep the latest event only as reply context; all counts remain in the
            # same incident and are never reset by a later cleanup batch.
            incident["event"] = event
    return incident


def _confirm_spam_ban_cleanup(bot, event, chat_id, user_id, seed_ids=()):
    """Seal a spam incident only after its ban/kick RPC really succeeded."""
    key = _spam_runtime_key(chat_id, user_id)
    incident = _spam_cleanup_incident(bot, key, event)
    incident["ban_confirmed"] = True
    return _schedule_auto_spam_cleanup(bot, event, chat_id, user_id, seed_ids)


def _schedule_auto_spam_cleanup(bot, event, chat_id, user_id, seed_ids, *, announce_cleanup=True):
    """Aggregate all batches in one incident and emit one final cleanup notice."""
    key = _spam_runtime_key(chat_id, user_id)
    incident = _spam_cleanup_incident(bot, key, event)
    pending = getattr(bot, "_auto_spam_cleanup_pending", None)
    if pending is None:
        pending = bot._auto_spam_cleanup_pending = {}
    pending.setdefault(key, set()).update(seed_ids)
    tasks = getattr(bot, "_auto_spam_cleanup_tasks", None)
    if tasks is None:
        tasks = bot._auto_spam_cleanup_tasks = {}
    existing = tasks.get(key)
    if existing is not None and not existing.done():
        return existing

    async def run():
        try:
            # New IDs can arrive while deletion is in progress. They are added
            # to the same incident and their successful deletes are accumulated
            # in ``incident['deleted']`` rather than announced per batch.
            while True:
                seeds = pending.pop(key, set())
                if not seeds:
                    # Yield once before declaring the incident drained, so a
                    # concurrent incoming-message handler can join this wave.
                    await _asyncio.sleep(0)
                    seeds = pending.pop(key, set())
                    if not seeds:
                        break
                spam_ids = await collect_accessible_spam_ids(
                    bot, chat_id, user_id, seeds
                )
                deleted, remaining = await cleanup_spam_messages(
                    bot, chat_id, user_id, spam_ids)
                incident["deleted"] += deleted
                _record_spam_ban_deletes(
                    bot, event, chat_id, user_id,
                    set(spam_ids) - set(remaining or ()),
                )
                finalized = finalize_spam_wave(
                    chat_id, user_id, len(spam_ids), deleted, remaining)
                if remaining:
                    bot.logger.log_error(
                        "SPAM DELETE INCOMPLETE "
                        f"chat_id={chat_id} user_id={user_id} "
                        f"selected={len(spam_ids)} deleted={deleted} "
                        f"remaining={len(remaining)}")
                if not finalized:
                    break

            if not announce_cleanup:
                getattr(bot, "_spam_cleanup_incidents", {}).pop(key, None)
                return
            action = getattr(bot, "config_manager", None)
            action = action.get("action_on_threshold") if action is not None else None
            if action in {"ban", "kick"}:
                # A ban intent is not enough: before its RPC success callback,
                # cleanup may run in several batches. Keep their total and wait
                # for that callback to seal the incident.
                if not incident.get("ban_confirmed"):
                    bot.logger.log_info(
                        "SPAM CLEANUP NOTICE DEFERRED "
                        f"chat_id={chat_id} user_id={user_id} "
                        f"deleted_so_far={incident['deleted']}"
                    )
                    return
                _schedule_spam_ban_notice(bot, event, chat_id, user_id)
            elif incident["deleted"]:
                notice_event = incident.get("event") or event
                sender2 = getattr(bot, "outgoing_sender", None)
                if sender2 is not None:
                    sender2.enqueue_reply(notice_event, f"🗑 {_fullwidth_digits(incident['deleted'])} پیام هرزنامه پاک شد", on_done=lambda sent: capture_sent(bot, chat_id, sent))
                    getattr(bot, "_spam_cleanup_incidents", {}).pop(key, None)
                else:
                    sent = await notice_event.reply(
                        f"🗑 {_fullwidth_digits(incident['deleted'])} پیام هرزنامه پاک شد")
                    capture_sent(bot, chat_id, sent)
                    getattr(bot, "_spam_cleanup_incidents", {}).pop(key, None)

        except _asyncio.CancelledError:
            raise
        except Exception as error:
            bot.logger.log_error(
                f"SPAM CLEANUP BACKGROUND FAILED chat_id={chat_id} "
                f"user_id={user_id} error={error!r}"
            )
        finally:
            if tasks.get(key) is _asyncio.current_task():
                tasks.pop(key, None)
                # A message may have joined between the final empty check and
                # task teardown. Start a continuation instead of discarding
                # its IDs; it retains the same incident total/notice token.
                if pending.get(key):
                    _schedule_auto_spam_cleanup(
                        bot, incident.get("event") or event,
                        chat_id, user_id, (),
                        announce_cleanup=announce_cleanup,
                    )
                else:
                    pending.pop(key, None)

    task = _asyncio.create_task(run())
    tasks[key] = task
    return task


async def cleanup_spam_messages(bot, chat_id, user_id, ids, *, batch_size=60):
    """Delete tracked spam in bounded batches of at most 60 IDs."""
    pending = sorted({i for i in ids if isinstance(i, int) and i > 0})
    queue = getattr(bot, "message_delete_queue", None)
    if queue is not None:
        return await queue.enqueue(chat_id, pending)
    requested = len(pending)
    deleted = 0
    remaining = []
    bot.logger.log_info(
        "SPAM CLEANUP ENTRY "
        f"chat_id={chat_id} user_id={user_id} "
        f"current_message_id={pending[-1] if pending else None} source=cleanup_spam_messages"
    )
    bot.logger.log_info(
        f"SPAM DELETE START total_ids={requested} ids={pending!r} batch_size={batch_size}"
    )
    # Process in bounded batches so a large cleanup cannot monopolize sender RPCs.
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        success = False
        last_error = None
        for attempt in range(1, 4):
            try:
                await bot.client.delete_messages(chat_id, batch)
                success = True
                deleted += len(batch)
                for message_id in batch:
                    bot.logger.log_info(
                        f"SPAM DELETE ITEM message_id={message_id} success=True"
                    )
                break
            except Exception as error:
                last_error = error
                bot.logger.log_error(
                    f"SPAM DELETE BATCH attempt={attempt} batch={batch!r} error={error!r}"
                )
                if attempt < 3:
                    await _asyncio.sleep(0.2 * attempt)
        if not success:
            # Fallback to individual deletes for this batch to isolate failures
            for message_id in batch:
                ind_success = False
                ind_error = None
                for attempt in range(1, 4):
                    try:
                        await bot.client.delete_messages(chat_id, [message_id])
                        ind_success = True
                        deleted += 1
                        bot.logger.log_info(
                            f"SPAM DELETE ITEM message_id={message_id} success=True"
                        )
                        break
                    except Exception as error:
                        ind_error = error
                        bot.logger.log_error(
                            f"SPAM DELETE ITEM message_id={message_id} "
                            f"attempt={attempt} error={error!r}"
                        )
                        if attempt < 3:
                            await _asyncio.sleep(0.2 * attempt)
                if not ind_success:
                    remaining.append(message_id)
                    bot.logger.log_error(
                        f"SPAM DELETE ITEM message_id={message_id} success=False "
                        f"error={ind_error!r}"
                    )
    bot.logger.log_info(
        f"SPAM DELETE FINISHED requested={requested} deleted={deleted} "
        f"remaining={len(remaining)}"
    )
    return deleted, remaining


async def _cleanup_heavy_spam_history(bot, event, chat_id, user_id):
    # Use the single authoritative runtime tracker; spam_history is retained
    # for repeat detection but must not be the cleanup source.
    history = message_tracker.get_user_recent_messages(chat_id, user_id)
    ids = {
        item.get("message_id") for item in history
        if isinstance(item.get("message_id"), int)
        and item.get("message_id") > 0
    }
    current_id = getattr(event.message, "id", None)
    if current_id:
        ids.add(current_id)
    if not ids:
        bot.logger.log_error(
            "SPAM CLEANUP VERIFY "
            f"group_id={chat_id} user_id={user_id} detected=0 deleted=0 remaining=0"
        )
        return

    # Retained for compatibility with legacy callers. It now joins the same
    # incident worker as every other cleanup path, so it cannot emit its own
    # per-batch reply.
    _schedule_auto_spam_cleanup(bot, event, chat_id, user_id, ids)


async def get_activation_admin_info(bot, chat_id):
    owner = None
    admins = []
    admin_ids = set()

    def collect_participants(users, participants):
        nonlocal owner
        users = {
            getattr(user, "id", None): user
            for user in users
        }

        for participant in participants:
            user_id = getattr(participant, "user_id", None)
            user = users.get(user_id)
            if not user:
                continue

            participant_type = participant.__class__.__name__
            if "Creator" in participant_type:
                owner = _format_group_member(user)
            elif "Admin" in participant_type and user_id not in admin_ids:
                admin_ids.add(user_id)
                admins.append(_format_group_member(user))

    try:
        channel = await bot.client.get_input_entity(chat_id)
        offset = 0
        limit = 100

        while True:
            result = await bot.client(
                functions.channels.GetParticipantsRequest(
                    channel=channel,
                    filter=types.ChannelParticipantsAdmins(),
                    offset=offset,
                    limit=limit,
                    hash=0,
                )
            )
            users = getattr(result, "users", [])
            if not users:
                break

            collect_participants(
                users,
                getattr(result, "participants", []),
            )
            if len(users) < limit:
                break
            offset += len(users)

    except Exception as channel_error:
        # Basic groups do not support channels.GetParticipantsRequest.
        try:
            result = await bot.client(
                functions.messages.GetFullChatRequest(chat_id=chat_id)
            )
            participant_container = getattr(
                getattr(result, "full_chat", None),
                "participants",
                None,
            )
            collect_participants(
                getattr(result, "users", []),
                getattr(participant_container, "participants", []),
            )
        except Exception as basic_chat_error:
            bot.logger.log_error(
                "خطا در دریافت مالک و ادمین‌های گروه "
                f"{chat_id}: channel={channel_error}; basic_chat={basic_chat_error}"
            )

    return owner, admins


async def send_activation_message(bot, event, chat_id, title):
    owner, admins = await get_activation_admin_info(bot, chat_id)
    owner_text = owner or "یافت نشد (دسترسی کافی ندارم)"
    admins_text = (
        "\n".join(
            f"{index}. {admin}"
            for index, admin in enumerate(admins, 1)
        )
        if admins else "ندارد"
    )

    owner_section = f"👑 مالک گروه:\n{owner_text}"
    admins_section = f"👮 ادمین های گروه:\n{admins_text}"
    activation_hint = (
        "برای آشنایی بیشتر کلمه راهنما را ارسال کنید یا بیو ربات، "
        "کانال راهنما را مطالعه کنید."
    )
    activation_text = (
        f"🦊 روباه در گروه «{title}» فعال سازی شد ✅\n\n"
        f"{owner_section}\n\n{admins_section}\n\n{activation_hint}"
    )

    def u16_length(value):
        return len(value.encode("utf-16-le")) // 2

    owner_offset = activation_text.index(owner_section)
    admins_offset = activation_text.index(admins_section)
    hint_offset = activation_text.index(activation_hint)
    entities = [
        MessageEntityBlockquote(
            offset=u16_length(activation_text[:owner_offset]),
            length=u16_length(owner_section),
        ),
        MessageEntityBold(
            offset=u16_length(activation_text[:owner_offset]),
            length=u16_length("👑 مالک گروه:"),
        ),
        MessageEntityBlockquote(
            offset=u16_length(activation_text[:admins_offset]),
            length=u16_length(admins_section),
        ),
        MessageEntityBold(
            offset=u16_length(activation_text[:admins_offset]),
            length=u16_length("👮 ادمین های گروه:"),
        ),
        MessageEntityBold(
            offset=u16_length(activation_text[:hint_offset]),
            length=u16_length(activation_hint),
        ),
    ]
    await event.respond(activation_text, formatting_entities=entities)


# Owner/management commands that must not wait on the heavy group pipeline.
# Exact match only — user chat, games, and greetings never belong here.
FAST_OWNER_COMMANDS = frozenset({
    "فعال", "غیر فعال", "فعال سازی",
    "ثبت گروه", "ثبت مالک",
})


def is_fast_owner_command(text):
    """True only for the five owner fast-path commands.

    Detection must never raise: a failure returns False so the caller can
    continue on the normal handler path.
    """
    try:
        if not text:
            return False
        normalized = normalize_command(text)
        return normalized in FAST_OWNER_COMMANDS
    except Exception:
        return False


def _command_timing_log(bot, message):
    logger = getattr(bot, "logger", None)
    if logger is not None:
        logger.log_info(message)


async def _fast_owner_sender(event):
    """Prefer already-resolved sender fields. Await get_sender only if needed."""
    sender = (
        getattr(event, "_bot_cached_sender", None)
        or getattr(event, "sender", None)
    )
    if sender is None:
        get_sender = getattr(event, "get_sender", None)
        if callable(get_sender):
            try:
                sender = await get_sender()
            except Exception:
                sender = None
        try:
            event._bot_cached_sender = sender
        except Exception:
            pass
    user_id = getattr(event, "sender_id", None)
    if user_id is None:
        user_id = getattr(sender, "id", None)
    return sender, user_id


async def _fast_owner_chat(event, *, need_title=False):
    """Use cached chat/title. Call get_chat only when the title is required."""
    chat = (
        getattr(event, "_bot_cached_chat", None)
        or getattr(event, "chat", None)
    )
    chat_id = getattr(event, "chat_id", None)
    title = getattr(chat, "title", None) if chat is not None else None
    if chat is None or (need_title and not title):
        get_chat = getattr(event, "get_chat", None)
        if callable(get_chat):
            try:
                chat = await get_chat()
            except Exception:
                chat = chat
        try:
            event._bot_cached_chat = chat
        except Exception:
            pass
        if chat is not None:
            chat_id = getattr(chat, "id", chat_id)
            if not title:
                title = getattr(chat, "title", None)
    return chat, chat_id, title or ""


async def handle_fast_owner_command(bot, event, text=None):
    """Run owner group commands without spam/AI/search/native-admin work.

    Returns True when the command was consumed. Private chats return False
    so the existing DM path is unchanged.
    """
    if getattr(event, "is_private", False):
        return False
    started = time.perf_counter()
    if text is None:
        message = getattr(event, "message", None)
        raw = ""
        if message is not None:
            raw = (
                getattr(message, "message", None)
                or getattr(message, "caption", None)
                or ""
            )
        text = normalize_command(raw)
    if not is_fast_owner_command(text):
        return False

    chat_id = getattr(event, "chat_id", None)
    message_id = getattr(getattr(event, "message", None), "id", None)
    _command_timing_log(
        bot,
        f"COMMAND RECEIVED command={text} chat_id={chat_id} "
        f"message_id={message_id}",
    )
    _sender, user_id = await _fast_owner_sender(event)
    _command_timing_log(
        bot,
        f"COMMAND HANDLER START command={text} chat_id={chat_id} "
        f"user_id={user_id}",
    )
    owner = is_global_owner(user_id)

    async def finish(replied=True):
        elapsed_ms = (time.perf_counter() - started) * 1000
        _command_timing_log(
            bot,
            f"COMMAND RESPONSE SENT command={text} chat_id={chat_id} "
            f"replied={replied} elapsed_ms={elapsed_ms:.1f}",
        )
        _command_timing_log(
            bot,
            f"TOTAL COMMAND TIME command={text} chat_id={chat_id} "
            f"elapsed_ms={elapsed_ms:.1f}",
        )
        return True

    if text == "فعال":
        need_title = bool(owner and chat_id is not None and not is_active(chat_id))
        _chat, chat_id, title = await _fast_owner_chat(
            event, need_title=need_title
        )
        if owner and chat_id is not None and not is_active(chat_id):
            activate_group(chat_id, title)
            _command_timing_log(
                bot, f"COMMAND SAVED command={text} chat_id={chat_id}"
            )
            await send_activation_message(bot, event, chat_id, title)
            return await finish(True)
        return await finish(False)

    if text == "غیر فعال":
        if owner:
            _chat, chat_id, title = await _fast_owner_chat(
                event, need_title=True
            )
            deactivate_group(chat_id, title)
            for task in getattr(bot, "group_timer_tasks", {}).pop(chat_id, set()):
                task.cancel()
            cancel_name_family_round(chat_id)
            _command_timing_log(
                bot, f"COMMAND SAVED command={text} chat_id={chat_id}"
            )
            await event.reply(f"🦊 روباه در گروه «{title}» غیر فعال شد ❌")
            return await finish(True)
        return await finish(False)

    if text == "فعال سازی":
        if not owner:
            await event.reply("❌ فقط مالک ربات اجازه این دستور را دارد")
            return await finish(True)
        _chat, chat_id, title = await _fast_owner_chat(event, need_title=True)
        activate_group(chat_id, title)
        _command_timing_log(
            bot, f"COMMAND SAVED command={text} chat_id={chat_id}"
        )
        await send_activation_message(bot, event, chat_id, title)
        return await finish(True)

    if text == "ثبت گروه":
        if not owner:
            await event.reply("❌ فقط مالک ربات اجازه ثبت گروه دارد")
            return await finish(True)
        try:
            _chat, chat_id, title = await _fast_owner_chat(
                event, need_title=True
            )
            activate_group(chat_id, title)
            _command_timing_log(
                bot, f"COMMAND SAVED command={text} chat_id={chat_id}"
            )
            # مالک اصلی = مالک بومی خودِ گروه (نه فرستندهٔ دستور)؛ بدون
            # username → نام نمایشی. خطوط بدون فاصلهٔ خالی.
            _owner_display = await _group_main_owner_display(
                bot, _chat, _sender, chat_id=chat_id)
            await event.reply(
                f"↻- گروه\n\u200f「 {title} 」ثبت شد ☑️\n"
                f"**مالک ربات** : ❨ {_owner_display}❩"
            )
        except Exception as error:
            await event.reply(f"❌ خطا در ثبت گروه: {error}")
        return await finish(True)

    if text == "ثبت مالک":
        if not owner:
            await event.reply(
                "❌ فقط مالک اصلی ربات اجازه ثبت مالک گروه را دارد"
            )
            return await finish(True)
        if not getattr(event, "reply_to", None):
            await event.reply(
                "❌ برای ثبت مالک باید روی پیام کاربر ریپلای کنید"
            )
            return await finish(True)
        try:
            reply_msg = await bot.client.get_messages(
                chat_id,
                ids=event.reply_to.reply_to_msg_id,
            )
            target_user = await reply_msg.get_sender() if reply_msg else None
            if not target_user:
                await event.reply("❌ کاربر پیدا نشد")
                return await finish(True)
            set_group_owner(chat_id, target_user.id)
            _command_timing_log(
                bot, f"COMMAND SAVED command={text} chat_id={chat_id}"
            )
            # Bold با ** (Markdown پیش‌فرض send_message). نام کاربری و
            # در نبود آن، نام نمایشی از policy واحد format_user می‌آید.
            await event.reply(
                f"**مالـک ثبت شد** 「 {_format_group_member(target_user)}」‌𓆤"
            )
        except Exception as error:
            logger = getattr(bot, "logger", None)
            if logger is not None:
                logger.log_error(f"خطا در ثبت مالک گروه: {error}")
            await event.reply(f"❌ خطا در ثبت مالک: {error}")
        return await finish(True)

    return False


FAST_MODERATION_COMMANDS = frozenset({"سکوت", "قفل", "باز"})


def is_fast_moderation_command(text):
    try:
        return normalize_command(text) in FAST_MODERATION_COMMANDS
    except Exception:
        return False


async def handle_fast_moderation_command(
    bot, event, text=None, sender=None
):
    """Queue manual mute without traversing the multi-thousand-line pipeline.

    The command handler performs only cached authorization and enqueue. Reply
    lookup, target resolution and the potentially slow native-admin list RPC
    run inside ``ModerationQueue`` so the admin lane is released immediately.
    Returns ``False`` when the sender is not a registered/global/group owner so
    the existing compatibility path may still verify native Soroush admins.
    """
    clean_text = normalize_command(text or "")
    if clean_text not in FAST_MODERATION_COMMANDS:
        return False
    if getattr(event, "is_private", False):
        return False

    chat_id = getattr(event, "chat_id", None)
    if sender is None:
        sender = (
            getattr(event, "_bot_cached_sender", None)
            or getattr(event, "sender", None)
        )
    if sender is None:
        try:
            sender = await event.get_sender()
        except Exception:
            sender = None
    user_id = getattr(sender, "id", getattr(event, "sender_id", None))
    sender_username = getattr(sender, "username", None)

    # This synchronous check is cache/file backed and costs no Soroush RPC.
    if not _has_group_management_permission(
        bot, chat_id, user_id, sender_username
    ):
        return False

    if clean_text in {"قفل", "باز"}:
        action = "lock" if clean_text == "قفل" else "unlock"
        async def group_action_succeeded(_result):
            admin_tools.log_action(
                chat_id, sender,
                "قفل کردن گروه" if action == "lock" else "باز کردن گروه",
            )
            await event.reply("🔒 گروه قفل شد" if action == "lock" else "🔓 گروه باز شد")

        async def group_action_failed(_error):
            await event.reply("❌ انجام قفل گروه ناموفق بود" if action == "lock" else "❌ انجام باز کردن گروه ناموفق بود")

        bot.moderation_queue.enqueue(
            chat_id, action, user_id=f"group:{chat_id}", timeout_seconds=20,
            operation=(
                (lambda: bot.group_actions.lock_group(chat_id))
                if action == "lock" else
                (lambda: bot.group_actions.unlock_group(chat_id))
            ),
            on_success=group_action_succeeded,
            on_failure=group_action_failed,
        )
        return True

    if not getattr(event, "reply_to", None):
        _schedule_reply(bot, event, "❌ باید روی پیام کاربر ریپلای کنید")
        return True

    reply_id = getattr(event.reply_to, "reply_to_msg_id", None)
    if reply_id is None:
        _schedule_reply(bot, event, "❌ پیام ریپلای شده پیدا نشد")
        return True

    resolved_permission_chat = (
        getattr(event, "_bot_cached_chat", None)
        or getattr(event, "chat", None)
        or _resolved_event_peer(event)
        or getattr(bot, "reply_input_peer_cache", {}).get(chat_id)
    )

    async def fast_mute_operation():
        # Reply lookup, target resolution and native-admin RPC all run in the
        # isolated moderation worker.  The command dispatcher only enqueues.
        reply_msg = await bot.client.get_messages(chat_id, ids=reply_id)
        if not reply_msg:
            return {"error": "reply_not_found"}
        target_user = await reply_msg.get_sender()
        if not target_user:
            return {"error": "user_not_found"}

        target_username = getattr(target_user, "username", None)
        if _has_group_management_permission(
            bot, chat_id, target_user.id, target_username
        ):
            return {
                "protected_admin": True,
                "muted": False,
                "target_user": target_user,
            }
        # This can take one network RTT on a cold admin-list cache, but it no
        # longer holds the command lane or blocks a following mute/ban command.
        if await _is_native_group_admin(
            bot,
            chat_id,
            target_user.id,
            target_user,
            resolved_permission_chat,
        ):
            return {
                "protected_admin": True,
                "muted": False,
                "target_user": target_user,
            }
        muted = await bot.admin_actions.mute_user(
            chat_id, target_user.id, user=target_user,
            chat=resolved_permission_chat,
        )
        if not muted:
            raise RuntimeError("mute operation returned False")
        return {
            "protected_admin": False,
            "muted": True,
            "target_user": target_user,
        }

    async def fast_mute_succeeded(result):
        error = result.get("error") if isinstance(result, dict) else None
        if error == "reply_not_found":
            await event.reply("❌ پیام ریپلای شده پیدا نشد")
            return
        if error == "user_not_found":
            await event.reply("❌ کاربر پیدا نشد")
            return
        if isinstance(result, dict) and result.get("protected_admin"):
            await event.reply("⚠️ این کاربر ادمین است و سکوت نشد")
            return
        target_user = result.get("target_user") if isinstance(result, dict) else None
        if target_user is None:
            await event.reply("❌ انجام سکوت ناموفق بود")
            return
        add_mute(chat_id)
        # ثبت «سکوت دستی»: «آزاد» روی این سکوت عمل نمی‌کند و رفعش فقط
        # با «رفع سکوت» است.
        try:
            from modules import manual_mute_storage
            manual_mute_storage.add_manual_mute(
                chat_id, target_user.id)
        except Exception as mm_error:
            bot.logger.log_error(
                f"MANUAL MUTE MARK FAILED: {mm_error}")
        admin_tools.log_action(
            chat_id, sender, "سکوت کاربر", target=target_user
        )
        try:
            user_history.add_mute(
                chat_id,
                target_user,
                "سکوت دستی توسط مالک یا ادمین",
            )
        except Exception as history_error:
            bot.logger.log_error(
                f"USER HISTORY MUTE FAILED: {history_error}"
            )
        # Bold با ** (Markdown پیش‌فرض). نام کاربری و در نبود
        # آن، نام نمایشی از policy واحد format_user می‌آید.
        await event.reply(
            f"「 {_format_banned_user(target_user, target_user.id)} 」**سکوت دائم شد** 🔊"
        )

    async def fast_mute_failed(_error):
        await event.reply("❌ انجام سکوت ناموفق بود")

    accepted = bot.moderation_queue.enqueue(
        chat_id,
        "mute",
        user_id=f"reply:{reply_id}",
        timeout_seconds=15,
        operation=fast_mute_operation,
        on_success=fast_mute_succeeded,
        on_failure=fast_mute_failed,
    )
    bot.logger.log_info(
        "FAST MODERATION QUEUED "
        f"command=سکوت chat_id={chat_id} reply_id={reply_id} "
        f"accepted={accepted}"
    )
    # Do not send an interim queue acknowledgement.  It costs another outgoing
    # RPC and is misleading when the mute later fails; the callback above sends
    # exactly one final success or failure message.
    return True


# ---------------------------------------------------------------------------
# Command routing
#
# «ثبت اسم علی» و «ثبت ادمین» هر دو با «ثبت » شروع می‌شوند. اگر مسیر حافظهٔ گروه
# با startswith("ثبت ") کار کند، دستور «ثبت ادمین» را می‌بلعد و چون آن مسیر در
# پایان return می‌کند، هرگز به admin handler نمی‌رسد.
#
# راه‌حل: هر دستور چندکلمه‌ای و حساس اینجا صریح ثبت می‌شود و *پیش از* هر
# الگوی عمومی بررسی می‌گردد. ترتیب این tuple اهمیت دارد: طولانی‌ترین و
# دقیق‌ترین دستور اول.
# ---------------------------------------------------------------------------

# (متن دقیق دستور، نام handler مقصد) — هیچ‌کدام نباید به مسیر حافظهٔ گروه بروند.
RESERVED_COMMANDS = (
    # --- مدیریت ادمین و مالک ---
    ("ثبت ادمین", "admin_registration"),
    ("لغو ادمین", "admin_removal"),
    ("برکناری ادمین", "admin_removal"),
    ("ثبت مالک", "group_owner.set"),
    ("لغو مالک", "group_owner.remove"),
    ("برکناری مالک", "group_owner.remove"),
    ("لیست ادمین", "admin_list"),
    # --- مدیریت گروه ---
    ("ثبت گروه", "group_registration"),
    ("حذف گروه", "group_removal"),
    ("ثبت قوانین", "group_rules.set"),
    ("حذف قوانین", "group_rules.remove"),
    ("قوانین", "group_rules.show"),
    # --- حافظه و اطلاعات کاربر ---
    ("ثبت اصل", "user_original.set"),
    ("اصلم", "user_original.show"),
    ("حذف حافظه", "group_memory.remove_other"),
    ("حذف اسم", "group_memory.remove_self"),
    ("حافظه من", "group_memory.show"),
)

# واژهٔ دوم در «ثبت …» که هرگز یک اسم نیست، بلکه نشانهٔ یک دستور مدیریتی است.
# این نگهبان ساختاری تضمین می‌کند حتی اگر دستور تازه‌ای به کد اضافه شود و
# ثبتش در RESERVED_COMMANDS فراموش شود، باز هم به مسیر «ثبت اسم» نشت نکند.
ADMIN_OBJECT_WORDS = frozenset({
    "ادمین", "ادمین‌ها", "ادمینها", "مدیر", "مدیران",
    "مالک", "مالکیت", "صاحب",
    "گروه", "گپ", "چت", "کانال",
    "قوانین", "قانون", "رول", "رولز",
    "اصل", "اصلیت",
    "کاربر", "عضو", "ربات", "بات",
    "فیلتر", "کلمه", "کلمات", "لیست",
})

# پیشوندهایی که مسیر حافظهٔ گروه می‌پذیرد، به ترتیب دقیق‌بودن.
MEMORY_REGISTER_PREFIXES = ("ثبت اسم ", "ثبت ")

# فاصلهٔ مجازی/نیم‌فاصله و نویسه‌های عربی که کاربر ممکن است تایپ کند.
_NORMALIZE_MAP = {
    "\u200c": " ",  # ZWNJ
    "\u200f": "",   # RTL mark
    "\u200e": "",   # LTR mark
    "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
    "\u0643": "\u06a9",  # Arabic kaf -> Persian kaf
}


def normalize_command(text):
    """متن را برای مقایسهٔ دقیق دستور یکسان‌سازی می‌کند.

    فاصله‌های تکراری، نیم‌فاصله و نویسه‌های عربی حذف/تبدیل می‌شوند تا
    «ثبت  ادمین» و «ثبت ادمين» هم درست تشخیص داده شوند. متن اصلی دست‌نخورده
    می‌ماند؛ این فقط برای تصمیم‌گیری routing است.
    """
    if not text:
        return ""
    normalized = str(text)
    for source, target in _NORMALIZE_MAP.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def match_reserved_command(text):
    """اگر متن یک دستور رزروشده باشد، (دستور، handler) را برمی‌گرداند.

    تطبیق دقیق است: یا کل متن برابر دستور است، یا دستور به‌همراه یک آرگومان
    آمده (مثل «ثبت ادمین @ali»). «ثبت اسمی» یا «ثبت ادمینها» تطبیق نمی‌کند.
    """
    normalized = normalize_command(text)
    for command, handler in RESERVED_COMMANDS:
        if normalized == command or normalized.startswith(command + " "):
            return command, handler
    return None, None


def resolve_registration_prefix(text):
    """پیشوند حافظهٔ گروه را برمی‌گرداند، یا None اگر دستور رزروشده باشد.

    این تنها نقطه‌ای است که تصمیم می‌گیرد یک پیام «ثبت …» به حافظهٔ گروه برود.
    """
    # ۱) هر دستور رزروشده مطلقاً بیرون از مسیر ثبت اسم است.
    command, _handler = match_reserved_command(text)
    if command is not None:
        return None

    normalized = normalize_command(text)
    # ۲) «ثبت» یا «ثبت اسم» بدون نام، ثبت نیست.
    if normalized in {"ثبت", "ثبت اسم"}:
        return None

    for prefix in MEMORY_REGISTER_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        remainder = normalized[len(prefix):].strip()
        if not remainder:
            return None
        # ۳) نگهبان ساختاری: «ثبت <واژهٔ مدیریتی>» هرگز ثبت اسم نیست، حتی اگر
        #    آن دستور هنوز در RESERVED_COMMANDS ثبت نشده باشد.
        if prefix == "ثبت " and remainder.split()[0] in ADMIN_OBJECT_WORDS:
            return None
        return prefix
    return None


def _log_command_route(bot, text, matched_command, handler):
    """ردیابی تصمیم routing برای هر دستور حساس."""
    try:
        _debug_log(
            bot,
            "COMMAND ROUTE MATCH "
            f"text={text[:60]!r} "
            f"matched_command={matched_command!r} "
            f"handler={handler!r}",
        )
    except Exception:
        pass


def _can_manage_group_admins(bot, chat_id, user_id, username):
    if is_global_owner(user_id):
        return True

    group_owner_id = get_group_owner(chat_id)
    return group_owner_id is not None and str(user_id) == str(group_owner_id)


DELETE_COMMAND_COOLDOWNS = {}
# قفلِ گروه برای اجرای پاک: فقط یک عملیات حذف در هر گروه در لحظه اجرا می‌شود
# تا چند ادمینِ هم‌زمان روی هم نیفتند و خطای RPC ندهند.
_DELETE_GROUP_LOCKS = {}
# سقفِ حافظهٔ cooldown تا بی‌نهایت رشد نکند.
DELETE_COOLDOWN_MAX_ENTRIES = 2000
ADMIN_PERMISSION_CACHE = {}
ADMIN_PERMISSION_CACHE_TTL_SECONDS = 45
ADMIN_PERMISSION_CACHE_MAX_ENTRIES = 4000


def _has_group_management_permission(bot, chat_id, user_id, username):
    normalized_username = (username or "").lstrip("@").lower()
    cache_key = (chat_id, user_id, normalized_username)
    now = _asyncio.get_running_loop().time()
    cached = ADMIN_PERMISSION_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    if cached:
        ADMIN_PERMISSION_CACHE.pop(cache_key, None)

    group_owner_id = get_group_owner(chat_id)
    if is_global_owner(user_id):
        result, source = True, "global_owner"
    elif group_owner_id is not None and str(user_id) == str(group_owner_id):
        result, source = True, "registered_group_owner"
    elif is_admin(chat_id, user_id, username):
        result, source = True, "registered_group_admin"
    else:
        result, source = False, "none"

    ADMIN_PERMISSION_CACHE[cache_key] = (
        now + ADMIN_PERMISSION_CACHE_TTL_SECONDS, result
    )
    if len(ADMIN_PERMISSION_CACHE) > ADMIN_PERMISSION_CACHE_MAX_ENTRIES:
        for key, (expires_at, _value) in list(ADMIN_PERMISSION_CACHE.items()):
            if expires_at <= now:
                ADMIN_PERMISSION_CACHE.pop(key, None)
        while len(ADMIN_PERMISSION_CACHE) > ADMIN_PERMISSION_CACHE_MAX_ENTRIES:
            ADMIN_PERMISSION_CACHE.pop(next(iter(ADMIN_PERMISSION_CACHE)), None)
    # این helper برای هر پیام گروهی اجرا می‌شود؛ log synchronous فقط در
    # حالت debug نگه داشته می‌شود تا مسیر عادی کاربران I/O اضافی نداشته باشد.
    if result:
        _debug_log(
            bot,
            "ADMIN CHECK DEBUG "
            f"user_id={user_id} username={username} group_id={chat_id} "
            f"result={result} source={source}",
        )
    return result


def _can_delete_messages(bot, chat_id, user_id, username):
    return _has_group_management_permission(
        bot, chat_id, user_id, username
    )


def _delete_group_lock(chat_id):
    """قفلِ per-group برای اجرای پاک (ایجاد lazy)."""
    lock = _DELETE_GROUP_LOCKS.get(chat_id)
    if lock is None:
        lock = _asyncio.Lock()
        _DELETE_GROUP_LOCKS[chat_id] = lock
    return lock


def _prune_delete_cooldowns():
    """حافظهٔ cooldown را محدود نگه می‌دارد تا بی‌نهایت رشد نکند.

    ورودی‌های قدیمی‌تر از پنجرهٔ ۶۰ ثانیه حذف می‌شوند و اگر همچنان بیش از
    سقف باقی بماند، قدیمی‌ترین‌ها پاک می‌شوند.
    """
    now = _asyncio.get_running_loop().time()
    cutoff = now - 60
    stale = [k for k, ts in DELETE_COMMAND_COOLDOWNS.items() if ts < cutoff]
    for k in stale:
        DELETE_COMMAND_COOLDOWNS.pop(k, None)
    while len(DELETE_COMMAND_COOLDOWNS) > DELETE_COOLDOWN_MAX_ENTRIES:
        try:
            oldest = min(DELETE_COMMAND_COOLDOWNS, key=DELETE_COMMAND_COOLDOWNS.get)
            DELETE_COMMAND_COOLDOWNS.pop(oldest, None)
        except (KeyError, ValueError):
            break
    # قفل‌های گروه‌هایی که cooldown آن‌ها دیگر در حافظه نیست هم پاک می‌شوند
    # تا _DELETE_GROUP_LOCKS بی‌نهایت رشد نکند.
    if len(_DELETE_GROUP_LOCKS) > DELETE_COOLDOWN_MAX_ENTRIES:
        keys = list(_DELETE_GROUP_LOCKS.keys())
        for k in keys[:len(keys) - DELETE_COOLDOWN_MAX_ENTRIES]:
            _DELETE_GROUP_LOCKS.pop(k, None)


def _delete_cooldown_allowed(chat_id):
    """بررسی/ثبت cooldown برای کل گروه (نه هر کاربر).

    اگر کمتر از ۵ ثانیه از آخرین پاکِ همین گروه گذشته باشد، False برمی‌گرداند
    (یعنی باید پیام «صبر کنید» بدهیم). در غیر این صورت زمان را ثبت و True
    برمی‌گرداند.
    """
    now = _asyncio.get_running_loop().time()
    last_cleanup = DELETE_COMMAND_COOLDOWNS.get(chat_id)
    if last_cleanup is not None and now - last_cleanup < 5:
        return False
    DELETE_COMMAND_COOLDOWNS[chat_id] = now
    _prune_delete_cooldowns()
    return True


def _loop_now(now=None):
    if now is not None:
        return now
    try:
        return _asyncio.get_running_loop().time()
    except RuntimeError:
        return time.monotonic()


def _task_is_live(task):
    if task is None:
        return False
    done = getattr(task, "done", None)
    try:
        return not (done() if callable(done) else True)
    except Exception:
        return False


def _prune_ttl_cache(cache, now):
    """Drop expired ``(value, expires_at)`` or ``(expires_at, value)`` rows."""
    if not isinstance(cache, dict):
        return 0
    removed = 0
    for key, row in list(cache.items()):
        try:
            expires_at = row[1] if isinstance(row, tuple) and len(row) > 1 else None
        except (TypeError, IndexError):
            expires_at = None
        if expires_at is None or expires_at <= now:
            cache.pop(key, None)
            removed += 1
    return removed


def cleanup_expired_handler_state(bot, now=None):
    """TTL-sweep handler maps owned by the 60s cleanup loop.

    These maps already have expiry on read or a FIFO cap. Without a periodic
    sweep, expired (chat, user) keys stay until restart and the bot slows
    as unique senders accumulate.
    """
    now = _loop_now(now)
    removed = 0
    removed += _prune_ttl_cache(
        getattr(bot, "native_group_admin_cache", None), now
    )
    removed += _prune_ttl_cache(
        getattr(bot, "native_group_admin_ids_cache", None), now
    )
    fail_log = getattr(bot, "_native_admin_fail_logged", None)
    if isinstance(fail_log, dict):
        for key, until in list(fail_log.items()):
            if until <= now:
                fail_log.pop(key, None)
                removed += 1
    for key, (expires_at, _value) in list(ADMIN_PERMISSION_CACHE.items()):
        if expires_at <= now:
            ADMIN_PERMISSION_CACHE.pop(key, None)
            removed += 1
    albums = getattr(bot, "_forward_albums", None)
    if isinstance(albums, dict):
        for key, row in list(albums.items()):
            expires = row.get("expires") if isinstance(row, dict) else None
            if expires is None or expires <= now:
                albums.pop(key, None)
                removed += 1
    timers = getattr(bot, "group_timer_tasks", None)
    if isinstance(timers, dict):
        for chat_id, tasks in list(timers.items()):
            live = set()
            for task in list(tasks or ()):
                if _task_is_live(task):
                    live.add(task)
                else:
                    removed += 1
            if live:
                timers[chat_id] = live
            else:
                timers.pop(chat_id, None)
    incident_ttl = 10 * 60
    incidents = getattr(bot, "_spam_cleanup_incidents", None) or {}
    auto_tasks = getattr(bot, "_auto_spam_cleanup_tasks", None) or {}
    pending = getattr(bot, "_auto_spam_cleanup_pending", None) or {}
    big = getattr(bot, "_big_spam_incidents", None) or {}
    for key, incident in list(incidents.items()):
        if not isinstance(incident, dict):
            incidents.pop(key, None)
            removed += 1
            continue
        big_inc = big.get(key)
        big_task = (
            big_inc.get("cleanup_task") if isinstance(big_inc, dict) else None
        )
        if (
            _task_is_live(incident.get("notice_task"))
            or _task_is_live(auto_tasks.get(key))
            or _task_is_live(big_task)
        ):
            continue
        touched = float(incident.get("_touched_at") or 0)
        if touched and now - touched < incident_ttl:
            continue
        incidents.pop(key, None)
        pending.pop(key, None)
        removed += 1
    for key, task in list(auto_tasks.items()):
        if not _task_is_live(task):
            auto_tasks.pop(key, None)
            removed += 1
    for key, incident in list(big.items()):
        if not isinstance(incident, dict):
            big.pop(key, None)
            removed += 1
            continue
        if _task_is_live(incident.get("cleanup_task")):
            continue
        if incident.get("ban_state") == "pending":
            deadline = incident.get("ban_absolute_deadline")
            if deadline is not None and now < float(deadline):
                continue
        touched = float(incident.get("_touched_at") or 0)
        if touched and now - touched < incident_ttl:
            continue
        big.pop(key, None)
        removed += 1
    return removed


# Commands which belong to this bot must never be interpreted as an AI/search
# prompt merely because they are sent as a reply to a bot message.  Keep this
# routing guard deliberately side-effect free: it only tells the search route
# to stand down, so the existing command handlers below remain authoritative.
_INTERNAL_EXACT_COMMANDS = frozenset({
    "تست دکمه", "راهنما", "لیست بازی", "لیست بازی ها", "لیست بازی‌ها",
    "سرگرمی خاموش", "سرگرمی فعال",
    "لیست کاربران", "لیست ادمین", "لیست ادمینی", "آمارم", "بیوگرافی",
    "یاد آوری", "ترجمه", "قفل", "باز", "جک", "تصحیح کلمات",
    "اسم فامیل", "حدس ایموجی", "حدس پرچم", "چهار گزینه ای", "جای خالی", "چیستان",
    "کی بیشتر بلده", "دروغ یا حقیقت",
    "دانستنی", "حافظه من", "حذف اسم", "حذف حافظه", "قوانین",
    "ثبت قوانین", "حذف قوانین", "ثبت اصل", "اصلم", "موجودی", "فروشگاه",
    "انتقال سکه", "سکوت", "رفع سکوت", "آزاد", "اخطار", "اخراج", "بن",
    "سنجاق", "پیام سنجاق", "پاک", "ریست آمار", "ریست اخراجی ها",
    "سطح گروه", "سابقه ها", "سابقه‌ها", "راهنمای امتیاز", "امتیاز من",
    "رتبه ها", "رتبه‌ها", "فعال سازی", "فعال", "غیر فعال",
    "لغو کلمات ممنوعه", "فعال کلمات ممنوعه", "پاکسازی خودکار",
    "ثبت ادمین", "لغو ادمین", "برکناری ادمین", "ثبت مالک", "لغو مالک",
    "برکناری مالک", "ثبت گروه", "حذف گروه", "حذف اخطار", "حذف اخطارها",
    "تغییر اخطار", "تغییر مجازات",
    "لاگ مدیریتی", "مین یاب", "بهترین جواب", "نبرد", "بخند یا بباز",
    "وضعیت ربات", "پینگ ربات",
    "سایت بازی", "سایت", "لینک بازی", "/game", "/site",
    "جعبه شانسی", "خون آشام", "خون‌آشام", "جرعت", "جرات", "جرئت",
    "حقیقت", "حقیقت بگو", "ربات", "روباه", "/help", "!help", "help",
}) | frozenset(command for command, _handler in RESERVED_COMMANDS) | FOX_GAME_COMMANDS | EMOJI_RESET_COMMANDS


def _is_known_internal_command(clean_text, chat_id, user_id):
    """Whether a message belongs to an existing command/game route.

    This is intentionally checked only by the Google-search gateway.  It does
    not execute, authorize, or otherwise change the downstream command logic.
    """
    if clean_text in _INTERNAL_EXACT_COMMANDS:
        return True
    if clean_text.startswith(("!", "/", ".")):
        return True
    if clean_text.startswith((
        "ثبت ", "ثبت اسم ", "شخصیت ", "جستجو ", "فونت ",
        "فیلتر کلمه", "حذف کلمه", "افزودن کلمه", "ثبت کلمه",
        "لیست کلمات", "پاک کردن کلمات",
    )):
        return True
    # During a game, answers must be delivered to that game's existing handler
    # rather than being consumed as a factual-search prompt.
    return bool(
        name_family_active(chat_id)
        or fox_game_active(chat_id)
        or emoji_guess_active(chat_id)
        or flag_guess_active(chat_id)
        or get_correction(chat_id) is not None
        or get_active_question(chat_id) is not None
        or get_fill_token(chat_id, user_id) is not None
        or get_riddle_token(chat_id, user_id) is not None
        or _who_knows.is_active(chat_id)
        or _truth_lie.is_active(chat_id)
    )


def _search_reply_message_id(event):
    message = getattr(event, "message", None)
    message_reply = getattr(message, "reply_to", None)
    return (
        getattr(message, "reply_to_msg_id", None)
        or getattr(message_reply, "reply_to_msg_id", None)
        or getattr(message_reply, "reply_to_top_id", None)
        or getattr(event, "reply_to_msg_id", None)
        or getattr(getattr(event, "reply_to", None), "reply_to_msg_id", None)
    )


async def _handle_google_search_group_message(bot, event, chat_id, user_id, sender,
                                   clean_text, message_text):
    """Handle Google Search administration and eligible prompts for one group."""
    if event.is_private:
        return False
    sender_username = getattr(sender, "username", None)
    can_manage = admin_tools.has_admin_permission(chat_id, user_id, sender_username)

    if clean_text in {"هوش مصنوعی فعال", "هوش مصنوعی خاموش"}:
        if not can_manage:
            await event.reply("❌ فقط مالک یا ادمین‌های گروه اجازه مدیریت هوش مصنوعی را دارند")
            return True
        enabled = clean_text == "هوش مصنوعی فعال"
        search_access.set_enabled(chat_id, enabled)
        bot.logger.log_info(
            f"SEARCH ACCESS COMMAND chat_id={chat_id} user_id={user_id} enabled={enabled}"
        )
        await event.reply(
            "✅ هوش مصنوعی گوگل این گروه فعال شد." if enabled
            else "✅ هوش مصنوعی گوگل این گروه خاموش شد."
        )
        return True

    is_grant_command = clean_text == "مجاز" or clean_text.startswith("مجاز @")
    is_revoke_command = clean_text in {"غیرمجاز", "غیر مجاز"} or clean_text.startswith("غیر مجاز @") or clean_text.startswith("غیرمجاز @")
    if is_grant_command or is_revoke_command:
        if not can_manage:
            await event.reply("❌ فقط مالک یا ادمین‌های گروه اجازه مدیریت هوش مصنوعی را دارند")
            return True
        reply_id = _search_reply_message_id(event)
        target = None
        if reply_id:
            reply_message = await bot.client.get_messages(chat_id, ids=reply_id)
            target = await reply_message.get_sender() if reply_message else None
        else:
            # Support the documented direct form: «مجاز @username».
            parts = message_text.strip().split()
            username_arg = next((part for part in parts[1:] if part.startswith("@")), None)
            if username_arg:
                try:
                    target = await bot.client.get_entity(username_arg)
                except Exception as error:
                    bot.logger.log_error(
                        f"SEARCH ACCESS USER RESOLVE FAILED chat_id={chat_id} username={username_arg!r} error={error!r}"
                    )
        if not target:
            await event.reply("❌ باید روی پیام کاربر ریپلای کنید یا @username وارد کنید")
            return True
        if is_grant_command:
            saved = search_access.allow(chat_id, target)
            enabled_now, allowed_now = search_access.access_state(chat_id, target.id)
            bot.logger.log_info(
                "SEARCH ACCESS COMMAND "
                f"chat_id={chat_id} target_user_id={target.id} "
                f"enabled={enabled_now} allowed={allowed_now} saved={saved}"
            )
            if saved and allowed_now:
                await event.reply(
                    f"✅ کاربر : {format_user(target)}\n\n"
                    "به لیست کاربران مجاز هوش مصنوعی گوگل اضافه شد."
                )
            else:
                await event.reply("❌ ذخیره دسترسی هوش مصنوعی گوگل انجام نشد.")
        elif is_revoke_command and search_access.disallow(chat_id, target.id):
            await event.reply("✅ دسترسی هوش مصنوعی گوگل کاربر حذف شد.")
        else:
            await event.reply("⚠️ این کاربر در لیست کاربران مجاز هوش مصنوعی گوگل نیست.")
        return True

    if clean_text == "لیست هوش مصنوعی":
        if not can_manage:
            await event.reply("❌ فقط مالک یا ادمین‌های گروه اجازه مشاهده این لیست را دارند")
            return True
        rows = search_access.allowed_users(chat_id)
        if not rows:
            await event.reply("📋 هنوز کاربری برای هوش مصنوعی مجاز نشده است.")
            return True
        lines = ["✅ کاربران مجاز جستجوی گوگل:\n"]
        for index, row in enumerate(rows, 1):
            username = str(row.get("username") or "").strip().lstrip("@")
            shown = "@" + username if username else row.get("display", "کاربر ناشناس")
            lines.append(f"{index}- {shown}")
        await event.reply("\n".join(lines))
        return True

    # Search administration above remains owned by this module. Every other
    # known bot command must continue through the normal command/game route.
    if _is_known_internal_command(clean_text, chat_id, user_id):
        _debug_log(
            bot,
            "SEARCH ROUTE SKIPPED internal_command "
            f"chat_id={chat_id} user_id={user_id} command={clean_text!r}",
        )
        return False

    enabled, allowed_user = search_access.access_state(chat_id, user_id)
    reply_id = _search_reply_message_id(event)
    request_text = message_text.strip()
    is_information_request, topic = web_search.factual_intent(request_text)
    if not enabled or not allowed_user or not reply_id or not is_information_request:
        return False
    bot.logger.log_info(
        "AI ACCESS CHECK "
        f"user_id={user_id} chat_id={chat_id} enabled={enabled} "
        f"allowed={allowed_user} reply_id={reply_id or 'none'} "
        f"text_length={len(request_text)}"
    )
    try:
        reply_message = await bot.client.get_messages(chat_id, ids=reply_id)
    except Exception as error:
        bot.logger.log_error(
            f"SEARCH REPLY LOAD FAILED chat_id={chat_id} reply_id={reply_id} error={error!r}"
        )
        return False
    if not reply_message:
        return False
    reply_sender_id = getattr(reply_message, "sender_id", None)
    if reply_sender_id is None:
        reply_sender = await reply_message.get_sender()
        reply_sender_id = getattr(reply_sender, "id", None)
    if str(reply_sender_id) != str(getattr(bot, "bot_account_id", None)):
        return False
    replied_text = (getattr(reply_message, "message", None) or getattr(reply_message, "caption", None) or "").strip()
    query = f"{replied_text} {topic}".strip()

    async def answer_from_public_source():
        try:
            bot.logger.log_info(
                f"AI REQUEST PROCESS START chat_id={chat_id} user_id={user_id} query_length={len(query)}"
            )
            try:
                answer = await _asyncio.to_thread(
                    web_search.search_factual, topic, request_text
                )
            except web_search.FactualSearchError as primary_error:
                # Wikipedia remains a secondary factual fallback only.
                bot.logger.log_info(
                    f"SEARCH PROVIDER FALLBACK provider=DuckDuckGo reason={primary_error!s}"
                )
                answer = await _asyncio.to_thread(wiki_search_service.answer, query)
            await event.reply(answer)
            bot.logger.log_info(
                f"AI RESPONSE SENT chat_id={chat_id} user_id={user_id} chars={len(answer)}"
            )
        except (web_search.FactualSearchError, wiki_search_service.WikiSearchError) as error:
            bot.logger.log_error(
                f"SEARCH RESPONSE ERROR chat_id={chat_id} user_id={user_id} reason={error!s}"
            )
            await event.reply("ℹ️ اطلاعات کافی و قابل‌اعتمادی برای پاسخ پیدا نشد.")
        except Exception as error:
            bot.logger.log_error(
                f"SEARCH RESPONSE ERROR chat_id={chat_id} user_id={user_id} error={error!r}"
            )

    _asyncio.create_task(answer_from_public_source(), name="web:public-source")
    return True


async def handle_new_message(bot, event):
    """هندلر اصلی برای پیام‌های جدید"""
    profiler = MessagePerformance()
    response_token = begin_response_measurement()
    chat_id = getattr(event, "chat_id", None)
    try:
        # SPAM DEBUG INCOMING — اولین خط handler قبل از هر فیلتر
        try:
            _dbg_raw = getattr(getattr(event, 'message', None), 'message', '') or getattr(getattr(event, 'message', None), 'caption', '') or ""
            _dbg_chat = getattr(event, 'chat_id', None)
            _dbg_mid = getattr(getattr(event, 'message', None), 'id', None)
            _dbg_sender_tmp = getattr(event, 'sender', None)
            _dbg_sid = getattr(_dbg_sender_tmp, 'id', None) if _dbg_sender_tmp else getattr(event, 'sender_id', None)
            # fallback: try event.get_sender not awaited, keep unknown
            import hashlib as _hl_tmp
            _dbg_hash = _hl_tmp.md5(str(_dbg_raw).encode('utf-8', errors='ignore')).hexdigest()[:8] if _dbg_raw else "empty"
            _dbg_len = len(str(_dbg_raw))
            _debug_log(bot, f"SPAM DEBUG INCOMING chat_id={_dbg_chat} message_id={_dbg_mid} sender_id={_dbg_sid} text_hash={_dbg_hash} text_length={_dbg_len}")
        except Exception as _dbg_e:
            try:
                bot.logger.log_error(f"SPAM DEBUG INCOMING failed { _dbg_e!r}")
            except: pass
        # اگر پیام متنی نیست رد کن (مثلا سرویس)
        if not event.message or not hasattr(event.message, 'message'):
            try:
                _er_chat = getattr(event, 'chat_id', None)
                _er_mid = getattr(getattr(event, 'message', None), 'id', None)
                _debug_log(bot, f"SPAM DEBUG EARLY RETURN reason=no_message_attr chat_id={_er_chat} message_id={_er_mid}")
            except: pass
            return

        # اطلاعات پیام
        message_text = getattr(event.message, "message", "") or ""
        _debug_log(bot,
            "MESSAGE HANDLER ENTER "
            f"chat_id={getattr(event, 'chat_id', None)} "
            f"user_id={getattr(getattr(event, 'sender', None), 'id', None)} "
            f"message_id={getattr(event.message, 'id', None)} "
            f"text={message_text!r}"
        )
        # برای کپشن عکس/فایل هم چک کن
        if not message_text and hasattr(
                event.message, 'file') and event.message.file:
            # اگر فایل دارد، نام فایل یا کپشن را چک کن
            try:
                caption = getattr(event.message, 'caption', None) or ""
                message_text = caption
            except BaseException:
                pass

        if not getattr(event, "is_private", False):
            try:
                early_command = normalize_command(message_text)
                if is_fast_owner_command(early_command):
                    if await handle_fast_owner_command(bot, event, early_command):
                        return
            except Exception as fast_error:
                bot.logger.log_error(
                    "FAST OWNER COMMAND FALLBACK "
                    f"chat_id={getattr(event, 'chat_id', None)} "
                    f"error={fast_error!r}"
                )

        # Core may have resolved these already; prefer the per-bot InputPeer
        # cache and event fields before asking SPlusthon to resolve a chat.
        event_chat = (getattr(event, "_bot_cached_chat", None)
                      or getattr(event, "chat", None))
        cached_peer = getattr(bot, "reply_input_peer_cache", {}).get(
            getattr(event, "chat_id", None)
        )
        if event_chat is None and cached_peer is None:
            event_chat = await event.get_chat()
        chat_id = getattr(event_chat, "id", event.chat_id) if event_chat else event.chat_id
        _warm_reply_input_chat(bot, event, event_chat)
        sender = (getattr(event, "_bot_cached_sender", None)
                  or getattr(event, "sender", None))
        if sender is None:
            try:
                sender = await event.get_sender()
            except Exception:
                sender = None
        user_id = sender.id if sender else (getattr(event, "sender_id", None) or 0)
        if sender is None and user_id:
            try:
                sender = await bot.client.get_entity(user_id)
                event._bot_cached_sender = sender
            except Exception:
                pass

        # Big-spam incidents are the sole opt-in per-message ID registry.
        # Capture before any later return/lock branch can race this event.
        _capture_big_spam_message(
            bot, chat_id, user_id, getattr(event.message, "id", None)
        )
        # پیام‌های معمولیِ اکانت سشن نباید وارد moderation شوند، اما همین
        # اکانت در سروش نقش رابط ربات را هم دارد و مالک با آن «راهنما» و
        # «روباه» را می‌فرستد. بازگرداندنِ همهٔ event.out ها باعث می‌شد فقط
        # مسیرهای مدیریتیِ زودهنگام کار کنند و فرمان‌های عمومی بی‌صدا شوند.
        # فقط فرمان‌های شناخته‌شدهٔ خود اکانت اجازهٔ عبور دارند؛ پاسخ‌های
        # تولیدشدهٔ ربات و چت عادی همچنان برای جلوگیری از حلقه رد می‌شوند.
        if user_id and user_id == getattr(bot, "bot_account_id", None):
            own_text = normalize_command(message_text)
            _own_priority, own_kind = classify_priority(own_text, event)
            if own_kind not in {"admin", "command"}:
                return
            bot.logger.log_info(
                f"SELF COMMAND ALLOWED chat_id={chat_id} command={own_text!r}"
            )

        # A captionless ordinary media message has no text to inspect.  Return
        # before the tracker and every text-only route (commands, word filters,
        # repeat/flood text checks and SpamDetector).  GIFs and forwards keep
        # their dedicated anti-abuse paths below, because those checks inspect
        # media/forward metadata rather than text.
        has_text_content = bool(message_text.strip())
        is_forwarded_media, _early_fwd_field, _early_fwd_fields = (
            _get_forward_metadata(event.message, event)
        )
        is_gif_media = is_gif_message(event.message)
        if not has_text_content and not is_forwarded_media and not is_gif_media:
            return

        sender_username = (getattr(sender, "username", None) or "").lstrip("@").lower()
        # Current group authority is checked before every spam cache, banned
        # storage, tracker and lock path. Historical spam state cannot outrank
        # a current owner/admin role.
        registered_admin_bypass = bool(
            not event.is_private and admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            )
        )
        # Native Soroush role is only needed to authorize management
        # commands. Regular chat and filter paths must not call
        # get_permissions (KeyError + one RTT per ordinary user).
        resolved_permission_chat = (
            event_chat
            or _resolved_event_peer(event)
            or getattr(bot, "reply_input_peer_cache", {}).get(
                getattr(event, "chat_id", None)
            )
        )
        native_admin_bypass = bool(
            _should_check_native_admin(
                event.is_private, registered_admin_bypass, message_text
            )
            and await _is_native_group_admin(
                bot, chat_id, user_id, sender, resolved_permission_chat
            )
        )
        # A native group admin who is not registered in the bot follows the
        # warning counter, but can never enter automatic delete/ban/mute state.
        # Registered bot admins retain the existing full bypass policy.
        native_admin_warn_only = native_admin_bypass and not registered_admin_bypass
        admin_bypass = registered_admin_bypass
        blocked_cache = bot.is_spam_locked((chat_id, user_id))
        if native_admin_warn_only and blocked_cache:
            # This is stale state created before the native role was known.
            # It must not delete the current or later admin messages.
            state_cleared = _clear_native_admin_moderation_state(
                bot, chat_id, user_id, force=True
            )
            blocked_cache = False
        else:
            state_cleared = False
        if not native_admin_bypass:
            getattr(bot, "native_admin_state_cleared", set()).discard(
                (normalize_group_id(chat_id), str(user_id))
            )
        _debug_log(bot,
            "ADMIN BYPASS CHECK "
            f"user_id={user_id} group_id={chat_id} "
            f"registered_admin={registered_admin_bypass} "
            f"native_group_admin={native_admin_bypass} "
            f"state_cleared={state_cleared} is_admin={admin_bypass} "
            f"blocked_cache={blocked_cache} spam_history={False if admin_bypass else 'unchecked'}"
        )
        status_key = _punishment_key(chat_id, user_id)
        tracker_is_banned = getattr(bot.tracker, "is_banned", None)
        tracker_is_muted = getattr(bot.tracker, "is_muted", None)
        status_banned = False if admin_bypass else (
            is_banned(chat_id, user_id, getattr(sender, "username", None))
            or (tracker_is_banned(chat_id, user_id)
                if callable(tracker_is_banned) else False)
            or blocked_cache
        )
        status_muted = False if admin_bypass else (
            tracker_is_muted(chat_id, user_id)
            if callable(tracker_is_muted) else False
        )
        history_count = 0 if admin_bypass else len(get_user_history(chat_id, user_id) or [])
        _debug_log(bot,
            "USER MODERATION STATUS "
            f"user_id={user_id} is_banned={status_banned} "
            f"spam_score={bot.tracker.get_count(chat_id, user_id)} "
            f"history_count={history_count} group_id={chat_id}"
        )
        _debug_log(bot,
            "USER MODERATION STATUS DETAIL "
            f"user_id={user_id} group_id={chat_id} "
            f"is_banned={status_banned} is_muted={status_muted} "
            f"warning_count={bot.tracker.get_count(chat_id, user_id)} "
            f"spam_count={bot.tracker.get_count(chat_id, user_id)}"
        )
        # === SPAM FLOW TRACE: BEFORE_TRACKER ===
        _trace_msg_id = getattr(event.message, "id", None)
        _trace_hist_before = 0 if admin_bypass else len(message_tracker.get_user_recent_messages(chat_id, user_id))
        _debug_log(bot,
            f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={_trace_msg_id} stage=BEFORE_TRACKER hist_before={_trace_hist_before} bot_id={id(bot)} lock_id={id(getattr(bot, 'spam_lock', set()))}"
        )
        # Track every incoming group message before the spam-lock early drop;
        # otherwise messages after the first threshold hit never enter history.
        # Management commands skip tracker/big-spam/forward so بن/قفل/پاک
        # do not wait on those inspections.
        skip_inspect = (not event.is_private) and _is_management_command(
            message_text
        )
        tracked_ok = False if admin_bypass or skip_inspect else message_tracker.add_message(
            chat_id, user_id, getattr(event.message, "id", None), message_text
        )
        _trace_hist_after = 0 if admin_bypass else len(message_tracker.get_user_recent_messages(chat_id, user_id))
        _debug_log(bot,
            f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={_trace_msg_id} stage=AFTER_TRACKER tracked_ok={tracked_ok} hist_after={_trace_hist_after}"
        )
        if tracked_ok:
            _debug_log(bot,
                "SPAM TRACK ADD "
                f"chat_id={chat_id} user_id={user_id} "
                f"message_id={getattr(event.message, 'id', None)} "
                f"history_size_after_add={len(message_tracker.get_user_recent_messages(chat_id, user_id))}"
            )
        # Banned words run before the spam/burst filter so obfuscated
        # forms map to the original listed word, not to generic flood.
        banned_precheck = False
        banned_precheck_reason = None
        if (not skip_inspect and not event.is_private and not admin_bypass
                and not native_admin_warn_only):
            banned_precheck, banned_precheck_reason = bot.detector.check_banned_words(
                message_text, chat_id
            )
            if banned_precheck:
                bot.logger.log_info(
                    "BANNED WORD PRECHECK "
                    f"chat_id={chat_id} user_id={user_id} "
                    f"reason=banned_word detail={banned_precheck_reason!r} "
                    f"text={message_text[:60]!r}"
                )

        # Fast lane for promotional/repeated payloads: it runs immediately
        # after the in-memory tracker update. Two clearly similar ads, or
        # one packed promotional box, queue the ban and start cleanup now.
        if (not skip_inspect and not event.is_private and not admin_bypass
                and not native_admin_warn_only):
            big_spam, big_reason, big_ids = _big_repeated_spam(
                chat_id, user_id, message_text
            )
            if big_spam:
                current_id = getattr(event.message, "id", None)
                if current_id:
                    big_ids.add(current_id)
                if banned_precheck:
                    big_reason = f"spam_banned_word {banned_precheck_reason}"
                    bot.logger.log_info(
                        "SPAM BANNED WORD "
                        f"chat_id={chat_id} user_id={user_id} "
                        f"reason={big_reason!r}"
                    )
                _queue_big_spam_ban(
                    bot, event, chat_id, user_id, sender, big_ids, big_reason
                )
                return

        # Single-forward delete runs here, before command/game/filter routes.
        # A forwarded «راهنما» or a captionless album item must not skip
        # this path. Consecutive-forward mute still uses the same counter.
        if not event.is_private and not skip_inspect:
            album_ids = _album_forward_ids(
                bot, chat_id, event.message, is_forwarded_media
            )
            if (
                (is_forwarded_media or album_ids)
                and not admin_bypass
                and not native_admin_warn_only
            ):
                profiler.mark("FORWARD_CHECK")
                _handle_forwarded_group_message(
                    bot, event, chat_id, user_id, sender, sender_username,
                    is_forwarded=is_forwarded_media,
                    forward_field=_early_fwd_field,
                    forward_fields=_early_fwd_fields,
                    delete_ids=album_ids,
                )
                return

        spam_lock_key = (chat_id, user_id)
        _is_locked = False if admin_bypass else bot.is_spam_locked(spam_lock_key)
        _lock_size = len(getattr(bot, "spam_lock", set()))
        _debug_log(bot,
            f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={_trace_msg_id} stage=BEFORE_SPAM_LOCK key={spam_lock_key!r} is_locked={_is_locked} lock_size={_lock_size} chat_id_type={type(chat_id).__name__} user_id_type={type(user_id).__name__}"
        )
        if (not event.is_private
                and not admin_bypass
                and not native_admin_warn_only
                and bot.is_spam_locked(spam_lock_key)):
            if _spam_runtime_key(chat_id, user_id) in getattr(bot, "_big_spam_incidents", {}):
                # Ban and drain are already running. The ID was captured
                # before this branch and will be deleted with the incident.
                bot.logger.log_info(
                    "BIG SPAM MESSAGE DEFERRED "
                    f"chat_id={chat_id} user_id={user_id} "
                    f"message_id={event.message.id}"
                )
                return
            _debug_log(bot,
                f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={_trace_msg_id} stage=INSIDE_SPAM_LOCK"
            )
            _queue_message_deletes(bot, chat_id, [event.message.id])
            _debug_log(bot, f"SPAM LOCK DROP QUEUED chat_id={chat_id} user_id={user_id} message_id={event.message.id}")
            locked_ids = message_tracker.spam_snapshot(
                chat_id, user_id, getattr(event.message, "id", None)
            )
            _debug_log(bot,
                f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={_trace_msg_id} stage=SNAPSHOT_COUNT count={len(locked_ids)} ids={locked_ids!r} snapshot_source=spam_snapshot"
            )
            _schedule_auto_spam_cleanup(
                bot, event, chat_id, user_id, set(locked_ids)
            )
            _debug_log(bot,
                f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} "
                f"message_id={_trace_msg_id} stage=CLEANUP_QUEUED "
                f"requested={len(locked_ids)}"
            )
            _debug_log(bot, "EARLY RETURN DEBUG reason=spam_lock "
                f"chat_id={chat_id} user_id={user_id} message_id={event.message.id}")
            return
        profiler.mark("RECEIVE")
        # Independent advertising-name guard: runs before text moderation and
        # never contributes a warning or banned-word record.
        command_priority = normalize_command(message_text) in {
            "راهنما", "لیست بازی", "لیست بازی ها", "لیست بازی‌ها",
            "لیست ادمین", "لیست ادمینی", "لیست کاربران", "رتبه ها", "رتبه‌ها",
            "موجودی", "فروشگاه", "انتقال سکه", "قفل", "باز", "اخطار",
            "حدس ایموجی", "حدس جمله", "ساخت جمله", "معما", "حدس پرچم",
            "مین یاب", "سابقه ها", "سابقه‌ها", "سطح گروه",
            "فعال", "غیر فعال", "فعال سازی",
            "ثبت مالک", "لغو مالک", "برکناری مالک",
            "ثبت گروه", "حذف گروه",
            "۵ روز", "یک هفته", "دو هفته", "یک ماه",
        }
        if (sender and not event.is_private and not command_priority
                and not is_global_owner(user_id)
                and not native_admin_warn_only):
            if not admin_tools.has_admin_permission(chat_id, user_id, sender_username):
                ad_reason = ad_name_detector.reason(sender)
                if ad_reason:
                    # Claim the incident before any await. A burst can produce
                    # several NewMessage events before the kick RPC completes;
                    # only its first event may queue the ban or later notify.
                    punish_key = _punishment_key(chat_id, user_id)
                    if punish_key in bot.punished_users:
                        bot.logger.log_info(
                            "AD NAME INCIDENT DUPLICATE SKIPPED "
                            f"chat_id={chat_id} user_id={user_id} "
                            f"message_id={getattr(event.message, 'id', None)}"
                        )
                        return
                    bot.punished_users.add(punish_key)
                    shown_name = ad_name_detector.display_name(sender)
                    if punishment_mode.is_mute(chat_id):
                        ad_action_line = "به دلیل داشتن نام تبلیغاتی و لینک سکوت دائم شد."
                    else:
                        ad_action_line = "به دلیل داشتن نام تبلیغاتی و لینک اخراج شد."
                    notice = (
                        "⚠️ کاربر\n"
                        f"{shown_name}\n\n"
                        f"{ad_action_line}"
                    )

                    async def ad_name_ban_succeeded(_result):
                        # The announcement is deliberately after the real ban
                        # succeeds, and is owned by this one incident only.
                        sender3 = getattr(bot, "outgoing_sender", None)
                        if sender3 is not None:
                            # Use outgoing queue so this notice does not block moderation worker
                            try:
                                name_start = len("⚠️ کاربر\n".encode("utf-16-le")) // 2
                                name_len = len(shown_name.encode("utf-16-le")) // 2
                                bold_len = len("⚠️ کاربر".encode("utf-16-le")) // 2
                                entities = [
                                    MessageEntityBold(offset=0, length=bold_len),
                                    MessageEntityBlockquote(offset=name_start, length=name_len),
                                ]
                                sender3.enqueue_reply(event, notice, formatting_entities=entities, on_done=lambda sent: capture_sent(bot, chat_id, sent))
                            except Exception:
                                sender3.enqueue_reply(event, notice, on_done=lambda sent: capture_sent(bot, chat_id, sent))
                        else:
                            try:
                                name_start = len("⚠️ کاربر\n".encode("utf-16-le")) // 2
                                name_len = len(shown_name.encode("utf-16-le")) // 2
                                bold_len = len("⚠️ کاربر".encode("utf-16-le")) // 2
                                sent = await event.reply(notice, formatting_entities=[
                                    MessageEntityBold(offset=0, length=bold_len),
                                    MessageEntityBlockquote(
                                        offset=name_start, length=name_len
                                    ),
                                ])
                            except Exception:
                                sent = await event.reply(notice)
                            capture_sent(bot, chat_id, sent)
                        bot.logger.log_info(
                            "AD NAME BAN FINISHED "
                            f"chat_id={chat_id} user_id={user_id} "
                            f"reason={ad_reason!r} notification_sent=True"
                        )

                    async def ad_name_ban_failed(error):
                        # A failed RPC must be retryable by a later event; it
                        # must not leave a permanent in-memory incident lock.
                        bot.punished_users.discard(punish_key)
                        bot.logger.log_error(
                            "AD NAME BAN FAILED "
                            f"chat_id={chat_id} user_id={user_id} error={error!r}"
                        )

                    queued = bot.moderation_queue.enqueue(
                        chat_id,
                        "ban",
                        user_id=user_id,
                        timeout_seconds=45,
                        operation=lambda: bot.admin_actions.ban_user(
                            chat_id, user_id, reason="نام تبلیغاتی",
                            user=sender,
                        ),
                        on_success=ad_name_ban_succeeded,
                        on_failure=ad_name_ban_failed,
                    )
                    if not queued:
                        bot.punished_users.discard(punish_key)
                        bot.logger.log_info(
                            "AD NAME INCIDENT QUEUE DUPLICATE "
                            f"chat_id={chat_id} user_id={user_id}"
                        )
                    else:
                        bot.logger.log_info(
                            "AD NAME BAN QUEUED "
                            f"chat_id={chat_id} user_id={user_id} "
                            f"name={shown_name!r} reason={ad_reason!r}"
                        )
                    return
        # حساب سشن نباید وارد activity، فیلتر یا مجازات شود. با این حال، در
        # معماری userbot مالک همان حساب برای صدور فرمان عمومی استفاده می‌کند.
        # پیش‌تر این گیتِ دوم، فرمانی را که از گیت اول عبور کرده بود دوباره
        # می‌بلعید و «راهنما»/«روباه» هیچ‌وقت به handler نمی‌رسیدند.
        clean_text = normalize_command(message_text)
        is_session_account = user_id == getattr(bot, "bot_account_id", None)
        is_named_bot_account = sender_username in {"aifox", "osine2"}
        _self_priority, self_command_kind = classify_priority(clean_text, event)
        is_session_command = (
            is_session_account and self_command_kind in {"admin", "command"}
        )
        if ((is_session_account or is_named_bot_account)
                and not is_global_owner(user_id)
                and not is_session_command):
            if message_text.strip() == "اسم فامیل" or len(message_text.splitlines()) >= 7:
                bot.logger.log_info(
                    "NAME FAMILY TRACE HANDLER_BLOCK "
                    f"reason=bot_account chat_id={chat_id} user_id={user_id}"
                )
            bot.logger.log_info(
                "EARLY RETURN DEBUG reason=bot_account "
                f"chat_id={chat_id} user_id={user_id} message_id={event.message.id}"
            )
            return
        # Normalize only the routing copy; keep message_text unchanged for filters.
        # COMMAND_MATCH is the cheap text classify only — never include
        # get_entity / search / economy time in this stage.
        profiler.mark("COMMAND_MATCH")
        # 📢 مسیر گروهی اطلاع‌رسانی: فقط مالک اصلی ربات؛ همان workflow پیوی.
        # قبل از هر هندلر دیگری چک می‌شود تا بدنهٔ اطلاعیه (متن آزاد) توسط
        # بازی/حافظه/جستجو بلعیده نشود. برای بقیهٔ کاربران فقط یک مقایسهٔ
        # ارزان is_global_owner است.
        if not getattr(event, "is_private", False) and is_global_owner(user_id):
            try:
                from handlers.broadcast_handler import handle_group_broadcast
                if await handle_group_broadcast(bot, event, user_id, message_text):
                    return
            except Exception as broadcast_error:
                bot.logger.log_error(
                    "GROUP BROADCAST ROUTE FAILED "
                    f"chat_id={chat_id} error={broadcast_error!r}"
                )
        _legacy_commands = {
            "راهنما", "لیست بازی", "لیست بازی ها", "لیست بازی‌ها",
            "لیست ادمین", "لیست ادمینی", "لیست کاربران", "رتبه ها", "رتبه‌ها",
            "موجودی", "فروشگاه", "انتقال سکه", "قفل", "باز", "اخطار",
            "سابقه ها", "سابقه‌ها", "سطح گروه",
        }
        _debug_log(
            bot,
            "PUBLIC COMMAND ROUTE ENTER "
            f"chat_id={chat_id} user_id={user_id} text={message_text!r} "
            f"normalized={clean_text!r}",
        )
        _debug_log(
            bot,
            "COMMAND MATCH CHECK "
            f"command={clean_text!r} matched={clean_text in _legacy_commands}",
        )

        # ------------------------------------------------------------------
        # 📋 لیست انقضا — فقط مالک اصلی و فقط در همان گروه.
        # این گزارش فقط خواندنی است؛ storage و watcher اصلی انقضا را تغییر
        # نمی‌دهد و هیچ route خصوصی برای آن لازم نیست.
        # ------------------------------------------------------------------
        if not event.is_private and clean_text == "لیست انقضا":
            owner = get_owner()
            authorized = is_global_owner(user_id)
            bot.logger.log_info(
                "EXPIRY LIST OWNER CHECK "
                f"user_id={user_id} owner_id={owner.get('user_id')} "
                f"chat_id={chat_id} authorized={authorized} sent=False"
            )
            if authorized:
                try:
                    await event.reply(build_group_list(bot.logger))
                    bot.logger.log_info(
                        "EXPIRY LIST OWNER CHECK "
                        f"user_id={user_id} owner_id={owner.get('user_id')} "
                        f"chat_id={chat_id} authorized=True sent=True"
                    )
                except Exception as error:
                    bot.logger.log_error(
                        f"EXPIRY LIST SEND FAILED chat_id={chat_id} error={error!r}"
                    )
            return

        # ------------------------------------------------------------------
        # 🤖 تشخیصِ رباتِ دیگر در گروه و غیرفعال‌سازیِ خودکارِ روباه
        # ------------------------------------------------------------------
        if not event.is_private:
            if bot_detector.is_disabled(chat_id):
                # خاموش‌کردن دائمی گروه پس از دیدن یک ربات دیگر، مسیر عمومی
                # را می‌بست درحالی‌که moderation زودتر از این بخش اجرا می‌شد.
                # وضعیت کهنه را پاک کن و ادامه بده؛ حضور ربات دیگر نباید
                # روباه را برای کاربران خاموش کند.
                bot_detector.reenable(chat_id)
                bot.logger.log_info(
                    f"BOT DISABLED STATE CLEARED chat_id={chat_id}"
                )
            # آیا فرستندهٔ این پیام یک رباتِ دیگر است؟ تشخیص فقط بر اساسِ فیلدِ
            # مستقیمِ API (User.bot). entity ناقص (bot=None) روی مسیر داغ
            # get_entity نمی‌زند تا سندر مشترک قفل نشود.
            # حسابِ خودِ روباه و مالک از قبل در is_bot_account / is_global_owner
            # مستثنا شده‌اند.
            # این لاگ قبل از تصمیم‌گیری ثبت می‌شود تا معلوم باشد sender به
            # مسیر تشخیص رسیده است؛ حساب خود روباه بالاتر عمداً return می‌شود.
            _debug_log(bot,
                "BOT DETECTION DEBUG\n"
                f"group_id={chat_id}\n"
                f"sender_id={user_id}\n"
                f"sender_username={getattr(sender, 'username', None)!r}\n"
                f"sender_type={sender.__class__.__name__ if sender else 'None'}\n"
                f"is_bot={getattr(sender, 'bot', None)!r}\n"
                "detection_result=sender_detected_resolving")
            skip_bot_probe = classify_priority(clean_text)[1] in {
                "admin", "command",
            }
            is_other_bot = False
            if not skip_bot_probe:
                is_other_bot = await bot_detector.resolve_is_bot(
                    bot.client, sender, user_id)
            # خاموش‌سازی خودکار فقط با فعال‌سازی صریح تنظیم اجرا می‌شود؛
            # مقدار پیش‌فرض خاموش است تا یک ربات دیگر کل گروه را بی‌پاسخ نکند.
            auto_disable_for_other_bot = os.getenv(
                "BOT_DISABLE_FOR_OTHER_BOTS", "0"
            ).strip().lower() in {"1", "true", "yes", "on"}
            if (is_other_bot and not is_global_owner(user_id)
                    and auto_disable_for_other_bot):
                title = getattr(event_chat, "title", "") or ""
                bot_id = getattr(sender, "id", None)
                bot_name = bot_detector.display(sender)
                disable_called = False
                disabled_state = False
                notification_sent = False
                try:
                    disable_called = True
                    persisted = bot_detector.disable_for_bot(chat_id, sender)
                    disabled_state = bot_detector.is_disabled(chat_id)
                    bot.logger.log_info(
                        "BOT SHUTDOWN DEBUG\n"
                        f"group_id={chat_id}\n"
                        f"bot_id={bot_id}\n"
                        f"bot_name={bot_name!r}\n"
                        "resolve_is_bot=True\n"
                        f"disable_for_bot_called={disable_called}\n"
                        f"bot_disabled_groups_updated={persisted}\n"
                        f"disabled_state={disabled_state}\n"
                        "notification_sent=False")
                    if not persisted or not disabled_state:
                        raise RuntimeError("bot_disabled_groups.json persistence verification failed")
                    sender4 = getattr(bot, "outgoing_sender", None)
                    if sender4 is not None:
                        sender4.enqueue_reply(event, "🤖 ربات دیگری در این گروه فعال است.\nبه دلیل فعال بودن این ربات، روباه در این گروه خاموش شد.", on_done=lambda sent: capture_sent(bot, chat_id, sent))
                    else:
                        sent = await event.reply(
                            "🤖 ربات دیگری در این گروه فعال است.\n"
                            "به دلیل فعال بودن این ربات، روباه در این گروه خاموش شد.")
                        capture_sent(bot, chat_id, sent)
                    notification_sent = True
                    bot.logger.log_info(
                        "BOT SHUTDOWN DEBUG\n"
                        f"group_id={chat_id}\n"
                        f"bot_id={bot_id}\n"
                        f"bot_name={bot_name!r}\n"
                        "resolve_is_bot=True\n"
                        f"disable_for_bot_called={disable_called}\n"
                        f"disabled_state={disabled_state}\n"
                        f"notification_sent={notification_sent}")
                    return
                except Exception as error:
                    bot.logger.log_error(
                        "BOT SHUTDOWN DEBUG FAILED\n"
                        f"group_id={chat_id}\n"
                        f"bot_id={bot_id}\n"
                        f"bot_name={bot_name!r}\n"
                        "resolve_is_bot=True\n"
                        f"disable_for_bot_called={disable_called}\n"
                        f"disabled_state={disabled_state}\n"
                        f"notification_sent={notification_sent}\n"
                        f"error={error!r}")
                    # در خطای ذخیره/تأیید/اعلان وانمود نمی‌کنیم shutdown کامل
                    # شده است؛ رویداد به مسیر عادی ادامه می‌یابد.

        # ------------------------------------------------------------------
        # 🧪 تست موقت دکمهٔ شیشه‌ای — کاملاً مستقل و قابل حذف.
        # این بخش فقط برای تأیید نمایش Inline Button در گروه سروش‌پلاس است؛
        # هیچ CallbackQuery یا مسیر کلیک دیگری به ربات اضافه نمی‌کند.
        # ------------------------------------------------------------------
        if clean_text == "تست دکمه":
            await event.reply(
                "تست دکمه شیشه‌ای",
                buttons=[[Button.inline("سلام", data=b"test_salam")]],
            )
            return

        # ------------------------------------------------------------------
        # 📥 دانلود عکس — اتصالِ زودهنگام تا پیامِ مرحله‌ای (عبارت/تأیید/لغو)
        # پیش از spam/repeat/سایر شاخه‌ها به هندلرِ مستقل برسد. فقط وقتی
        # جریانِ دانلودِ این کاربر فعال است یا خودِ دستور ارسال شده.
        # ------------------------------------------------------------------
        from modules import photo_download as _photo_dl
        if (clean_text == _photo_dl.COMMAND
                or _photo_dl.session(chat_id, user_id) is not None):
            if await handle_photo_download(
                bot, event, chat_id, user_id, sender, clean_text, bot.logger
            ):
                return

        # ------------------------------------------------------------------
        # 📇 دفترچهٔ یوزرنیم — پیش از هر شاخهٔ دستوری.
        #
        # انتقال سکه با یوزرنیم انجام می‌شود، پس مقصد باید شناخته شده
        # باشد. اگر این ثبت پشت گیت fast_command و بعد از دَه‌ها return
        # می‌ماند، کاربری که فقط دستور می‌فرستد هرگز ثبت نمی‌شد و
        # نمی‌شد به او سکه فرستاد. نوشتن defer است، پس مسیر داغ را کند
        # نمی‌کند.
        # ------------------------------------------------------------------
        if not event.is_private:
            try:
                username_directory.remember(
                    chat_id, user_id, getattr(sender, "username", None),
                )
            except Exception as error:
                _log_username_directory_failure(bot, error)

        # ------------------------------------------------------------------
        # ⏳ تاریخ انقضای گروه — پیش از هر دستور دیگری.
        #
        # مسیر این سه دستور کاملاً جداست و تطبیق دقیق است، پس هیچ
        # startswith عمومی نمی‌تواند آن‌ها را با دستور دیگری اشتباه بگیرد.
        # ------------------------------------------------------------------
        if not event.is_private:
            if await handle_group_expiry(
                bot, event, chat_id, sender, clean_text, bot.logger
            ):
                return
            # گروه منقضی: همهٔ قابلیت‌ها متوقف می‌شوند تا مالک اصلی دوباره
            # یکی از سه دستور را بفرستد.
            if group_expiry_blocks(chat_id, sender):
                return

        # ------------------------------------------------------------------
        # 🔎 جستجوی گوگل گروه — فقط مدیریت ادمین یا reply مجاز به پیام ربات.
        # درخواست HTTPS خودش در task جدا اجرا می‌شود.
        # ------------------------------------------------------------------
        if await _handle_google_search_group_message(
            bot, event, chat_id, user_id, sender, clean_text, message_text
        ):
            return

        # ------------------------------------------------------------------
        # 💰 اقتصاد — دو بخش مستقل «موجودی» و «فروشگاه».
        # پیش از بازی‌ها بررسی می‌شود تا گفتگوی باز منو با پاسخ بازی‌ها
        # تداخل نکند.
        # ------------------------------------------------------------------
        if clean_text in {"موجودی", "فروشگاه", "انتقال سکه"}:
            bot.logger.log_info(f"HANDLER CALLED handler=economy command={clean_text!r}")
        if await handle_economy(
            bot, event, chat_id, user_id, sender, clean_text, bot.logger
        ):
            return

        name_family_trace = (
            clean_text == "اسم فامیل" or name_family_active(chat_id)
        )
        if name_family_trace:
            bot.logger.log_info(
                "NAME FAMILY TRACE HANDLER_ENTER "
                f"chat_id={chat_id} user_id={user_id} message_id={getattr(event.message, 'id', None)} "
                f"line_count={len(clean_text.splitlines())} char_count={len(clean_text)} "
                f"round_active={name_family_active(chat_id)}"
            )

        # حافظهٔ گروه: هر کاربر فقط نام متصل به user_id خودش را ثبت می‌کند.
        # ⚠️ دستورهای رزروشده (مثل «ثبت ادمین») هرگز نباید به این مسیر برسند؛
        # تفکیک آن‌ها در resolve_registration_prefix انجام می‌شود.
        register_prefix = resolve_registration_prefix(clean_text)
        if register_prefix is not None:
            _log_command_route(bot, clean_text, f"{register_prefix.strip()} …",
                               "group_memory.set_name")
            if event.is_private:
                await event.reply("❌ حافظه گروه فقط داخل گروه فعال است.")
                return
            display_name, error = extract_name(clean_text[len(register_prefix):])
            if error == "too_long":
                await event.reply("❌ نام خیلی طولانی است.")
            elif error == "restricted":
                await event.reply(name_filter.MESSAGE_RESTRICTED)
            elif error == "banned":
                await event.reply(name_filter.MESSAGE_BANNED)
            elif error:
                await event.reply("❌ نام معتبر نیست، لطفاً یک اسم یا لقب مناسب وارد کنید.")
            else:
                set_memory_name(chat_id, user_id, display_name)
                await event.reply(f"✅ حافظه شما ثبت شد: {display_name}")
            return

        if clean_text == "حافظه من":
            saved_name = get_memory_name(chat_id, user_id)
            await event.reply(
                f"🧠 حافظه شما: {saved_name}" if saved_name else "🧠 هنوز اسمی ثبت نکردی."
            )
            return

        if clean_text == "حذف اسم":
            if remove_memory_name(chat_id, user_id):
                await event.reply("✅ حافظه شما حذف شد.")
            else:
                await event.reply("🧠 حافظه‌ای برای حذف ندارید.")
            return

        if clean_text.startswith("شخصیت "):
            report = name_personality_report(clean_text.replace("شخصیت ", "", 1))
            await event.reply(report or "❌ نام معتبر وارد کنید.")
            return

        if clean_text == "دانستنی":
            await event.reply(f"🧠 دانستنی:\n\n{get_fact()}")
            return

        saved_name = get_memory_name(chat_id, user_id)
        personal_reply = friendly_reply(saved_name, clean_text) if saved_name else None
        if personal_reply:
            _schedule_reply(bot, event, personal_reply)
            return

        fast_command = (
            clean_text in SIMPLE_REPLIES
            or clean_text in INSULTS
            or clean_text in {"راهنما", "/help", "!help", "help", "لیست کاربران", "لیست ادمین", "لیست ادمینی", "آمارم", "راهنمای امتیاز", "امتیاز من", "رتبه ها", "بیوگرافی", "یاد آوری", "ترجمه", "قفل", "باز", "لیست بازی", "لیست بازی ها", "لیست بازی‌ها", "جک", "تصحیح کلمات", "اسم فامیل", "حدس ایموجی", "حدس پرچم", "دانستنی", "حافظه من", "حذف اسم", "قوانین", "ثبت قوانین", "حذف قوانین", "حذف حافظه", "موجودی", "فروشگاه", "سکوت", "رفع سکوت", "آزاد", "اخطار", "اخراج", "بن", "ثبت ادمین", "برکناری ادمین", "لغو ادمین", "تغییر اخطار", "تغییر مجازات", "سنجاق", "قفل", "باز", "سابقه ها", "سابقه‌ها", "سطح گروه", "vip", "لغو vip", "لیست vip"} | EMOJI_RESET_COMMANDS | FOX_GAME_COMMANDS
            or (
                clean_text.startswith(("!", "/", "."))
                and not clean_text.startswith(("/فیلتر ", "/رفع "))
                and clean_text != "/فیلترها"
            )
        )
        # پاسخ ویژه فقط برای مالکِ ثبت‌شدهٔ همین گروه، پیش از پاسخ‌های عمومی.
        registered_owner_id = get_group_owner(chat_id) if not event.is_private else None
        owner_reply = registered_owner_greeting_response(
            clean_text,
            user_id,
            registered_owner_id,
            is_private=event.is_private,
        )
        if owner_reply:
            _schedule_reply(bot, event, owner_reply)
            return

        # پاسخ‌های ثابت بدون ورود به moderation و I/O پاسخ می‌گیرند.
        # COMMAND_MATCH was already marked at normalize_command above.
        simple_reply = SIMPLE_REPLIES.get(clean_text)
        if simple_reply:
            _schedule_reply(bot, event, simple_reply)
            return
        if clean_text in INSULTS:
            _schedule_reply(bot, event, INSULT_REPLY)
            return

        # فرمان‌های کوتاه نباید برای ثبت آمار/فعالیت منتظر I/O فایل بمانند.
        if not event.is_private and not fast_command:
            _run_background(
                bot, "user_activity", record_activity, chat_id, user_id, event.message
            )
        sender_username = getattr(sender, "username", None)
        # فرمان‌های سریع permission مخصوص خود را در branch فرمان بررسی می‌کنند.
        profiler.skip_to()
        is_group_moderator = admin_bypass or (
            not event.is_private
            and not fast_command
            and _has_group_management_permission(
                bot, chat_id, user_id, sender_username
            )
        )
        # Native admins may receive ordinary warnings, but none of the
        # automatic delete/mute/ban branches may act on them.
        auto_punish_protected = is_group_moderator or native_admin_warn_only
        profiler.mark("ADMIN_CHECK")
        if not is_group_moderator and not is_gif_message(event.message):
            reset_gif_history(chat_id, user_id)

        # قوانین گروه فقط توسط مدیر/مالک ثبت، تغییر یا حذف می‌شوند.
        can_manage_group = (
            not event.is_private
            and _has_group_management_permission(
                bot, chat_id, user_id, getattr(sender, "username", None)
            )
        )
        if clean_text == "ثبت قوانین":
            _log_command_route(bot, clean_text, "ثبت قوانین", "group_rules.set")
            if not can_manage_group:
                await event.reply("❌ فقط مدیر گروه اجازه ثبت قوانین دارد.")
            else:
                begin_rules(chat_id, user_id)
                await event.reply("📜 لطفاً قوانین گروه را ارسال کنید.")
            return

        if waiting_rules(chat_id, user_id):
            if not can_manage_group:
                cancel_rules(chat_id, user_id)
                await event.reply("❌ فقط مدیر گروه اجازه ثبت قوانین دارد.")
            elif save_rules(chat_id, user_id, message_text):
                await event.reply("📜 قوانین گروه ثبت شد ✅")
            else:
                await event.reply("❌ متن قوانین معتبر نیست یا خیلی طولانی است.")
            return

        if clean_text == "حذف قوانین":
            _log_command_route(bot, clean_text, "حذف قوانین", "group_rules.remove")
            if not can_manage_group:
                await event.reply("❌ فقط مدیر گروه اجازه حذف قوانین دارد.")
            elif remove_rules(chat_id):
                await event.reply("✅ قوانین گروه حذف شد.")
            else:
                await event.reply("📜 قانونی برای حذف ثبت نشده است.")
            return

        if clean_text == "قوانین":
            await event.reply(format_rules(chat_id) or "📜 هنوز قانونی برای این گروه ثبت نشده است.")
            return

        # مدیر با ریپلای روی پیام کاربر می‌تواند حافظهٔ همان کاربر را حذف کند.
        if clean_text == "حذف حافظه":
            if not can_manage_group:
                await event.reply("❌ فقط مدیر گروه اجازه مدیریت حافظه‌ها را دارد.")
                return
            if not event.reply_to:
                await event.reply("❌ روی پیام کاربر ریپلای کنید.")
                return
            reply_msg = await bot.client.get_messages(chat_id, ids=event.reply_to.reply_to_msg_id)
            target_user = await reply_msg.get_sender() if reply_msg else None
            if not target_user:
                await event.reply("❌ کاربر پیدا نشد.")
            elif remove_memory_name(chat_id, target_user.id):
                await event.reply("✅ حافظه کاربر حذف شد.")
            else:
                await event.reply("🧠 حافظه‌ای برای این کاربر ثبت نشده است.")
            return

        if not has_text_content and not is_forwarded_media and not is_gif_media:
            return

        if not fast_command and not admin_bypass:
            save_history_message(chat_id, user_id, event.message.id, message_text)
        if not auto_punish_protected:
            if is_gif_message(event.message):
                # مسیر مستقل GIF: ثبت، صف‌بندی و حذف دسته‌ای با تلاش مجدد.
                repeated_gif_ids, newly_flagged = handle_gif_message(
                    chat_id,
                    user_id,
                    event.message.id,
                    client=bot.client,
                    logger=bot.logger,
                    delete_queue=getattr(bot, "message_delete_queue", None),
                )
                deleted = len(repeated_gif_ids)
                if repeated_gif_ids:
                    bot.logger.log_info(
                        "DUPLICATE GIF DETECTED "
                        f"user={user_id} chat_id={chat_id} count={len(repeated_gif_ids)}"
                    )
                    bot.logger.log_info(
                        "DELETE QUEUE SIZE "
                        f"user={user_id} chat_id={chat_id} size={gif_pending_count(chat_id)}"
                    )
                    bot.logger.log_info(
                        "DELETE START "
                        f"message_ids={repeated_gif_ids!r}"
                    )
                    # handle_gif already scheduled a per-chat flush worker.
                    # Awaiting it here blocked this group's (and previously
                    # the whole bot's) command path for 400ms plus delete RPCs.
                    bot.logger.log_info(
                        "GIF DELETE SCHEDULED "
                        f"chat_id={chat_id} count={len(repeated_gif_ids)}"
                    )
                if newly_flagged:
                    bot.set_spam_lock((chat_id, user_id))
                    _debug_log(bot,
                        f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={getattr(event.message, 'id', None)} stage=LOCK_SET key={(chat_id, user_id)!r} reason=duplicate_gif lock_size={len(getattr(bot, 'spam_lock', set()))}"
                    )
                    bot.logger.log_info(
                        f"SPAM LOCK SET chat_id={chat_id} user_id={user_id} reason=duplicate_gif"
                    )
                    async def gif_mute_succeeded(_result):
                        print("USER MUTED 3600")
                        notification_key = (chat_id, user_id)
                        now = _asyncio.get_running_loop().time()
                        notified_until = getattr(bot, "gif_spam_notification_until", {})
                        if notified_until.get(notification_key, 0) <= now:
                            if not hasattr(bot, "gif_spam_notification_until"):
                                bot.gif_spam_notification_until = {}
                            bot.gif_spam_notification_until[notification_key] = now + 3600
                            await _send_moderation_notification_once(
                                bot, chat_id, user_id, "gif_mute", event.message.id,
                                "🔹کاربر ← "
                                f"{_format_banned_user(sender, user_id)}\n\n"
                                "به دلیل ارسال گیف تکراری 𝟭 ساعت سکوت شد",
                            )
                            print("GIF WARNING SENT")

                    async def gif_mute_failed(_error):
                        reset_gif_history(chat_id, user_id)

                    bot.moderation_queue.enqueue(
                        chat_id,
                        "auto_mute",
                        user_id=user_id,
                        timeout_seconds=15,
                        operation=lambda: bot.admin_actions.mute_user(
                            chat_id, user_id, 3600, user=sender,
                        ),
                        on_success=gif_mute_succeeded,
                        on_failure=gif_mute_failed,
                    )
                    if deleted:
                        bot.logger.log_info(
                            f"consecutive GIF spam deleted chat_id={chat_id} user_id={user_id} count={deleted}"
                        )
                # هر GIF مشمول، چه در آستانه و چه پس از آن، همین‌جا پایان
                # می‌یابد و وارد فیلترهای دیگر نمی‌شود.
                if repeated_gif_ids:
                    return

        burst_key = (chat_id, user_id)
        if burst_key in bot.spam_burst_users:
            # Join the existing ban incident instead of a second burst worker;
            # otherwise its deleted IDs are missing from the final total and
            # its lifecycle can race a second cleanup/notice.
            _schedule_auto_spam_cleanup(
                bot, event, chat_id, user_id, {event.message.id}
            )
            if name_family_trace:
                bot.logger.log_info(
                    "NAME FAMILY TRACE HANDLER_BLOCK "
                    f"reason=spam_burst chat_id={chat_id} user_id={user_id}"
                )
            return

        if clean_text == "صفر":
            # فقط مالک اصلی ربات یا مالک گروه؛ ادمینِ عادی اجازه ندارد.
            if not admin_tools.has_zero_permission(chat_id, user_id):
                await event.reply(
                    "❌ فقط مالک اصلی ربات یا مالک گروه اجازه صفر کردن تخلفات را دارد")
                return
            if not event.reply_to:
                await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                return

            try:
                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id,
                )
                target_user = await reply_msg.get_sender() if reply_msg else None
                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                bot.tracker.reset_count(chat_id, target_user.id)
                admin_tools.log_action(
                    chat_id, sender, "صفر کردن تخلفات", target=target_user)
                await event.reply("✅ تخلفات کاربر صفر شد.")
            except Exception as e:
                bot.logger.log_error(f"خطا در صفر کردن تخلفات: {e}")
                await event.reply(f"❌ خطا: {e}")
            return

        # حذف اخطار با ریپلای
        if clean_text == "حذف اخطار":
            sender_username = getattr(sender, "username", None)
            if not admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            ):
                await event.reply(
                    "❌ فقط مالک یا ادمین اجازه حذف اخطار را دارند")
                return
            if not event.reply_to:
                await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                return

            try:
                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id,
                )
                target_user = await reply_msg.get_sender() if reply_msg else None
                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                before = bot.tracker.get_count(chat_id, target_user.id)
                bot.tracker.reset_count(chat_id, target_user.id)
                admin_tools.log_action(
                    chat_id, sender, "حذف اخطار", target=target_user,
                    note=f"{before} → 0")
                await event.reply("✅ تمام اخطارهای کاربر حذف شد.")
            except Exception as e:
                bot.logger.log_error(f"خطا در حذف اخطار: {e}")
                await event.reply(f"❌ خطا: {e}")
            return

        # حذف اخطارها (جمع) — همهٔ اخطارهای کاربر صفر می‌شود
        if clean_text == "حذف اخطارها":
            sender_username = getattr(sender, "username", None)
            if not admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            ):
                await event.reply(
                    "❌ فقط مالک یا ادمین اجازه حذف اخطارها را دارند")
                return
            if not event.reply_to:
                await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                return

            try:
                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id,
                )
                target_user = await reply_msg.get_sender() if reply_msg else None
                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                before = bot.tracker.get_count(chat_id, target_user.id)
                bot.tracker.reset_count(chat_id, target_user.id)
                admin_tools.log_action(
                    chat_id, sender, "حذف اخطارها", target=target_user,
                    note=f"{before} → 0")
                await event.reply(
                    f"✅ همهٔ اخطارهای کاربر حذف شد.\n"
                    f"تعداد اخطار: 0")
            except Exception as e:
                bot.logger.log_error(f"خطا در حذف اخطارها: {e}")
                await event.reply(f"❌ خطا: {e}")
            return

        # لاگ مدیریتی
        if clean_text == "لاگ مدیریتی":
            sender_username = getattr(sender, "username", None)
            if not admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            ):
                await event.reply("❌ فقط مالک یا ادمین اجازه مشاهده لاگ را دارند")
                return
            text, entities = admin_tools.format_log(chat_id)
            await event.reply(text, formatting_entities=entities or None)
            return

        # 🗂 سابقه ها — پروندهٔ تخلفِ کاربران (فقط مالک و ادمین‌ها)
        if clean_text in {"سابقه ها", "سابقه‌ها"}:
            sender_username = getattr(sender, "username", None)
            if not admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            ):
                await event.reply(user_history.NO_PERMISSION)
                return
            text, entities = user_history.format_history(chat_id)
            await event.reply(text, formatting_entities=entities or None)
            return

        # 🏆 سطح گروه — یک سطح به ازای هر ۱۰۰۰ پیام تا سطح ۲۰ (برای همه)
        if clean_text == "سطح گروه":
            if event.is_private:
                await event.reply("ℹ️ این دستور فقط داخل گروه کار می‌کند.")
                return
            await event.reply(group_level.format_level(chat_id))
            # اگر همین حالا گروه ارتقا یافته، تبریک هم فرستاده می‌شود.
            congrats = group_level.check_level_up(chat_id)
            if congrats:
                try:
                    await event.reply(congrats)
                except Exception as error:
                    bot.logger.log_error(f"GROUP LEVEL CONGRATS FAILED: {error}")
            return

        # پاکسازی خودکار — جریانِ مرحله‌به‌مرحله
        if clean_text == "پاکسازی خودکار":
            sender_username = getattr(sender, "username", None)
            if not admin_tools.has_admin_permission(
                chat_id, user_id, sender_username
            ):
                await event.reply("❌ فقط مالک یا ادمین اجازه پاکسازی خودکار را دارند")
                return
            admin_tools._PENDING_CLEANUP[chat_id] = {
                "step": "day", "day": None, "time": None,
                "user_id": user_id}
            await event.reply(
                "🧹 پاکسازی خودکار\n\n"
                "پاکسازی چه زمانی انجام شود؟\n"
                "گزینه‌ها:\n"
                "- امروز\n"
                "- فردا")
            return

        # مرحلهٔ پاکسازی خودکار (پاسخِ مرحله‌ای) — فقط برای همان ادمینِ شروع‌کننده
        pending_cleanup = admin_tools._PENDING_CLEANUP.get(chat_id)
        if pending_cleanup and pending_cleanup.get("user_id") == user_id:
            state = pending_cleanup
            if state.get("step") == "day":
                day = admin_tools.valid_day(clean_text)
                if day is None:
                    await event.reply(
                        "❌ لطفاً یکی از گزینه‌های «امروز» یا «فردا» را ارسال کنید.")
                    return
                state["day"] = day
                state["step"] = "time"
                await event.reply(
                    "🕐 ساعت انجام پاکسازی را وارد کنید:\n"
                    "مثال: «13:32»")
                return
            if state.get("step") == "time":
                # یک snapshot واحد از تهران برای parse، مقایسه و ذخیره‌سازی
                # استفاده می‌شود؛ چند now جدا نزدیک نیمه‌شب می‌توانند تاریخ
                # متفاوت بدهند و پیام «گذشته است» را اشتباه کنند.
                schedule_now = admin_tools.now_local()
                time_str = admin_tools.parse_time(clean_text, now=schedule_now)
                if time_str is None:
                    await event.reply(
                        "❌ ساعت نامعتبر است؛ مانند «15:12»، «۷ صبح»، "
                        "«۷ شب» یا «ساعت ۷» ارسال کنید.")
                    return
                scheduled = admin_tools.compute_scheduled_at(
                    state.get("day"), time_str, now=schedule_now)
                if scheduled is None:
                    await event.reply("❌ ساعت نامعتبر است؛ دوباره تلاش کنید.")
                    return
                hour = int(time_str.split(":")[0])
                tod = admin_tools.time_of_day(hour)
                rolled_to_tomorrow = (
                    state.get("day") == "today"
                    and scheduled.date() > schedule_now.date()
                )
                if rolled_to_tomorrow:
                    await event.reply(
                        f"⏰ ساعت {time_str} ({tod}) گذشته است و برای جلوگیری "
                        "از اشتباه، فردا لحاظ می‌شود.\n"
                        "اگر منظورتان همین امروز است، یک ساعتِ بعدی انتخاب "
                        "کنید؛ در غیر این صورت ادامه می‌دهیم.")
                state["time"] = time_str
                state["scheduled_at"] = scheduled.isoformat()
                state["step"] = "count"
                await event.reply(
                    "🗑️ چه تعداد پیام حذف شود؟\n"
                    "عددی بین ۱ تا ۳۰۰۰ ارسال کنید (مثلاً «800»).")
                return
            if state.get("step") == "count":
                count = admin_tools.valid_count(clean_text)
                if count is None:
                    await event.reply(
                        "❌ تعداد نامعتبر است؛ عددی بین ۱ تا ۳۰۰۰ ارسال کنید.")
                    return
                result = admin_tools.set_cleanup(
                    chat_id, state.get("day"), state["time"], count,
                    scheduled_at=state.get("scheduled_at"))
                admin_tools._PENDING_CLEANUP.pop(chat_id, None)
                if result is None:
                    await event.reply("❌ خطا در ذخیرهٔ تنظیم؛ دوباره تلاش کنید.")
                    return
                admin_tools.log_action(
                    chat_id, sender, "تنظیم پاکسازی خودکار",
                    note=(f"روز {state.get('day')}، ساعت {state['time']}، "
                          f"{count} پیام"))
                await event.reply(
                    f"✅ پاکسازی خودکار تنظیم شد.\n\n"
                    f"{admin_tools.format_cleanup(chat_id)}")
                return

        if clean_text == "تغییر اخطار":
            _log_command_route(
                bot, clean_text, "تغییر اخطار", "warning_threshold.prompt")
            if not _can_manage_group_admins(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply(
                    "❌ فقط مالک اصلی ربات یا مالک همین گروه اجازه تغییر اخطار را دارد"
                )
                return
            current_threshold = warning_threshold.get_threshold(
                chat_id, bot.config_manager.get("spam_threshold", 5))
            warning_threshold.begin_change(chat_id, user_id)
            prompt_prefix = "⚙ "
            prompt_title = "تغییر اخطار"
            prompt_text = (
                f"{prompt_prefix}{prompt_title}\n\n"
                f"تعداد اخطار فعلی {current_threshold}\n\n\n\n"
                "از ۱ تا ۱۲ میتوانید یک تعداد برای اخطار تایین کنید مثلا « 7 »"
            )
            await event.reply(
                prompt_text,
                formatting_entities=[
                    MessageEntityBold(
                        offset=len(prompt_prefix.encode("utf-16-le")) // 2,
                        length=len(prompt_title.encode("utf-16-le")) // 2,
                    )
                ],
            )
            return

        if warning_threshold.has_pending(chat_id, user_id):
            _chosen, _valid = warning_threshold.parse_choice(clean_text)
            if _chosen is not None:
                if _valid:
                    warning_threshold.set_threshold(chat_id, _chosen)
                    warning_threshold.clear_pending(chat_id, user_id)
                    await event.reply(
                        f"🔒 تعداد اخطار تغییر کرد « {_chosen} »"
                    )
                else:
                    await event.reply(
                        "❌ فقط عددی بین ۱ تا ۱۲ مجاز است. دوباره بنویسید مثلا « 7 »"
                    )
                return
            # متن غیرعددی → انتظار لغو می‌شود و پیام مسیر عادی خود را می‌رود.
            warning_threshold.clear_pending(chat_id, user_id)

        if clean_text == "تغییر مجازات":
            _log_command_route(
                bot, clean_text, "تغییر مجازات", "punishment_mode.prompt")
            if not _can_manage_group_admins(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply(
                    "❌ فقط مالک اصلی ربات یا مالک همین گروه اجازه تغییر مجازات را دارد"
                )
                return
            punish_header = "⚠️ تغییر مجازات"
            if punishment_mode.is_mute(chat_id):
                punish_body = (
                    "در حال حاضر مجازات به صورت سکوت انجام می‌شود "
                    "آیا میخواهید مجازات به بن تبدیل شود و از این پس "
                    "به جای سکوت کاربر ؛ مستقیم اخراج شود؟"
                )
            else:
                punish_body = (
                    "در حال حاضر مجازات به صورت بن انجام می‌شود "
                    "آیا میخواهید مجازات به سکوت دائمی تبدیل شود و از این پس "
                    "به جای اخراج کاربر؛ مستقیم سکوت دائم شود؟"
                )
            punish_text = (
                f"{punish_header}\n\n{punish_body}\n\n\n\n🔸تایید\n\n🔸لغو"
            )
            punishment_mode.begin_change(chat_id, user_id)
            _bold_off = len("⚠️ ".encode("utf-16-le")) // 2
            _bold_len = len("تغییر مجازات".encode("utf-16-le")) // 2
            try:
                await event.reply(
                    punish_text,
                    formatting_entities=[
                        MessageEntityBlockquote(
                            offset=0,
                            length=len(punish_header.encode("utf-16-le")) // 2,
                        ),
                        MessageEntityBold(offset=_bold_off, length=_bold_len),
                    ],
                )
            except Exception:
                # شکست فرمت نباید جریان تغییر مجازات را بشکند.
                await event.reply(punish_text)
            return

        if punishment_mode.has_pending(chat_id, user_id):
            if clean_text in punishment_mode.CONFIRM_WORDS:
                new_mode = punishment_mode.toggle(chat_id)
                punishment_mode.clear_pending(chat_id, user_id)
                await event.reply(
                    f"📌 مجازات تغییر کرد « {punishment_mode.mode_label(new_mode)} »\n"
                    "برای تغییر دوباره مجازات همان دستور رو ارسال کنید"
                )
                return
            if clean_text in punishment_mode.CANCEL_WORDS:
                punishment_mode.clear_pending(chat_id, user_id)
                await event.reply("❌ تغییر مجازات لغو شد")
                return
            # هر متن دیگر → انتظار لغو می‌شود و پیام مسیر عادی خود را می‌رود.
            punishment_mode.clear_pending(chat_id, user_id)

        if clean_text == "ثبت اصل":
            _log_command_route(bot, clean_text, "ثبت اصل", "user_original.set")
            begin_registration(user_id)
            await event.reply("لقب یا اصل خودتو بنویس")
            return

        if is_waiting_for_original(user_id):
            save_original(user_id, clean_text)
            await event.reply("✅ اصل شما ثبت شد")
            return

        if clean_text == "اصلم":
            original = get_original(user_id)
            if original:
                original_text = str(original)
                await event.reply(
                    original_text,
                    formatting_entities=[
                        MessageEntityBold(
                            offset=0,
                            length=len(original_text.encode("utf-16-le")) // 2,
                        )
                    ],
                )
            else:
                await event.reply(
                    "هنوز اصلی ثبت نکردی. برای ثبت بنویس: ثبت اصل"
                )
            return

        if clean_text in INSULTS:
            await event.reply(INSULT_REPLY)
            return

        simple_reply = SIMPLE_REPLIES.get(clean_text)
        if simple_reply:
            await event.reply(simple_reply)
            return

        # بیوگرافی باید پیش از فیلتر گروهیِ کلمهٔ مستقل «بیو» اجرا شود.
        if clean_text == "بیوگرافی":
            await event.reply(get_biography(chat_id))
            return

        if clean_text == "یاد آوری":
            begin_reminder(chat_id, user_id, _format_admin_display(sender))
            await event.reply("📝 متن یادآوری و زمان موردنظر را ارسال کنید.")
            return

        if waiting_reminder(chat_id, user_id):
            reminder = capture_reminder(chat_id, user_id, message_text)
            if reminder is False:
                await event.reply("❌ زمان را مانند «۳۰ دقیقه آب بخور» ارسال کنید.")
            else:
                await event.reply(
                    "✅ یادآوری ثبت شد.\n\n"
                    f"⏰ زمان: {reminder['time_label']}\n"
                    f"📝 متن: {reminder['text']}"
                )
            return

        if clean_text == "ترجمه":
            begin_translation(chat_id, user_id)
            await event.reply("🌐 متن انگلیسی خود را ارسال کنید.")
            return

        if waiting_translation(chat_id, user_id):
            # ترجمه هم درخواست HTTP همگام است؛ خارج از حلقه اجرا می‌شود.
            translated, error = await _asyncio.to_thread(
                translate_to_persian, message_text)
            clear_translation(chat_id, user_id)
            if error:
                await event.reply(error)
            else:
                translation_text = (
                    "🌐 ترجمه\n\n"
                    f"🇬🇧 متن:\n\n{message_text}\n\n"
                    f"🇮🇷 ترجمه:\n\n{translated}"
                )
                def translation_u16(value):
                    return len(value.encode("utf-16-le")) // 2
                title = "🌐 ترجمه"
                source_title = "🇬🇧 متن:"
                target_title = "🇮🇷 ترجمه:"
                target_start = translation_text.rfind(translated)
                entities = []
                for label in (title, source_title, target_title):
                    pos = translation_text.index(label)
                    entities.append(MessageEntityBold(offset=translation_u16(translation_text[:pos]), length=translation_u16(label)))
                entities.append(MessageEntityBold(offset=translation_u16(translation_text[:target_start]), length=translation_u16(translated)))
                entities.append(MessageEntityBlockquote(offset=translation_u16(translation_text[:target_start]), length=translation_u16(translated)))
                await event.reply(translation_text, formatting_entities=entities)
            return

        # ضدتکرار فقط برای پیام‌های سریع و یکسانِ کاربران عادی اجرا می‌شود.
        if not fast_command and not auto_punish_protected:
            try:
                if is_repeat(chat_id, user_id, message_text):
                    punish_key = _punishment_key(chat_id, user_id)
                    _log_ban_execution(bot, chat_id, user_id, "اسپم تکراری")
                    if punish_key in bot.punished_users:
                        tracked_existing = message_tracker.get_user_recent_messages(
                            chat_id, user_id
                        )
                        existing_ids = {
                            row["message_id"] for row in tracked_existing
                            if isinstance(row.get("message_id"), int)
                            and row["message_id"] > 0
                        }
                        if event.message.id not in existing_ids:
                            existing_ids.add(event.message.id)
                        bot.logger.log_info(
                            "SPAM BULK CLEANUP QUEUED "
                            f"chat_id={chat_id} user_id={user_id} "
                            f"seed_ids={len(existing_ids)}"
                        )
                        # Never await bulk delete/get-history from a received
                        # message. The per-user cleanup task owns it instead.
                        _schedule_auto_spam_cleanup(
                            bot, event, chat_id, user_id, existing_ids
                        )
                        return
                    bot.punished_users.add(punish_key)
                    bot.spam_burst_users.add((chat_id, user_id))
                    bot.touch_temporary_state("burst", (chat_id, user_id))
                    bot.set_spam_lock((chat_id, user_id))
                    _debug_log(bot,
                        f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={getattr(event.message, 'id', None)} stage=LOCK_SET key={(chat_id, user_id)!r} reason=is_repeat_severe lock_size={len(getattr(bot, 'spam_lock', set()))}"
                    )
                    ids = message_tracker.spam_snapshot(
                        chat_id, user_id, getattr(event.message, "id", None)
                    )
                    bot.logger.log_info(
                        "SPAM HISTORY SNAPSHOT "
                        f"chat_id={chat_id} user_id={user_id} "
                        f"count={len(ids)} ids={ids!r}"
                    )
                    async def repeat_history_ban_succeeded(_result):
                        bot.logger.log_info(
                            f"PUNISHMENT RESULT user={user_id} success=True"
                        )
                        # Do not send a separate ban notice or start a second
                        # cleanup here. This seals the shared incident, whose
                        # task combines all earlier/later deletion batches.
                        _confirm_spam_ban_cleanup(
                            bot, event, chat_id, user_id, set(ids)
                        )
                        bot.spam_burst_users.discard((chat_id, user_id))

                    async def repeat_history_ban_failed(_error):
                        bot.punished_users.discard(punish_key)
                        bot.spam_burst_users.discard((chat_id, user_id))

                    bot.moderation_queue.enqueue(
                        chat_id,
                        "ban",
                        user_id=user_id,
                        timeout_seconds=20,
                        operation=lambda: bot.admin_actions.ban_user(
                            chat_id, user_id, reason="اسپم تکراری",
                            user=sender,
                        ),
                        on_success=repeat_history_ban_succeeded,
                        on_failure=repeat_history_ban_failed,
                    )
                    if name_family_trace:
                        bot.logger.log_info(
                            "NAME FAMILY TRACE HANDLER_BLOCK "
                            f"reason=repeat_spam chat_id={chat_id} user_id={user_id}"
                        )
                    return
            except Exception as e:
                print("history error:", e)

        # جستجوی وب
        if clean_text.startswith("جستجو "):
            query = clean_text.replace("جستجو ", "", 1).strip()

            # فیلتر مطالب غیرمجاز جستجو
            blocked_search_words = [
    "porn",
    "porno",
    "xxx",
    "sex",
    "s e x",
    "سکس",
    "سکسی",
    "پورن",
    "فیلم پورن",
    "فیلم سوپر",
    "سوپر",
    "gay",
    "گی",
    "lez",
    "les",
    "لز",
    "تریسام",
    "threesome",
    "adult",
    "nude",
    "naked",
    "برهنه",
    "18+",
    "18",
    "erotic",
    "شهوت",
    "شهوانی"
]

            if any(word.lower() in query.lower() for word in blocked_search_words):
                await event.reply("🚫 جستجو این مطلب غیرمجاز است.")
                return

            if query:
                ok, wait = can_search(user_id)
                if not ok:
                    await event.reply(f"⏳ لطفاً {wait} ثانیه صبر کنید")
                    return

                # جستجو یک درخواست HTTP همگام با timeout تا ۲۰ ثانیه است.
                # اجرای مستقیم آن، حلقهٔ رویداد و در نتیجه همهٔ گروه‌ها را
                # تا پایان درخواست قفل می‌کرد.
                result = await _asyncio.to_thread(search_web, query)
                await event.reply(result)
                return


        # ------------------------------------------------------------------
        # 🎮 کنترل سرگرمی به تفکیک گروه.
        # دو شاخهٔ «روشن/خاموش» و بعد گارد مرکزیِ بازی‌ها. هر دو **پیش از**
        # هر مسیر بازی قرار دارند تا هیچ state، تایمر، سکه یا شمارنده‌ای در
        # گروه خاموش ساخته نشود. «لیست بازی» گارد نمی‌شود، چون پیام
        # فعال‌سازی خودش کاربر را به همان ارجاع می‌دهد.
        # ------------------------------------------------------------------
        entertainment_command = entertainment_control.normalize(clean_text)
        if entertainment_command in entertainment_control.COMMANDS:
            bot.logger.log_info(
                "HANDLER CALLED handler=entertainment_control "
                f"command={entertainment_command!r} chat_id={chat_id}"
            )
            if event.is_private:
                await event.reply(entertainment_control.PRIVATE_CHAT_NOTICE)
                return
            if not admin_tools.has_admin_permission(
                chat_id, user_id, getattr(sender, "username", None)
            ):
                await entertainment_control.send_permission_denied(event)
                return
            if entertainment_command == entertainment_control.COMMAND_DISABLE:
                entertainment_control.disable(chat_id)
                await entertainment_control.send_disabled_notice(event)
            else:
                entertainment_control.enable(chat_id)
                await entertainment_control.send_enabled_notice(event)
            return

        # گارد مرکزی — هر بازی داخلی از همین یک نقطه رد می‌شود.
        if await entertainment_control.guard(event, chat_id, clean_text):
            bot.logger.log_info(
                f"ENTERTAINMENT BLOCKED chat_id={chat_id} command={clean_text!r}"
            )
            return

        # ---- 📥 دانلود عکس (مستقل، قبل از بازی‌ها) ----
        if await handle_photo_download(
            bot, event, chat_id, user_id, sender, clean_text, bot.logger
        ):
            return

        # ---- 🦊 سیستم اختصاصی ورود به سایت بازی روباه (Fox Game Center) ----
        if clean_text in ("سایت بازی", "سایت", "لینک بازی", "/game", "/site"):
            from modules import group_storage

            if not group_storage.is_active(chat_id):
                await event.reply(
                    "❌ روباه در این گروه فعال نیست.\n"
                    "برای استفاده از سایت بازی، ابتدا روباه باید با دستور «فعال» در گروه فعال‌سازی شود."
                )
                return

            site_user_id = user_id or getattr(event, "sender_id", None) or getattr(sender, "id", None)
            cost_bronze = 20
            user_balance = economy.get_balance(chat_id, site_user_id)
            try:
                current_bronze = int(user_balance.get(economy.BRONZE, 0) or 0)
            except (TypeError, ValueError):
                current_bronze = 0

            if current_bronze < cost_bronze:
                bot.logger.log_info(
                    "FOX GAME SITE INSUFFICIENT "
                    f"user_id={site_user_id} chat_id={chat_id} "
                    f"bronze={current_bronze} need={cost_bronze} "
                    f"wallet={economy.resolve_user_key(chat_id, site_user_id)}"
                )
                await event.reply(
                    "❌ موجودی کافی نیست\n"
                    f"موجودی فعلی شما: {current_bronze} برنز\n"
                    "برای دریافت سایت حداقل ۲۰ برنز نیاز دارید"
                )
                return

            try:
                economy.spend(
                    chat_id, site_user_id, cost_bronze, economy.BRONZE,
                    note="ورود به سایت بازی روباه",
                )
            except Exception as spend_err:
                bot.logger.log_error(
                    "FOX GAME SITE SPEND FAILED "
                    f"chat_id={chat_id} user_id={site_user_id} error={spend_err!r}"
                )
                await event.reply("❌ خطا در کسر سکه، لطفاً مجدداً امتحان کنید.")
                return

            group_title = f"گروه {chat_id}"
            try:
                g_info = group_storage.load_groups().get(str(chat_id), {})
                if g_info.get("title"):
                    group_title = g_info["title"]
            except Exception:
                pass

            bot.logger.log_info(
                f"FOX GAME SITE LINK user_id={site_user_id} chat_id={chat_id} cost={cost_bronze}"
            )

            msg = (
                "🖇لینک سایت بازی روباه\n"
                "https://fox-game.aifox-chat.workers.dev/\n\n"
                f"🔘 گروه فعال شده {group_title}\n\n"
                "                          ─━━━━━━⊱✿⊰━━━━━━─\n"
                "اطلاعات و رتبه‌بندی شما در سایت ذخیره می‌شود.\n"
                "                           ─━━━━━━⊱✿⊰━━━━━━─"
            )
            await event.reply(msg)
            return

        # ---- بازی‌های Fox AI (کاملاً مستقل، فقط از این نقطه وصل می‌شوند) ----
        if (
            clean_text in FOX_GAME_COMMANDS or fox_game_active(chat_id)
        ) and await handle_fox_games(
            bot, event, chat_id, user_id, sender, clean_text, bot.logger
        ):
            return

        # بازی اسم فامیل
        if clean_text == "اسم فامیل":
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            bot.logger.log_info(f"NAME FAMILY HANDLER START TRY chat_id={chat_id} user_id={user_id}")
            game = start_name_family(chat_id, logger=bot.logger)
            if not game:
                bot.logger.log_info(f"NAME FAMILY HANDLER START FAILED chat_id={chat_id} reason=already_active_or_no_letter")
                await event.reply(GAME_BUSY_MESSAGE)
                return
            bot.logger.log_info(f"NAME FAMILY HANDLER START SUCCESS chat_id={chat_id} round_id={game['round_id']} letter={game['letter']}")
            await event.reply(
                "🎮 اسم فامیل\n\n"
                f"حرف: {game['letter']}\n\n"
                "⏳ زمان: 90 ثانیه\n\n"
                "👤 نام\n👤 فامیل\n🌍 شهر\n🍇 میوه\n📦 وسیله\n🐶 حیوان\n🎵 خواننده"
            )
            bot.logger.log_info(f"NAME FAMILY HANDLER REPLY SENT chat_id={chat_id} round_id={game['round_id']}")
            async def name_family_results(ranking):
                """نمایش نتایج؛ توسط مسیر اختصاصی همین بازی فراخوانی می‌شود."""
                bot.logger.log_info(f"NAME FAMILY HANDLER RESULTS CALLBACK ENTER chat_id={chat_id} round_id={game['round_id']} ranking_len={len(ranking) if ranking else 0}")
                if not ranking:
                    bot.logger.log_info(f"NAME FAMILY HANDLER RESULTS EMPTY chat_id={chat_id} round_id={game['round_id']}")
                    await event.reply("🏆 نتایج\n\nشرکت‌کننده‌ای پاسخ صحیح ثبت نکرد.")
                    return
                medals = ("🥇", "🥈", "🥉")
                lines = ["🏆 نتایج\n"]
                for index, player in enumerate(ranking, 1):
                    medal = medals[index - 1] if index <= 3 else "•"
                    reward = ""
                    if player["points"] >= 70:
                        try:
                            economy.award_game(
                                chat_id, player.get("user_id", "unknown"),
                                "name_family",
                                reference=f"namefamily:{chat_id}:"
                                          f"{game['round_id']}:"
                                          f"{player.get('user_id')}",
                                name=player["name"],
                            )
                            reward = (
                                " — 🪙 +"
                                f"{_math_digits(economy.rewards.amount_for('name_family'))}"
                                " سکه "
                                f"{economy.rewards.coin_name(economy.rewards.coin_for('name_family'))}"
                            )
                        except Exception as error:
                            # پاداش نباید مانع نمایش نتایج شود.
                            bot.logger.log_error(
                                f"NAME FAMILY REWARD FAILED chat_id={chat_id} "
                                f"player={player['name']} error={error!r}"
                            )
                    lines.append(f"{medal} {player['name']} — {player['points']} امتیاز{reward}")
                await event.reply("\n".join(lines))

            # تایمر این بازی در صف اختصاصی خودش نگه داشته می‌شود، نه در
            # group_timer_tasks مشترک؛ پس هیچ بازی یا دستور دیگری نمی‌تواند
            # آن را لغو کند و نتایج همیشه ارسال می‌شوند.
            schedule_name_family_round(
                chat_id,
                game["round_id"],
                name_family_results,
                logger=bot.logger,
            )
            bot.logger.log_info(
                "NAME FAMILY ROUND STARTED "
                f"chat_id={chat_id} round_id={game['round_id']} "
                f"letter={game['letter']} seconds={game.get('seconds', 90)}"
            )
            return

        # ثبت پاسخ اسم فامیل در همان بازی فعال
        if name_family_active(chat_id):
            bot.logger.log_info(
                "NAME FAMILY TRACE HANDLER_BEFORE_SUBMIT "
                f"chat_id={chat_id} user_id={user_id} "
                f"line_count={len(message_text.splitlines())} char_count={len(message_text)}"
            )
            # هر ثبت اسم فامیل ممکن است تا ۷ جستجوی وب همگام انجام دهد
            # (هر دسته یک بار، هرکدام تا ۲ ثانیه). اجرای مستقیم آن حلقه را
            # ده‌ها ثانیه قفل می‌کرد و همهٔ گروه‌ها بی‌پاسخ می‌ماندند.
            #
            # ⚠️ متن «خام» پیام پاس داده می‌شود، نه clean_text:
            # normalize_command همهٔ خط‌ها را به فاصله تبدیل می‌کرد، پس
            # پاسخ ۷ خطی همیشه یک‌خطی می‌رسید و parse_failed می‌شد —
            # همان باگی که هیچ شرکت‌کننده‌ای ثبت نمی‌شد.
            submitted = await _asyncio.to_thread(
                submit_name_family,
                chat_id,
                user_id,
                _format_group_member(sender),
                message_text,
                logger=bot.logger,
                learning_min_observations=bot.config_manager.get("name_family_learning_min_observations", 5),
                learning_min_unique_users=bot.config_manager.get("name_family_learning_min_unique_users", 3),
                learning_min_unique_chats=bot.config_manager.get("name_family_learning_min_unique_chats", 2),
            )
            bot.logger.log_info(
                "NAME FAMILY TRACE HANDLER_AFTER_SUBMIT "
                f"chat_id={chat_id} user_id={user_id} submitted={submitted!r}"
            )
            if submitted is not None:
                await event.reply("✅ پاسخ ثبت شد")
                return

        # ریست پیشرفت حدس ایموجی — تنها راه پاک کردن پیشرفت.
        # ری‌استارت ربات هرگز پیشرفت را پاک نمی‌کند.
        if clean_text in EMOJI_RESET_COMMANDS:
            emoji_guess_reset(chat_id, user_id)
            await event.reply(
                "🔄 پیشرفت حدس ایموجی شما در این گروه پاک شد.\n\n"
                "با «حدس ایموجی» از مرحله ۱ شروع کنید."
            )
            return

        # بازی حدس ایموجی
        if clean_text == "حدس ایموجی":
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            # معمای باز خودِ کاربر نباید با دستور دوباره بازنویسی شود.
            if emoji_guess_active(chat_id, user_id):
                await event.reply(
                    "⏳ شما یک معمای باز دارید؛ اول همان را پاسخ دهید."
                )
                return
            # تاریخچه به تفکیک کاربر: هیچ معمای تکراری برای همان کاربر
            # ارسال نمی‌شود. وقتی همهٔ مرحله‌ها مصرف شد، خودِ start یک
            # «دور» تازه می‌سازد، پس اینجا دیگر جلوی کاربر گرفته نمی‌شود.
            puzzle = start_emoji_guess(chat_id, user_id)
            if puzzle is None:
                await event.reply(EMOJI_GUESS_EXHAUSTED_MESSAGE)
                return
            await event.reply(
                "🎮 حدس ایموجی\n\n"
                f"مرحله {_math_digits(puzzle['stage'])} از "
                f"{_math_digits(EMOJI_GUESS_TOTAL)} — سطح {puzzle['tier']}\n\n"
                f"{puzzle['emoji']}\n\n"
                f"⏳ {_math_digits(EMOJI_GUESS_SECONDS)} ثانیه فرصت دارید"
            )

            async def emoji_timer():
                await _asyncio.sleep(EMOJI_GUESS_SECONDS)
                answer = finish_emoji_guess(
                    chat_id, puzzle["token"], user_id)
                if answer:
                    await event.reply(f"⏰ زمان تمام شد!\n\n✅ پاسخ درست:\n{answer}")
            _track_group_timer(bot, chat_id, _asyncio.create_task(emoji_timer()))
            return

        if emoji_guess_active(chat_id, user_id):
            emoji_token = puzzle_token_for(chat_id, user_id)
            winner_answer = answer_emoji_guess(chat_id, user_id, _format_group_member(sender), clean_text)
            if winner_answer:
                # سکه را خودِ ماژول از راه API اقتصاد پرداخت کرده است؛
                # اینجا فقط موجودی تازه از دیتابیس خوانده و اعلام می‌شود
                # تا دوبار پرداخت نشود.
                balance = economy.get_balance(chat_id, user_id)
                await event.reply(
                    "🎉 پاسخ صحیح بود.\n\n"
                    f"🪙 شما +{_math_digits(EMOJI_REWARD_BRONZE)} سکه برنز دریافت کردید.\n\n"
                    f"💰 موجودی برنز:\n🥉 {_math_digits(balance[economy.BRONZE])}\n\n"
                    f"💎 ارزش کل:\n{_math_digits(balance['total_coin_value'])}"
                )
                return

        # بازی حدس پرچم؛ پرچم Unicode برای نمایش پایدار در Soroush Plus استفاده می‌شود.
        if clean_text == "حدس پرچم":
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            # محدودیت به تفکیک کاربر: وقتی کاربری همهٔ پرچم‌ها را دید، بازی
            # برای او بسته می‌شود تا امتیاز تکراری نگیرد. سایر کاربران آزادند.
            if flag_guess_exhausted(user_id):
                await event.reply(FLAG_GUESS_EXHAUSTED_MESSAGE)
                return
            flag_game = start_flag_guess(chat_id, user_id)
            if flag_game is None:
                await event.reply(FLAG_GUESS_EXHAUSTED_MESSAGE)
                return
            await event.reply(
                "🌍 حدس پرچم\n\n"
                f"{flag_game['flag']}\n\n"
                "این پرچم متعلق به کدام کشور است؟\n\n"
                "⏳ زمان: 30 ثانیه"
            )

            async def flag_timer():
                await _asyncio.sleep(30)
                answer = finish_flag_guess(chat_id, flag_game["token"])
                if answer:
                    await event.reply(f"⏰ زمان تمام شد!\n\n✅ پاسخ درست: {answer}")

            _track_group_timer(bot, chat_id, _asyncio.create_task(flag_timer()))
            return

        if flag_guess_active(chat_id):
            # ⚠️ token باید *پیش* از answer() خوانده شود؛ answer() جلسه را
            # می‌بندد. پیش‌تر اینجا از متغیر flag_game استفاده می‌شد که فقط
            # در شاخهٔ «شروع» ساخته می‌شد، پس در پیام پاسخ اصلاً وجود نداشت
            # و UnboundLocalError می‌داد: کاربر پیام «+۳ سکه» می‌دید ولی
            # هیچ سکه‌ای دریافت نمی‌کرد.
            flag_state = get_flag_guess(chat_id)
            flag_token = flag_state["token"] if flag_state else 0
            country = answer_flag_guess(chat_id, clean_text, user_id)
            if country:
                await _reward_game_reply(
                    event, chat_id, user_id, sender, "flag",
                    reference=f"flag:{chat_id}:{user_id}:{flag_token}",
                )
                return

        # بازی تصحیح کلمات
        if clean_text == "تصحیح کلمات":
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            game = start_correction(chat_id)
            await event.reply(f"{game['wrong']}\n\n۳۰ ثانیه زمان دارید صحیح کلمه را بنویسید")
            async def correction_timer():
                await _asyncio.sleep(30)
                active = get_correction(chat_id)
                if active and active['token'] == game['token']:
                    clear_correction(chat_id, game['token'])
                    await event.reply(f"پاسخ درست:\n{active['correct']}")
            _track_group_timer(bot, chat_id, _asyncio.create_task(correction_timer()))
            return

        correction_state = get_correction(chat_id)
        result_correction = answer_correction(chat_id, clean_text)
        if result_correction is not None:
            if result_correction:
                await _reward_game_reply(
                    event, chat_id, user_id, sender, "correction",
                    reference=f"correction:{chat_id}:"
                              f"{correction_state['token'] if correction_state else 0}",
                )
            return

        # 🧠 کی بیشتر بلده — پاسخ مرحلهٔ فعال
        if _who_knows.is_active(chat_id) and clean_text != "کی بیشتر بلده":
            wk_result = _who_knows.answer(chat_id, user_id, clean_text)
            if wk_result is not None:
                try:
                    economy.award_game(
                        chat_id, user_id, "who_knows",
                        reference=f"who_knows:{chat_id}:{wk_result['token']}:{user_id}",
                        name=_format_group_member(sender),
                    )
                except Exception as error:
                    bot.logger.log_error(f"WHO KNOWS REWARD FAILED: {error!r}")
                await event.reply("✅ درست است!\n\n🥉 +۲ سکه برنز")
                next_stage = _who_knows.start(chat_id)
                if next_stage == "finished":
                    await event.reply(_who_knows.END_MESSAGE)
                elif next_stage:
                    await event.reply(
                        "🧠 کی بیشتر بلده؟\n\n"
                        f"«حرف {next_stage['letter']}»\n\n"
                        f"با این حرف یک {_who_knows.CATEGORY_LABEL[next_stage['category']]} بگو:\n\n"
                        "⏳ زمان: ۲۵ ثانیه"
                    )

                    async def who_knows_timer(stage=next_stage):
                        await _asyncio.sleep(_who_knows.ANSWER_SECONDS)
                        if _who_knows.timeout(chat_id, stage["token"]):
                            await event.reply(
                                "⏰ زمان تمام شد!\n\n"
                                "🧠 مرحله بسته شد.\n"
                                "برای ادامه بنویسید: کی بیشتر بلده"
                            )

                    _track_group_timer(
                        bot, chat_id,
                        _asyncio.create_task(who_knows_timer()),
                    )
                return

        # 🧠 دروغ یا حقیقت — پاسخ سوال فعال (قبل از دستور «حقیقت» جرأت‌حقیقت)
        if _truth_lie.is_active(chat_id):
            tl_result = _truth_lie.answer(chat_id, user_id, clean_text)
            if tl_result is not None:
                if tl_result["correct"]:
                    try:
                        economy.award_game(
                            chat_id, user_id, "truth_lie",
                            reference=f"truth_lie:{chat_id}:{tl_result['token']}:{user_id}",
                            name=_format_group_member(sender),
                        )
                    except Exception as error:
                        bot.logger.log_error(f"TRUTH LIE REWARD FAILED: {error!r}")
                    await event.reply(
                        "✅ درست گفتی!\n\n"
                        f"جواب صحیح:\n{tl_result['truth_label']}\n\n"
                        "🎁 جایزه:\n🥉 +۲ برنز"
                    )
                else:
                    await event.reply(
                        "❌ اشتباه بود!\n\n"
                        f"جواب صحیح:\n{tl_result['truth_label']}"
                    )
                return

        # 🧠 شروع بازی «کی بیشتر بلده»
        if clean_text == "کی بیشتر بلده":
            if _who_knows.is_active(chat_id):
                await event.reply("⏳ یک مرحله همین حالا باز است؛ اول همان را جواب بدهید.")
                return
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            wk_stage = _who_knows.start(chat_id)
            if wk_stage == "finished":
                await event.reply(_who_knows.END_MESSAGE)
                return
            if not wk_stage:
                await event.reply(GAME_BUSY_MESSAGE)
                return
            await event.reply(
                "🧠 کی بیشتر بلده؟\n\n"
                f"«حرف {wk_stage['letter']}»\n\n"
                f"با این حرف یک {_who_knows.CATEGORY_LABEL[wk_stage['category']]} بگو:\n\n"
                "⏳ زمان: ۲۵ ثانیه"
            )

            async def who_knows_start_timer(stage=wk_stage):
                await _asyncio.sleep(_who_knows.ANSWER_SECONDS)
                if _who_knows.timeout(chat_id, stage["token"]):
                    await event.reply(
                        "⏰ زمان تمام شد!\n\n"
                        "🧠 مرحله بسته شد.\n"
                        "برای ادامه بنویسید: کی بیشتر بلده"
                    )

            _track_group_timer(
                bot, chat_id,
                _asyncio.create_task(who_knows_start_timer()),
            )
            return

        # 🧠 شروع بازی «دروغ یا حقیقت»
        if clean_text == "دروغ یا حقیقت":
            if _truth_lie.is_active(chat_id):
                await event.reply("⏳ یک سوال همین حالا باز است؛ اول همان را جواب بدهید.")
                return
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            tl_stage = _truth_lie.start(chat_id)
            if not tl_stage:
                await event.reply(GAME_BUSY_MESSAGE)
                return
            await event.reply(
                "🧠 دروغ یا حقیقت؟\n\n"
                "سوال:\n"
                f"«{tl_stage['question']}»\n\n"
                "جوابت را بفرست:\n\n"
                "1️⃣ حقیقت\n"
                "2️⃣ دروغ\n\n"
                "⏳ زمان: ۲۵ ثانیه"
            )

            async def truth_lie_timer(stage=tl_stage):
                await _asyncio.sleep(_truth_lie.ANSWER_SECONDS)
                tl_timeout = _truth_lie.timeout(chat_id, stage["token"])
                if tl_timeout:
                    await event.reply(
                        "⏰ زمان تمام شد!\n\n"
                        f"جواب صحیح:\n{tl_timeout['truth_label']}"
                    )

            _track_group_timer(
                bot, chat_id,
                _asyncio.create_task(truth_lie_timer()),
            )
            return

        # بازی چهار گزینه‌ای
        normalized_game_command = " ".join(
            clean_text.replace("‌", " ").split()
        )
        if normalized_game_command == "چهار گزینه ای":
            if _chat_game_busy(chat_id):
                await event.reply(GAME_BUSY_MESSAGE)
                return
            try:
                # ⚠️ اینجا عمداً گیتِ «تمام شد» وجود ندارد.
                #
                # پیش‌تر اگر کاربر همهٔ سوال‌ها را دیده بود، بازی برای
                # همیشه برایش بسته می‌شد. حالا ``start_question`` خودش
                # دور تازه می‌سازد و سوال‌هایی که دیرتر دیده شده‌اند
                # دوباره وارد چرخه می‌شوند. ``None`` فقط یعنی واقعاً
                # هیچ سوالی در بانک نیست.
                quiz = start_question(chat_id, user_id)
                if quiz is None:
                    await event.reply(QUIZ_EXHAUSTED_MESSAGE)
                    return
                options_text = "\n".join(
                    f"{index}) {option}"
                    for index, option in enumerate(quiz["options"], 1)
                )
                quiz_text = (
                    "🎯 سوال چهار گزینه‌ای:\n\n"
                    f"{quiz['question']}\n\n"
                    f"{options_text}"
                )

                def u16_length(value):
                    return len(value.encode("utf-16-le")) // 2

                option_start = quiz_text.index(options_text)
                entities = []
                current_offset = option_start
                for option_line in options_text.split("\n"):
                    entities.append(
                        MessageEntityBold(
                            offset=u16_length(quiz_text[:current_offset]),
                            length=u16_length(option_line),
                        )
                    )
                    current_offset += len(option_line) + 1

                await event.reply(quiz_text, formatting_entities=entities)

                async def multiple_choice_timer():
                    await _asyncio.sleep(QUIZ_SECONDS)
                    active_quiz = get_active_question(chat_id)
                    if active_quiz and active_quiz["token"] == quiz["token"]:
                        clear_question(chat_id, quiz["token"])
                        await event.reply(
                            "⏰ زمان تمام شد!\n\n"
                            f"پاسخ درست:\nگزینه {active_quiz['answer']}"
                        )

                _track_group_timer(
                    bot,
                    chat_id,
                    _asyncio.create_task(multiple_choice_timer()),
                )

            except Exception as e:
                bot.logger.log_error(f"خطای بازی چهار گزینه‌ای: {e}")
            return

        # بازی جای خالی
        if clean_text == "جای خالی":
            try:
                q = new_fill(chat_id, user_id)
                fill_token = get_fill_token(chat_id, user_id)
                await event.reply(
                    "📝 جای خالی:\n\n" + q
                    + f"\n\n⏳ {_math_digits(FILL_TIMEOUT)} ثانیه فرصت داری"
                )

                async def fill_timer():
                    # مهلت تایمر دقیقاً برابر مهلت پذیرش پاسخ است و پاک‌سازی
                    # با توکن انجام می‌شود، پس تایمر دور قبلی نمی‌تواند پاسخ
                    # دور جدید را لو بدهد.
                    await _asyncio.sleep(FILL_TIMEOUT)
                    ans = clear_fill(chat_id, user_id, fill_token)
                    if ans:
                        await event.reply(f"⏰ زمان تمام شد!\n✅ پاسخ: {ans}")

                _track_group_timer(
                    bot,
                    chat_id,
                    _asyncio.create_task(fill_timer()),
                )

            except Exception as e:
                bot.logger.log_error(f"خطای جای خالی: {e}")
            return

        # RIDDLE_SAFE_INSERTED
        if clean_text == "چیستان":
            try:
                q = new_riddle(chat_id, user_id)
                riddle_token = get_riddle_token(chat_id, user_id)
                await event.reply(
                    "🧩 چیستان:\n\n" + q
                    + f"\n\n⏳ {_math_digits(RIDDLE_TIMEOUT)} ثانیه فرصت داری جواب بده"
                )

                async def riddle_timer():
                    # قبلاً تایمر ۶۰ ثانیه بود ولی پذیرش پاسخ ۵۰ ثانیه؛ یعنی
                    # ۱۰ ثانیه کاربر پاسخ درست می‌داد و هیچ اتفاقی نمی‌افتاد.
                    await _asyncio.sleep(RIDDLE_TIMEOUT)
                    answer = clear_riddle(chat_id, user_id, riddle_token)
                    if answer:
                        await event.reply(f"⏰ زمان چیستان تمام شد!\n✅ پاسخ: {answer}")

                _track_group_timer(
                    bot,
                    chat_id,
                    _asyncio.create_task(riddle_timer()),
                )

            except Exception as e:
                bot.logger.log_error(f"خطای چیستان: {e}")
            return


        # بررسی جواب جای خالی
        try:
            fill_state = get_fill_token(chat_id, user_id)
            if check_fill(chat_id, user_id, clean_text):
                # پیش‌تر این بازی هیچ جایزه‌ای نمی‌داد.
                await _reward_game_reply(
                    event, chat_id, user_id, sender, "fill_blank",
                    reference=f"fill:{chat_id}:{user_id}:{fill_state}",
                )
                return
        except Exception as e:
            bot.logger.log_error(f"خطای جای خالی: {e}")

        try:
            riddle_answer_token = get_riddle_token(chat_id, user_id)
            if check_answer(chat_id, user_id, clean_text):
                await _reward_game_reply(
                    event, chat_id, user_id, sender, "riddle",
                    reference=f"riddle:{chat_id}:{user_id}:{riddle_answer_token}",
                )
                return
        except Exception as e:
            bot.logger.log_error(f"خطای بررسی جواب چیستان: {e}")

        try:
            quiz_state = get_active_question(chat_id)
            result = answer_question(chat_id, clean_text, user_id)
            if result is not None:
                is_correct, correct_option = result
                if is_correct:
                    await _reward_game_reply(
                        event, chat_id, user_id, sender, "quiz",
                        reference=f"quiz:{chat_id}:"
                                  f"{quiz_state['token'] if quiz_state else 0}",
                    )
                else:
                    await event.reply(
                        f"❌ غلط بود. گزینه {correct_option} درست بود."
                    )
                return
        except Exception as e:
            bot.logger.log_error(f"خطای بررسی پاسخ چهار گزینه‌ای: {e}")

# ثبت آمار پیام گروه
        try:
            if not event.is_private and not fast_command:
                # sender/chat در ابتدای handler resolve شده‌اند؛ دوباره API نخوان.
                _run_background(
                    bot,
                    "group_stats",
                    add_message,
                    chat_id,
                    user_id,
                    getattr(sender, "username", "") or "",
                )
                record_coin_message(
                    chat_id, user_id, _format_admin_display(sender),
                )
                # 🏆 ارتقایِ سطحِ گروه (هر ۱۰۰۰ پیام). فقط وقتی سطح واقعاً
                # عوض شود پیام تبریک فرستاده می‌شود؛ بقیهٔ پیام‌ها فقط یک
                # مقایسهٔ ساده در حافظه هزینه دارند.
                congrats = group_level.maybe_level_up(chat_id)
                if congrats:
                    await event.reply(congrats)

        except Exception as e:
            bot.logger.log_error(
                f"خطای ثبت آمار پیام: {e}"
            )

        # اتصال دستورات فیلتر کلمات گروه
        try:
            # از sender/chat resolve‌شده در ابتدای handler استفاده می‌کنیم.
            handled_group_word = (
                not fast_command and await bot.check_group_word_commands(
                    event, clean_text, chat_id, user_id
                )
            )
            if handled_group_word:
                return

        except Exception as e:
            bot.logger.log_error(
                f"خطای فیلتر گروه: {e}"
            )

        # بازی جرعت حقیقت
        clean_text = message_text.strip()

        if clean_text in ["جرعت", "جرات", "جرئت"]:
            await event.reply("🎯 جرعت:\n" + get_jorat(chat_id))
            return

        if clean_text in ["حقیقت", "حقیقت بگو"]:
            await event.reply("🧠 حقیقت:\n" + get_haghighat(chat_id))
            return



        # فونت ساز چند مدلی
        if clean_text.startswith("فونت "):
            font_text = clean_text.replace("فونت ", "", 1).strip()

            if font_text:
                try:
                    result = make_fonts(font_text)

                    if isinstance(result, list):
                        result = "\n\n".join(result)

                    await event.reply(
                        "✨ فونت‌های ساخته شده:\n\n" + str(result)
                    )

                except Exception as e:
                    bot.logger.log_error(
                        f"خطای فونت ساز: {e}"
                    )

            return


        # جک
        if clean_text == "جک":
            await event.reply(get_joke(chat_id))
            return

        # پاسخ معرفی و فراخوانی مستقیم ربات (فقط تطابق دقیق عبارت کامل).
        if clean_text.strip() in ["ربات", "روباه"]:
            await event.reply(
                "🦊 سلام، من روباه هستم 🤖\n\n"
                "برای آشنایی با امکانات و خدمات بیشتر، کلمه «راهنما» را ارسال کنید."
            )
            return


        # 🩺 دستور تشخیصی مالک: «وضعیت ربات» — در لحظه کندی نشان می‌دهد
        # مشکل از حافظه/CPU خود ربات است یا از شبکه/سرور سروش.
        if clean_text in {"وضعیت ربات", "پینگ ربات"}:
            if is_global_owner(user_id):
                try:
                    await event.reply(await _bot_status_text(bot))
                except Exception as status_error:
                    bot.logger.log_error(f"BOT STATUS FAILED: {status_error!r}")
            return

        if clean_text == "ریست آمار":
            try:
                from modules.group_stats import load_stats, save_stats

                data = load_stats()
                gid = str(chat_id)

                if gid in data:
                    old_members = data[gid].get("members", 0)

                    data[gid]["messages"] = 0
                    data[gid]["deleted"] = 0
                    data[gid]["kicked"] = 0
                    data[gid]["muted"] = 0
                    data[gid]["users"] = {}
                    data[gid]["members"] = old_members

                    save_stats(data)

                await event.reply("✅ آمار گروه ریست شد\n👥 تعداد اعضا حفظ شد")
            except Exception as e:
                await event.reply(f"❌ خطا: {e}")

            return

        # آمار گروه
        if clean_text in ["آمار گپ", "آمار گروه"]:
            member_count = 0

            try:
                entity = await bot.client.get_input_entity(chat_id)
                full = await bot.client(
                    functions.channels.GetFullChannelRequest(entity)
                )
                member_count = full.full_chat.participants_count
            except Exception as e:
                print("MEMBER COUNT ERROR:", repr(e))
                member_count = 0

            print("FINAL MEMBER COUNT:", member_count)
            await event.reply(make_report(chat_id, member_count))
            return

        # لیست بازی
        if clean_text.strip() in ["لیست بازی", "لیست بازی ها", "لیست بازی‌ها", "بازی ها", "بازی‌ها"]:
            bot.logger.log_info(f"HANDLER CALLED handler=game_list command={clean_text!r}")
            games_text = (
                "🎮 لیست بازی‌های روباه\n\n"
                "🧩 چیستان\n"
                "معماهای متنوع برای افزایش هوش و دقت.\n\n"
                "😀 حدس ایموجی\n"
                "حدس عبارت یا کلمه از روی ایموجی‌ها.\n\n"
                "🌍 حدس پرچم\n"
                "تشخیص کشورها از روی پرچم‌های ایموجی.\n\n"
                "📝 اسم فامیل\n"
                "رقابت گروهی با امتیازدهی خودکار.\n\n"
                "✍️ تصحیح کلمات\n"
                "پیدا کردن شکل صحیح کلمات.\n\n"
                "❓ چهار گزینه‌ای\n"
                "پاسخ به سوالات چهارگزینه‌ای در موضوعات مختلف.\n\n"
                "📝 جای خالی\n"
                "تکمیل جمله‌ها و سوالات متنوع.\n\n"
                "😂 بخند یا بباز\n"
                "اولین نفری که ایموجی خنده ارسال کند برنده می‌شود.\n\n"
                "🏕 بقا\n"
                "مرحله‌به‌مرحله به سوالات پاسخ بده و تا پایان بازی زنده بمان.\n\n"
                "🎁 جعبه شانسی\n"
                "از بین ۹ جعبه یکی را انتخاب کن و جایزه یا پوچ بگیر.\n\n"
                "🧛 خون‌آشام\n"
                "خون‌آشام مخفی را قبل از تمام شدن زمان پیدا کن و جایزه بگیر.\n\n"
                "🧩 معما\n"
                "هر بار با ارسال «معما» یک معمای فکری پرسیده می‌شود؛ بعد از پاسخ صحیح یا پایان زمان، بازی تمام می‌شود.\n\n"
                "🧩 حدس کلمه\n"
                "یک سرنخ شامل جمله و ایموجی به شما داده می‌شود، ۳۰ ثانیه زمان دارید.\n\n"
                "✏️ ساخت جمله\n"
                "کلمه‌های به‌هم‌ریخته را مرتب کن و جملهٔ درست را بساز؛ سوال هر نفر جداگانه است.\n\n"
                "💣 مین یاب\n"
                "از بین ۹ خانه یکی را انتخاب کن؛ اگر روی مین نروی جایزه می‌گیری. روزی ۲ شانس.\n\n"
                "🎯 بهترین جواب\n"
                "به فکری‌ترین و دقیق‌ترین پاسخ برس و جایزه بگیر.\n\n"
                "⚔️ نبرد\n"
                "رقابت دو نفره با سوالات سخت، علمی و فکری.\n\n"
                "🎭 جرأت حقیقت\n"
                "با ارسال «جرعت» یا «حقیقت»، یک جرأت یا سوال صادقانه دریافت کن.\n\n"
                "🧠 کی بیشتر بلده\n"
                "حدس کلمات با حرف تصادفی و جایزه.\n\n"
                "🧠 دروغ یا حقیقت\n"
                "تشخیص درست یا غلط بودن سوال‌ها.\n\n"
                "🕵️ کارگاه\n"
                "حل پرونده و پیدا کردن دزد.\n\n"
                "😄 جک\n"
                "با ارسال «جک»، یک جوک یا لطیفه خنده‌دار دریافت کن.\n"
                "برای بازی خصوصی و انلاین بنویسید 🪄\n"
                "سایت بازی"
            )

            entities = []

            def u16(x):
                return len(x.encode("utf-16-le")) // 2

            for word in [
                "🎮 لیست بازی‌های روباه",
                "🧩 چیستان",
                "😀 حدس ایموجی",
                "🌍 حدس پرچم",
                "📝 اسم فامیل",
                "✍️ تصحیح کلمات",
                "❓ چهار گزینه‌ای",
                "📝 جای خالی",
                "😂 بخند یا بباز",
                "🏕 بقا",
                "🎁 جعبه شانسی",
                "🧛 خون‌آشام",
                "🧩 معما",
                "🧩 حدس کلمه",
                "✏️ ساخت جمله",
                "💣 مین یاب",
                "🎯 بهترین جواب",
                "⚔️ نبرد",
                "🎭 جرأت حقیقت",
                "با ارسال «جرعت» یا «حقیقت»، یک جرأت یا سوال صادقانه دریافت کن.",
                "🧠 کی بیشتر بلده",
                "🧠 دروغ یا حقیقت",
                "🕵️ کارگاه",
                "😄 جک",
                "با ارسال «جک»، یک جوک یا لطیفه خنده‌دار دریافت کن.",
                "برای بازی خصوصی و انلاین بنویسید",
            ]:
                pos = games_text.find(word)
                if pos != -1:
                    entities.append(
                        MessageEntityBold(
                            offset=u16(games_text[:pos]),
                            length=u16(word)
                        )
                    )

            await event.reply(
                games_text,
                formatting_entities=entities
            )
            return

        # راهنمای ربات
        help_commands = {"راهنما", "/help", "!help", "help", "لیست کاربران", "لیست ادمینی"}
        if clean_text.strip() in help_commands:
            bot.logger.log_info(f"HANDLER CALLED handler=help command={clean_text!r}")
            # متن راهنما برای همهٔ کاربران یکسان است؛ هیچ نام یا اطلاعات
            # شخصی‌ای داخل آن قرار نمی‌گیرد. دستور «شخصیت» منطق جداگانهٔ
            # خودش را دارد و فقط نامی را تحلیل می‌کند که کاربر خودش می‌نویسد.
            full_help_text = (
                "📌 راهنمای روباه\n\n"

                "👤 کاربران:\n\n"
                "برای ثبت اصل بنویسید:\n"
                "ثبت اصل\n\n"
                "برای نمایش اصل بنویسید:\n"
                "اصلم\n\n"
                "آمار یک کاربر:\n"
                "برای دریافت آمار بنویسید:\n"
                "آمارم\n\n"
                "برای گرفتن بیوگرافی:\n"
                "بیوگرافی\n\n"
                "📥 دانلود عکس مستقیم:\n"
                "برای دانلود عکس به صورت مستقیم، بنویسید:\n"
                "دانلود عکس\n\n"

                "🎮 لیست بازی‌ها:\n\n"
                "برای مشاهده بازی‌ها بنویسید:\n"
                "لیست بازی\n"
                "برای بازی خصوصی و انلاین بنویسید 🪄\n"
                "سایت بازی\n\n"

                "🧩 معما:\n"
                "با ارسال «معما» یک معما از روی ایموجی‌ها شروع می‌شود.\n"
                "فقط خودت می‌توانی پاسخ دهی. زمان: ۴۰ ثانیه.\n"
                "پاسخ صحیح: ۳ سکه برنز.\n\n"
                "🎯 بهترین جواب:\n"
                "با ارسال «بهترین جواب» یک سوال فکری مطرح می‌شود.\n"
                "پاسخ خود را بفرستید؛ بهترین پاسخ برنده است. زمان: ۴۰ ثانیه.\n"
                "جایزه بهترین پاسخ: ۲ سکه برنز.\n\n"
                "⚔️ نبرد:\n"
                "با «نبرد» شروع و بازیکن دوم با «شرکت» می‌پیوندد.\n"
                "هر بازیکن ۳ سوال سخت می‌گیرد؛ هر کدام ۳۰ ثانیه.\nبرنده: ۲ سکه برنز (اگر مساوی شود هر دو ۲ سکه برنز).\n\n"
                "🎭 جرأت حقیقت:\n"
                "با ارسال «جرعت» یا «حقیقت»، یک جرأت یا سوال صادقانه دریافت کن.\n\n"
                "😄 جک:\n"
                "با ارسال «جک»، یک جوک یا لطیفه خنده‌دار دریافت کن.\n\n"

                "🎵 جستجوی آهنگ و مطالب:\n\n"
                "برای جستجو بنویسید:\n"
                "جستجو دانلود اسم آهنگ\n\n"
                "برای جستجو مطالب بنویسید:\n"
                "جستجو اسم مطلبی که می‌خواهید بدانید\n\n"

                "✍️ ساخت فونت:\n\n"
                "فونت متن شما\n\n"

                "🌐 ترجمه انگلیسی به فارسی:\n\n"
                "برای استفاده بنویسید:\n"
                "ترجمه\n\n"

                "🏆 امتیاز و رتبه:\n\n"
                "برای دریافت راهنمای امتیاز:\n"
                "راهنمای امتیاز\n\n"
                "برای نمایش امتیاز خود:\n"
                "امتیاز من\n\n"
                "برای مشاهده برترین کاربران گروه:\n"
                "رتبه ها\n\n"

                "⏰ یادآوری:\n\n"
                "برای ثبت یادآوری:\n"
                "یاد آوری\n\n"

                "🧠 حافظه گروه:\n\n"
                "حافظه گروه بعد از ثبت اسم، ربات شما را با اسم صدا می‌کند.\n\n"
                "ثبت اسم:\n"
                "ثبت اسم علی\n"
                "یا\n"
                "ثبت علی\n\n"
                "مشاهده حافظه:\n"
                "حافظه من\n\n"
                "حذف اسم:\n"
                "حذف اسم\n\n"

                "🧩 تحلیل نام:\n\n"
                "شخصیت اسم خودتو بنویس\n\n"

                "📚 دانستنی:\n\n"
                "برای دریافت یک دانستنی:\n"
                "دانستنی\n\n"

                "🏆 سطح گروه:\n\n"
                "هر ۱۰۰۰ پیام یک سطح؛ تا سطح ۲۰.\n"
                "برای دیدن سطح گروه و فعال‌ترین عضو بنویسید:\n"
                "سطح گروه\n\n"

                "🛒 اقتصاد و آیتم‌ها:\n\n"
                "برای دیدن لیست خرید و آیتم‌ها بنویسید:\n"
                "فروشگاه\n\n"
                "برای انتقال سکه، تبدیل سکه‌ها و مشاهده امکانات مالی بنویسید:\n"
                "موجودی\n\n"
                "برای ثبت و مدیریت پروفایل خود بنویسید:\n"
                "ثبت پرفایل | پرفایلم | حذف پرفایل\n\n"

                "🛡️ امنیت گروه:\n\n"
                "پیام‌های تبلیغاتی، فورواردی، تکراری و هرزنامه‌ها خودکار بررسی می‌شوند.\n\n"

                "👑 دستورات ادمین‌ها:\n\n"
                "دیدن لیست ادمین‌ها\n"
                "بنویسید:\n"
                "لیست ادمین\n\n"
                "برای قفل کردن ارسال پیام گروه:\nقفل\n\n"
                "برای باز کردن ارسال پیام در گروه بنویسید:\nباز\n\n"
                "برای خالی کردن لیست اخراج شده ها:\nریست اخراجی ها\n\n"
                "📜 قوانین گروه (مدیر)\n"
                "ثبت قوانین  |  قوانین  |  حذف قوانین\n\n"
                "برای حذف حافظهٔ یک کاربر روی پیام او ریپلای کنید و بنویسید:\n\n"
                "روی کاربر ریپلای کنید بنویسید: حذف حافظه\n\n"
                "⚠️ اخطار دادن به کاربر:\n"
                "روی پیام ریپلای کنید و بنویسید:\n"
                "اخطار\n\n"
                "برای تایین سقف اخطار و تغییر اخطار بنویسید\n\n"
                "تغییر اخطار\n\n"
                "برای تغییر مجازات از اخراج کردن به سکوت و برعکس بنویسید\n\n"
                "تغییر مجازات\n\n"
                "🔤 فیلتر کلمات گروه:\n"
                "/فیلتر کلمه  ← افزودن کلمه ممنوعه\n"
                "/رفع کلمه  ← حذف کلمه از فیلتر\n"
                "/فیلترها  ← نمایش لیست فیلترهای گروه\n\n"
                "📊 آمار گروه\n"
                "نمایش آمار پیام‌ها، تعداد اعضا و کاربران فعال گروه\n\n"
                "♻️ ریست آمار\n"
                "صفر کردن آمار گروه (تعداد اعضا باقی می‌ماند)\n\n"
                "✏️ تغییر اسم گروه:\n"
                "!اسم نام جدید گروه\n\n"
                "👑 مدیریت ادمین‌ها:\n\n"
                "➕ افزودن ادمین:\n\n"
                "مالک گروه روی پیام کاربر ریپلای کند و بنویسد:\n"
                "ثبت ادمین\n\n"
                "برای برکناری ادمین بنویسید:\n\n"
                "برای برکناری ادمین:\n"
                "مالک گروه روی پیام ادمین ریپلای کند و بنویسد:\n\n"
                "برکناری ادمین\n\n"
                "یا\n\n"
                "لغو ادمین\n\n"
                "برای اینکه ربات به یک کاربری که ادمین نیست روش ریپلای کنید و بنویسید\n\n"
                "vip\n\n"
                "برای لغو ریپلای کنید بنویسی\n\n"
                "لغو vip\n\n"
                "برای دیدن لیست vip ها بنویسید\n\n"
                "لیست vip\n\n"
                "🛡️ حالت سختگیرانه:\n\n"
                "فعال سازی:\n"
                "فعال کلمات ممنوعه\n\n"
                "غیرفعال سازی:\n"
                "لغو کلمات ممنوعه\n\n"
                "🗑️ حذف پیام:\n"
                "حذف یک پیام با ریپلای:\n"
                "پاک\n\n"
                "حذف چند پیام آخر گروه:\n\n"
                "پاک + عدد مورد نیاز\n\n"
                "مثال:\n"
                "پاک 10\n"
                "پاک 100\n"
                "پاک 700\n\n"
                "🔇 سکوت کاربر:\n"
                "روی پیام ریپلای کنید و بنویسید:\n"
                "سکوت\n\n"
                "🔊 رفع سکوت کاربر:\n"
                "روی پیام ریپلای کنید و بنویسید:\n"
                "رفع سکوت\n\n"
                "🚪 اخراج کاربر:\n"
                "روی پیام ریپلای کنید و بنویسید:\n"
                "اخراج\n\n"
                "♻️ آزاد کردن کاربر:\n"
                "برای آزاد کردن روی پیام کاربر محروم شده بنویسید:\n\n"
                "آزاد\n\n"
                "برای آزاد کردن با یوزرنیم به این صورت بنویسید:\n\n"
                "آزاد @username\n\n"
                "علامت @ باید قبل از یوزرنیم قرار بگیرد\n\n"
                "برای سنجاق کردن پیام\n"
                "روی پیام موردنظر ریپلای کنید و بنویسید:\n"
                "سنجاق\n\n"
                "برای نمایش پیام سنجاق‌شده\n"
                "بنویسید:\n"
                "پیام سنجاق\n\n"
                "🧾 لاگ مدیریتی:\n"
                "برای دیدن اینکه ادمین‌ها چه کسی و چه پیامی را حذف کردند\n"
                "«🧾 \"لاگ مدیریتی\"»\n\n"
                "🗂 سابقه‌ها:\n"
                "برای دیدن سابقهٔ اخراج، سکوت و اخطار کاربران (۲۴ ساعت اخیر)\n"
                "«🗂 \"سابقه ها\"»\n\n"
                "🧹 پاکسازی خودکار:\n"
                "برای پاکسازی خودکار پیام‌ها\n"
                "«🧹 \"پاکسازی خودکار\"»\n\n"
                "🤖 سیستم هوش مصنوعی گوگل ربات\n\n"
                "برای فعال کردن: هوش مصنوعی فعال\n"
                "برای خاموش کردن: هوش مصنوعی خاموش\n"
                "برای انتخاب کاربری که بتواند از هوش مصنوعی استفاده کند: روی پیام کاربر ریپلای کنید و بنویسید: مجاز\n"
                "برای حذف دسترسی: غیر مجاز\n"
                "برای دیدن افرادی که مجاز هستند: لیست هوش مصنوعی\n\n"
                "⚠️ صفر کردن تخلفات:\n"
                "صفر کردن تخلفات توسط مالک اصلی ربات یا مالک گروه\n"
                "«روی کاربر ریپلای کنید و بنویسید \"صفر\"»\n\n"
                "🗑️ حذف اخطار:\n"
                "برای حذف اخطار داده‌شده به یک کاربر\n"
                "«روی پیام کاربر ریپلای کنید و بنویسید \"حذف اخطار\"»\n\n"
                "با سازنده ربات تماس بگیرید:\n"
                "@osine2"
            )

            admin_marker = "👑 دستورات ادمین‌ها:\n\n"
            games_marker = "🎮 لیست بازی‌ها:\n\n"
            if clean_text.strip() == "لیست کاربران":
                bot.logger.log_info("HANDLER CALLED handler=user_list")
                # «لیست کاربران» فقط دستورات کاربری را نشان می‌دهد؛ بخش بازی‌ها
                # از آن حذف می‌شود تا بازی‌ها فقط در «🎮 لیست بازی‌ها» دیده شوند.
                pre_admin = full_help_text[:full_help_text.index(admin_marker)]
                if games_marker in pre_admin:
                    gs = pre_admin.index(games_marker)
                    # پایان بخش بازی‌ها = شروع «جستجوی آهنگ»
                    ge = pre_admin.index("🎵 جستجوی آهنگ و مطالب:")
                    # بخش «🎮 لیست بازی‌ها» را نگه می‌داریم ولی فقط تا قبل از
                    # اولین بازی؛ تا کاربر بداند برای دیدن بازی‌ها «لیست بازی»
                    # بنویسد، بدون اینکه تک‌تک بازی‌ها در «لیست کاربران» بیایند.
                    first_game = pre_admin.find("🧩 معما:", gs)
                    games_intro = pre_admin[gs:first_game] if first_game != -1 \
                        else pre_admin[gs:ge]
                    help_text = pre_admin[:gs] + games_intro + pre_admin[ge:]
                else:
                    help_text = pre_admin
            elif clean_text.strip() == "لیست ادمینی":
                help_text = full_help_text[full_help_text.index(admin_marker):]
            else:
                help_text = (
                    "🦊 راهنمای روباه\n\n"
                    "برای دریافت دستورات عمومی و کاربران بنویسید:\n\n"
                    "لیست کاربران\n\n"
                    "برای دریافت دستورات مالک و ادمین‌ها بنویسید:\n\n"
                    "لیست ادمینی"
                )

            entities = []

            def u16(x):
                return len(x.encode("utf-16-le")) // 2

            # بولد کردن عنوان چیستان
            try:
                idx = help_text.find("🧩 چیستان")
                if idx >= 0:
                    entities.append(
                        MessageEntityBold(
                            offset=u16(idx),
                            length=u16(len("🧩 چیستان"))
                        )
                    )
            except Exception:
                pass

            # فقط عنوان‌ها و جمله‌های توضیحی Bold می‌شوند؛ دستورهایی که
            # کاربر باید بفرستد عمداً عادی می‌مانند تا قابل تشخیص باشند.
            # Bold با entity داخلی سروش پلاس ساخته می‌شود، نه Markdown.
            bold_pieces = [
                # عنوان بخش‌ها
                "👤 کاربران:",
                "🎮 لیست بازی‌ها:",
                "🎵 جستجوی آهنگ و مطالب:",
                "✍️ ساخت فونت:",
                "🌐 ترجمه انگلیسی به فارسی:",
                "🏆 امتیاز و رتبه:",
                "⏰ یادآوری:",
                "🧠 حافظه گروه:",
                "🧩 تحلیل نام:",
                "📚 دانستنی:",
                "🏆 سطح گروه:",
                "🛒 اقتصاد و آیتم‌ها:",
                "🛡️ امنیت گروه:",
                # جمله‌های توضیحی
                "برای ثبت اصل بنویسید:",
                "برای نمایش اصل بنویسید:",
                "آمار یک کاربر:",
                "برای دریافت آمار بنویسید:",
                "برای گرفتن بیوگرافی:",
                "📥 دانلود عکس مستقیم:",
                "برای دانلود عکس به صورت مستقیم، بنویسید:",
                "دانلود عکس",
                "برای مشاهده بازی‌ها بنویسید:",
                "برای بازی خصوصی و انلاین بنویسید",
                "🧩 معما:\nبا ارسال «معما» یک معما از روی ایموجی‌ها شروع می‌شود.\nفقط خودت می‌توانی پاسخ دهی. زمان: ۴۰ ثانیه.\nپاسخ صحیح: ۳ سکه برنز.",
                "🎯 بهترین جواب:\nبا ارسال «بهترین جواب» یک سوال فکری مطرح می‌شود.\nپاسخ خود را بفرستید؛ بهترین پاسخ برنده است. زمان: ۴۰ ثانیه.\nجایزه بهترین پاسخ: ۲ سکه برنز.",
                "⚔️ نبرد:\nبا «نبرد» شروع و بازیکن دوم با «شرکت» می‌پیوندد.\nسوالات سخت، هر کدام ۳۰ ثانیه.\nبرنده: ۲ سکه برنز (اگر مساوی شود هر دو ۲ سکه برنز).",
                "🎭 جرأت حقیقت:\nبا ارسال «جرعت» یا «حقیقت»، یک جرأت یا سوال صادقانه دریافت کن.",
                "😄 جک:\nبا ارسال «جک»، یک جوک یا لطیفه خنده‌دار دریافت کن.",
                "برای جستجو بنویسید:",
                "برای جستجو مطالب بنویسید:",
                "برای استفاده بنویسید:",
                "برای دریافت راهنمای امتیاز:",
                "برای نمایش امتیاز خود:",
                "برای مشاهده برترین کاربران گروه:",
                "برای ثبت یادآوری:",
                "حافظه گروه بعد از ثبت اسم، ربات شما را با اسم صدا می‌کند.",
                "ثبت اسم:",
                "مشاهده حافظه:",
                "حذف اسم:",
                "برای دریافت یک دانستنی:",
                "هر ۱۰۰۰ پیام یک سطح؛ تا سطح ۲۰.",
                "برای دیدن سطح گروه و فعال‌ترین عضو بنویسید:",
                "برای دیدن لیست خرید و آیتم‌ها بنویسید:",
                "برای انتقال سکه، تبدیل سکه‌ها و مشاهده امکانات مالی بنویسید:",
                "برای ثبت و مدیریت پروفایل خود بنویسید:",
                "پیام‌های تبلیغاتی، فورواردی، تکراری و هرزنامه‌ها خودکار بررسی می‌شوند.",
                # منوی کوتاه
                "برای دریافت دستورات عمومی و کاربران بنویسید:",
                "برای دریافت دستورات مالک و ادمین‌ها بنویسید:",
                # بخش ادمین (دست‌نخورده)
                "👑 دستورات ادمین‌ها:",
                "دیدن لیست ادمین‌ها",
                "برای سنجاق کردن پیام",
                "برای نمایش پیام سنجاق‌شده",
                "برای قفل کردن ارسال پیام گروه:",
                "برای باز کردن ارسال پیام در گروه بنویسید:",
                "📜 قوانین گروه (مدیر)",
                "برای حذف حافظهٔ یک کاربر روی پیام او ریپلای کنید و بنویسید:",
                "👑 مدیریت ادمین‌ها:",
                "➕ افزودن ادمین:",
                "برای برکناری ادمین بنویسید:",
                "🛡️ حالت سختگیرانه:",
                "فعال سازی:",
                "غیرفعال سازی:",
                "🔤 فیلتر کلمات گروه:",
                "📊 آمار گروه",
                "♻️ ریست آمار",
                "✏️ تغییر اسم گروه:",
                "🗑️ حذف پیام:",
                "حذف یک پیام با ریپلای:",
                "حذف چند پیام آخر گروه:",
                "🔇 سکوت کاربر:",
                "🔊 رفع سکوت کاربر:",
                "🚪 اخراج کاربر:",
                # کل بخش «آزاد کردن کاربر» یک‌جا بولد می‌شود تا همراه
                # نقل‌قول شیشه‌ای یکپارچه باشد.
                "♻️ آزاد کردن کاربر:\nبرای آزاد کردن روی پیام کاربر محروم شده بنویسید:\n\nآزاد\n\nبرای آزاد کردن با یوزرنیم به این صورت بنویسید:\n\nآزاد @username\n\nعلامت @ باید قبل از یوزرنیم قرار بگیرد",
                "⚠️ اخطار دادن به کاربر:",
                # عنوان‌های سقف اخطار و تغییر مجازات بولد؛ خود دستورها عادی.
                "برای تایین سقف اخطار و تغییر اخطار بنویسید",
                "برای تغییر مجازات از اخراج کردن به سکوت و برعکس بنویسید",
                "⚠️ صفر کردن تخلفات:",
                # قابلیت‌های مدیریتی جدید
                "🧾 لاگ مدیریتی:",
                "برای دیدن اینکه ادمین‌ها چه کسی و چه پیامی را حذف کردند",
                "🗂 سابقه‌ها:",
                "برای دیدن سابقهٔ اخراج، سکوت و اخطار کاربران (۲۴ ساعت اخیر)",
                "🧹 پاکسازی خودکار:",
                "برای پاکسازی خودکار پیام‌ها",
                "برای فعال کردن:",
                "برای خاموش کردن:",
                "برای انتخاب کاربری که بتواند از هوش مصنوعی استفاده کند:",
                "برای حذف دسترسی:",
                "برای دیدن افرادی که مجاز هستند:",
                "صفر کردن تخلفات توسط مالک اصلی ربات یا مالک گروه",
                "🗑️ حذف اخطار:",
                "برای حذف اخطار داده‌شده به یک کاربر",
            ]
            # هر تکه ممکن است چند بار در متن بیاید (مثل «حذف اسم:» که هم
            # عنوان است هم دستور)؛ فقط جایگاه‌های واقعی علامت می‌خورند.
            for word in bold_pieces:
                search_from = 0
                while True:
                    pos = help_text.find(word, search_from)
                    if pos == -1:
                        break
                    entities.append(
                        MessageEntityBold(
                            offset=u16(help_text[:pos]),
                            length=u16(word)
                        )
                    )
                    search_from = pos + len(word)

            admin_command_quotes = (
                ("دیدن لیست ادمین‌ها\nبنویسید:\nلیست ادمین", "لیست ادمین"),
                ("برای سنجاق کردن پیام\nروی پیام موردنظر ریپلای کنید و بنویسید:\nسنجاق", "سنجاق"),
                ("برای نمایش پیام سنجاق‌شده\nبنویسید:\nپیام سنجاق", "پیام سنجاق"),
                ("برای قفل کردن ارسال پیام گروه:\nقفل", "قفل"),
                ("برای باز کردن ارسال پیام در گروه بنویسید:\nباز", "باز"),
                ("برای خالی کردن لیست اخراج شده ها:\nریست اخراجی ها", None),
            )
            for section, command in admin_command_quotes:
                section_start = help_text.find(section)
                if section_start == -1:
                    continue
                command_start = section_start
                command_length = len(section)
                if command is not None:
                    command_start += section.rfind(command)
                    command_length = len(command)
                entities.append(
                    MessageEntityBlockquote(
                        offset=u16(help_text[:command_start]),
                        length=u16(help_text[command_start:command_start + command_length]),
                    )
                )

            quote_sections = [
                "لیست کاربران",
                "لیست ادمینی",
                # کل بخش قوانین گروه باید یک نقل قول شیشه‌ای یکپارچه باشد.
                "📜 قوانین گروه (مدیر)\n"
                "ثبت قوانین  |  قوانین  |  حذف قوانین\n\n"
                "برای حذف حافظهٔ یک کاربر روی پیام او ریپلای کنید و بنویسید:\n\n"
                "روی کاربر ریپلای کنید بنویسید: حذف حافظه",
                "⚠️ اخطار دادن به کاربر:\nروی پیام ریپلای کنید و بنویسید:\nاخطار",
                # هر بخش کامل داخل یک نقل قول شیشه‌ای جدا.
                "برای تایین سقف اخطار و تغییر اخطار بنویسید\n\nتغییر اخطار",
                "برای تغییر مجازات از اخراج کردن به سکوت و برعکس بنویسید\n\nتغییر مجازات",
                "🔤 فیلتر کلمات گروه:\n/فیلتر کلمه  ← افزودن کلمه ممنوعه\n/رفع کلمه  ← حذف کلمه از فیلتر\n/فیلترها  ← نمایش لیست فیلترهای گروه",
                "📊 آمار گروه\nنمایش آمار پیام‌ها، تعداد اعضا و کاربران فعال گروه",
                "♻️ ریست آمار\nصفر کردن آمار گروه (تعداد اعضا باقی می‌ماند)",
                "✏️ تغییر اسم گروه:\n!اسم نام جدید گروه",
                "👑 مدیریت ادمین‌ها:\n\n➕ افزودن ادمین:\n\nمالک گروه روی پیام کاربر ریپلای کند و بنویسد:\nثبت ادمین\n\nبرای برکناری ادمین بنویسید:\n\nبرای برکناری ادمین:\nمالک گروه روی پیام ادمین ریپلای کند و بنویسد:\n\nبرکناری ادمین\n\nیا\n\nلغو ادمین",
                "🛡️ حالت سختگیرانه:\n\nفعال سازی:\nفعال کلمات ممنوعه\n\nغیرفعال سازی:\nلغو کلمات ممنوعه",
                "🗑️ حذف پیام:\nحذف یک پیام با ریپلای:\nپاک\n\nحذف چند پیام آخر گروه:\n\nپاک + عدد مورد نیاز\n\nمثال:\nپاک 10\nپاک 100\nپاک 700",
                "🔇 سکوت کاربر:\nروی پیام ریپلای کنید و بنویسید:\nسکوت",
                "🔊 رفع سکوت کاربر:\nروی پیام ریپلای کنید و بنویسید:\nرفع سکوت",
                "🚪 اخراج کاربر:\nروی پیام ریپلای کنید و بنویسید:\nاخراج",
                "♻️ آزاد کردن کاربر:\nبرای آزاد کردن روی پیام کاربر محروم شده بنویسید:\n\nآزاد\n\nبرای آزاد کردن با یوزرنیم به این صورت بنویسید:\n\nآزاد @username\n\nعلامت @ باید قبل از یوزرنیم قرار بگیرد",
                "🤖 سیستم هوش مصنوعی گوگل ربات\n\n"
                "برای فعال کردن: هوش مصنوعی فعال\n"
                "برای خاموش کردن: هوش مصنوعی خاموش\n"
                "برای انتخاب کاربری که بتواند از هوش مصنوعی استفاده کند: روی پیام کاربر ریپلای کنید و بنویسید: مجاز\n"
                "برای حذف دسترسی: غیر مجاز\n"
                "برای دیدن افرادی که مجاز هستند: لیست هوش مصنوعی",
                "⚠️ صفر کردن تخلفات:\nبا سازنده ربات تماس بگیرید:\n@osine2",
                # قابلیت‌های مدیریتی جدید
                "🧾 لاگ مدیریتی:\nبرای دیدن اینکه ادمین‌ها چه کسی و چه پیامی را حذف کردند\n«🧾 \"لاگ مدیریتی\"»",
                "🗂 سابقه‌ها:\nبرای دیدن سابقهٔ اخراج، سکوت و اخطار کاربران (۲۴ ساعت اخیر)\n«🗂 \"سابقه ها\"»",
                "🧹 پاکسازی خودکار:\nبرای پاکسازی خودکار پیام‌ها\n«🧹 \"پاکسازی خودکار\"»",
                "صفر کردن تخلفات توسط مالک اصلی ربات یا مالک گروه\n«روی کاربر ریپلای کنید و بنویسید \"صفر\"»",
                "🗑️ حذف اخطار:\nبرای حذف اخطار داده‌شده به یک کاربر\n«روی پیام کاربر ریپلای کنید و بنویسید \"حذف اخطار\"»",
            ]
            # بخش vip: کل متن داخل یک نقل‌قول شیشه‌ای
            vip_help_section = (
                "برای اینکه ربات به یک کاربری که ادمین نیست روش ریپلای کنید و بنویسید\n\n"
                "vip\n\n"
                "برای لغو ریپلای کنید بنویسی\n\n"
                "لغو vip\n\n"
                "برای دیدن لیست vip ها بنویسید\n\n"
                "لیست vip"
            )
            for section in quote_sections + [vip_help_section]:
                pos = help_text.find(section)
                if pos != -1:
                    entities.append(
                        MessageEntityBlockquote(
                            offset=u16(help_text[:pos]),
                            length=u16(section)
                        )
                    )

            # دستورات vip: بولد در موقعیت دقیق تا «vip»ِ داخل «لغو vip» و
            # «لیست vip» تکراری/هم‌پوشان نشود. anchor دقیقاً تا پایان
            # کلمهٔ دستور تمام می‌شود.
            for _vip_anchor, _vip_word in (
                ("ریپلای کنید و بنویسید\n\nvip", "vip"),
                ("ریپلای کنید بنویسی\n\nلغو vip", "لغو vip"),
                ("بنویسید\n\nلیست vip", "لیست vip"),
            ):
                _vip_pos = help_text.find(_vip_anchor)
                if _vip_pos != -1:
                    _vip_start = _vip_pos + len(_vip_anchor) - len(_vip_word)
                    entities.append(
                        MessageEntityBold(
                            offset=u16(help_text[:_vip_start]),
                            length=u16(_vip_word),
                        )
                    )

            await event.reply(
                help_text,
                                                        formatting_entities=entities
            )
            return

        # فعال‌سازی گروه توسط مالک اصلی
        if clean_text == "فعال سازی":
            try:
                sender = await event.get_sender()
                print("OWNER DEBUG:", getattr(sender, "username", None), getattr(sender, "id", None), getattr(sender, "first_name", None))
                if not is_global_owner(getattr(sender, "id", None)):
                    await event.reply("❌ فقط مالک ربات اجازه این دستور را دارد")
                    return

                chat = await event.get_chat()
                gid = getattr(chat, "id", None)
                title = getattr(chat, "title", )

                if clean_text == "فعال سازی":
                    activate_group(gid, title)

                    await send_activation_message(bot, event, gid, title)

            except Exception as e:
                await event.reply(f"❌ خطا: {e}")

            return

        chat = event_chat
        if chat is None:
            try:
                chat = await event.get_chat()
            except Exception:
                chat = None
        chat_id = getattr(chat, "id", None) if chat is not None else chat_id

        # اجرای دستورات مدیریتی
        if clean_text in ["لغو کلمات ممنوعه", "فعال کلمات ممنوعه"]:
            try:
                sender = await event.get_sender()
                await handle_admin_commands(bot, 
                    event,
                    clean_text,
                    getattr(sender, "id", 0),
                    chat_id
                )
                return
            except Exception as e:
                bot.logger.log_error(f"خطای اجرای دستور کلمات ممنوعه: {e}")

        if (
            clean_text.startswith(("!", "/", "."))
            and not clean_text.startswith(("/فیلتر ", "/رفع "))
            and clean_text != "/فیلترها"
        ):
            try:
                sender = await event.get_sender()
                await handle_admin_commands(bot, 
                    event,
                    clean_text,
                    getattr(sender, "id", 0),
                    chat_id
                )
                return
            except Exception as e:
                bot.logger.log_error(f"خطای اجرای دستور مدیر: {e}")
        chat_title = getattr(chat, "title", "Unknown") if chat is not None else "Unknown"

        user_id = getattr(sender, "id", None)
        username = (
            getattr(sender, "username", None)
            or getattr(sender, "first_name", "Unknown")
        )

        if clean_text == "ریست اخراجی ها":
            if str(user_id) != str(get_group_owner(chat_id)):
                await event.reply("❌ فقط مالک ثبت‌شده اجازه استفاده از این دستور را دارد")
                return

            banned_data = load_banned()
            group_key = str(chat_id)
            removed_count, remaining_entries = await reset_system_removed_users(
                bot.client,
                chat_id,
                banned_data.get(group_key, []),
                bot.logger,
                resolved_chat=chat,
            )
            if remaining_entries:
                banned_data[group_key] = remaining_entries
            else:
                banned_data.pop(group_key, None)
            save_banned(banned_data)
            await event.reply(f"🔗[ {removed_count} کاربران اخراج شده ] از لیست خارج شد")
            return

        if clean_text == "لیست ادمین":
            _log_command_route(bot, clean_text, "لیست ادمین", "admin_list")
            if not _has_group_management_permission(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply("❌ فقط مالک یا ادمین ثبت‌شده اجازه استفاده دارد")
                return

            async def admin_display(user_id=None, username=None):
                if username:
                    return f"@{username.lstrip('@')}"
                if user_id is not None:
                    try:
                        entity = await bot.client.get_entity(user_id)
                        return _format_admin_display(entity)
                    except Exception:
                        pass
                return "Unknown User"

            # بخش اول فقط از storage پایدار ادمین‌های ثبت‌شده توسط ربات.
            registered_entries = load_admins().get(normalize_group_id(chat_id), [])
            registered_admins = []
            for entry in registered_entries:
                if isinstance(entry, dict):
                    formatted = await admin_display(
                        user_id=entry.get("user_id"), username=entry.get("username")
                    )
                else:
                    formatted = await admin_display(username=entry)
                if formatted != "Unknown User":
                    registered_admins.append(formatted)

            # بخش دوم فقط از API ادمین‌های واقعی همین گروه.
            group_admins = []
            try:
                async for participant in bot.client.iter_participants(
                    chat_id, filter=types.ChannelParticipantsAdmins()
                ):
                    formatted = _format_admin_display(participant)
                    if formatted != "Unknown User":
                        group_admins.append(formatted)
            except Exception as error:
                bot.logger.log_error(f"خطا در دریافت ادمین‌های گروه: {error}")

            registered_text = "\n".join(
                f"★ : {admin}" for admin in registered_admins
            ) if registered_admins else "ندارد"
            group_text = "\n".join(
                f"☆ : {admin}" for admin in group_admins
            ) if group_admins else "ندارد"
            admin_text = (
                "✍ ادمین‌های ثبت‌شده ربات\n"
                f"{registered_text}\n\n"
                "✍ ادمین‌های گروه\n"
                f"{group_text}"
            )

            def admin_u16(value):
                return len(value.encode("utf-16-le")) // 2

            registered_title = "✍ ادمین‌های ثبت‌شده ربات"
            group_title = "✍ ادمین‌های گروه"
            registered_start = len(registered_title) + 1
            group_start = admin_text.index(group_title) + len(group_title) + 1
            entities = [
                MessageEntityBold(offset=0, length=admin_u16(registered_title)),
                MessageEntityBlockquote(
                    offset=admin_u16(admin_text[:registered_start]),
                    length=admin_u16(registered_text),
                ),
                MessageEntityBold(
                    offset=admin_u16(admin_text[:admin_text.index(group_title)]),
                    length=admin_u16(group_title),
                ),
                MessageEntityBlockquote(
                    offset=admin_u16(admin_text[:group_start]),
                    length=admin_u16(group_text),
                ),
            ]
            await event.reply(admin_text, formatting_entities=entities)
            return

        if clean_text == "سنجاق":
            if not _has_group_management_permission(bot, chat_id, user_id, getattr(sender, "username", None)):
                await event.reply("❌ فقط مالک یا ادمین ثبت‌شده اجازه استفاده دارد")
                return
            if not event.reply_to:
                await event.reply("❌ باید روی پیام موردنظر ریپلای کنید")
                return
            message_id = event.reply_to.reply_to_msg_id
            try:
                await bot.client.pin_message(chat_id, message_id, notify=False)
                save_pinned_message(chat_id, message_id)
                await event.reply("📌 پیام با موفقیت سنجاق شد.")
            except Exception as error:
                bot.logger.log_error(f"خطا در سنجاق پیام: {error}")
                await event.reply("❌ سنجاق پیام انجام نشد")
            return

        if clean_text == "پیام سنجاق":
            message_id = get_pinned_message(chat_id)
            if not message_id:
                await event.reply("📌 پیامی سنجاق نشده است.")
                return
            try:
                pinned = await bot.client.get_messages(chat_id, ids=message_id)
                content = getattr(pinned, "message", None) if pinned else None
                await event.reply(content or "📌 پیام سنجاق‌شده قابل نمایش نیست.")
            except Exception as error:
                bot.logger.log_error(f"خطا در نمایش پیام سنجاق: {error}")
                await event.reply("📌 پیام سنجاق‌شده قابل نمایش نیست.")
            return

        if clean_text in {"قفل", "باز"}:
            if not _has_group_management_permission(bot, chat_id, user_id, getattr(sender, 'username', None)):
                await event.reply("❌ فقط مالک یا ادمین ثبت‌شده اجازه استفاده دارد")
                return
            if clean_text == "قفل":
                bot.logger.log_info("LOCK COMMAND RECEIVED")
                await bot.group_actions.lock_group(chat_id)
                admin_tools.log_action(chat_id, sender, "قفل کردن گروه")
                await event.reply("🔒 گروه قفل شد")
            else:
                bot.logger.log_info("UNLOCK COMMAND RECEIVED")
                await bot.group_actions.unlock_group(chat_id)
                admin_tools.log_action(chat_id, sender, "باز کردن گروه")
                await event.reply("🔓 گروه باز شد")
            return

        if clean_text == "راهنمای امتیاز":
            guide_text = (
                "🏅 راهنمای امتیاز\n\n"
                "🧩 حدس چیستان:\n+3 سکه\n\n"
                "😀 حدس ایموجی:\n+4 سکه\n\n"
                "🌍 حدس پرچم:\n+3 سکه\n\n"
                "📝 اسم فامیل (70 امتیاز یا بیشتر):\n+6 سکه\n\n"
                "✍️ تصحیح کلمات:\n+1 سکه\n\n"
                "❓ چهار گزینه‌ای:\n+3 سکه\n\n"
                "😂 بخند یا بباز:\n+1 سکه (اولین نفری که ایموجی خنده ارسال کند)\n\n"
                "🏕 بقا:\n+8 سکه (برنده نهایی)\n\n"
                "🧛 خون‌آشام:\n+7 سکه (حدس صحیح خون‌آشام)\n\n"
                "🧩 معما:\nپاسخ صحیح: ۳ سکه برنز\n\n"
                "حدس کلمه: ۴ سکه برنز\n\n"
                "🎯 بهترین جواب:\nبا ارسال بهترین و کاربردی‌ترین پاسخ به سوال، برنده انتخاب می‌شود.\n🪙 جایزه: ۲ سکه برنز\n\n"
                "⚔️ نبرد:\nبرنده: ۲ سکه برنز (اگر مساوی شود هر دو ۲ سکه برنز)\n\n"
                "📈 پایان هر روز:\n\n"
                "🥇 رتبه اول:\n+12 سکه\n\n"
                "🥈 رتبه دوم:\n+8 سکه\n\n"
                "🥉 رتبه سوم:\n+5 سکه"
            )
            def guide_u16(value):
                return len(value.encode("utf-16-le")) // 2
            guide_labels = ("🏅 راهنمای امتیاز", "🧩 حدس چیستان:", "😀 حدس ایموجی:", "🌍 حدس پرچم:", "📝 اسم فامیل (70 امتیاز یا بیشتر):", "✍️ تصحیح کلمات:", "❓ چهار گزینه‌ای:", "😂 بخند یا بباز:", "🏕 بقا:", "🧛 خون‌آشام:", "🧩 معما:", "حدس کلمه:", "🎯 بهترین جواب:", "⚔️ نبرد:", "📈 پایان هر روز:", "🥇 رتبه اول:", "🥈 رتبه دوم:", "🥉 رتبه سوم:")
            entities = [MessageEntityBold(offset=guide_u16(guide_text[:guide_text.index(label)]), length=guide_u16(label)) for label in guide_labels]
            await event.reply(guide_text, formatting_entities=entities)
            return

        if clean_text == "امتیاز من":
            profile = get_coin_profile(chat_id, user_id)
            activity = get_activity(chat_id, user_id)
            first = activity.get("first", 0)
            membership_days = 0
            if first:
                from time import time as _time
                membership_days = max(0, int((_time() - first) // 86400))
            profile_text = (
                "🏅 پروفایل امتیاز\n\n"
                f"ᯓ نام کاربری: {_format_admin_display(sender)}\n\n"
                f"🥉 برنز: ← {_math_digits(profile.get(economy.BRONZE, 0))}\n\n"
                f"🥈 نقره: ← {_math_digits(profile.get(economy.SILVER, 0))}\n\n"
                f"🥇 طلا: ← {_math_digits(profile.get(economy.GOLD, 0))}\n\n"
                f"💎 ارزش کل: ← {_math_digits(profile.get('total_coin_value', 0))}\n\n"
                f"🏆 رتبه: ← {_math_digits(coin_rank(chat_id, user_id)) if coin_rank(chat_id, user_id) else 'ندارد'}\n\n"
                f"🎮 برد در بازی‌ها: ← {_math_digits(profile.get('wins', 0))}\n\n"
                f"📅 مدت عضویت: 「 {_math_digits(membership_days)} 」"
            )
            def profile_u16(value):
                return len(value.encode("utf-16-le")) // 2
            labels = ("🏅 پروفایل امتیاز", "ᯓ نام کاربری:", "🥉 برنز:", "🥈 نقره:", "🥇 طلا:", "💎 ارزش کل:", "🏆 رتبه:", "🎮 برد در بازی‌ها:", "📅 مدت عضویت:")
            entities = []
            for label in labels:
                pos = profile_text.index(label)
                entities.append(MessageEntityBold(offset=profile_u16(profile_text[:pos]), length=profile_u16(label)))
            duration = f"「 {_math_digits(membership_days)} 」"
            duration_pos = profile_text.index(duration)
            entities.append(MessageEntityBlockquote(offset=profile_u16(profile_text[:duration_pos]), length=profile_u16(duration)))
            await event.reply(profile_text, formatting_entities=entities)
            return

        if clean_text == "رتبه ها":
            # رتبه‌بندی فقط بر پایهٔ ارزش کل؛ در تساوی، هرکس زودتر رسیده بالاتر.
            ranking = coin_leaderboard(chat_id, 5)
            # شمارهٔ رتبه با ایموجی عددی نمایش داده می‌شود؛ مدال‌های
            # 🥇🥈🥉 فقط برای «نوع سکه» در خط دوم می‌مانند.
            rank_digits = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
                           "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
            ranking_text = "🏆 برترین کاربران"
            entries = []
            for index, row in enumerate(ranking, 1):
                number = (rank_digits[index - 1] if index <= len(rank_digits)
                          else f"{_math_digits(index)}.")
                display = row.get("name") or f"کاربر {row['user_id']}"
                entry = (
                    f"{number} {display} — 💎 {_math_digits(row['total_coin_value'])}"
                    f"\n🥉 {_math_digits(row['bronze'])} | "
                    f"🥈 {_math_digits(row['silver'])} | "
                    f"🥇 {_math_digits(row['gold'])}"
                )
                entries.append(entry)
            if entries:
                ranking_text += "\n\n" + "\n\n".join(entries)
            else:
                ranking_text += "\n\nندارد"
            def ranking_u16(value):
                return len(value.encode("utf-16-le")) // 2
            entities = [MessageEntityBold(offset=0, length=ranking_u16("🏆 برترین کاربران"))]
            cursor = len("🏆 برترین کاربران\n\n")
            for entry in entries:
                entities.append(MessageEntityBlockquote(offset=ranking_u16(ranking_text[:cursor]), length=ranking_u16(entry)))
                cursor += len(entry) + 2
            await event.reply(ranking_text, formatting_entities=entities)
            return

        if clean_text == "آمارم":
            activity = get_activity(chat_id, user_id)
            group_stats = get_stats(chat_id)
            user_stats = group_stats.get('users', {}).get(str(user_id), {})
            messages = user_stats.get('messages', 0)
            violations = bot.tracker.get_count(chat_id, user_id)
            hours = max(0, (activity.get('last', 0) - activity.get('first', 0)) / 3600)
            score = min(10, max(1, (messages // 10) + activity.get('gifs', 0) + activity.get('videos', 0)))
            display_name = " ".join(part for part in (getattr(sender, 'first_name', None), getattr(sender, 'last_name', None)) if part) or str(user_id)
            stats_text = (
                f"📆 تاریخ : 『 {_jalali_today()} 』\n\n"
                f"                 ⟣ {display_name} ⟢\n\n"
                "     ═───────◇───────═\n\n"
                f"● تعداد پیام [ {_math_digits(messages)} ]\n\n"
                f"● تعداد گیف [ {_math_digits(activity.get('gifs', 0))} ]\n\n"
                f"● تعداد تخلف [ {_math_digits(violations)} ]\n\n"
                f"● تعداد فیلم‌ها [ {_math_digits(activity.get('videos', 0))} ]\n\n"
                f"● ساعاتی که داخل گروه فعالیت کرد [ {_math_digits(f'{hours:.1f}')} ]\n\n"
                f"⎋ [ امتیاز کاربر: {_math_digits(score)} از {_math_digits(10)} ]"
            )
            score_text = f"⎋ [ امتیاز کاربر: {_math_digits(score)} از {_math_digits(10)} ]"
            score_offset = len(stats_text[:stats_text.index(score_text)].encode("utf-16-le")) // 2
            await event.reply(
                stats_text,
                formatting_entities=[
                    MessageEntityBlockquote(
                        offset=score_offset,
                        length=len(score_text.encode("utf-16-le")) // 2,
                    )
                ],
            )
            return

        if clean_text == "ثبت مالک":
            _log_command_route(bot, clean_text, "ثبت مالک", "group_owner.set")
            if not is_global_owner(getattr(sender, "id", None)):
                await event.reply("❌ فقط مالک اصلی ربات اجازه ثبت مالک گروه را دارد")
                return

            if not event.reply_to:
                await event.reply("❌ برای ثبت مالک باید روی پیام کاربر ریپلای کنید")
                return

            try:
                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id,
                )
                target_user = await reply_msg.get_sender() if reply_msg else None
                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                set_group_owner(chat_id, target_user.id)
                await event.reply(
                    f"**مالـک ثبت شد** 「 {_format_group_member(target_user)}」‌𓆤"
                )
            except Exception as e:
                bot.logger.log_error(f"خطا در ثبت مالک گروه: {e}")
                await event.reply(f"❌ خطا در ثبت مالک: {e}")
            return

        if clean_text == "لغو مالک":
            _log_command_route(bot, clean_text, "لغو مالک", "group_owner.remove")
            if not is_global_owner(getattr(sender, "id", None)):
                await event.reply("❌ فقط مالک اصلی ربات اجازه لغو مالک گروه را دارد")
                return

            removed_owner = remove_group_owner(chat_id)
            if removed_owner:
                await event.reply("✅ مالک گروه لغو شد")
            else:
                await event.reply("❌ برای این گروه مالک ثبت‌شده‌ای وجود ندارد")
            return

        # ثبت گروه توسط مالک ربات
        if clean_text == "ثبت گروه":
            _log_command_route(bot, clean_text, "ثبت گروه", "group_registration")

            try:
                if not is_global_owner(getattr(sender, "id", None)):
                    await event.reply(
                        "❌ فقط مالک ربات اجازه ثبت گروه دارد"
                    )
                    return

                chat = await event.get_chat()

                gid = getattr(chat, "id", None)
                title = getattr(chat, "title", )

                activate_group(
                    gid,
                    title
                )

                # مالک اصلی = مالک بومی خودِ گروه (نه فرستندهٔ دستور)؛ بدون
                # username → نام نمایشی. خطوط بدون فاصلهٔ خالی.
                _owner_display = await _group_main_owner_display(
                    bot, chat, sender, chat_id=gid)
                await event.reply(
                    f"↻- گروه\n\u200f「 {title} 」ثبت شد ☑️\n"
                    f"**مالک ربات** : ❨ {_owner_display}❩"
                )

            except Exception as e:
                await event.reply(
                    f"❌ خطا در ثبت گروه: {e}"
                )

            return


        # فعال و غیرفعال کردن گروه توسط مالک اصلی
        # ثبت ادمین توسط مالک ربات

        _reserved_command, _reserved_handler = match_reserved_command(clean_text)

        if _reserved_command == "ثبت ادمین":
            _log_command_route(bot, clean_text, _reserved_command, _reserved_handler)
            if not _can_manage_group_admins(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply(
                    "❌ فقط مالک اصلی ربات یا مالک همین گروه اجازه مدیریت ادمین‌ها را دارد"
                )
                return

            try:
                admin_user = None
                if event.reply_to:
                    reply_msg = await bot.client.get_messages(
                        chat_id, ids=event.reply_to.reply_to_msg_id
                    )
                    if reply_msg:
                        admin_user = await reply_msg.get_sender()

                if not admin_user:
                    parts = clean_text.split()
                    if len(parts) >= 3:
                        admin_user = await bot.client.get_entity(parts[2])

                if not admin_user:
                    await event.reply("❌ باید ریپلای کنید یا @username بدهید")
                    return

                admin_username = getattr(admin_user, "username", None)
                if add_admin(chat_id, admin_user.id, admin_username):
                    # Bold با ** (Markdown پیش‌فرض). نام کاربری و در نبود
                    # آن، نام نمایشی از policy واحد format_user می‌آید.
                    # دو خط بدون فاصلهٔ خالی بینشان (طبق اسپک).
                    await event.reply(
                        f"کاربر : 「 {_format_admin_display(admin_user)} 」\n"
                        f"↵ **ادمیـن ربات شد**"
                    )
                else:
                    await event.reply("⚠️ این کاربر قبلا ادمین ثبت شده است")

            except Exception as e:
                await event.reply(f"❌ خطا: {e}")

            return


        # حذف ادمین توسط مالک اصلی یا مالک ثبت‌شده گروه
        if _reserved_command in {"برکناری ادمین", "لغو ادمین"}:
            _log_command_route(bot, clean_text, _reserved_command, _reserved_handler)
            if not _can_manage_group_admins(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply(
                    "❌ فقط مالک اصلی ربات یا مالک همین گروه اجازه مدیریت ادمین‌ها را دارد"
                )
                return

            try:
                admin_user = None
                if event.reply_to:
                    reply_msg = await bot.client.get_messages(
                        chat_id, ids=event.reply_to.reply_to_msg_id
                    )
                    if reply_msg:
                        admin_user = await reply_msg.get_sender()

                if not admin_user:
                    parts = clean_text.split()
                    if len(parts) >= 3:
                        admin_user = await bot.client.get_entity(parts[2])

                if not admin_user:
                    await event.reply("❌ باید ریپلای کنید یا @username بدهید")
                    return

                admin_username = getattr(admin_user, "username", None)
                if remove_admin(chat_id, admin_user.id):
                    await event.reply(
                        f"ادمـین لغو شد ✅  「 {_format_admin_display(admin_user)}」‌𓆤"
                    )
                else:
                    await event.reply("❌ این کاربر ادمین ثبت‌شده نیست")

            except Exception as e:
                await event.reply(f"❌ خطا: {e}")

            return


        # حذف چند پیام آخر با پاک عدد
        if clean_text.startswith("پاک "):
            try:
                sender_username = getattr(sender, "username", None)
                if not _can_delete_messages(
                    bot, chat_id, user_id, sender_username
                ):
                    await event.reply("❌ فقط مالک و ادمین‌ها اجازه حذف پیام دارند")
                    return

                parts = clean_text.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    await event.reply("❌ استفاده: پاک + عدد مورد نیاز")
                    return

                requested_count = int(parts[1])
                if requested_count < 1 or requested_count > 700:
                    await event.reply("❌ تعداد پیام باید بین 1 تا 700 باشد")
                    return

                # cooldown و Lock برای کل گروه، نه فقط هر کاربر؛ تا چند
                # ادمینِ هم‌زمان روی هم نیفتند و محدودیت ۵ ثانیه رعایت شود.
                if not _delete_cooldown_allowed(chat_id):
                    await event.reply(
                        "لطفا ۵ ثانیه صبر کنید تا پاکسازی قبلی کامل شود ⏳"
                    )
                    return
                lock = _delete_group_lock(chat_id)
                async with lock:
                    messages = await bot.client.get_messages(
                        chat_id,
                        limit=requested_count,
                    )
                    message_ids = [
                        message.id for message in messages
                        if getattr(message, "id", None)
                    ]

                    delete_future = _queue_message_deletes(
                        bot, chat_id, message_ids, priority=0
                    )

                async def finish_manual_bulk_delete():
                    deleted_count, remaining = await delete_future
                    if deleted_count:
                        add_deleted_count(
                            chat_id, user_id, sender_username or "", deleted_count
                        )
                    admin_tools.log_action(
                        chat_id, sender, "حذف دسته‌ای پیام",
                        note=f"درخواست {len(message_ids)}، حذف واقعی {deleted_count}")
                    if remaining:
                        bot.logger.log_error(
                            f"MANUAL DELETE INCOMPLETE chat_id={chat_id} "
                            f"deleted={deleted_count} remaining={len(remaining)}"
                        )
                    # Report only after the queue has completed, using the
                    # real successful count rather than the requested count.
                    await event.reply(
                        f"{_fullwidth_digits(deleted_count)} پیام پاک شد 💣"
                    )
                _asyncio.create_task(finish_manual_bulk_delete(), name="delete:bulk-finish")
                return

            except Exception as e:
                await event.reply(f"❌ خطا: {e}")
                return

        # حذف پیام با ریپلای
        if clean_text == "پاک":
            try:
                sender_username = getattr(sender, "username", None)
                if not _can_delete_messages(
                    bot, chat_id, user_id, sender_username
                ):
                    await event.reply("❌ فقط مالک و ادمین‌ها اجازه حذف پیام دارند")
                    return

                # cooldown و Lock برای کل گروه (مشترک با «پاک عدد»).
                if not _delete_cooldown_allowed(chat_id):
                    await event.reply(
                        "لطفا ۵ ثانیه صبر کنید تا پاکسازی قبلی کامل شود ⏳"
                    )
                    return

                if not event.reply_to:
                    await event.reply("❌ باید روی پیام ریپلای کنید")
                    return

                lock = _delete_group_lock(chat_id)
                async with lock:
                    _queue_message_deletes(
                        bot, chat_id, [event.reply_to.reply_to_msg_id],
                        priority=0,
                    )
                try:
                    reply_msg = await bot.client.get_messages(
                        chat_id, ids=event.reply_to.reply_to_msg_id)
                    target_user = await reply_msg.get_sender() if reply_msg else None
                    admin_tools.log_action(
                        chat_id, sender, "حذف پیام", target=target_user)
                except Exception:
                    admin_tools.log_action(chat_id, sender, "حذف پیام")

            except Exception as e:
                await event.reply(f"❌ خطا: {e}")

            return

# اخراج کاربر با ریپلای
        if clean_text == "اخراج":
            try:
                sender = await event.get_sender()
                sender_username = getattr(sender, "username", None)

                if not _has_group_management_permission(
                    bot, chat_id, user_id, sender_username
                ):
                    await event.reply("❌ فقط ادمین‌ها اجازه اخراج دارند")
                    return

                if not event.reply_to:
                    await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                    return

                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id
                )

                target_user = await reply_msg.get_sender()

                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                async def kick_succeeded(_result):
                    add_kick(chat_id)
                    target_username = getattr(target_user, "username", None)
                    target_display_name = " ".join(
                        part for part in (
                            getattr(target_user, "first_name", None),
                            getattr(target_user, "last_name", None),
                        ) if part
                    ).strip()
                    add_banned(
                        chat_id,
                        target_user.id,
                        username=target_username,
                        display_name=target_display_name,
                        reason="اخراج دستی توسط مالک یا ادمین",
                        source="manual",
                    )
                    admin_tools.log_action(
                        chat_id, sender, "اخراج کاربر", target=target_user)
                    # 🗂 ثبت در سابقه‌ها (فایل جدا؛ سیستم اخراج دست‌نخورده).
                    try:
                        user_history.add_kick(
                            chat_id, target_user,
                            "اخراج دستی توسط مالک یا ادمین")
                    except Exception as history_error:
                        bot.logger.log_error(
                            f"USER HISTORY KICK FAILED: {history_error}")
                    await event.reply("⟳ کاربر اخراج شد")

                async def kick_failed(_error):
                    await event.reply("❌ اخراج کاربر انجام نشد")

                bot.moderation_queue.enqueue(
                    chat_id,
                    "kick",
                    user_id=target_user.id,
                    timeout_seconds=20,
                    operation=lambda: bot.client.edit_permissions(
                        chat_id, target_user, until_date=None, view_messages=False
                    ),
                    on_success=kick_succeeded,
                    on_failure=kick_failed,
                )

            except Exception as e:
                bot.logger.log_error(f"خطای اخراج: {e}")
                await event.reply(f"❌ خطا در اخراج:\n{e}")

            return


# آزاد کردن کاربر محروم شده
        # ===== vip: معاف از اخطار و حذف پیام (بدون نیاز به ادمین بودن هدف) =====
        if clean_text in ("vip", "لغو vip", "لیست vip"):
            try:
                from modules import vip_storage
                _vip_sender = await event.get_sender()
                if not _has_group_management_permission(
                    bot, chat_id, user_id,
                    getattr(_vip_sender, "username", None),
                ):
                    await event.reply("❌ فقط ادمین‌ها اجازه استفاده از vip را دارند")
                    return
                if clean_text == "لیست vip":
                    _vip_ids = vip_storage.list_vips(chat_id)[:20]
                    _vip_lines = []
                    for _vuid in _vip_ids:
                        try:
                            _vuser = await bot.client.get_entity(int(_vuid))
                            _vip_lines.append(
                                f"\u200f➛ 「 {format_user(_vuser)} 」")
                        except Exception:
                            _vip_lines.append("\u200f➛ 「」")
                    if not _vip_lines:
                        _vip_lines = ["\u200f➛ 「」"]
                    # کلاینت جهت هر خط را با اولین نویسهٔ قوی همان خط
                    # تعیین می‌کند؛ RLM نامرئی اول هر خط باعث می‌شود
                    # عنوان و آیتم‌ها هم‌راستای راست قرار بگیرند.
                    await event.reply(
                        "\u200f☴ \U0001D5E9\U0001D5DC\U0001D5E3 "
                        "\U0001D5DF\U0001D5DC\U0001D5E6\U0001D5E7 #plus\n\n"
                        + "\n\n".join(_vip_lines)
                    )
                    return
                # vip / لغو vip — هر دو روی پیام کاربر
                if not event.reply_to:
                    await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                    return
                _vmsg = await bot.client.get_messages(
                    chat_id, ids=event.reply_to.reply_to_msg_id)
                _vuser = await _vmsg.get_sender() if _vmsg else None
                if not _vuser:
                    await event.reply("❌ کاربر پیدا نشد")
                    return
                if clean_text == "vip":
                    if is_admin(
                        chat_id, _vuser.id,
                        getattr(_vuser, "username", None),
                    ):
                        await event.reply("⚠️ این کاربر ادمین است و vip نشد")
                        return
                    if not vip_storage.add_vip(chat_id, _vuser.id):
                        await event.reply("⚠️ این کاربر قبلا vip ثبت شده است")
                        return
                    # «لغو vip» و «لیست vip» بولد — با entity صریح ساخته
                    # می‌شود (پارسر Markdown دو بولدِ مجزا را درست جفت نمی‌کند).
                    _vip_notice = (
                        "\u200f☰ \U0001D5E9\U0001D5DC\U0001D5E3 , #plus\n"
                        f"🏔کاربر  「 {format_user(_vuser)} 」\n\n"
                        "» لغو vip\n"
                        "» لیست vip"
                    )
                    _vip_ents = []
                    for _vw in ("لغو vip", "لیست vip"):
                        _vp = _vip_notice.find("» " + _vw)
                        if _vp != -1:
                            _vs = _vp + 2
                            _vip_ents.append(
                                MessageEntityBold(
                                    offset=len(_vip_notice[:_vs].encode("utf-16-le")) // 2,
                                    length=len(_vw.encode("utf-16-le")) // 2,
                                )
                            )
                    await event.reply(_vip_notice, formatting_entities=_vip_ents)
                else:  # لغو vip
                    if not vip_storage.remove_vip(chat_id, _vuser.id):
                        await event.reply("⚠️ این کاربر vip نیست")
                        return
                    await event.reply(
                        "\u200f☰ \U0001D5E9\U0001D5DC\U0001D5E3 , #plus\n"
                        f"🏔کاربر  「 {format_user(_vuser)} 」\n\n"
                        "\u200f❌ vip لغو شد"
                    )
            except Exception as e:
                bot.logger.log_error(f"خطای vip: {e}")
                await event.reply(f"❌ خطا: {e}")
            return

        if clean_text == "آزاد" or clean_text.startswith("آزاد ") or clean_text.startswith("آزاد@"):
            if not _has_group_management_permission(
                bot, chat_id, user_id, getattr(sender, "username", None)
            ):
                await event.reply("❌ فقط مالک یا ادمین ثبت‌شده اجازه استفاده دارد")
                return
            try:
                # --- پشتیبانی از دو حالت: ریپلای و یوزرنیم ---
                # آیدی عددی پشتیبانی نمی‌شود
                target_username_arg = None
                if clean_text != "آزاد":
                    # استخراج آرگومان بعد از "آزاد"
                    # clean_text نرمالایز شده است، پس فاصله‌ها یکسان هستند
                    raw_arg = clean_text[4:].strip()
                    if raw_arg.startswith("@"):
                        raw_arg = raw_arg[1:].strip()
                    if raw_arg:
                        # فقط اولین توکن به عنوان یوزرنیم
                        target_username_arg = raw_arg.split()[0].lstrip("@").strip()
                    if target_username_arg is not None:
                        if target_username_arg.isdigit():
                            await event.reply("❌ لطفاً از نام کاربری استفاده کنید، آیدی عددی پشتیبانی نمی‌شود")
                            return
                        if not target_username_arg:
                            await event.reply("❌ نام کاربری مشخص نشده است")
                            return
                        import re as _re_azad
                        if not _re_azad.match(r"^[A-Za-z0-9_]{4,32}$", target_username_arg):
                            await event.reply(f"❌ نام کاربری نامعتبر است: @{target_username_arg}")
                            return

                user = None
                username_for_unban = None
                if target_username_arg:
                    # حل یوزرنیم از طریق SPlusthon بدون نیاز به پیام قبلی
                    try:
                        try:
                            user = await bot.client.get_entity(target_username_arg)
                        except Exception as _e1:
                            try:
                                user = await bot.client.get_entity(f"@{target_username_arg}")
                            except Exception:
                                raise _e1
                    except Exception as e:
                        bot.logger.log_error(f"AZAD RESOLVE FAILED username=@{target_username_arg} error={e!r}")
                        await event.reply(f"❌ کاربر با نام کاربری @{target_username_arg} پیدا نشد")
                        return
                    if not user or not getattr(user, "id", None):
                        await event.reply(f"❌ کاربر با نام کاربری @{target_username_arg} پیدا نشد")
                        return
                    username_for_unban = getattr(user, "username", None) or target_username_arg
                else:
                    if not event.reply_to:
                        await event.reply("❌ باید روی پیام کاربر ریپلای کنید یا به صورت «آزاد @username» بنویسید")
                        return

                    reply_msg = await bot.client.get_messages(
                        chat_id,
                        ids=event.reply_to.reply_to_msg_id
                    )

                    user = await reply_msg.get_sender() if reply_msg else None

                    if not user:
                        await event.reply("❌ کاربر پیدا نشد")
                        return
                    username_for_unban = getattr(user, "username", None)

                # Use independent moderation worker (per-chat, limited concurrency)
                _u = user
                _un = username_for_unban
                _c = chat_id
                _ev = event
                _b = bot
                # ادمینِ صادرکنندهٔ دستور برای ثبت در لاگ مدیریتی؛ نبودِ
                # همین alias باعث خطای «name '_s' is not defined» در
                # آزادکردن با ریپلای می‌شد.
                _s = sender
                async def _on_ok(_r):
                    try:
                        before_spam = _b.tracker.get_count(_c, _u.id)
                        before_warning = before_spam
                        _b.logger.log_info(
                            "UNBAN STATE BEFORE\n"
                            f"user_id={_u.id}\n"
                            f"group_id={_c}\n"
                            "is_banned=False\n"
                            f"spam_count={before_spam}\n"
                            f"warning_count={before_warning}"
                        )
                        released_key = _punishment_key(_c, _u.id)
                        if hasattr(_b, "clear_released_user_state"):
                            _b.clear_released_user_state(_c, _u.id)
                        _b.punished_users.discard(released_key)
                        _b.tracker.reset_count(_c, _u.id)
                        clear_user(_c, _u.id)
                        message_tracker.clear_user_history(_c, _u.id)
                        _b.clear_spam_lock((_c, _u.id))
                        _b.tracker.banned_users.pop(released_key, None)
                        _b.tracker.muted_users.pop(released_key, None)
                        _b.rejoin_spam_state.pop((_c, _u.id), None)
                        _b.spam_burst_users.discard((_c, _u.id))
                        _b.spam_burst_messages.pop((_c, _u.id), None)
                        getattr(_b, "forward_spam_counts", {}).pop((_c, _u.id), None)
                        getattr(_b, "forward_spam_processing", set()).discard((_c, _u.id))
                        try:
                            from modules.group_id import normalize_group_id as _norm_gid
                            _norm = _norm_gid(_c)
                            _str_gid = str(_c)
                            for _k in list(getattr(_b, "punished_users", set())):
                                if _k.endswith(f":{_u.id}") or _k.endswith(f":{str(_u.id)}"):
                                    _chat_part = _k.split(":")[0]
                                    if _chat_part in (str(_c), _norm, _str_gid):
                                        _b.punished_users.discard(_k)
                            for _gid in (_c, _norm, _str_gid):
                                for _kk in (f"{_gid}:{_u.id}", f"{_gid}:{str(_u.id)}", f"{str(_gid)}:{_u.id}", f"{str(_gid)}:{str(_u.id)}"):
                                    _b.tracker.banned_users.pop(_kk, None)
                                    _b.tracker.muted_users.pop(_kk, None)
                            for _t in list(getattr(_b, "spam_lock", set())):
                                try:
                                    if str(_t[0]) in (str(_c), _norm, _str_gid) and str(_t[1]) == str(_u.id):
                                        _b.clear_spam_lock(_t)
                                except: pass
                            for _k in list(_b.rejoin_spam_state.keys()):
                                try:
                                    if str(_k[0]) in (str(_c), _norm, _str_gid) and str(_k[1]) == str(_u.id):
                                        _b.rejoin_spam_state.pop(_k, None)
                                except: pass
                            for _t in list(getattr(_b, "spam_burst_users", set())):
                                try:
                                    if str(_t[0]) in (str(_c), _norm, _str_gid) and str(_t[1]) == str(_u.id):
                                        getattr(_b, "spam_burst_users", set()).discard(_t)
                                except: pass
                            for _k in list(getattr(_b, "spam_burst_messages", {}).keys()):
                                try:
                                    if str(_k[0]) in (str(_c), _norm, _str_gid) and str(_k[1]) == str(_u.id):
                                        _b.spam_burst_messages.pop(_k, None)
                                except: pass
                            for _k in list(getattr(_b, "forward_spam_counts", {}).keys()):
                                try:
                                    if str(_k[0]) in (str(_c), _norm, _str_gid) and str(_k[1]) == str(_u.id):
                                        getattr(_b, "forward_spam_counts", {}).pop(_k, None)
                                except: pass
                            for _t in list(getattr(_b, "forward_spam_processing", set())):
                                try:
                                    if str(_t[0]) in (str(_c), _norm, _str_gid) and str(_t[1]) == str(_u.id):
                                        getattr(_b, "forward_spam_processing", set()).discard(_t)
                                except: pass
                            try:
                                clear_user(_norm, _u.id)
                            except: pass
                            try:
                                clear_user(_str_gid, _u.id)
                            except: pass
                            try:
                                message_tracker.clear_user_history(_norm, _u.id)
                            except: pass
                            try:
                                message_tracker.clear_user_history(_str_gid, _u.id)
                            except: pass
                            try:
                                _b.tracker.reset_count(_norm, _u.id)
                            except: pass
                            try:
                                if hasattr(_b, "flood_messages") and _c in _b.flood_messages:
                                    _b.flood_messages[_c] = [x for x in _b.flood_messages[_c] if str(x[2]) != str(_u.id)]
                                    if not _b.flood_messages[_c]:
                                        _b.flood_messages.pop(_c, None)
                                for _gid in (_norm, _str_gid):
                                    if hasattr(_b, "flood_messages") and _gid in _b.flood_messages:
                                        _b.flood_messages[_gid] = [x for x in _b.flood_messages[_gid] if str(x[2]) != str(_u.id)]
                                        if not _b.flood_messages[_gid]:
                                            _b.flood_messages.pop(_gid, None)
                            except: pass
                            try:
                                if hasattr(_b, "spammer_messages"):
                                    _b.spammer_messages.pop(_u.id, None)
                                    _b.spammer_messages.pop(str(_u.id), None)
                            except: pass
                            try:
                                if hasattr(_b, "user_messages"):
                                    _b.user_messages.pop(_u.id, None)
                                    _b.user_messages.pop(str(_u.id), None)
                                    _b.user_messages.pop((_c, _u.id), None)
                            except: pass
                            try:
                                if hasattr(_b, "repeat_messages"):
                                    _b.repeat_messages.pop(_u.id, None)
                                    _b.repeat_messages.pop(str(_u.id), None)
                            except: pass
                        except Exception as _e:
                            try:
                                _b.logger.log_error(f"UNBAN ROBUST CLEAR FAILED { _e!r}")
                            except: pass
                        after_spam = _b.tracker.get_count(_c, _u.id)
                        _b.logger.log_info(
                            "UNBAN STATE AFTER\n"
                            f"user_id={_u.id}\n"
                            f"group_id={_c}\n"
                            "is_banned=False\n"
                            f"spam_count={after_spam}\n"
                            f"warning_count={after_spam}"
                        )
                        _b.logger.log_info(
                            "USER RELEASED CACHE CLEARED "
                            f"chat_id={_c} user_id={_u.id} "
                            "banned_storage=False"
                        )
                        admin_tools.log_action(
                            _c, _s, "آزاد کردن کاربر", target=_u)
                        # Bold/فرمت طبق اسپک؛ بدون username → نام نمایشی.
                        _release_notice = (
                            f"♻️ کاربر آزاد شد ᯓ⁪⁮ [ {format_user(_u)} ]")
                        _sender_ok = getattr(_b, "outgoing_sender", None)
                        if _sender_ok is not None:
                            _sender_ok.enqueue_reply(_ev, _release_notice)
                        else:
                            await _ev.reply(_release_notice)
                    except Exception as e:
                        try:
                            _sender_ok2 = getattr(_b, "outgoing_sender", None)
                            if _sender_ok2 is not None:
                                _sender_ok2.enqueue_reply(_ev, f"❌ خطا در آزاد کردن:\n{e}")
                            else:
                                await _ev.reply(f"❌ خطا در آزاد کردن:\n{e}")
                        except Exception:
                            pass

                async def _on_fail(_err):
                    try:
                        _sender_ok = getattr(_b, "outgoing_sender", None)
                        if _sender_ok is not None:
                            _sender_ok.enqueue_reply(_ev, "❌ آزاد کردن انجام نشد")
                        else:
                            await _ev.reply("❌ آزاد کردن انجام نشد")
                    except Exception:
                        pass

                # سکوت دستی با «آزاد» رفع نمی‌شود؛ فقط «رفع سکوت» می‌تواند
                # آن را بردارد.
                try:
                    from modules import manual_mute_storage
                    if manual_mute_storage.is_manual_muted(_c, _u.id):
                        _mm_sender = getattr(_b, "outgoing_sender", None)
                        _mm_notice = (
                            "⚠️ این کاربر سکوت دستی دارد؛ برای رفعش روی پیامش "
                            "ریپلای کنید و بنویسید: رفع سکوت"
                        )
                        if _mm_sender is not None:
                            _mm_sender.enqueue_reply(_ev, _mm_notice)
                        else:
                            await _ev.reply(_mm_notice)
                        return
                except Exception:
                    pass

                _b.moderation_queue.enqueue(
                    _c, "unban",
                    user_id=_u.id,
                    timeout_seconds=20,
                    operation=lambda: _b.admin_actions.unban_user(_c, _u.id, _un),
                    on_success=_on_ok,
                    on_failure=_on_fail,
                )
                # Free GroupDispatcher worker immediately
                return

            except Exception as e:
                _sender_err = getattr(bot, "outgoing_sender", None)
                if _sender_err is not None:
                    _sender_err.enqueue_reply(event, f"❌ خطا در آزاد کردن:\n{e}")
                else:
                    await event.reply(f"❌ خطا در آزاد کردن:\n{e}")
                    # === FIX: robust clearing for already_punished / is_repeat / spam_history after unban ===
                    # First spam flow is already correct, this only ensures second wave after unban is treated as new.
                    try:
                        from modules.group_id import normalize_group_id as _norm_gid
                        _norm = _norm_gid(chat_id)
                        _str_gid = str(chat_id)
                        # clear punished_users for any representation of this user (raw, normalized, str)
                        for _k in list(getattr(bot, "punished_users", set())):
                            if _k.endswith(f":{user.id}") or _k.endswith(f":{str(user.id)}"):
                                # keep only those matching this user, remove to allow re-punishment
                                # To avoid clearing other groups unintentionally, only discard if chat part matches current group in any form
                                _chat_part = _k.split(":")[0]
                                if _chat_part in (str(chat_id), _norm, _str_gid):
                                    bot.punished_users.discard(_k)
                        for _gid in (chat_id, _norm, _str_gid):
                            for _k in (f"{_gid}:{user.id}", f"{_gid}:{str(user.id)}", f"{str(_gid)}:{user.id}", f"{str(_gid)}:{str(user.id)}"):
                                bot.tracker.banned_users.pop(_k, None)
                                bot.tracker.muted_users.pop(_k, None)
                        # robust iterative clearing for tuple-based states (handle any string/int mismatch)
                        try:
                            for _t in list(getattr(bot, "spam_lock", set())):
                                try:
                                    if str(_t[0]) in (str(chat_id), _norm, _str_gid) and str(_t[1]) == str(user.id):
                                        bot.clear_spam_lock(_t)
                                except: pass
                        except: pass
                        try:
                            for _k in list(bot.rejoin_spam_state.keys()):
                                try:
                                    if str(_k[0]) in (str(chat_id), _norm, _str_gid) and str(_k[1]) == str(user.id):
                                        bot.rejoin_spam_state.pop(_k, None)
                                except: pass
                        except: pass
                        try:
                            for _t in list(getattr(bot, "spam_burst_users", set())):
                                try:
                                    if str(_t[0]) in (str(chat_id), _norm, _str_gid) and str(_t[1]) == str(user.id):
                                        getattr(bot, "spam_burst_users", set()).discard(_t)
                                except: pass
                        except: pass
                        try:
                            for _k in list(getattr(bot, "spam_burst_messages", {}).keys()):
                                try:
                                    if str(_k[0]) in (str(chat_id), _norm, _str_gid) and str(_k[1]) == str(user.id):
                                        bot.spam_burst_messages.pop(_k, None)
                                except: pass
                        except: pass
                        try:
                            for _k in list(getattr(bot, "forward_spam_counts", {}).keys()):
                                try:
                                    if str(_k[0]) in (str(chat_id), _norm, _str_gid) and str(_k[1]) == str(user.id):
                                        getattr(bot, "forward_spam_counts", {}).pop(_k, None)
                                except: pass
                        except: pass
                        try:
                            for _t in list(getattr(bot, "forward_spam_processing", set())):
                                try:
                                    if str(_t[0]) in (str(chat_id), _norm, _str_gid) and str(_t[1]) == str(user.id):
                                        getattr(bot, "forward_spam_processing", set()).discard(_t)
                                except: pass
                        except: pass
                        # also ensure spam_history and tracker history cleared for normalized variants
                        try:
                            clear_user(_norm, user.id)
                        except: pass
                        try:
                            clear_user(_str_gid, user.id)
                        except: pass
                        try:
                            message_tracker.clear_user_history(_norm, user.id)
                        except: pass
                        try:
                            message_tracker.clear_user_history(_str_gid, user.id)
                        except: pass
                        try:
                            bot.tracker.reset_count(_norm, user.id)
                        except: pass
                        # Clear flood and spammer history for this user to prevent simple messages after unban being deleted as flood
                        try:
                            if hasattr(bot, "flood_messages") and chat_id in bot.flood_messages:
                                bot.flood_messages[chat_id] = [x for x in bot.flood_messages[chat_id] if str(x[2]) != str(user.id)]
                                if not bot.flood_messages[chat_id]:
                                    bot.flood_messages.pop(chat_id, None)
                            for _gid in (_norm, _str_gid):
                                if hasattr(bot, "flood_messages") and _gid in bot.flood_messages:
                                    bot.flood_messages[_gid] = [x for x in bot.flood_messages[_gid] if str(x[2]) != str(user.id)]
                                    if not bot.flood_messages[_gid]:
                                        bot.flood_messages.pop(_gid, None)
                        except: pass
                        try:
                            if hasattr(bot, "spammer_messages"):
                                bot.spammer_messages.pop(user.id, None)
                                bot.spammer_messages.pop(str(user.id), None)
                        except: pass
                        try:
                            if hasattr(bot, "user_messages"):
                                bot.user_messages.pop(user.id, None)
                                bot.user_messages.pop(str(user.id), None)
                                bot.user_messages.pop((chat_id, user.id), None)
                        except: pass
                        try:
                            if hasattr(bot, "repeat_messages"):
                                bot.repeat_messages.pop(user.id, None)
                                bot.repeat_messages.pop(str(user.id), None)
                        except: pass
                    except Exception as _e:
                        try:
                            bot.logger.log_error(f"UNBAN ROBUST CLEAR FAILED { _e!r}")
                        except: pass
                    after_spam = bot.tracker.get_count(chat_id, user.id)
                    bot.logger.log_info(
                        "UNBAN STATE AFTER\n"
                        f"user_id={user.id}\n"
                        f"group_id={chat_id}\n"
                        "is_banned=False\n"
                        f"spam_count={after_spam}\n"
                        f"warning_count={after_spam}"
                    )
                    bot.logger.log_info(
                        "USER RELEASED CACHE CLEARED "
                        f"chat_id={chat_id} user_id={user.id} "
                        "banned_storage=False"
                    )
                    admin_tools.log_action(
                        chat_id, sender, "آزاد کردن کاربر", target=user)
                    # بدون username → نام نمایشی (format_user).
                    await event.reply(
                        f"♻️ کاربر آزاد شد ᯓ⁪ [ {format_user(user)} ]")

            except Exception as e:
                await event.reply(f"❌ خطا در آزاد کردن:\n{e}")

            return

# اخطار کاربر با ریپلای
        if clean_text == "اخطار":
            sender_username = getattr(sender, "username", None)
            if not _has_group_management_permission(
                bot, chat_id, user_id, sender_username
            ):
                await event.reply("❌ فقط ادمین‌ها اجازه استفاده از این دستور را دارند")
                return

            try:
                if not event.reply_to:
                    await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                    return

                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id
                )

                user = await reply_msg.get_sender()

                if not user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                username = getattr(user, "username", None) or "کاربر"

                count = bot.tracker.increment(chat_id, user.id)
                threshold = warning_threshold.get_threshold(
                    chat_id, bot.config_manager.get("spam_threshold", 5))
                admin_tools.log_action(
                    chat_id, sender, "اخطار", target=user,
                    note=f"تعداد {count}")
                # 🗂 ثبت در سابقه‌ها (فایل جدا؛ سیستم اخطار دست‌نخورده).
                try:
                    user_history.add_warn(
                        chat_id, user,
                        f"اخطار دستی توسط مالک یا ادمین (اخطار شمارهٔ {count})")
                except Exception as history_error:
                    bot.logger.log_error(
                        f"USER HISTORY WARN FAILED: {history_error}")

                manual_name = _format_group_member(user)
                manual_header = f"⚠️ کاربر {manual_name}"
                manual_text = (
                    f"{manual_header}\n"
                    "یک اخطار دستی دریافت کرد\n\n"
                    f"تعداد اخطار: {_math_digits(count)}/{_math_digits(threshold)}"
                )
                header_u16 = len(manual_header.encode("utf-16-le")) // 2
                try:
                    await event.reply(
                        manual_text,
                        formatting_entities=[
                            MessageEntityBlockquote(offset=0, length=header_u16)
                        ]
                    )
                except Exception:
                    # Formatting failure must not affect warning persistence.
                    await event.reply(manual_text)

                if bot.tracker.should_punish(chat_id, user.id, threshold=threshold):
                    async def warning_punish_succeeded(_result):
                        if (
                            count >= threshold
                            and bot.config_manager.get("action_on_threshold") in ["ban", "kick"]
                        ):
                            await _send_moderation_notification_once(
                                bot, chat_id, user.id, "warning_ban", event.message.id,
                                "🚫 کاربر 「"
                                f"{_format_banned_user(user, user.id)}"
                                + (
                                    "」\nبه دلیل تخلفات سکوت دائم شد."
                                    if punishment_mode.is_mute(chat_id)
                                    else "」\nبه دلیل تخلفات از گروه اخراج شد."
                                ),
                            )

                    bot.moderation_queue.enqueue(
                        chat_id,
                        "punish",
                        user_id=user.id,
                        timeout_seconds=20,
                        operation=lambda: bot.admin_actions.punish_user(
                            chat_id, user.id, username, announce=False,
                            user=user,
                        ),
                        on_success=warning_punish_succeeded,
                    )
                    bot.tracker.reset_count(chat_id, user.id)

            except Exception as e:
                await event.reply(f"❌ خطا در اخطار:\n{e}")

            return

# سکوت کاربر با ریپلای
        if clean_text == "سکوت":
            try:
                sender = await event.get_sender()

                sender_username = getattr(sender, "username", None)
                if not _has_group_management_permission(
                    bot, chat_id, user_id, sender_username
                ):
                    await event.reply("❌ فقط ادمین‌ها اجازه استفاده از سکوت را دارند")
                    return

                if not event.reply_to:
                    await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                    return

                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id
                )

                if not reply_msg:
                    await event.reply("❌ پیام ریپلای شده پیدا نشد")
                    return

                target_user = await reply_msg.get_sender()

                if not target_user:
                    await event.reply("❌ کاربر پیدا نشد")
                    return

                # Protect native Soroush admins without fetching every member
                # of a large group. The old unfiltered get_participants call
                # scaled with group size and ran before moderation enqueue.
                # Reuse the bounded filtered admin-list cache instead.
                if await _is_native_group_admin(
                    bot, chat_id, target_user.id, target_user,
                    resolved_permission_chat,
                ):
                    await event.reply("⚠️ این کاربر ادمین است و سکوت نشد")
                    return

                async def mute_succeeded(_result):
                    add_mute(chat_id)
                    # ثبت «سکوت دستی»: «آزاد» روی این سکوت عمل نمی‌کند و
                    # رفعش فقط با «رفع سکوت» است.
                    try:
                        from modules import manual_mute_storage
                        manual_mute_storage.add_manual_mute(
                            chat_id, target_user.id)
                    except Exception as mm_error:
                        bot.logger.log_error(
                            f"MANUAL MUTE MARK FAILED: {mm_error}")
                    admin_tools.log_action(
                        chat_id, sender, "سکوت کاربر", target=target_user)
                    # 🗂 ثبت در سابقه‌ها (فایل جدا؛ سیستم سکوت دست‌نخورده).
                    try:
                        user_history.add_mute(
                            chat_id, target_user,
                            "سکوت دستی توسط مالک یا ادمین")
                    except Exception as history_error:
                        bot.logger.log_error(
                            f"USER HISTORY MUTE FAILED: {history_error}")
                    # Bold با ** (Markdown پیش‌فرض). نام کاربری و در نبود
                    # آن، نام نمایشی از policy واحد format_user می‌آید.
                    await event.reply(
                        f"「 {_format_banned_user(target_user, target_user.id)} 」**سکوت دائم شد** 🔊"
                    )

                async def mute_failed(_error):
                    await event.reply("❌ انجام سکوت ناموفق بود")

                bot.moderation_queue.enqueue(
                    chat_id,
                    "mute",
                    user_id=target_user.id,
                    timeout_seconds=15,
                    operation=lambda: bot.admin_actions.mute_user(
                        chat_id, target_user.id, user=target_user,
                        chat=resolved_permission_chat,
                    ),
                    on_success=mute_succeeded,
                    on_failure=mute_failed,
                )

            except Exception as e:
                bot.logger.log_error(
                    f"خطای سکوت کاربر: {e}"
                )
                await event.reply(f"❌ خطا در سکوت کاربر:\n{e}")

            return



        # رفع سکوت کاربر با ریپلای
        if clean_text == "رفع سکوت":
            sender_username = getattr(sender, "username", None)
            if not _has_group_management_permission(
                bot, chat_id, user_id, sender_username
            ):
                await event.reply("❌ فقط ادمین‌ها اجازه استفاده از این دستور را دارند")
                return

            try:
                if not event.reply_to:
                    await event.reply("❌ باید روی پیام کاربر ریپلای کنید")
                    return

                reply_msg = await bot.client.get_messages(
                    chat_id,
                    ids=event.reply_to.reply_to_msg_id
                )

                if not reply_msg:
                    await event.reply("❌ پیام پیدا نشد")
                    return

                target_user = await reply_msg.get_sender()

                async def unmute_succeeded(_result):
                    target_id = getattr(target_user, "id", None)
                    target_key = f"{chat_id}:{target_id}"
                    # برداشتن نشان «سکوت دستی»؛ از این لحظه «آزاد» هم
                    # مثل قبل روی این کاربر کار می‌کند.
                    try:
                        from modules import manual_mute_storage
                        manual_mute_storage.remove_manual_mute(
                            chat_id, target_id)
                    except Exception as mm_error:
                        bot.logger.log_error(
                            f"MANUAL MUTE UNMARK FAILED: {mm_error}")
                    if hasattr(bot, "clear_released_user_state"):
                        bot.clear_released_user_state(chat_id, target_id)
                    bot.clear_spam_lock((chat_id, target_id))
                    bot.punished_users.discard(target_key)
                    bot.tracker.muted_users.pop(target_key, None)
                    bot.tracker.banned_users.pop(target_key, None)
                    bot.tracker.reset_count(chat_id, target_id)
                    bot.rejoin_spam_state.pop((chat_id, target_id), None)
                    bot.spam_burst_users.discard((chat_id, target_id))
                    bot.spam_burst_messages.pop((chat_id, target_id), None)
                    getattr(bot, "forward_spam_counts", {}).pop((chat_id, target_id), None)
                    getattr(bot, "forward_spam_processing", set()).discard((chat_id, target_id))
                    bot.logger.log_info(
                        "UNMUTE STATE CLEARED "
                        f"user_id={target_id} group_id={chat_id} "
                        "is_banned=False is_muted=False warning_count=0 spam_count=0"
                    )
                    add_mute(chat_id)
                    admin_tools.log_action(
                        chat_id, sender, "رفع سکوت کاربر", target=target_user)
                    await event.reply("🔊 سکوت کاربر برداشته شد")

                async def unmute_failed(_error):
                    await event.reply("❌ رفع سکوت انجام نشد")

                bot.moderation_queue.enqueue(
                    chat_id,
                    "unmute",
                    user_id=target_user.id,
                    timeout_seconds=15,
                    operation=lambda: bot.admin_actions.unmute_user(
                        chat_id, target_user.id, user=target_user,
                        chat=resolved_permission_chat,
                    ),
                    on_success=unmute_succeeded,
                    on_failure=unmute_failed,
                )

            except Exception as e:
                bot.logger.log_error(f"خطای رفع سکوت: {e}")
                await event.reply(f"❌ خطا در رفع سکوت:\n{e}")

            return

        # حذف دستی پیام با ریپلای و کلمه پاک
        if clean_text == "پاک":
            try:
                reply_id = getattr(
                    event.message,
                    "reply_to_msg_id",
                    None
                )

                if reply_id:
                    delete_future = _queue_message_deletes(
                        bot, chat.id, [reply_id], priority=0
                    )
                    _asyncio.create_task(event.delete(), name="delete:event")

                    async def finish_single_delete():
                        deleted, remaining = await delete_future
                        if deleted:
                            await event.reply("✅ با موفقیت پاک شد")
                        else:
                            bot.logger.log_error(
                                f"SINGLE DELETE INCOMPLETE chat_id={chat.id} "
                                f"remaining={remaining!r}"
                            )
                            await event.reply("❌ پاک کردن پیام انجام نشد")
                    _asyncio.create_task(finish_single_delete(), name="delete:single-finish")

                return

            except Exception as e:
                bot.logger.log_error(
                    f"DELETE COMMAND ERROR: {e}"
                )
                return


        # ضد اسپم پیام‌های پشت سرهم
        try:
            if not hasattr(bot, "flood_messages"):
                bot.flood_messages = {}

            if chat_id not in bot.flood_messages:
                bot.flood_messages[chat_id] = []

            bot.flood_messages[chat_id].append(
                (
                    _asyncio.get_running_loop().time(),
                    event.message.id,
                    user_id,
                    message_text.strip()
                )
            )

            now = _asyncio.get_running_loop().time()

            bot.flood_messages[chat_id] = [
                x for x in bot.flood_messages[chat_id]
                if now - x[0] <= 10
            ]

            user_msgs = [
                x for x in bot.flood_messages[chat_id]
                if x[2] == user_id
            ]

            # فقط پیام‌های تکراری یک کاربر حذف شوند
            if not auto_punish_protected and len(user_msgs) >= 5:

                texts = [
                    x[3]
                    for x in user_msgs
                ]

                normalized = [
                    t.replace(" ", "")
                     .replace("\n", "")
                    for t in texts
                ]

                # پیام‌های متفاوت مکالمه عادی هستند
                if len(set(normalized)) > 2:
                    return

                ids = [
                    x[1]
                    for x in user_msgs
                ]

                queue = getattr(bot, "message_delete_queue", None)
                if queue is not None:
                    queue.enqueue(chat_id, ids)
                else:
                    _asyncio.create_task(bot.client.delete_messages(chat_id, ids), name="delete:flood-batch")

                bot.flood_messages[chat_id] = []

                bot.logger.log_info(
                    "DUPLICATE FLOOD DETECTED "
                    f"chat_id={chat_id} user_id={user_id} count={len(ids)}"
                )
                if bot.acquire_delete_notice_lock(chat_id):
                    sender5 = getattr(bot, "outgoing_sender", None)
                    if sender5 is not None:
                        sender5.enqueue_reply(event, "پیام‌های پشت سر هم حذف شدند", on_done=lambda sent: capture_sent(bot, chat_id, sent))
                    else:
                        sent = await event.reply("پیام‌های پشت سر هم حذف شدند")
                        capture_sent(bot, chat_id, sent)

                return

        except Exception as e:
            bot.logger.log_error(
                f"خطای ضد فلود: {e}"
            )

        except Exception as e:
            bot.logger.log_error(
                f"خطای حذف تکراری: {e}"
            )


        profiler.skip_to()
        profiler.mark("FILTER")
        # بررسی تکرار شدید داخل یک پیام
        try:
            import re

            words = re.findall(r"\w+|[آ-ی]+", message_text.lower())
            counts = Counter(word for word in words if len(word) >= 3)
            repeat_word, repeat_count = (max(counts.items(), key=lambda item: item[1]) if counts else (None, 0))
            repeat_found = repeat_count >= 8

            if repeat_found and not auto_punish_protected:
                bot.logger.log_info(
                    "SPAM HEAVY DETECTED "
                    f"chat_id={chat_id} user_id={user_id} word={repeat_word!r} count={repeat_count}"
                )
                from modules.user_map import save_user

                save_user(chat_id, username, user_id)

                print("🚨 HEAVY REPEAT SPAM BAN:", username, user_id)

                punish_key = _punishment_key(chat_id, user_id)
                _log_ban_execution(bot, chat_id, user_id, "تکرار شدید داخل پیام")

                if punish_key not in bot.punished_users:
                    bot.punished_users.add(punish_key)
                    bot.logger.log_info(
                        "SPAM DETECTED "
                        f"user={user_id} chat_id={chat_id} reason=heavy_repeat"
                    )
                    bot.logger.log_info(
                        "SPAM ACTION TYPE = severe\n"
                        "WARNING_SKIPPED = true\n"
                        "PUNISHMENT_STARTED = true"
                    )

                    async def heavy_repeat_succeeded(_result):
                        # This callback only seals the shared incident. The
                        # incident worker owns every cleanup batch and emits
                        # the single final ban+cleanup notification.
                        history = message_tracker.get_user_recent_messages(chat_id, user_id)
                        ids = {
                            item.get("message_id") for item in history
                            if isinstance(item.get("message_id"), int)
                            and item.get("message_id") > 0
                        }
                        current_id = getattr(event.message, "id", None)
                        if current_id:
                            ids.add(current_id)
                        _confirm_spam_ban_cleanup(bot, event, chat_id, user_id, ids)

                    async def heavy_repeat_failed(_error):
                        bot.punished_users.discard(punish_key)

                    bot.moderation_queue.enqueue(
                        chat_id,
                        "punish",
                        user_id=user_id,
                        timeout_seconds=20,
                        operation=lambda: bot.admin_actions.punish_user(
                            chat_id, user_id, username, announce=False,
                            user=sender,
                        ),
                        on_success=heavy_repeat_succeeded,
                        on_failure=heavy_repeat_failed,
                    )

                return

        except Exception as e:
            bot.logger.log_error(f"خطای بررسی تکرار داخلی: {e}")

        # Every public @username from a normal user is prohibited.  This is
        # intentionally after the registered-admin/owner decision above: only
        # those recorded authorities are exempt, never a merely native admin.
        public_username_spam = bool(
            not admin_bypass
            and bot.detector.has_public_username(message_text)
        )

        # Keep the cause separate from the shared deletion path.  The
        # ModerationQueue deletes both content-filter and spam messages, but
        # only a real spam trigger is allowed to emit the spam cleanup notice.
        moderation_trigger = "none"
        # بررسی کلمات فیلتر شده گروه
        group_word_spam = False
        group_word_reason = None

        # دستورات مدیریت کلمات نباید توسط فیلتر گرفته شوند
        word_admin_commands = (
            "فیلتر کلمه",
            "حذف کلمه",
            "افزودن کلمه",
            "ثبت کلمه",
            "لیست کلمات",
            "پاک کردن کلمات"
        )

        if any(message_text.startswith(x) for x in word_admin_commands):
            group_word_spam = False

        # === SEPARATE SYSTEMS ===
        # 1. FILTER WORDS (/filter): manual per-group filter, always active if words exist
        #    Independent from strict mode. Uses group_words.json
        # 2. BANNED WORDS (strict mode): global banned_words.txt, per-group toggle via "فعال کلمات ممنوعه"
        #    Controlled by group_banned_words_control.is_enabled, checked inside SpamDetector.check_banned_words
        # Two DBs, two handlers, two logics - completely separate

        # --- FILTER WORDS: check custom per-group filter (always, not gated by strict mode) ---
        try:
            from modules.group_words_storage import (
                find_matching_filter_word,
                get_words,
            )

            matched_word = find_matching_filter_word(
                message_text, get_words(chat_id)
            )
            if matched_word:
                group_word_spam = True
                group_word_reason = f"فیلتر گروه ({matched_word})"
                bot.logger.log_info(f"FILTER WORD DETECTED chat_id={chat_id} word={matched_word!r} text={message_text[:50]!r}")

        except Exception as e:
            bot.logger.log_error(f"خطای بررسی کلمات فیلتر گروه (/filter): {e}")

        # --- BANNED WORDS: strict mode, gated by is_enabled, handled inside SpamDetector ---
        # No separate check here; it will be checked in bot.detector.is_spam which internally checks is_enabled
        # If strict mode is off, check_banned_words will return False and log why

        # کاربر vip از فیلتر خودکار (اخطار/حذف پیام/بن) معاف است؛ مثل
        # مدیر/مالک ثبت‌شده اما بدون اینکه ادمین باشد.
        _vip_exempt = False
        if not (is_group_moderator or fast_command) and user_id:
            try:
                from modules import vip_storage
                _vip_exempt = vip_storage.is_vip(chat_id, user_id)
            except Exception:
                _vip_exempt = False
        # مدیر/مالک ثبت‌شده از فیلتر خودکار و فیلتر کلمات گروه عبور می‌کند،
        # اما اجرای راهنما، بازی‌ها و فرمان‌های مدیریت باید ادامه داشته باشد.
        if is_group_moderator or fast_command or _vip_exempt:
            if is_group_moderator:
                _debug_log(bot, f"✅ ADMIN BYPASS FILTER: {sender_username}")
            elif _vip_exempt:
                _debug_log(bot, f"✅ VIP BYPASS FILTER: {sender_username}")
            is_spam = False
            reason = ""
        elif public_username_spam:
            is_spam = True
            reason = "آیدی عمومی ممنوع"
            moderation_trigger = "public_username"
        elif group_word_spam:
            is_spam = True
            reason = group_word_reason
            moderation_trigger = "group_filter"
        else:
            # `is_spam` remains the sole detector call.  Its existing reason
            # only labels the notification route after the decision is made.
            # BANNED WORDS check is inside is_spam -> check_banned_words which checks strict mode
            is_spam, reason = bot.detector.is_spam(message_text, chat_id)
            # Log for debugging why banned word did or didn't trigger
            try:
                from modules.group_banned_words_control import is_enabled as _is_strict_check
                _strict_on = _is_strict_check(chat_id)
                if not _strict_on:
                    bot.logger.log_info(f"BANNED WORD SKIP strict_off chat_id={chat_id} text={message_text[:60]!r}")
                elif is_spam and ("کلمه ممنوعه" in str(reason) or "banned_word" in str(reason)):
                    kind = "spam_banned_word" if "spam_banned_word" in str(reason) else "banned_word"
                    bot.logger.log_info(
                        f"BANNED WORD HIT kind={kind} chat_id={chat_id} "
                        f"reason={reason!r} text={message_text[:60]!r}"
                    )
                elif not is_spam:
                    # Check if text would have matched banned word but strict off or no match
                    # We do a quick check without full pattern to avoid double work
                    pass
            except Exception:
                pass
            if is_spam:
                moderation_trigger = _detector_moderation_trigger(reason)

        _debug_log(
            bot,
            f"MODERATION TYPE={'SPAM' if moderation_trigger == 'spam' else 'FILTER_GROUP'} "
            f"chat_id={chat_id} user_id={user_id} reason={reason!r}",
        )
        profiler.mark("SPAM_CHECK")
        if is_spam:
            bot.logger.log_info(
                "SPAM DETECTED "
                f"user={user_id} chat_id={chat_id} reason={reason!r}"
            )
            bot.logger.log_info(
                "SPAM DETECT TIME "
                f"user={user_id} chat_id={chat_id} message_id={getattr(event.message, 'id', None)}"
            )
            profiler.mark("AUTO_MODERATION")
            rejoin_state = getattr(bot, "rejoin_spam_state", {}).get(
                (chat_id, user_id), {}
            )
            if rejoin_state.get("previously_banned"):
                bot.logger.log_info(
                    "SPLUS REJOIN STATE DEBUG\n"
                    f"user_id={user_id}\n"
                    f"chat_id={chat_id}\n"
                    "previously_banned=True\n"
                    f"previous_violations={rejoin_state.get('previous_violations', 0)}\n"
                    "new_spam_detected=True\n"
                    f"ban_triggered={f'{chat_id}:{user_id}' not in bot.punished_users}"
                )

            # اسپم تکراری شدید: ذخیره + حذف + بن مستقیم
            try:
                from modules.user_map import save_user
                save_user(chat_id, username, user_id)

                # فقط متن‌های خیلی بلند و تکراری را اسپم شدید حساب کن
                normalized = message_text.strip()
                repeat_spam = (
                    len(normalized) > 300
                    and len(set(normalized.split())) < 20
                )

                if repeat_spam:
                    bot.logger.log_deleted_message(
                        user_id=user_id,
                        username=username,
                        group_id=chat_id,
                        group_title=chat_title,
                        original_text=message_text,
                        reason="اسپم تکراری شدید",
                        message_id=event.message.id
                    )

                    repeated_ids = message_tracker.spam_snapshot(
                        chat_id, user_id, getattr(event.message, "id", None)
                    )
                    bot.logger.log_info(
                        "SPAM HISTORY SNAPSHOT "
                        f"chat_id={chat_id} user_id={user_id} "
                        f"count={len(repeated_ids)} ids={repeated_ids!r}"
                    )

                    if hasattr(bot.admin_actions, "ban_user"):
                        punish_key = _punishment_key(chat_id, user_id)
                        _log_ban_execution(bot, chat_id, user_id, "اسپم تکراری شدید")
                        if punish_key not in bot.punished_users:
                            bot.punished_users.add(punish_key)
                            async def repeat_ban_succeeded(_result):
                                # Merge this direct-ban path into the same
                                # incident as threshold/lock cleanup work.
                                _confirm_spam_ban_cleanup(
                                    bot, event, chat_id, user_id,
                                    set(repeated_ids),
                                )

                            async def repeat_ban_failed(_error):
                                bot.punished_users.discard(punish_key)

                            bot.moderation_queue.enqueue(
                                chat_id,
                                "ban",
                                user_id=user_id,
                                timeout_seconds=20,
                                operation=lambda: bot.admin_actions.ban_user(
                                    chat_id, user_id, reason="اسپم مکرر شدید",
                                    user=sender,
                                ),
                                on_success=repeat_ban_succeeded,
                                on_failure=repeat_ban_failed,
                            )

                    return
            except Exception as e:
                print("repeat spam check error:", e)

            # افزایش شمارنده
            from modules.user_map import save_user

            save_user(chat_id, username, user_id)

            previous_warnings = bot.tracker.get_count(chat_id, user_id)
            _debug_log(bot,
                "WARNING LOAD DEBUG\n"
                f"user_id={user_id}\n"
                f"group_id={chat_id}\n"
                f"previous_warnings={previous_warnings}"
            )
            count = bot.tracker.increment(chat_id, user_id)
            _debug_log(bot,
                "WARNING LOAD DEBUG\n"
                f"user_id={user_id}\n"
                f"group_id={chat_id}\n"
                f"previous_warnings={previous_warnings}\n"
                f"new_warning_count={count}"
            )

            threshold = warning_threshold.get_threshold(
                chat_id, bot.config_manager.get("spam_threshold", 3))
            if native_admin_warn_only and count >= threshold:
                # Native admins may accumulate ordinary warnings, but reaching
                # the threshold resets their moderation lifecycle instead of
                # creating a lock, deletion job, or ban attempt.
                _asyncio.create_task(bot.admin_actions.send_warning(
                    chat_id=chat_id, username=username, user=sender,
                    reason=reason, count=count, threshold=threshold, reply_to=None,
                ), name="warn:send")
                _clear_native_admin_moderation_state(
                    bot, chat_id, user_id, force=True
                )
                bot.logger.log_info(
                    "NATIVE ADMIN WARNING CYCLE RESET "
                    f"chat_id={chat_id} user_id={user_id} count={count} "
                    "reason=threshold_no_auto_punish"
                )
                return
            if count >= threshold:
                bot.set_spam_lock((chat_id, user_id))
                _debug_log(bot,
                    f"SPAM FLOW TRACE chat_id={chat_id} user_id={user_id} message_id={getattr(event.message, 'id', None)} stage=LOCK_SET key={(chat_id, user_id)!r} reason=threshold count={count} lock_size={len(getattr(bot, 'spam_lock', set()))}"
                )
                bot.logger.log_info(
                    f"SPAM LOCK SET chat_id={chat_id} user_id={user_id} count={count}"
                )

            # لاگ
            # لاگ
            bot.logger.log_deleted_message(
                user_id=user_id,
                username=username,
                group_id=chat_id,
                group_title=chat_title,
                original_text=message_text,
                reason=reason,
                message_id=event.message.id
            )

            # حذف پیام
            if bot.config_manager.get("delete_spam", True):
                spam_rows = message_tracker.get_user_recent_messages(
                    chat_id, user_id
                )
                # The current detection is authoritative. Older tracker rows
                # are included only when they independently satisfy the real
                # SpamDetector branch, never merely a forbidden/group word.
                spam_ids = {
                    row.get("message_id") for row in spam_rows
                    if isinstance(row.get("message_id"), int)
                    and row.get("message_id") > 0
                    and _is_true_auto_spam_text(bot, chat_id, row.get("text"))
                }
                current_message_id = getattr(event.message, "id", None)
                if current_message_id:
                    spam_ids.add(current_message_id)
                # Keep IDs ready, but do not start history/delete work until
                # the immediate punish job below has been queued.
                pending_spam_cleanup_ids = spam_ids
            else:
                pending_spam_cleanup_ids = set()

            # بررسی مجازات
            if bot.tracker.should_punish(chat_id, user_id, threshold=threshold):
                punish_key = _punishment_key(chat_id, user_id)
                _log_ban_execution(bot, chat_id, user_id, "رسیدن به آستانه تخلفات")

                if punish_key not in bot.punished_users:
                    bot.punished_users.add(punish_key)

                    print(
                        f"⚠️ کاربر {username}({user_id}) به آستانه {threshold} رسید - اعمال مجازات"
                    )

                    threshold_action = bot.config_manager.get(
                        "action_on_threshold", "mute"
                    )
                    bot.logger.log_info(
                        "PUNISH START "
                        f"user={user_id} chat_id={chat_id} "
                        f"action={threshold_action}"
                    )
                    async def threshold_punish_succeeded(_result):
                        bot.logger.log_info(
                            "PUNISH FINISHED "
                            f"user={user_id} chat_id={chat_id} "
                            f"action={threshold_action} success=True"
                        )
                        permanent = threshold_action in ["ban", "kick"]
                        # The spam cleanup task sends the single combined
                        # cleanup notification; do not emit a second notice.
                        if permanent:
                            # The generic detector may already have queued one
                            # or more delete batches. Seal that same incident
                            # only now, after the ban/kick operation succeeded.
                            _confirm_spam_ban_cleanup(
                                bot, event, chat_id, user_id
                            )
                        bot.tracker.reset_count(chat_id, user_id)
                        if not permanent:
                            bot.punished_users.discard(punish_key)

                    async def threshold_punish_failed(_error):
                        bot.punished_users.discard(punish_key)

                    bot.logger.log_info(
                        "PUNISH QUEUED "
                        f"user={user_id} chat_id={chat_id} "
                        f"action={threshold_action}"
                    )
                    bot.moderation_queue.enqueue(
                        chat_id,
                        "punish",
                        user_id=user_id,
                        timeout_seconds=20,
                        operation=lambda: bot.admin_actions.punish_user(
                            chat_id, user_id, username, announce=False,
                            user=sender,
                        ),
                        on_success=threshold_punish_succeeded,
                        on_failure=threshold_punish_failed,
                    )

            # Warning and deletion are non-critical side effects.  Start them
            # after the urgent punish job is queued, never before it.
            if count <= 5:
                _asyncio.create_task(bot.admin_actions.send_warning(
                    chat_id=chat_id, username=username, user=sender,
                    reason=reason, count=count, threshold=threshold, reply_to=None,
                ), name="warn:send")
            if pending_spam_cleanup_ids:
                _schedule_auto_spam_cleanup(
                    bot, event, chat_id, user_id, pending_spam_cleanup_ids,
                    announce_cleanup=_send_spam_cleanup_notice(moderation_trigger),
                )
                bot.logger.log_info(
                    "SPAM CLEANUP QUEUED "
                    f"chat_id={chat_id} user_id={user_id} seed_ids={len(pending_spam_cleanup_ids)}"
                )
            # پیام سالم - می‌توان برای آنالیز بیشتر لاگ کرد
            pass

    except Exception as e:
        bot.logger.log_error(f"خطا در هندل پیام: {e}")
        import traceback
        traceback.print_exc()
    finally:
        profiler.set("SEND_RESPONSE", response_rpc_ms())
        performance_result = profiler.finish(bot.logger, chat_id)
        try:
            event._bot_performance_result = performance_result
        except Exception:
            pass
        end_response_measurement(response_token)
