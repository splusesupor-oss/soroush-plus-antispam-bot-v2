from modules.security.security_manager import check_security, remove_message
from modules.security.attack_guard import check_attack, clear_attack
from modules.security import attack_guard as security_attack_guard
from modules.security import media_spam as security_media_spam
from modules.security.delete_queue import process_delete
import asyncio
from modules.admin_storage import is_admin, add_admin, remove_admin
from modules.riddles import new_riddle, check_answer, get_answer
from modules.spam_history import get_user_history, clear_user as clear_spam_history
from modules import message_tracker
from modules.group_id import normalize_group_id
from modules.group_stats import add_message, add_deleted, add_kick, add_mute, make_report
from modules import ConfigManager, SpamDetector, BotLogger, UserTracker, AdminActions
from modules.jorat_haghighat import get_jorat, get_haghighat
from modules.font_converter import make_fonts
from modules.owner_check import get_owner, is_global_owner, normalize_username
from modules.owner_private import remember_owner_peer
from modules.group_expiry import match_command as expiry_command
from modules.expiry_report import build_report as build_expiry_report
from modules.admin_tools import run_cleanup_watcher
from modules import access_profile_guard
from handlers.group_expiry_handler import (
    run_expiry_watcher as run_group_expiry_watcher,
)
from modules.banned_storage import (
    add_banned,
    remove_banned,
    is_banned,
    load_banned,
    get_matching_ban_records,
    remove_banned_everywhere,
    FILE as BANNED_STORAGE_FILE,
)
from modules.group_words_commands import handle_group_word_command
from modules.group_banned_words_control import enable, disable
from modules.group_storage import activate_group, deactivate_group, is_active, update_group_title
from modules.group_storage_migration import migrate_all_group_storage
from modules.group_actions import GroupActions
# 💰 تسویهٔ روزانه از راه API اقتصاد جدید.
from economy import flush as flush_economy, settle_previous_days
from economy import upgrade_migration
from modules.group_stats import flush as flush_group_stats
from modules.user_activity import flush as flush_user_activity
from modules.game_progress_storage import flush_all as flush_game_progress
from modules.reminders import due as due_reminders, mark_sent as mark_reminder_sent
from modules.moderation_queue import ModerationQueue
from modules.outgoing_profiler import instrument_client, instrument_event
from modules.message_delete_queue import MessageDeleteQueue
from modules.notice_cleanup import NoticeCleanup
from modules.outgoing_sender import install as install_outgoing_sender, install_event_wrapper
from modules.group_dispatch import GroupDispatcher, classify_priority, looks_like_link
from modules.light_spam_ingest import ingest_event
from modules import connection_guard
from modules import site_policy
from modules.runtime_maintenance import run as run_runtime_maintenance
from modules.watchdog_reporting import deliver_pending_reports
from modules.performance_monitor import SlowProcessMonitor
from modules.runtime_snapshot import RuntimeSnapshotMonitor
from handlers.message_handler import (
    handle_new_message,
    send_activation_message,
    handle_fast_owner_command,
    is_fast_owner_command,
    handle_fast_moderation_command,
    is_fast_moderation_command,
    is_game_answer_active,
    _resolved_event_peer,
)
from handlers.broadcast_handler import handle_private_broadcast
from handlers.private_handler import (
    register_private_handlers,
    try_handle_private_start,
)
from modules.name_family import cancel_round as cancel_name_family_round
from modules.broadcast_state import (
    BROADCAST_COMMAND_WORDS,
    get as get_broadcast_state,
    is_broadcast_command,
    normalize_command_text,
    normalize_broadcast_trigger,
    match_broadcast_trigger,
)
from handlers.admin_handler import handle_admin_commands
import random
"""
ربات مدیریت گروه سروش پلاس - ضد هرزنامه
اجرا روی حساب کاربری شما با SPlusthon (فورک Telethon برای سروش)

ویژگی‌ها:
- بررسی تمام پیام‌های جدید گروه
- تشخیص لینک، شماره، آیدی، کلمات تبلیغاتی
- حذف خودکار + سایلنت/بن بعد از 3 تخلف
- وایت لیست مدیران
- افزودن کلمات ممنوعه از طریق فایل یا دستور
- لاگ کامل
- ماژولار

نویسنده: Agent for Soroush Plus
"""

import os
import asyncio
import sys
import time
from dotenv import load_dotenv
from splusthon.tl.types import MessageEntityBold, MessageEntityBlockquote

# Load the project .env by an absolute path.  A service/restart may launch
# from another working directory, where bare ``load_dotenv()`` misses it.
_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path=_ENV_FILE, override=False)


# اگر پوشه ماژول‌ها در مسیر نیست اضافه کن
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# تلاش برای import SPlusthon
try:
    from splusthon import SoroushClient, events
    from splusthon.sessions import StringSession
    SPLUSTHON_AVAILABLE = True
except ImportError:
    SPLUSTHON_AVAILABLE = False
    print("⚠️ کتابخانه splusthon نصب نیست. ابتدا pip install splusthon را اجرا کنید")
    print("راهنما: pip install -r requirements.txt")


from splusthon import types
global functions

from splusthon.tl import functions
from collections import defaultdict, deque

# وصلهٔ ارسالِ فایل: درخواست‌های SaveFilePart را به media DC می‌فرستد تا
# خطای FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER در آپلود عکس رخ ندهد.
try:
    from modules.splusthon_upload_fix import install_media_upload
    _MEDIA_UPLOAD_PATCH_AVAILABLE = True
except Exception:  # pragma: no cover - اگر ماژول در دسترس نبود، ربات بی‌ضرر ادامه می‌دهد
    _MEDIA_UPLOAD_PATCH_AVAILABLE = False
# ---------------------------------------------------


# 📢 دلیل دورریختن پیام گروه‌های inactive باید در ترمینال دیده شود؛
# بدون این لاگ، سکوت ناگهانی یک گروه (groups.json خراب/انقضا/
# ناهماهنگی id) غیرقابل ردیابی بود.
_INACTIVE_GATE_LOGGED = {}


def _log_inactive_gate(bot, chat_id, text):
    try:
        now = time.monotonic()
        if now - _INACTIVE_GATE_LOGGED.get(chat_id, 0.0) < 300:
            return
        _INACTIVE_GATE_LOGGED[chat_id] = now
        if len(_INACTIVE_GATE_LOGGED) > 500:
            for key in [
                key for key, ts in _INACTIVE_GATE_LOGGED.items()
                if now - ts > 600
            ]:
                _INACTIVE_GATE_LOGGED.pop(key, None)
        bot.logger.log_error(
            "GROUP GATE INACTIVE — message dropped "
            f"chat_id={chat_id} text={str(text or '')[:30]!r} "
            "reason=group not active in groups.json "
            "(بررسی: دستور «فعال» مالک، انقضای گروه، سالم بودن فایل groups.json)"
        )
    except Exception:
        pass


class SoroushAntiSpamBot:
    def __init__(self, config_path="config/config.json"):
        print("🚀 در حال بارگذاری تنظیمات...")
        site_policy.load()
        migrated_files = migrate_all_group_storage()
        self.config_manager = ConfigManager(config_path=config_path)
        if migrated_files:
            print("GROUP STORAGE MIGRATED:", ", ".join(migrated_files))
        self.bot_sent_messages = []
        self.logger = BotLogger(
            log_file=self.config_manager.get(
                "log_file", "logs/deleted_messages.log"))
        self.detector = SpamDetector(self.config_manager)
        self.tracker = UserTracker(
            spam_counts_file=self.config_manager.get(
                "spam_counts_file",
                "logs/spam_counts.json"),
            threshold=self.config_manager.get(
                "spam_threshold",
                3))

        self.client = None
        # One fair connection-wide application RPC budget. It is created by
        # outgoing_sender.install after .env has loaded and reused on rebuild.
        self.rpc_governor = None
        # InputPeer cache used by ordinary replies; avoids per-message dialog
        # lookup while staying bounded for long-running multi-group sessions.
        self.reply_input_peer_cache = {}
        self.admin_actions = None
        self.moderation_queue = ModerationQueue(self.logger)
        self.group_actions = None
        # Transient moderation state.  All keys below are bounded by the
        # periodic cleanup so a long-running account cannot retain a key per
        # user/chat forever.
        self.delete_notice_lock = {}
        self.punished_users = set()
        # Light ingest runs before the heavy game router. This pure state probe
        # prevents legitimate game answers from entering generic flood rules.
        self._light_game_answer_active = is_game_answer_active
        # Per-user/group fast gate set as soon as severe spam is detected.
        # Values are monotonic timestamps, not just set membership.
        self.spam_lock = {}
        self.repeat_messages = {}
        self.flood_messages = {}
        self.user_messages = {}
        self.group_timer_tasks = {}
        self.spam_burst_users = set()
        self.spam_burst_messages = {}
        self.spam_burst_tasks = {}
        self.rejoin_spam_state = {}
        self.forward_spam_counts = {}
        self._temporary_state_touched = {}
        self._spammer_messages_touched = {}
        self._temporary_state_cleanup_task = None
        from modules.delete_queue import process_delete
        self.process_delete = process_delete
        self.group_dispatcher = GroupDispatcher(
            logger=self.logger,
            debug_timing=self.config_manager.get(
                "debug_message_pipeline", False),
        )
        # ⏱️ زمان شروع برای دستور تشخیصی «وضعیت ربات».
        self.started_at = time.time()
        from modules.observability import MetricsCollector, PeriodicHealthMonitor
        self.metrics_collector = MetricsCollector.get_instance(self.logger)
        self.health_monitor = PeriodicHealthMonitor(self, self.logger, interval_seconds=600.0)
        self.outgoing_sender = None
        self.performance_monitor = None
        self.runtime_snapshot = None
        self.notice_cleanup = NoticeCleanup(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config",
                "notice_cleanup.json",
            ),
            logger=self.logger,
            ttl_seconds=60,
        )

        self.logger.log_info("✅ تنظیمات بارگذاری شد")
        self.logger.log_info(
            f"📚 تعداد کلمات ممنوعه: {len(self.config_manager.banned_words)}")
        self.logger.log_info(
            f"🛡️ تعداد کاربران سفید: {len(self.config_manager.whitelisted_ids)}")

    # TTLs affect only in-memory gates/caches.  They deliberately do not
    # change spam scoring, moderation actions, bans, warnings, or storage.
    SPAM_LOCK_TTL = 5 * 60
    DELETE_NOTICE_LOCK_TTL = 5 * 60
    BURST_STATE_TTL = 15 * 60
    FORWARD_STATE_TTL = 15 * 60
    REJOIN_STATE_TTL = 24 * 60 * 60
    SPAMMER_MESSAGES_TTL = 15 * 60
    # Safety cap for punished_users: reconciliation drops only entries whose
    # punishment is verified inactive; the cap applies to that same verified
    # subset and never removes an active punishment.
    PUNISHED_USERS_MAX = 5000

    def _state_now(self):
        return time.monotonic()

    def debug_message_log(self, message):
        if self.config_manager.get("debug_message_pipeline", False):
            self.logger.log_info(message)

    def touch_temporary_state(self, bucket, key, now=None):
        self._temporary_state_touched[(bucket, key)] = (
            self._state_now() if now is None else now
        )

    @staticmethod
    def _spam_state_key(key):
        try:
            return normalize_group_id(key[0]), str(key[1])
        except (TypeError, IndexError):
            return key

    def set_spam_lock(self, key, now=None):
        if not hasattr(self, "spam_lock"):
            self.spam_lock = {}
        key = self._spam_state_key(key)
        self.spam_lock[key] = self._state_now() if now is None else now

    def is_spam_locked(self, key, now=None):
        now = self._state_now() if now is None else now
        locks = getattr(self, "spam_lock", {})
        key = self._spam_state_key(key)
        created = locks.get(key)
        if created is None:
            return False
        if now - created >= self.SPAM_LOCK_TTL:
            locks.pop(key, None)
            return False
        return True

    def clear_spam_lock(self, key):
        getattr(self, "spam_lock", {}).pop(self._spam_state_key(key), None)

    def clear_released_user_state(self, chat_id, user_id):
        """Erase every prior punishment/delete cache for a released user.

        A release is a fresh moderation lifecycle.  In particular, this must
        not leave or recreate a rejoin marker that can make later messages
        eligible for deletion.  Persistent ban removal remains the unban RPC's
        responsibility; this method clears runtime and persisted spam counts.
        """
        canonical_group = normalize_group_id(chat_id)

        def same_group(value):
            return normalize_group_id(value) == canonical_group

        def same_pair(key):
            try:
                return same_group(key[0]) and str(key[1]) == str(user_id)
            except (IndexError, TypeError):
                return False

        # UserTracker's current keys and legacy raw group-id keys can coexist
        # in spam_counts.json after a restart; remove both forms.
        tracker_changed = False
        with self.tracker._lock:
            for group_key in list(getattr(self.tracker, "spam_counts", {})):
                if not same_group(group_key):
                    continue
                users = self.tracker.spam_counts.get(group_key, {})
                before = len(users)
                for candidate_user in (str(user_id), user_id):
                    users.pop(candidate_user, None)
                tracker_changed = tracker_changed or len(users) != before
                if not users:
                    self.tracker.spam_counts.pop(group_key, None)
            if tracker_changed:
                self.tracker.mark_dirty()
        self.tracker.save()

        for mapping_name in ("banned_users", "muted_users"):
            mapping = getattr(self.tracker, mapping_name, {})
            for key in list(mapping):
                try:
                    group_key, stored_user_id = str(key).rsplit(":", 1)
                except ValueError:
                    continue
                if same_group(group_key) and stored_user_id == str(user_id):
                    mapping.pop(key, None)

        for key in list(self.spam_lock):
            if same_pair(key):
                self.clear_spam_lock(key)
        self.punished_users = {
            key for key in self.punished_users
            if not (":" in str(key)
                    and same_group(str(key).rsplit(":", 1)[0])
                    and str(key).rsplit(":", 1)[1] == str(user_id))
        }
        for mapping_name in (
            "rejoin_spam_state", "spam_burst_messages", "spam_burst_tasks",
            "forward_spam_counts", "_auto_spam_cleanup_pending",
            "_auto_spam_cleanup_tasks", "_spam_cleanup_incidents",
            "_big_spam_incidents",
        ):
            mapping = getattr(self, mapping_name, {})
            for key in list(mapping):
                if same_pair(key):
                    task = (
                        mapping.get(key)
                        if mapping_name in {
                            "spam_burst_tasks", "_auto_spam_cleanup_tasks"
                        }
                        else None
                    )
                    if task is not None and not task.done():
                        task.cancel()
                    mapping.pop(key, None)
        for key in list(getattr(self, "spam_burst_users", set())):
            if same_pair(key):
                self.spam_burst_users.discard(key)
        for key in list(getattr(self, "forward_spam_processing", set())):
            if same_pair(key):
                self.forward_spam_processing.discard(key)
        for bucket_key in list(getattr(self, "_temporary_state_touched", {})):
            try:
                _bucket, key = bucket_key
            except (TypeError, ValueError):
                continue
            if same_pair(key):
                self._temporary_state_touched.pop(bucket_key, None)

        # spam_history used raw tuple keys in older versions; clear current,
        # short, and legacy -100 forms. message_tracker canonicalizes itself.
        group_forms = {chat_id, str(chat_id), canonical_group}
        try:
            group_forms.add(-1_000_000_000_000 - int(canonical_group))
        except (TypeError, ValueError):
            pass
        for group_form in group_forms:
            clear_spam_history(group_form, user_id)
            message_tracker.clear_user_history(group_form, user_id)
        for group_key, rows in list(getattr(self, "flood_messages", {}).items()):
            if same_group(group_key):
                kept = [row for row in rows if len(row) < 3 or str(row[2]) != str(user_id)]
                if kept:
                    self.flood_messages[group_key] = kept
                else:
                    self.flood_messages.pop(group_key, None)

        for mapping_name in ("repeat_messages", "user_messages"):
            mapping = getattr(self, mapping_name, {})
            for key in list(mapping):
                if key in (user_id, str(user_id)) or same_pair(key):
                    mapping.pop(key, None)
        for candidate_user in (user_id, str(user_id)):
            self.spammer_messages.pop(candidate_user, None)
            self._spammer_messages_touched.pop(candidate_user, None)

    def acquire_delete_notice_lock(self, chat_id, now=None):
        now = self._state_now() if now is None else now
        created = self.delete_notice_lock.get(chat_id)
        if created is not None and now - created < self.DELETE_NOTICE_LOCK_TTL:
            return False
        self.delete_notice_lock[chat_id] = now
        return True

    def cleanup_temporary_state(self, now=None):
        """Prune only expired runtime caches; moderation policy is untouched."""
        now = self._state_now() if now is None else now
        for key, created in list(self.spam_lock.items()):
            if now - created >= self.SPAM_LOCK_TTL:
                self.spam_lock.pop(key, None)
        for chat_id, created in list(self.delete_notice_lock.items()):
            if now - created >= self.DELETE_NOTICE_LOCK_TTL:
                self.delete_notice_lock.pop(chat_id, None)

        def stale(bucket, key, ttl):
            touched = self._temporary_state_touched.get((bucket, key))
            return touched is not None and now - touched >= ttl

        for key, task in list(self.spam_burst_tasks.items()):
            if task.done():
                self.spam_burst_tasks.pop(key, None)
        for key in list(self.spam_burst_messages):
            task = self.spam_burst_tasks.get(key)
            if stale("burst", key, self.BURST_STATE_TTL) and (task is None or task.done()):
                self.spam_burst_messages.pop(key, None)
                self.spam_burst_users.discard(key)
                self._temporary_state_touched.pop(("burst", key), None)
        for key in list(self.spam_burst_users):
            if stale("burst", key, self.BURST_STATE_TTL) and key not in self.spam_burst_tasks:
                self.spam_burst_users.discard(key)
                self._temporary_state_touched.pop(("burst", key), None)
        for key in list(self.forward_spam_counts):
            if stale("forward", key, self.FORWARD_STATE_TTL):
                self.forward_spam_counts.pop(key, None)
                self._temporary_state_touched.pop(("forward", key), None)
        for key, state in list(self.rejoin_spam_state.items()):
            touched = state.get("_touched_at") if isinstance(state, dict) else None
            if touched is not None and now - touched >= self.REJOIN_STATE_TTL:
                self.rejoin_spam_state.pop(key, None)
        for chat_id, rows in list(self.flood_messages.items()):
            fresh = [row for row in rows if row and now - row[0] <= 10]
            if fresh:
                self.flood_messages[chat_id] = fresh
            else:
                self.flood_messages.pop(chat_id, None)
        for user_id, touched in list(self._spammer_messages_touched.items()):
            if now - touched >= self.SPAMMER_MESSAGES_TTL:
                self.spammer_messages.pop(user_id, None)
                self._spammer_messages_touched.pop(user_id, None)
        # These are legacy temporary maps.  When code populates them it can
        # call touch_temporary_state; entries with no activity timestamp are
        # not removed here to avoid changing an unknown legacy flow.
        for bucket, mapping in (("repeat", self.repeat_messages), ("user", self.user_messages)):
            for key in list(mapping):
                if stale(bucket, key, self.BURST_STATE_TTL):
                    mapping.pop(key, None)
                    self._temporary_state_touched.pop((bucket, key), None)
        try:
            from handlers.message_handler import cleanup_expired_handler_state
            cleanup_expired_handler_state(self, now)
        except Exception:
            pass
        try:
            from modules.gif_spam_detector import cleanup_expired as gif_cleanup
            gif_cleanup()
        except Exception:
            pass
        try:
            from modules.runtime_snapshot import prune_unbounded_maps
            prune_unbounded_maps(self)
        except Exception:
            pass
        try:
            self.cleanup_punished_users_state()
        except Exception:
            pass

    def cleanup_punished_users_state(self):
        """هماهنگ‌سازی ``punished_users`` با منابع حقیقت مجازات فعال.

        فقط entryهایی حذف می‌شوند که دیگر مجازات فعال ندارند؛ بدون TTL
        کورکورانه:

        * گروه‌های بن: منبع حقیقت مجازات فعال، ذخیره‌گاه دائمی بن‌هاست
          (``banned_users.json``/SQLite). کاربری که دیگر در آن نیست (unban
          یا هر آزادسازی — همهٔ مسیرهای آزادسازی از آن ذخیره‌گاه پاک
          می‌شوند)، entry‌اش اینجا حذف می‌شود.
        * گروه‌های سکوت: مجازات «سکوت دائمی» است که فقط در سمت سرور
          زندگی می‌کند (ربات استور حالت mute ندارد و
          ``tracker.muted_users`` هیچ‌جا در کد زنده نوشته نمی‌شود)، پس
          entryها نگهداری می‌شوند؛ مسیرهای آزادسازی (رفع سکوت، unban و
          تشخیص آزادسازی دستی) در لحظهٔ آزادسازی entry را discard می‌کنند.
        * اگر key در mapهای ``tracker`` باشد نگهداری می‌شود (احتیاطی؛
          امروز خالی‌اند ولی اگر مسیر زنده‌ای روزی بنویسد، محافظت می‌شود).
        * هر خطا در هر چک → entry نگهداری می‌شود (پیش روی شک، حذف نکن).

        سقف ایمنی (``PUNISHED_USERS_MAX``) هیچ‌وقت مجازات فعال را حذف
        نمی‌کند؛ فقط روی همان دستهٔ «بدون مجازات فعال» اعمال می‌شود.
        """
        try:
            punished = self.punished_users
            if not punished:
                return 0
            from modules import punishment_mode
            try:
                ban_data = load_banned()
            except Exception:
                # ذخیره‌گاه بن خوانا نیست؛ نمی‌توان «فعال/غیرفعال» را تأیید
                # کرد → هیچ entry‌ای حذف نمی‌شود (پیش روی شک، پاک‌سازی
                # انجام نمی‌شود و sweep بعدی دوباره امتحان می‌کند).
                return 0

            def still_punished(key):
                if (key in self.tracker.banned_users
                        or key in self.tracker.muted_users):
                    return True
                group_key, sep, user_key = str(key).rpartition(":")
                if not sep or not group_key or not user_key:
                    return True  # فرمت ناشناخته: دست نزن
                try:
                    if punishment_mode.is_mute(group_key):
                        return True  # سکوت دائمی: منبع حقیقت سمت سرور است
                except Exception:
                    pass
                try:
                    if is_banned(group_key, user_key, data=ban_data):
                        return True
                except Exception:
                    return True  # شکست چک: نگهداری کن
                return False

            removed = 0
            for key in list(punished):
                if not still_punished(key):
                    punished.discard(key)
                    removed += 1
            if len(punished) > self.PUNISHED_USERS_MAX:
                for key in list(punished):
                    if len(punished) <= self.PUNISHED_USERS_MAX:
                        break
                    if not still_punished(key):
                        punished.discard(key)
                        removed += 1
            if removed:
                self.logger.log_info(
                    f"PUNISHED USERS RECONCILED removed={removed} "
                    f"remaining={len(punished)}"
                )
            return removed
        except Exception as error:
            try:
                self.logger.log_error(
                    f"PUNISHED USERS RECONCILE FAILED {error!r}")
            except Exception:
                pass
            return 0

    def _make_client(self):
        """یک ``SoroushClient`` کاملاً جدید با سشنِ تازه می‌سازد.

        روی سشنِ کهنهٔ خراب استفاده نمی‌شود؛ هر بار یک ``StringSession``
        تازه از همان session string می‌سازد تا sender/state/receive loop
        همگی از صفر باشند.
        """
        session_str = os.getenv("SOROUSH_SESSION_STRING") or self.config_manager.get(
            "session_string", "")
        api_id = os.getenv("API_ID") or self.config_manager.get("api_id")
        api_hash = os.getenv("API_HASH") or self.config_manager.get("api_hash")

        if session_str:
            session = StringSession(session_str)
        else:
            session = StringSession()

        if api_id and api_hash:
            client = SoroushClient(session, api_id, api_hash)
        else:
            client = SoroushClient(session)
        return client

    async def initialize_client(self):
        """ساخت کلاینت سروش"""
        if not SPLUSTHON_AVAILABLE:
            raise RuntimeError("SPlusthon نصب نیست")

        self.client = self._make_client()

        # وصلهٔ آپلودِ فایل (media DC) را روی کلاسِ کلاینت نصب می‌کند.
        # چون روی کلاس است، کلاینت‌هایِ بازسازی‌شده هم خودکار وصله‌خورده‌اند.
        if _MEDIA_UPLOAD_PATCH_AVAILABLE:
            install_media_upload()
            self.logger.log_info("MEDIA_UPLOAD_PATCH_LOADED=True")
        else:
            self.logger.log_info("MEDIA_UPLOAD_PATCH_LOADED=False (module missing)")

        self.spammer_messages = defaultdict(lambda: deque(maxlen=5000))
        instrument_client(self.client, self.logger)

        # 🛡️ لایهٔ پایداری اتصال.
        #
        # سه نقص اثبات‌شده در لایهٔ شبکهٔ SPlusthon را می‌بندد:
        #   • قاب‌های کهنهٔ سشن قبلی که بعد از reconnect باعث
        #     «Server replied with a wrong session ID» می‌شدند،
        #   • حلقهٔ reset دورهٔ ۳۰ دقیقه‌ای که خودش را cancel می‌کرد و
        #     ترنسپورت را برای همیشه مرده رها می‌کرد،
        #   • نبودِ سقف زمانی روی RPC که باعث می‌شد send_message
        #     دقیقه‌ها معلق بماند.
        #
        # باید *قبل از* connect() نصب شود تا اولین سوکت هم وصله‌خورده
        # ساخته شود.
        #
        # client_factory: وقتی supervisor تشخیص دهد RPCها یا سشن خراب است،
        # به‌جای connect روی همان کلاینتِ کهنه، یک کلاینت کاملاً جدید با
        # سشن تازه می‌سازد و client را عوض می‌کند.
        self.connection_supervisor = connection_guard.install(
            self.client,
            logger=self.logger,
            client_factory=self._rebuild_client,
        )

        self.admin_actions = AdminActions(
            self.client, self.logger, self.config_manager,
            peer_cache=self.reply_input_peer_cache,
            bot_account_id=getattr(self, "bot_account_id", None),
        )
        self.admin_actions.notice_cleanup = getattr(self, "notice_cleanup", None)

        self.group_actions = GroupActions(
            self.client, self.logger)
        return self.client

    async def _rebuild_client(self, old_client, reason):
        """کارخانهٔ ساخت کلاینتِ تازه برای supervisor.

        یک ``SoroushClient`` کاملاً جدید (سشن تازه، sender تازه) می‌سازد،
        هندلرهای رویدادِ کلاینتِ کهنه را به آن منتقل می‌کند، وصلهٔ RPC را
        دوباره نصب می‌کند و وصلش می‌کند. در پایان ``self.client`` و
        ``admin_actions``/``group_actions`` را به کلاینتِ جدید وصل می‌کند.

        هندلرها (NewMessage, ChatAction, Raw) به‌صورت داینامیک از
        ``self.client`` استفاده می‌کنند، پس همین که ``self.client`` عوض شود
        روی کلاینتِ جدید هم درست کار می‌کنند؛ فقط باید در ``_event_builders``
        کلاینتِ جدید ثبت شوند.
        """
        try:
            self.logger.log_info(
                "CLIENT REBUILD building fresh client "
                f"reason={reason!r}"
            )
            new_client = self._make_client()

            # انتقال هندلرها از کلاینت کهنه به کلاینت جدید
            old_builders = getattr(old_client, "_event_builders", None)
            if old_builders is not None:
                new_client._event_builders = list(old_builders)

            instrument_client(new_client, self.logger)

            # وصلهٔ سقف زمانی RPC را روی کلاینت جدید هم نصب کن
            # (فیلتر قاب کهنه و حلقهٔ reset کلاس‌محورند و یک‌بار نصب شده‌اند)
            connection_guard.install_rpc_timeout(
                new_client,
                timeout=60.0,
                on_timeout=self.connection_supervisor.note_rpc_timeout,
                logger=self.logger,
            )

            await new_client.connect()
            me = await new_client.get_me()
            self.bot_account_id = getattr(me, "id", self.bot_account_id)

            # سوئیچ مرجع‌های ربات به کلاینت جدید
            self.client = new_client
            if getattr(self, "message_delete_queue", None) is not None:
                self.message_delete_queue.client = new_client
            if getattr(self, "outgoing_sender", None) is not None:
                self.outgoing_sender.client = new_client
                # re-install wrapper for new client
                install_outgoing_sender(new_client, self, self.logger)
            if getattr(self, "performance_monitor", None) is not None:
                self.performance_monitor.update_client(new_client)
            self.admin_actions = AdminActions(
                new_client, self.logger, self.config_manager,
                peer_cache=self.reply_input_peer_cache,
                bot_account_id=self.bot_account_id,
            )
            self.admin_actions.notice_cleanup = getattr(self, "notice_cleanup", None)
            if getattr(self, "notice_cleanup", None) is not None:
                self.notice_cleanup.client = new_client
            self.group_actions = GroupActions(new_client, self.logger)

            self.logger.log_info("CLIENT REBUILD new client connected")
            return new_client
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.log_error(
                f"CLIENT REBUILD FAILED: {error!r}"
            )
            return None



    async def check_group_word_commands(self, event, text, chat_id, user_id):
        try:
            self.debug_message_log(
                f"FILTER ARGS: {text!r} {type(text)} {chat_id} {user_id}"
            )
            return await handle_group_word_command(
                self,
                event,
                text,
                chat_id,
                user_id
            )
        except Exception as e:
            self.logger.log_error(f"خطای فیلتر کلمه: {e}")
            return False


    async def is_admin_user(self, event, user_id):
        try:
            sender = await event.get_sender()
            username = getattr(sender, "username", None)

            chat = await event.get_chat()
            chat_id = getattr(chat, "id", None)

            if is_admin(chat_id, user_id, username):
                return True

            if is_global_owner(user_id):
                return True

            return False

        except Exception as e:
            self.logger.log_error(f"خطا در تشخیص مدیر: {e}")
            return False

    def _overflow_message(self, event):
        """Cheap per-group overflow path: delete locked/link/spam messages only.

        Called when a chat's ordinary queue is already full.  Must not await
        and must not touch other groups.
        """
        try:
            chat_id = getattr(event, "chat_id", None)
            message = getattr(event, "message", None)
            message_id = getattr(message, "id", None) if message is not None else None
            text = ""
            if message is not None:
                text = (
                    getattr(message, "message", None)
                    or getattr(message, "caption", None)
                    or ""
                )
            user_id = getattr(event, "sender_id", None)
            if user_id is None:
                sender = getattr(event, "sender", None)
                user_id = getattr(sender, "id", None)
            if chat_id is None or message_id is None:
                return
            locked = bool(
                user_id is not None
                and self.is_spam_locked((chat_id, user_id))
            )
            is_link = looks_like_link(text)
            detector = getattr(self, "spam_detector", None)
            is_spam = False
            if not locked and not is_link and detector is not None and text:
                try:
                    is_spam, _ = detector.is_spam(text, chat_id)
                except Exception:
                    is_spam = False

            if not locked and not is_link and not is_spam:
                return
            queue = getattr(self, "message_delete_queue", None)
            if queue is not None:
                rpc_peer = None
                for owner in (message, event):
                    if owner is None:
                        continue
                    for attr in ("_input_chat", "input_chat"):
                        try:
                            rpc_peer = getattr(owner, attr, None)
                        except Exception:
                            rpc_peer = None
                        if rpc_peer is not None:
                            break
                    if rpc_peer is not None:
                        break
                queue.enqueue(
                    chat_id, [message_id], priority=1,
                    rpc_peer=rpc_peer,
                )
            self.logger.log_info(
                "GROUP DISPATCH OVERFLOW DELETE "
                f"chat_id={chat_id} message_id={message_id} locked={locked} spam={is_spam}"
            )
        except Exception as error:
            self.logger.log_error(f"GROUP DISPATCH OVERFLOW FAILED {error!r}")

    async def run(self):
        """اجرای ربات"""
        # Database scans, WAL checkpoints and online backup must never run on
        # the asyncio message loop.  Integrity failure is fatal by design;
        # continuing to mutate a damaged economy would be unsafe.
        maintenance = await asyncio.to_thread(run_runtime_maintenance)
        self.logger.log_info(
            "RUNTIME STORAGE READY "
            f"economy_integrity={maintenance.get('economy_integrity')} "
            f"runtime_integrity={maintenance.get('runtime_integrity', 'json')} "
            f"backup={'ok' if maintenance.get('backup') else 'not-due'} "
            f"backup_error={maintenance.get('backup_error') or '-'} "
            f"temp_removed={len(maintenance.get('temporary_removed', []))} "
            f"backups_removed={len(maintenance.get('backups_removed', []))}"
        )
        await self.initialize_client()

        await self.client.connect()
        try:
            self.bot_account_id = getattr(await self.client.get_me(), "id", None)
        except Exception as error:
            self.bot_account_id = None
            self.logger.log_error(f"خطا در دریافت شناسه حساب ربات: {error}")
        if getattr(self, "admin_actions", None) is not None:
            self.admin_actions.bind_runtime_context(
                peer_cache=self.reply_input_peer_cache,
                bot_account_id=self.bot_account_id,
            )
        asyncio.create_task(process_delete(self))
        # Automatic deletions have their own per-group workers and never run
        # synchronously in the incoming-message handler.
        # Soroush routinely times out a 100-message DeleteMessagesRequest.
        # Small bounded batches complete reliably and allow command replies to
        # interleave with a spam-wave cleanup.
        self.message_delete_queue = MessageDeleteQueue(
            self.client, self.logger, batch_size=15, max_concurrent=4,
            inter_batch_delay=0,
            peer_cache=self.reply_input_peer_cache,
        )
        # Outgoing sender for normal replies - separate from delete queue.
        # install() is the single constructor so there is never an unused
        # duplicate sender/queue object at startup.
        self.outgoing_sender = install_outgoing_sender(
            self.client, self, self.logger
        )
        # Live slow-handler monitoring is separate from crash delivery.  Its
        # bounded worker sends at most one owner report per cooldown window;
        # the message hot path performs no await, disk write, or network call.
        self.performance_monitor = SlowProcessMonitor(
            self.client, self.logger
        )
        self.performance_monitor.start()

        # Watchdog reports are handed to the normal, already-connected bot
        # client.  This runs once at startup (never per message), targets only
        # the global owner from owner_check.py, and leaves a failed report
        # pending for the next healthy restart.  It is deliberately a
        # background task so a slow private-message RPC cannot delay startup.
        async def deliver_watchdog_startup_reports():
            try:
                delivered = await deliver_pending_reports(
                    self.client,
                    status="ربات دوباره راه‌اندازی شد",
                    logger=self.logger,
                )
                if delivered:
                    self.logger.log_info(
                        "WATCHDOG STARTUP REPORT DELIVERY "
                        f"delivered={delivered}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as watchdog_report_error:
                self.logger.log_error(
                    "WATCHDOG STARTUP REPORT DELIVERY FAILED "
                    f"error={watchdog_report_error!r}"
                )

        self._watchdog_report_task = asyncio.create_task(
            deliver_watchdog_startup_reports()
        )

        self.notice_cleanup.bind_delete_queue(self.message_delete_queue)
        self.notice_cleanup.client = self.client
        if getattr(self, "admin_actions", None) is not None:
            self.admin_actions.notice_cleanup = self.notice_cleanup
        self.notice_cleanup.start()
        if hasattr(self, "health_monitor") and self.health_monitor is not None:
            self.health_monitor.start()
        # Diagnostic-only: PERFORMANCE SNAPSHOT every 30–60s plus a 5-minute
        # ACCUMULATION REPORT. Does not change queues, governor, or RPC.
        self.runtime_snapshot = RuntimeSnapshotMonitor(self, self.logger)
        self.runtime_snapshot.start()
        self.logger.log_info(
            "NOTICE CLEANUP STARTED "
            f"ttl_s={self.notice_cleanup.ttl_seconds:g} "
            f"pending_groups={len(self.notice_cleanup._items)}"
        )

        async def temporary_state_cleanup_loop():
            while True:
                try:
                    self.cleanup_temporary_state()
                    if getattr(self, "message_delete_queue", None) is not None:
                        try:
                            self.message_delete_queue.cleanup_expired()
                        except Exception:
                            pass
                    # Tracker retention is independent from moderation state.
                    from modules import message_tracker
                    message_tracker.cleanup_expired()
                    # 🧹 تاریخچهٔ اسپم هم مثل tracker هرس دوره‌ای می‌شود؛
                    # بدون این، RAM در گروه‌های پرترافیک ساعت‌به‌ساعت رشد
                    # می‌کرد و ربات به‌تدریج کند می‌شد (رفع با ری‌استارت).
                    from modules import spam_history as _spam_history
                    _spam_history.cleanup_expired()
                    security_attack_guard.cleanup_expired()
                    security_media_spam.cleanup_expired()
                    # 🧟 هرس دوره‌ای زامبی‌های سِندر (sender_pending).
                    #
                    # drop_stale_pending پیش‌تر فقط هنگام timeout یک RPC
                    # اجرا می‌شد؛ ورودی‌هایی مثل پینگ‌های keepalive که از
                    # مسیر client._call نمی‌گذرند هرگز مهر زمان نمی‌خوردند
                    # و برای همیشه در _pending_state می‌ماندند (در لاگ:
                    # sender_pending=590 و سیل PONG های قدیمی). هر reconnect
                    # هم همهٔ آن‌ها را دوباره روی سوکت می‌فرستاد و همین
                    # لَگ‌های ناگهانی و کندی دستورات مدیریتی را می‌ساخت.
                    # حالا هر ۶۰ ثانیه: اول همهٔ معلق‌ها مهر زمان می‌خورند،
                    # بعد هر چه بیش از ۱۸۰ ثانیه مانده (سه برابر مهلت ۶۰
                    # ثانیه‌ای RPC — قطعاً مرده) پاک می‌شود.
                    try:
                        _sender = getattr(self.client, "_sender", None)
                        if _sender is not None:
                            connection_guard.note_pending(_sender)
                            _dropped = connection_guard.reclaim_dead_pending(
                                _sender, logger=self.logger
                            )
                            if _dropped:
                                _left = len(
                                    getattr(_sender, "_pending_state", None)
                                    or {})
                                self.logger.log_info(
                                    "SENDER PENDING PRUNED "
                                    f"dropped={_dropped} remaining={_left}")
                    except Exception as prune_error:
                        self.logger.log_error(
                            f"SENDER PENDING PRUNE FAILED: {prune_error!r}")
                except Exception as error:
                    self.logger.log_error(f"TEMPORARY STATE CLEANUP FAILED: {error!r}")
                await asyncio.sleep(60)

        self._temporary_state_cleanup_task = asyncio.create_task(
            temporary_state_cleanup_loop()
        )

        async def runtime_storage_maintenance_loop():
            # Startup maintenance already ran above.  Repeat only daily so
            # integrity scans and checkpoints cannot become hot-path pressure.
            while True:
                await asyncio.sleep(24 * 60 * 60)
                try:
                    report = await asyncio.to_thread(run_runtime_maintenance)
                    self.logger.log_info(
                        "RUNTIME STORAGE MAINTENANCE "
                        f"integrity={report.get('economy_integrity')}/"
                        f"{report.get('runtime_integrity', 'json')} "
                        f"backup={'ok' if report.get('backup') else 'not-due'} "
                        f"backup_error={report.get('backup_error') or '-'} "
                        f"backups_removed={len(report.get('backups_removed', []))}"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as maintenance_error:
                    self.logger.log_error(
                        "RUNTIME STORAGE MAINTENANCE FAILED: "
                        f"{maintenance_error!r}"
                    )

        self._runtime_storage_maintenance_task = asyncio.create_task(
            runtime_storage_maintenance_loop()
        )

        # 🛡️ ناظر اتصال: اگر سشن خراب شد یا RPCها پشت سر هم timeout
        # خوردند، درخواست‌های معلق را لغو و کلاینت را بدون ری‌استارت
        # ربات بازسازی می‌کند.
        if getattr(self, "connection_supervisor", None) is not None:
            asyncio.create_task(self.connection_supervisor.run())

        # ⬆️ جبران یک‌بارهٔ تبدیل‌هایی که با نرخ قدیمی انجام شده‌اند.
        # خودکار اجرا می‌شود تا کاربر لازم نباشد دستی کاری کند؛ اجرای
        # دوباره بی‌اثر است چون هر تبدیل علامت می‌خورد.
        try:
            compensated = upgrade_migration.run()
            if compensated:
                self.logger.log_info(
                    "UPGRADE MIGRATION applied to "
                    f"{len(compensated)} wallet(s): {compensated}"
                )
        except Exception as error:
            self.logger.log_error(f"UPGRADE MIGRATION FAILED: {error!r}")

        async def settle_daily_coins():
            while True:
                try:
                    awards = settle_previous_days()
                    for chat_id, user_id, amount in awards:
                        self.logger.log_info(
                            f"DAILY COIN AWARD chat_id={chat_id} "
                            f"user_id={user_id} bronze={amount}"
                        )
                except Exception as error:
                    self.logger.log_error(f"خطا در تسویه سکه روزانه: {error}")
                await asyncio.sleep(3600)

        asyncio.create_task(settle_daily_coins())

        async def reminder_loop():
            first_flush = True
            while True:
                for reminder in due_reminders():
                    try:
                        await self.client.send_message(
                            int(reminder["chat_id"]),
                            "⏰ یادآوری\n\n"
                            f"سلام {reminder['name']} 👋\n\n"
                            f"📝 {reminder['text']}",
                        )
                        mark_reminder_sent(reminder["id"])
                    except Exception as error:
                        self.logger.log_error(
                            f"خطا در ارسال یادآوری {reminder.get('id')}: {error}"
                        )
                # این دو تابع فایل JSON می‌نویسند. روی نصب‌های پرکاربر،
                # user_activity.json چند مگابایت می‌شود و صرفِ serialize
                # آن ~۳۰ms طول می‌کشد. چون json.dumps قفل GIL را نگه
                # می‌دارد، حتی thread هم آن را پنهان نمی‌کند؛ نتیجه‌اش
                # قفل شدن دوره‌ای حلقهٔ رویداد بود که به شکل تأخیر در
                # پاسخ و قطع شدن WebSocket دیده می‌شد.
                #
                # راه‌حل: فاصلهٔ ذخیره‌سازی متناسب با هزینهٔ واقعی آن
                # تنظیم می‌شود. فایل کوچک مثل قبل هر ۱۵ ثانیه ذخیره
                # می‌شود؛ فایل سنگین کمتر، تا سهم آن از زمان حلقه ناچیز
                # بماند. داده از دست نمی‌رود چون در حافظه نگه داشته
                # می‌شود و در نهایت نوشته خواهد شد.
                # Do not serialize several large runtime files while the
                # client is connecting and processing its initial updates.
                # That startup flush was the 10s stall visible in production.
                if first_flush:
                    first_flush = False
                    await asyncio.sleep(300)
                started = time.perf_counter()
                self.debug_message_log("FLUSH START")
                try:
                    await asyncio.to_thread(flush_group_stats)
                    await asyncio.to_thread(flush_user_activity)
                    await asyncio.to_thread(flush_game_progress)
                    await asyncio.to_thread(flush_economy)
                    await asyncio.to_thread(self.tracker.save, True)
                    cost = time.perf_counter() - started
                    self.debug_message_log(f"FLUSH END ms={cost * 1000:.0f}")
                except Exception as error:
                    cost = time.perf_counter() - started
                    self.debug_message_log(f"FLUSH END ms={cost * 1000:.0f}")
                    self.logger.log_error(f"خطا در ذخیرهٔ دوره‌ای: {error}")

                # فاصله هرگز کمتر از پنج دقیقه نمی‌شود؛ اگر ذخیره‌سازی گران
                # باشد فاصله بیشتر می‌شود تا سهم آن زیر ۰٫۲٪ بماند.
                delay = max(300.0, min(900.0, cost * 500))
                if delay > 300.0:
                    self.logger.log_info(
                        "PERIODIC FLUSH SLOW "
                        f"cost_ms={cost * 1000:.0f} next_in_s={delay:.0f}"
                    )
                await asyncio.sleep(delay)

        asyncio.create_task(reminder_loop())

        # ⏳ ناظر تاریخ انقضای گروه — کاملاً مستقل از بقیهٔ حلقه‌ها.
        # بدون نیاز به هیچ پیامی، دقیقاً در زمان تعیین‌شده گروه را می‌بندد.
        async def group_expiry_loop():
            self.logger.log_info(
                "EXPIRY WATCHER START "
                f"interval={getattr(run_group_expiry_watcher, '__name__', 'watcher')}"
            )
            def deactivate(group_id, title):
                deactivate_group(group_id, title)
                for task in self.group_timer_tasks.pop(group_id, set()):
                    task.cancel()

            await run_group_expiry_watcher(
                self, deactivate, logger=self.logger)

        asyncio.create_task(group_expiry_loop())

        # 🧹 ناظر پاکسازی خودکار — در ساعتِ تنظیم‌شده، پیام‌های گروه را پاک می‌کند.
        if not hasattr(self, "cleanup_tasks"):
            self.cleanup_tasks = {}
        asyncio.create_task(run_cleanup_watcher(self, logger=self.logger))

        async def is_currently_restricted(chat_id, user):
            """وضعیت فعلی عضو را از SPlusthon می‌خواند؛ خطا یعنی حفظ بن فعلی."""
            try:
                channel = await self.client.get_input_entity(chat_id)
                participant = await self.client.get_input_entity(user)
                result = await self.client(
                    functions.channels.GetParticipantRequest(
                        channel=channel,
                        participant=participant,
                    )
                )
                state = getattr(result, "participant", None)
                state_name = state.__class__.__name__ if state else "Unknown"
                restricted = "Banned" in state_name
                self.logger.log_info(
                    f"MANUAL RELEASE CHECK user_id={getattr(user, 'id', None)} "
                    f"state={state_name} restricted={restricted}"
                )
                return restricted
            except Exception as error:
                self.logger.log_error(
                    f"خطا در بررسی وضعیت بن کاربر {getattr(user, 'id', None)}: {error}"
                )
                return True

        @self.client.on(events.Raw(types.UpdateChannelParticipant))
        async def manual_unban_update(update):
            previous = getattr(update, "prev_participant", None)
            current = getattr(update, "new_participant", None)
            previous_name = previous.__class__.__name__ if previous else "None"
            current_name = current.__class__.__name__ if current else "None"

            if "Banned" not in previous_name or "Banned" in current_name:
                return

            chat_id = getattr(update, "channel_id", None)
            user_id = getattr(update, "user_id", None)
            if chat_id is None or user_id is None:
                return

            try:
                user = await self.client.get_entity(user_id)
                username = getattr(user, "username", None)
                display_name = " ".join(
                    part for part in (
                        getattr(user, "first_name", None),
                        getattr(user, "last_name", None),
                    ) if part
                ).strip()
                # The raw update itself proves the member was released.  Do
                # not require a banned_users.json record: it may already have
                # been removed while stale runtime spam state still exists.
                removed_count, _, remaining_records = remove_banned_everywhere(
                    user_id,
                    username,
                    display_name,
                )
                self.tracker.banned_users.pop(f"{chat_id}:{user_id}", None)
                self.clear_released_user_state(chat_id, user_id)
                self.spammer_messages.pop(user_id, None)
                self.logger.log_info(
                    "Detected manual release, removed user from permanent "
                    f"banned storage. user_id={user_id} "
                    f"update={previous_name}->{current_name} "
                    f"removed={removed_count} remaining={remaining_records}"
                )
            except Exception as error:
                self.logger.log_error(
                    f"خطا در همگام‌سازی آزادسازی دستی {user_id}: {error}"
                )


        @self.client.on(events.ChatAction())
        async def group_title_sync(event):
            """🔄 همگام‌سازی خودکار نام گروه‌های ثبت‌شده.

            اگر نام گروه عوض شود، عنوان ذخیره‌شده در groups.json به‌روز
            می‌شود تا «لیست انقضا» همیشه نام فعلی را نشان دهد. کاملاً
            مستقل است و به هیچ مسیر دیگری دست نمی‌زند؛ برای گروه‌های
            ثبت‌نشده هم هیچ رکوردی نمی‌سازد.
            """
            try:
                chat_id = getattr(event, "chat_id", None)
                if chat_id is None:
                    return
                # ۱) رویداد صریح تغییر نام
                new_title = getattr(event, "new_title", None)
                if not new_title:
                    # ۲) جبران نام‌هایی که هنگام خاموش بودن ربات عوض
                    # شده‌اند: در رویدادهای کم‌تکرار عضویت (join/leave)
                    # عنوان فعلی از chat کش‌شدهٔ خود رویداد خوانده می‌شود.
                    chat = getattr(event, "chat", None)
                    if chat is None:
                        try:
                            chat = await event.get_chat()
                        except Exception:
                            chat = None
                    new_title = getattr(chat, "title", None)
                if not new_title:
                    return
                if update_group_title(chat_id, new_title):
                    self.logger.log_info(
                        "GROUP TITLE SYNC "
                        f"chat_id={chat_id} new_title={str(new_title)[:60]!r}"
                    )
            except Exception as error:
                self.logger.log_error(f"GROUP TITLE SYNC FAILED: {error!r}")


        @self.client.on(events.ChatAction())
        async def banned_join_check(event):
            try:
                if not event.user_joined and not event.user_added:
                    return

                user = await event.get_user()
                if not user:
                    return

                chat_id = event.chat_id
                if not is_active(chat_id):
                    return

                user_id = user.id
                username = getattr(user, "username", None)
                runtime_group, runtime_user = self._spam_state_key((chat_id, user_id))
                punish_key = f"{runtime_group}:{runtime_user}"
                burst_key = (runtime_group, runtime_user)
                history = get_user_history(chat_id, user_id)
                rejoin_state = self.rejoin_spam_state.get(burst_key, {})
                self.logger.log_info(
                    "SPLUS REJOIN STATE DEBUG\n"
                    f"user_id={user_id}\n"
                    f"chat_id={chat_id}\n"
                    f"previously_banned={rejoin_state.get('previously_banned', False)}\n"
                    f"previous_violations={rejoin_state.get('previous_violations', 0)}\n"
                    "new_spam_detected=False\n"
                    "ban_triggered=False\n"
                    f"punish_key={punish_key}\n"
                    f"in_punished_users={punish_key in self.punished_users}\n"
                    f"in_spam_burst_users={burst_key in self.spam_burst_users}\n"
                    f"history_count={len(history) if history is not None else 0}\n"
                    f"spam_count={self.tracker.get_count(chat_id, user_id)}"
                )

                banned_data = load_banned()
                banned = is_banned(
                    chat_id, user_id, username, data=banned_data
                )
                matching_records = get_matching_ban_records(
                    chat_id, user_id, username, data=banned_data
                )
                self.logger.log_info(
                    "JOIN BAN CHECK "
                    f"user_id={user_id} username={username} is_banned={banned} "
                    f"file={BANNED_STORAGE_FILE} records={matching_records}"
                )
                print(
                    "JOIN BAN DEBUG "
                    f"user_id={user_id} username={username} "
                    f"source={BANNED_STORAGE_FILE} records={matching_records}"
                )
                if banned:
                    if not await is_currently_restricted(chat_id, user):
                        display_name = " ".join(
                            part for part in (
                                getattr(user, "first_name", None),
                                getattr(user, "last_name", None),
                            ) if part
                        ).strip()
                        removed_count, _, remaining_records = (
                            remove_banned_everywhere(
                                user_id,
                                username,
                                display_name,
                            )
                        )
                        self.tracker.banned_users.pop(
                            f"{chat_id}:{user_id}", None
                        )
                        self.clear_released_user_state(chat_id, user_id)
                        self.spammer_messages.pop(user_id, None)
                        self.logger.log_info(
                            "Detected manual release, removed user from permanent "
                            f"banned storage. user_id={user_id} "
                            f"removed={removed_count} remaining={remaining_records}"
                        )
                        return

                    self.moderation_queue.enqueue(
                        chat_id,
                        "ban",
                        user_id=user_id,
                        timeout_seconds=20,
                        operation=lambda: self.client.edit_permissions(
                            chat_id,
                            user,
                            until_date=None,
                            view_messages=False,
                        ),
                    )
                    print(f"🚫 queued banned user rejoin block: {user_id}")

            except Exception as e:
                print(f"join ban check error: {e}")


        async def process_priority_command(event):
            """Admin/user-command lane: skip profile, broadcast, and spam prelude.

            Mute/ban/lock must not wait on get_chat routing or per-message
            debug logs.  Private chats still use the full path so existing
            owner/DM behavior is unchanged. Owner group commands
            (فعال / ثبت گروه / ثبت مالک) run on a dedicated fast path.
            """
            started_cmd = time.perf_counter()
            text = ""
            try:
                instrument_event(event, self.logger)
                raw_text = ""
                try:
                    message = getattr(event, "message", None)
                    raw_text = (
                        getattr(message, "message", None)
                        or getattr(message, "caption", None)
                        or ""
                    ) if message is not None else ""
                except Exception:
                    raw_text = ""
                text = normalize_command_text(raw_text)
                if getattr(event, "is_private", False):
                    await process_incoming_message(event)
                    return
                try:
                    if is_fast_owner_command(text):
                        if await handle_fast_owner_command(self, event, text):
                            return
                except Exception as fast_error:
                    self.logger.log_error(
                        "FAST OWNER COMMAND FALLBACK "
                        f"chat_id={getattr(event, 'chat_id', None)} "
                        f"text={text!r} error={fast_error!r}"
                    )
                sender = (
                    getattr(event, "_bot_cached_sender", None)
                    or getattr(event, "sender", None)
                )
                if sender is None:
                    try:
                        sender = await event.get_sender()
                    except Exception:
                        sender = None
                sender_id = getattr(sender, "id", None) or getattr(event, "sender_id", None)
                if sender is None and sender_id:
                    try:
                        sender = await self.client.get_entity(sender_id)
                    except Exception:
                        pass
                try:
                    event._bot_cached_sender = sender
                except Exception:
                    pass
                if sender is not None and is_global_owner(
                    getattr(sender, "id", None)
                ):
                    asyncio.create_task(
                        remember_owner_peer(
                            self.client,
                            event=event,
                            sender=sender,
                            logger=self.logger,
                        ),
                        name="owner-peer:remember",
                    )
                chat_id = getattr(event, "chat_id", None)

                # 🔒 Profile Access Guard check in priority commands
                # Live reason() check is the only detection source; the stored
                # record is never re-injected as a reason and a renamed user is
                # restored on the first clean message (see sync_block_state).
                if sender_id and not is_global_owner(sender_id):
                    profile_bio = next((getattr(sender, n, None) for n in ("about", "bio", "biography") if getattr(sender, n, None)), None) if sender else None
                    guard_status, profile_reason = access_profile_guard.sync_block_state(
                        sender, sender_id, profile_bio)
                    if guard_status == access_profile_guard.STATUS_BLOCKED:
                        self.logger.log_info(
                            f"PROFILE ACCESS RESTRICTION ACTIVE user_id={sender_id} "
                            f"name={getattr(sender, 'first_name', '')!r} reason={profile_reason!r}"
                        )
                        await access_profile_guard.send_restriction_notice(
                            event, client=self.client, chat_id=chat_id)
                        return
                    if guard_status == access_profile_guard.STATUS_HELD:
                        self.logger.log_info(
                            f"PROFILE ACCESS RESTRICTION HELD user_id={sender_id} "
                            f"reason=profile_unverifiable")
                        return
                    if guard_status == access_profile_guard.STATUS_RESTORED:
                        self.logger.log_info(f"PROFILE ACCESS RESTORED user_id={sender_id}")

                if chat_id is None or not is_active(chat_id):
                    _log_inactive_gate(self, chat_id, text)
                    if (
                        expiry_command(text) is not None
                        and is_global_owner(sender_id)
                    ):
                        await process_incoming_message(event)
                    return
                if is_fast_moderation_command(text):
                    if await handle_fast_moderation_command(
                        self, event, text, sender
                    ):
                        return
                await handle_new_message(self, event)
            except Exception as handler_error:
                import traceback as _tb
                self.logger.log_error(
                    "PRIORITY COMMAND HANDLER CRASHED "
                    f"chat_id={getattr(event, 'chat_id', None)} "
                    f"error={handler_error!r}\n{_tb.format_exc()}"
                )
            finally:
                elapsed_ms = (time.perf_counter() - started_cmd) * 1000
                monitor = getattr(self, "performance_monitor", None)
                if monitor is not None:
                    monitor.record(
                        total_ms=elapsed_ms,
                        chat_id=getattr(event, "chat_id", None),
                        message_id=getattr(
                            getattr(event, "message", None), "id", None
                        ),
                        handler="process_priority_command",
                    )
                # در حالت عادی فقط دستورهای واقعاً کند ثبت می‌شوند؛ حالت
                # debug همان آستانهٔ قبلی ۵۰ms را نگه می‌دارد.
                _timing_threshold_ms = (
                    50 if self.config_manager.get(
                        "debug_message_pipeline", False) else float("inf")
                )
                if elapsed_ms >= _timing_threshold_ms:
                    self.logger.log_info(
                        "HANDLER TIME "
                        f"chat_id={getattr(event, 'chat_id', None)} "
                        f"path=priority handler_ms={elapsed_ms:.1f} "
                        f"text={text!r}"
                    )
                    self.logger.log_info(
                        "TOTAL COMMAND TIME "
                        f"chat_id={getattr(event, 'chat_id', None)} "
                        f"elapsed_ms={elapsed_ms:.1f} text={text!r}"
                    )

        async def process_incoming_message(event):
            started_message_handler = time.perf_counter()
            # === SPAM DEBUG INCOMING — اولین خط NewMessage ===
            try:
                _sd_raw = getattr(getattr(event, 'message', None), 'message', '') or getattr(getattr(event, 'message', None), 'caption', '') or ""
                _sd_chat = getattr(event, 'chat_id', None)
                _sd_mid = getattr(getattr(event, 'message', None), 'id', None)
                _sd_sid_try = getattr(event, 'sender_id', None)
                if _sd_sid_try is None:
                    _sd_sender_obj = getattr(event, 'sender', None)
                    _sd_sid_try = getattr(_sd_sender_obj, 'id', None) if _sd_sender_obj else None
                import hashlib as _sd_hl
                _sd_hash = _sd_hl.md5(str(_sd_raw).encode('utf-8', errors='ignore')).hexdigest()[:8] if _sd_raw else "empty"
                _sd_len = len(str(_sd_raw))
                self.debug_message_log(f"SPAM DEBUG INCOMING chat_id={_sd_chat} message_id={_sd_mid} sender_id={_sd_sid_try} text_hash={_sd_hash} text_length={_sd_len}")
            except Exception as _sd_e:
                try: self.logger.log_error(f"SPAM DEBUG INCOMING failed { _sd_e!r}")
                except: pass
            # === SPAM FLOW TRACE: CORE ENTRY INSTANCE CHECK ===
            try:
                _core_trace_chat = getattr(event, 'chat_id', None)
                _core_trace_msg = getattr(getattr(event, 'message', None), 'id', None)
                self.debug_message_log(
                    f"SPAM FLOW TRACE chat_id={_core_trace_chat} user_id=unknown message_id={_core_trace_msg} stage=CORE_RAW_ENTRY bot_id={id(self)} lock_id={id(getattr(self, 'spam_lock', set()))} lock_size={len(getattr(self, 'spam_lock', set()))} lock_keys={list(getattr(self, 'spam_lock', set()))[:5]!r}"
                )
            except Exception as _core_trace_err:
                self.logger.log_error(f"SPAM FLOW TRACE CORE entry failed { _core_trace_err!r}")
            self.debug_message_log(
                "RAW MESSAGE EVENT RECEIVED "
                f"chat_id={getattr(event, 'chat_id', None)} "
                f"message_id={getattr(getattr(event, 'message', None), 'id', None)} "
                f"event_out={getattr(event, 'out', None)}"
            )
            # ⛑️ نگهبان سراسری هندلر پیام.
            #
            # کل بدنهٔ این تابع بدون try بود؛ هر استثنا در همان خطوط اول
            # (instrument_event، خواندن متن، normalize) توسط splusthon
            # بلعیده می‌شد و پیام بی‌صدا دور ریخته می‌شد، بدون هیچ ردی در
            # لاگ. نتیجه: ربات روشن بود ولی به پیام‌ها جواب نمی‌داد.
            try:
                instrument_event(event, self.logger)
                # Temporary passive trace: record every incoming event before
                # routing/gates so Bot-originated messages cannot disappear
                # silently before message_handler.py.
                _entry_sender = getattr(event, "_bot_cached_sender", None) or getattr(event, "sender", None)
                try:
                    if _entry_sender is None:
                        _entry_sender = await event.get_sender()
                    if _entry_sender is None and getattr(event, "sender_id", None):
                        try:
                            _entry_sender = await self.client.get_entity(event.sender_id)
                        except Exception:
                            pass
                    try:
                        event._bot_cached_sender = _entry_sender
                    except Exception:
                        pass
                    if _entry_sender is not None and is_global_owner(
                        getattr(_entry_sender, "id", None)
                    ):
                        asyncio.create_task(
                            remember_owner_peer(
                                self.client,
                                event=event,
                                sender=_entry_sender,
                                logger=self.logger,
                            ),
                            name="owner-peer:remember",
                        )
                    self.debug_message_log(
                        "BOT EVENT ENTRY DEBUG\n"
                        f"event_out={getattr(event, 'out', None)}\n"
                        f"is_private={getattr(event, 'is_private', None)}\n"
                        f"chat_id={getattr(event, 'chat_id', None)}\n"
                        f"sender_id={getattr(_entry_sender, 'id', None)}\n"
                        f"sender_username={getattr(_entry_sender, 'username', None)!r}\n"
                        f"sender_type={_entry_sender.__class__.__name__ if _entry_sender else 'None'}\n"
                        f"sender_bot={getattr(_entry_sender, 'bot', None)!r}"
                    )
                except Exception as _entry_error:
                    self.logger.log_error(
                        "BOT EVENT ENTRY DEBUG FAILED "
                        f"chat_id={getattr(event, 'chat_id', None)} "
                        f"error={_entry_error!r}"
                    )
                raw_text = event.message.message or ""
                # Profile access guard runs before every command/game handler.
                profile_user = _entry_sender
                command_priority_text = normalize_command_text(raw_text)
                command_priority = command_priority_text in {
                    "راهنما", "لیست بازی", "لیست بازی ها", "لیست بازی‌ها",
                    "سایت بازی", "سایت", "لینک بازی",
                    "لیست ادمین", "لیست ادمینی", "لیست کاربران", "رتبه ها",
                    "رتبه‌ها", "موجودی", "فروشگاه", "انتقال سکه", "قفل", "باز", "سکوت", "رفع سکوت", "آزاد", "اخطار", "اخراج", "بن",
                    "ثبت ادمین", "برکناری ادمین", "لغو ادمین", "سنجاق",
                    "حدس ایموجی", "حدس جمله", "ساخت جمله", "معما", "حدس پرچم",
                    "مین یاب", "بهترین جواب", "نبرد", "بخند یا بباز",
                    "جعبه شانسی", "خون آشام", "خون‌آشام",
                    "فعال", "غیر فعال", "فعال سازی",
                    "ثبت مالک", "لغو مالک", "برکناری مالک",
                    "ثبت گروه", "حذف گروه",
                    "۵ روز", "یک هفته", "دو هفته", "یک ماه",
                }
                self.debug_message_log(
                    "COMMAND PRIORITY CHECK "
                    f"text={raw_text!r} normalized={command_priority_text!r} "
                    f"priority={command_priority}"
                )
                profile_id = getattr(profile_user, "id", None) or getattr(event, "sender_id", None)
                if profile_id and not is_global_owner(profile_id):
                    profile_bio = next((getattr(profile_user, n, None) for n in ("about", "bio", "biography") if getattr(profile_user, n, None)), None) if profile_user else None
                    # SoroushClient does not expose get_full_user; use only
                    # fields present on the received User entity and make the
                    # limitation explicit in runtime logs.
                    self.debug_message_log(
                        "PROFILE GUARD USER INFO\n"
                        f"username={getattr(profile_user, 'username', None)!r}\n"
                        f"name={' '.join(str(x) for x in (getattr(profile_user, 'first_name', None), getattr(profile_user, 'last_name', None)) if x)!r}\n"
                        f"bio={profile_bio!r}"
                    )
                    if profile_bio is None:
                        self.debug_message_log(
                            "PROFILE GUARD BIO UNAVAILABLE "
                            "reason=SoroushClient_User_entity_has_no_about_field"
                        )
                    # 🔒 Profile Access Guard — مسیر پیام‌های معمولی.
                    # همان منبع واحد تصمیم‌گیری که مسیر دستورهای اولویت‌دار
                    # و هندلر استفاده می‌کنند: فقط چک زندهٔ reason() (نام/
                    # یوزرنیم/بیوی *فعلی*) منبع تشخیص است و رکورد ذخیره‌شده
                    # هرگز به‌عنوان دلیل تزریق نمی‌شود. بنابراین کاربری که
                    # نامش را اصلاح کرده، در اولین پیام بعدی رکورد کهنه‌اش
                    # حذف (unblock) و پردازش عادی ادامه می‌یابد؛ نه اینکه
                    # برای همیشه با همان اعلان قدیمی دوباره بلوک شود
                    # (جزئیات: sync_block_state).
                    guard_status, profile_reason = access_profile_guard.sync_block_state(
                        profile_user, profile_id, profile_bio)
                    if guard_status == access_profile_guard.STATUS_BLOCKED:
                        self.logger.log_info(
                            f"PROFILE ACCESS RESTRICTION ACTIVE user_id={profile_id} "
                            f"name={getattr(profile_user, 'first_name', '')!r} reason={profile_reason!r}"
                        )
                        await access_profile_guard.send_restriction_notice(
                            event, client=self.client,
                            chat_id=getattr(event, "chat_id", None))
                        self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_733' chat_id={_sd_chat} message_id={_sd_mid}")
                        return
                    if guard_status == access_profile_guard.STATUS_HELD:
                        self.logger.log_info(
                            f"PROFILE ACCESS RESTRICTION HELD user_id={profile_id} "
                            f"reason=profile_unverifiable")
                        self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_733' chat_id={_sd_chat} message_id={_sd_mid}")
                        return
                    if guard_status == access_profile_guard.STATUS_RESTORED:
                        self.logger.log_info(f"PROFILE ACCESS RESTORED user_id={profile_id}")
                # کاربر ممکن است «اطلاع‌رسانی» را با نیم‌فاصله (ZWNJ) بنویسد — همان
                # املایی که خودِ ربات در پیام‌هایش به کار می‌برد. مقایسهٔ خام آن را
                # رد می‌کرد و دستور بی‌صدا نادیده گرفته می‌شد.
                text = normalize_command_text(raw_text)
                # Mandatory first-stage trace for every event. This must run
                # before any broadcast/private/group condition so a missing
                # command can be localized to event delivery or matching.
                _broadcast_detected = is_broadcast_command(raw_text)
                self.debug_message_log(
                    "PRIVATE COMMAND DEBUG\n"
                    f"text={raw_text!r}\n"
                    f"normalized={text!r}\n"
                    f"is_broadcast_command={_broadcast_detected}"
                )
                if _broadcast_detected:
                    self.logger.log_info(
                        "BROADCAST COMMAND DETECTED "
                        f"text={raw_text!r} normalized={text!r}"
                    )
                # Restore the original reliable private route: do not wait for
                # get_chat(), peer classification, or event.out. A DM is
                # routed using event.is_private and its actual sender exactly
                # as the original broadcast implementation did.
                event_chat_id_hint = getattr(event, "chat_id", None)
                # Positive numeric ids are not sufficient: SPlusthon may use
                # them for channel peers. The early route is only for an
                # explicit private event; unresolved peers are classified
                # strictly after get_chat()/peer resolution below.
                private_event = bool(getattr(event, "is_private", False))
                self.debug_message_log(
                    "PRIVATE BROADCAST DEBUG\n"
                    f"event_is_private={getattr(event, 'is_private', None)}\n"
                    f"chat_id={event_chat_id_hint}\n"
                    f"private_event={private_event}"
                )
                # Owner-first: privacy flags are advisory only for this
                # workflow because the live SPlusthon stream has emitted
                # private owner messages with is_private=False.
                if private_event:
                    private_sender = _entry_sender
                    if private_sender is None:
                        private_sender = await event.get_sender()
                    private_sender_id = getattr(private_sender, "id", None)
                    private_is_owner = is_global_owner(private_sender_id)
                    normalized_trigger_text = normalize_broadcast_trigger(raw_text)
                    matched_trigger = match_broadcast_trigger(raw_text)
                    private_state = get_broadcast_state(private_sender_id)
                    private_trigger = is_broadcast_command(raw_text)
                    self.logger.log_info(
                        "BROADCAST TRIGGER CHECK\n"
                        f"text={raw_text!r}\n"
                        f"normalized_text={normalized_trigger_text!r}\n"
                        f"matched_trigger={matched_trigger!r}\n"
                        f"owner_check={private_is_owner}"
                    )
                    self.debug_message_log(
                        "PRIVATE BROADCAST DEBUG\n"
                        f"user_id={private_sender_id}\n"
                        f"text={raw_text!r}\n"
                        f"matched={private_trigger}\n"
                        "handler_called=False\n"
                        f"is_private={getattr(event, 'is_private', None)}\n"
                        f"owner_check={private_is_owner}"
                    )
                    self.logger.log_info(
                        "PRIVATE OWNER CHECK\n"
                        f"user_id={private_sender_id}\n"
                        f"username={getattr(private_sender, 'username', None)!r}\n"
                        f"is_owner={private_is_owner}\n"
                        f"matched_command={private_trigger}\n"
                        "handler_called=False"
                    )
                    self.logger.log_info(
                        "BROADCAST COMMAND RECEIVED\n"
                        f"owner_id={private_sender_id}\n"
                        f"text={raw_text!r}\n"
                        f"trigger={private_trigger}\n"
                        f"owner_check={private_is_owner}"
                    )
                    # Preserve the original reliable contract: every private
                    # message from the owner is offered to the broadcast
                    # handler. The handler performs its own normalization and
                    # exact trigger/state decision. An outer boolean matcher
                    # must never prevent a valid spelling from reaching it.
                    if private_is_owner and (private_trigger or private_state):
                        handled = await handle_private_broadcast(
                            self, event, private_sender_id, raw_text
                        )
                        self.debug_message_log(
                            "PRIVATE BROADCAST DEBUG\n"
                            f"user_id={private_sender_id}\n"
                            f"text={raw_text!r}\n"
                            f"matched={private_trigger}\n"
                            "handler_called=True\n"
                            f"handled={handled}"
                        )
                        if handled:
                            self.logger.log_info(
                                "BROADCAST READY "
                                f"owner_id={private_sender_id} text={raw_text!r}"
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if handled:' chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        self.logger.log_info(
                            "BROADCAST ROUTE SKIP "
                            f"owner_id={private_sender_id} text={raw_text!r} "
                            "reason=handler_not_broadcast"
                        )

                # BROADCAST TRACE: قبل از هر await ثبت می‌شود تا اگر یکی از
                # فراخوانی‌های بعدی استثنا داد، بدانیم پیام اصلاً رسیده بود.
                _broadcast_words = BROADCAST_COMMAND_WORDS
                if is_broadcast_command(raw_text):
                    try:
                        _owner_cfg = get_owner()
                    except Exception as _owner_error:
                        _owner_cfg = {"error": repr(_owner_error)}
                    self.logger.log_info(
                        "BROADCAST_COMMAND_RECEIVED "
                        f"raw_text={raw_text!r} "
                        f"normalized_text={text!r} "
                        f"event_out={getattr(event, 'out', None)} "
                        f"is_private={getattr(event, 'is_private', None)} "
                        f"event_chat_id={getattr(event, 'chat_id', None)} "
                        f"owner_id_from_config={_owner_cfg} "
                        f"message_id={getattr(event.message, 'id', None)} "
                        f"entity_count={len(getattr(event.message, 'entities', None) or [])}"
                    )
                # get_chat() نیازمند resolve شدن peer است و روی session تازه (کش
                # entity خالی) می‌تواند خطا بدهد. چون هیچ try/except بیرونی وجود
                # ندارد، آن خطا کل handler را بی‌صدا از بین می‌برد و دستور کاربر
                # هرگز اجرا نمی‌شود. اینجا خطا مهار می‌شود تا مسیر ادامه یابد.
                routing_chat = (
                    getattr(event, "_bot_cached_chat", None)
                    or getattr(event, "chat", None)
                    or _resolved_event_peer(event)
                )
                if routing_chat is None:
                    try:
                        routing_chat = await event.get_chat()
                    except Exception as error:
                        self.logger.log_error(
                            "BROADCAST ROUTE ENTER get_chat FAILED "
                            f"text={text!r} error={error!r} -> continuing with peer fallback"
                        )
                try:
                    event._bot_cached_chat = routing_chat
                except Exception:
                    pass

                # وقتی get_chat ناموفق است، نوع چت از خودِ peer رویداد استنتاج
                # می‌شود؛ PeerUser یعنی پیوی. این مسیر به کش entity وابسته نیست.
                peer_is_user = isinstance(
                    getattr(event, "_chat_peer", None), types.PeerUser
                )
                # آخرین fallback: در سروش پلاس شناسهٔ مثبت یعنی کاربر و شناسهٔ منفی
                # یعنی گروه/کانال. فقط وقتی استفاده می‌شود که chat اصلاً resolve نشده.
                event_chat_id = getattr(event, "chat_id", None)
                # On some SPlusthon updates ``event.is_private`` is False and
                # entity resolution can fail for a DM. Only in that fallback
                # case, a positive peer ID identifies a private user chat.
                positive_chat_id = bool(
                    routing_chat is None
                    and isinstance(event_chat_id, int)
                    and event_chat_id > 0
                )
                routing_type = routing_chat.__class__.__name__ if routing_chat is not None else "None"
                routing_type_lower = routing_type.lower()
                # SPlusthon has returned several private-peer class names over
                # its lifetime. Do not rely on one exact ``User`` class.
                routing_is_private_entity = (
                    "user" in routing_type_lower
                    or "private" in routing_type_lower
                    or routing_type_lower in {"peeruser", "inputpeeruser"}
                )
                routing_is_group_entity = any(
                    marker in routing_type_lower
                    for marker in ("group", "channel", "chat")
                )
                is_private_splus = bool(
                    event.is_private
                    or routing_is_private_entity
                    or (peer_is_user and not routing_is_group_entity)
                    or positive_chat_id
                )
                self.debug_message_log(
                    "PRIVATE ROUTE RESOLUTION DEBUG\n"
                    f"event_is_private={getattr(event, 'is_private', None)}\n"
                    f"event_chat_id={event_chat_id}\n"
                    f"chat_type={routing_type}\n"
                    f"peer_is_user={peer_is_user}\n"
                    f"private_route={is_private_splus}"
                )
                _trace_sender = _entry_sender
                if _trace_sender is None:
                    _trace_sender = await event.get_sender()
                _trace_sender_id = getattr(_trace_sender, "id", None)
                _trace_owner_id = get_owner().get("user_id") if isinstance(get_owner(), dict) else None
                _trace_owner = is_global_owner(_trace_sender_id)
                self.debug_message_log(
                    "PRIVATE BROADCAST TRACE "
                    f"event_is_private={getattr(event, 'is_private', None)} "
                    f"chat_type={routing_type} "
                    f"sender_id={_trace_sender_id} "
                    f"owner_id={_trace_owner_id} "
                    f"is_owner={_trace_owner} "
                    f"text={raw_text!r} "
                    f"trigger={is_broadcast_command(raw_text)} "
                    f"handler_called=False "
                    f"private_route={is_private_splus}"
                )
                # Temporary targeted trace for the owner-only expiry command.
                # It is intentionally emitted before the private-route branch
                # so a misclassified SPlusthon DM remains diagnosable.
                if text == "لیست انقضا":
                    message_peer = getattr(getattr(event, "message", None), "peer_id", None)
                    event_peer = getattr(event, "_chat_peer", None)
                    self.logger.log_info(
                        "EXPIRY COMMAND DEBUG\n"
                        f"raw_text={raw_text!r}\n"
                        f"normalized_text={text!r}\n"
                        f"event_type={event.__class__.__module__}.{event.__class__.__name__}\n"
                        f"event_chat_id={event_chat_id!r}\n"
                        f"event_user_id={getattr(event, 'user_id', None)!r}\n"
                        f"event_sender_id={getattr(event, 'sender_id', None)!r}\n"
                        f"event_out={getattr(event, 'out', None)!r}\n"
                        f"event_is_private={getattr(event, 'is_private', None)!r}\n"
                        f"event_peer_type={event_peer.__class__.__name__ if event_peer else 'None'}\n"
                        f"message_peer_type={message_peer.__class__.__name__ if message_peer else 'None'}\n"
                        f"event_chat_type={getattr(event, 'chat', None).__class__.__name__ if getattr(event, 'chat', None) else 'None'}\n"
                        f"get_chat_type={routing_type}\n"
                        f"sender_type={_trace_sender.__class__.__name__ if _trace_sender else 'None'}\n"
                        f"sender_id={_trace_sender_id}\n"
                        f"owner_id={_trace_owner_id}\n"
                        f"is_private={is_private_splus}\n"
                        f"is_global_owner={_trace_owner}"
                    )
                if text in _broadcast_words:
                    self.logger.log_info(
                        "BROADCAST ROUTE CHAT RESOLVED "
                        f"chat_type={routing_type} "
                        f"chat_id={getattr(routing_chat, 'id', None)} "
                        f"private_route={is_private_splus}"
                    )
                is_broadcast_text = text in {"اطلاع رسانی", "تایید", "✅ تایید", "لغو", "❌ لغو"}
                is_name_family_trace_message = (
                    text == "اسم فامیل" or len(text.splitlines()) >= 7
                )
                if is_broadcast_text:
                    self.logger.log_info(
                        "BROADCAST COMMAND RECEIVED "
                        f"text={text!r} event_out={event.out} "
                        f"event_is_private={event.is_private} "
                        f"chat_type={routing_chat.__class__.__name__} "
                        f"private_route={is_private_splus}"
                    )
                # Dedicated private broadcast fast path. It runs before the
                # generic outgoing/self-message guards so SPlusthon variants
                # that mark an incoming DM as event.out cannot swallow the
                # owner's command.
                if is_private_splus:
                    private_sender = await event.get_sender()
                    private_sender_id = getattr(private_sender, "id", None)
                    private_is_owner = is_global_owner(private_sender_id)
                    private_has_state = bool(get_broadcast_state(private_sender_id))
                    private_is_broadcast = is_broadcast_command(text)
                    self.logger.log_info(
                        "BROADCAST PRIVATE ROUTE\n"
                        f"sender_id={private_sender_id}\n"
                        f"sender_username={getattr(private_sender, 'username', None)!r}\n"
                        f"event_out={getattr(event, 'out', None)}\n"
                        f"trigger={private_is_broadcast}\n"
                        f"state_present={private_has_state}\n"
                        f"owner_check={private_is_owner}"
                    )
                    if private_is_owner and (private_is_broadcast or private_has_state):
                        self.logger.log_info(
                            "BROADCAST COMMAND RECEIVED "
                            f"owner_id={private_sender_id} text={text!r}"
                        )
                        handled = await handle_private_broadcast(
                            self, event, private_sender_id, text
                        )
                        if handled:
                            self.logger.log_info(
                                "BROADCAST ROUTE HANDLED "
                                f"owner_id={private_sender_id} text={text!r}"
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if handled:' chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        self.logger.log_error(
                            "BROADCAST ROUTE NOT HANDLED "
                            f"owner_id={private_sender_id} text={text!r}"
                        )

                if (
                    event.out
                    and is_private_splus
                    and event.message.id in getattr(self, "broadcast_bot_message_ids", set())
                ):
                    self.broadcast_bot_message_ids.discard(event.message.id)
                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_990' chat_id={_sd_chat} message_id={_sd_mid}")
                    return

                is_mode_command = text in {"فعال", "غیر فعال"}
                mode_username = None
                if is_mode_command:
                    sender_for_mode = await event.get_sender()
                    sender_username_for_mode = getattr(sender_for_mode, "username", None)
                    try:
                        client_me = await self.client.get_me()
                        client_me_id = getattr(client_me, "id", None)
                        client_me_username = getattr(client_me, "username", None)
                    except Exception as error:
                        client_me_id = None
                        client_me_username = None
                        self.logger.log_error(f"OWNER RUNTIME TRACE get_me error: {error}")

                    normalized_sender = normalize_username(sender_username_for_mode)
                    normalized_client = normalize_username(client_me_username)
                    global_owner_config = get_owner()
                    is_global_owner_sender = is_global_owner(getattr(sender_for_mode, "id", None))
                    is_global_owner_client = is_global_owner(client_me_id)
                    mode_username = (
                        client_me_username if event.out else sender_username_for_mode
                    )
                    self.logger.log_info(
                        "OWNER RUNTIME TRACE\n"
                        f"raw_text={raw_text!r}\n"
                        f"event_out={event.out}\n"
                        f"sender_id={getattr(sender_for_mode, 'id', None)}\n"
                        f"sender_username={sender_username_for_mode!r}\n"
                        f"client_me_id={client_me_id}\n"
                        f"client_me_username={client_me_username!r}\n"
                        f"normalized_sender={normalized_sender!r}\n"
                        f"normalized_client={normalized_client!r}\n"
                        f"global_owner_config={global_owner_config!r}\n"
                        f"is_global_owner_sender={is_global_owner_sender}\n"
                        f"is_global_owner_client={is_global_owner_client}"
                    )
                    is_global_owner_for_mode = (
                        is_global_owner_client if event.out else is_global_owner_sender
                    )
                    if event.out and not is_global_owner_for_mode:
                        self.logger.log_info("OWNER RUNTIME TRACE STOP: event.out gate")
                        self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if event.out and not is_global_owner_for' chat_id={_sd_chat} message_id={_sd_mid}")
                        return
                elif event.out:
                    if is_private_splus:
                        private_sender = await event.get_sender()
                        if event.out:
                            private_me = await self.client.get_me()
                            private_owner_id = getattr(private_me, "id", None)
                        else:
                            private_owner_id = getattr(private_sender, "id", None)
                        is_broadcast_trigger = text == "اطلاع رسانی"
                        has_broadcast_session = bool(
                            get_broadcast_state(private_owner_id)
                        )
                        if (
                            is_global_owner(private_owner_id)
                            and (is_broadcast_trigger or has_broadcast_session)
                        ):
                            pass
                        # پیام‌های خروجی عادی باید به handler برسند؛ این ربات
                        # userbot است و فرمان مالک نیز event.out=True دارد.
                    # پاسخ‌های خود ربات فرمان نیستند و در handler واکنش تازه‌ای
                    # تولید نمی‌کنند؛ پاسخ‌های broadcast هم با message id جدا می‌شوند.

                # MASTER GROUP MODE GATE: every incoming group message passes here first.
                if not is_private_splus:
                    chat_lock = routing_chat
                    if chat_lock is None:
                        try:
                            chat_lock = await event.get_chat()
                        except Exception as error:
                            chat_lock = None
                            self.logger.log_error(
                                f"GROUP GATE get_chat FAILED error={error!r}"
                            )
                    lock_id = (
                        getattr(chat_lock, "id", None)
                        or getattr(event, "chat_id", None)
                        or getattr(chat_lock, "channel_id", None)
                        or getattr(chat_lock, "chat_id", None)
                    )
                    sender_lock = _entry_sender or _trace_sender
                    if sender_lock is None:
                        try:
                            sender_lock = await event.get_sender()
                        except Exception as error:
                            sender_lock = None
                            self.logger.log_error(
                                f"GROUP GATE get_sender FAILED error={error!r}"
                            )
                    sender_id = getattr(sender_lock, "id", None)
                    if lock_id is None:
                        # چت resolve نشده است؛ is_active(None) همیشه False است و
                        # پیام بی‌صدا دور ریخته می‌شود. این حالت باید دیده شود.
                        self.logger.log_error(
                            "GROUP GATE UNRESOLVED CHAT "
                            f"text={text[:40]!r} event_chat_id={event_chat_id} "
                            f"event_is_private={event.is_private} -> message dropped"
                        )
                    group_is_active = is_active(lock_id)
                    sender_username = (
                        mode_username if is_mode_command else getattr(
                            sender_lock, "username", None
                        )
                    )
                    normalized_username = normalize_username(sender_username)
                    can_change_group_mode = is_global_owner(sender_id)
                    is_enable_command = text == "فعال"
                    is_disable_command = text == "غیر فعال"

                    if is_enable_command or is_disable_command:
                        self.logger.log_info(
                            "GROUP MODE DEBUG "
                            f"chat_id={lock_id} sender_id={sender_id} "
                            f"sender_username={sender_username!r} "
                            f"normalized_username={normalized_username!r} "
                            f"text={text!r} disabled_before={not group_is_active} "
                            f"global_owner_check={can_change_group_mode} "
                            f"mode_owner_check={can_change_group_mode} "
                            f"enable_match={is_enable_command} "
                            f"disable_match={is_disable_command}"
                        )

                    if not group_is_active:
                        if is_name_family_trace_message:
                            self.logger.log_info(
                                "NAME FAMILY TRACE CORE_BLOCK "
                                f"reason=group_inactive chat_id={lock_id} "
                                f"message_id={getattr(event.message, 'id', None)}"
                            )
                        if is_enable_command and can_change_group_mode:
                            title = getattr(chat_lock, "title", "")
                            activate_group(lock_id, title)
                            await send_activation_message(
                                self, event, lock_id, title
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1119' chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        # ⏳ گروهی که با پایان مهلت بسته شده باید بتواند دوباره
                        # باز شود. بدون این استثنا، سه دستور انقضا هرگز به
                        # هندلر نمی‌رسیدند و گروه برای همیشه قفل می‌ماند.
                        if (
                            expiry_command(text) is not None
                            and can_change_group_mode
                        ):
                            self.logger.log_info(
                                "GROUP EXPIRY REACTIVATION ALLOWED "
                                f"chat_id={lock_id} sender_id={sender_id} "
                                f"command={text!r}"
                            )
                            title = getattr(chat_lock, "title", "")
                            activate_group(lock_id, title)
                        else:
                            _log_inactive_gate(self, lock_id, text)
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1135' chat_id={_sd_chat} message_id={_sd_mid}")
                            return

                    if is_disable_command:
                        if can_change_group_mode:
                            title = getattr(chat_lock, "title", "")
                            deactivate_group(lock_id, title)
                            for task in self.group_timer_tasks.pop(lock_id, set()):
                                task.cancel()
                            # اسم فامیل صف تایمر مستقل خودش را دارد و باید
                            # جداگانه و تمیز بسته شود.
                            cancel_name_family_round(lock_id)
                            await event.reply(
                                f"🦊 روباه در گروه «{title}» غیر فعال شد ❌"
                            )
                        self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1149' chat_id={_sd_chat} message_id={_sd_mid}")
                        return

                # آزاد کردن کاربر محروم شده
                if not is_private_splus and (text == "آزاد" or text.startswith("آزاد ") or text.startswith("آزاد@")):
                    try:
                        target_username_arg = None
                        if text != "آزاد":
                            raw_arg = text[4:].strip()
                            if raw_arg.startswith("@"):
                                raw_arg = raw_arg[1:].strip()
                            if raw_arg:
                                target_username_arg = raw_arg.split()[0].lstrip("@").strip()
                            if target_username_arg is not None:
                                if target_username_arg.isdigit():
                                    await event.reply("❌ لطفاً از نام کاربری استفاده کنید، آیدی عددی پشتیبانی نمی‌شود")
                                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='azad_digit' chat_id={_sd_chat} message_id={_sd_mid}")
                                    return
                                if not target_username_arg:
                                    await event.reply("❌ نام کاربری مشخص نشده است")
                                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='azad_empty' chat_id={_sd_chat} message_id={_sd_mid}")
                                    return
                                import re as _re_azad_core
                                if not _re_azad_core.match(r"^[A-Za-z0-9_]{4,32}$", target_username_arg):
                                    await event.reply(f"❌ نام کاربری نامعتبر است: @{target_username_arg}")
                                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='azad_invalid' chat_id={_sd_chat} message_id={_sd_mid}")
                                    return

                        user = None
                        username_for_unban = None
                        if target_username_arg:
                            try:
                                try:
                                    user = await self.client.get_entity(target_username_arg)
                                except Exception as _e1:
                                    try:
                                        user = await self.client.get_entity(f"@{target_username_arg}")
                                    except Exception:
                                        raise _e1
                            except Exception as e:
                                self.logger.log_error(f"AZAD RESOLVE FAILED username=@{target_username_arg} error={e!r}")
                                await event.reply(f"❌ کاربر با نام کاربری @{target_username_arg} پیدا نشد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='azad_not_found' chat_id={_sd_chat} message_id={_sd_mid}")
                                return
                            if not user or not getattr(user, "id", None):
                                await event.reply(f"❌ کاربر با نام کاربری @{target_username_arg} پیدا نشد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='azad_not_found2' chat_id={_sd_chat} message_id={_sd_mid}")
                                return
                            username_for_unban = getattr(user, "username", None) or target_username_arg
                        else:
                            if not event.reply_to:
                                await event.reply("❌ باید روی پیام کاربر ریپلای کنید یا به صورت «آزاد @username» بنویسید")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not event.reply_to:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return

                            reply_msg = await self.client.get_messages(
                                event.chat_id,
                                ids=event.reply_to.reply_to_msg_id
                            )

                            user = await reply_msg.get_sender() if reply_msg else None
                            if not user:
                                await event.reply("❌ کاربر پیدا نشد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not user:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return
                            username_for_unban = getattr(user, "username", None)

                        # برای جلوگیری از بسته شدن متغیر user در lambda، مقدار را کپی می‌کنیم
                        _azad_user_id = user.id
                        _azad_username = username_for_unban
                        _azad_user_obj = user

                        async def unban_succeeded(_result, _u=_azad_user_obj):
                            self.tracker.banned_users.pop(
                                f"{event.chat_id}:{_u.id}", None
                            )
                            self.clear_released_user_state(event.chat_id, _u.id)
                            self.spammer_messages.pop(_u.id, None)
                            self.logger.log_info(
                                f"UNBAN COMPLETE user_id={_u.id} removed successfully"
                            )
                            await event.reply("♻️ کاربر آزاد شد")

                        async def unban_failed(_error):
                            await event.reply("❌ آزاد کردن انجام نشد")

                        self.moderation_queue.enqueue(
                            event.chat_id,
                            "unban",
                            user_id=_azad_user_id,
                            timeout_seconds=20,
                            operation=lambda uid=_azad_user_id, uname=_azad_username: self.admin_actions.unban_user(
                                event.chat_id, uid, uname
                            ),
                            on_success=unban_succeeded,
                            on_failure=unban_failed,
                        )

                    except Exception as e:
                        await event.reply(f"❌ خطا در آزاد کردن: {e}")
                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1196' chat_id={_sd_chat} message_id={_sd_mid}")
                    return



                  # پیوی فقط دستور صفر کردن تخلف
                if is_private_splus:
                    text = normalize_command_text(
                        event.message.message or ""
                    )
                    # Use the same normalization as the broadcast handler;
                    # otherwise ZWNJ/Arabic spelling variants never reach
                    # the notification workflow.
                    _is_broadcast_word = is_broadcast_command(text)
                    if _is_broadcast_word:
                        self.logger.log_info(
                            f"BROADCAST ROUTE PRIVATE BRANCH text={text!r}"
                        )
                    try:
                        sender = await event.get_sender()
                    except Exception as error:
                        self.logger.log_error(
                            f"BROADCAST OWNER CHECK get_sender FAILED error={error!r}"
                        )
                        raise
                    # For a received private message, authorization must use
                    # the actual sender. Some SPlusthon builds expose an
                    # incoming DM with event.out=True; using get_me() here
                    # would authorize the fox account instead of the owner and
                    # silently stop the notification workflow.
                    sender_id = getattr(sender, "id", None)
                    _owner_ok = is_global_owner(sender_id)
                    if _is_broadcast_word or _owner_ok:
                        self.logger.log_info(
                            "BROADCAST OWNER CHECK "
                            f"sender_id={sender_id} "
                            f"sender_username={getattr(sender, 'username', None)!r} "
                            f"event_out={event.out} "
                            f"configured_owner={get_owner()!r} "
                            f"is_global_owner={_owner_ok}"
                        )
                    if not _owner_ok and _is_broadcast_word:
                        self.logger.log_info(
                            "BROADCAST ROUTE STOP reason=not_global_owner "
                            f"sender_id={sender_id}"
                        )

                    # گزارش انقضا یک فرمان خصوصیِ مستقل است: تنها مالک
                    # اصلی به آن دسترسی دارد و هرگز وارد مسیر گروه/بازی نمی‌شود.
                    if text == "لیست انقضا":
                        if _owner_ok:
                            try:
                                await event.reply(build_expiry_report(self.logger))
                                self.logger.log_info(
                                    "EXPIRY REPORT SENT authorized=True"
                                )
                            except Exception as error:
                                self.logger.log_error(
                                    f"EXPIRY REPORT SEND FAILED authorized=True error={error!r}"
                                )
                        else:
                            self.logger.log_info(
                                "EXPIRY REPORT DENIED reason=not_global_owner"
                            )
                        return

                    if _owner_ok:
                        self.logger.log_info(
                            "BROADCAST COMMAND RECEIVED "
                            f"owner_id={sender_id} text={text!r} event_out={event.out}"
                        )
                        if await handle_private_broadcast(self, event, sender_id, text):
                            self.logger.log_info(
                                f"BROADCAST ROUTE HANDLED text={text!r}"
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if await handle_private_broadcast(self, ' chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        if _is_broadcast_word:
                            self.logger.log_info(
                                "BROADCAST ROUTE NOT HANDLED "
                                f"text={text!r} (handler returned False)"
                            )

                    if "صفر" in text:
                        sender = await event.get_sender()
                        if not is_global_owner(getattr(sender, "id", None)):
                            await event.reply(
                                "❌ فقط مالک اصلی ربات اجازه استفاده از این دستور را دارد"
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason=core_not_global_owner chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        try:
                            import re
                            from modules.group_storage import load_groups

                            m = re.search(r"@([A-Za-z0-9_]+)", text)
                            if not m:
                                await event.reply("❌ آیدی کاربر پیدا نشد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not m:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return

                            username = m.group(1)

                            groups = load_groups()
                            if not groups:
                                await event.reply("❌ هیچ گروهی ثبت نشده")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not groups:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return

                            import json

                            with open("logs/user_map.json", "r", encoding="utf-8") as f:
                                user_map = json.load(f)

                            user_id = None

                            for gid, users in user_map.items():
                                for uname, uid in users.items():
                                    if str(uname).lower() == username.lower():
                                        user_id = int(uid)
                                        break
                                if user_id:
                                    break

                            if not user_id:
                                await event.reply("❌ کاربر در لیست ثبت شده پیدا نشد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not user_id:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return

                            reset_groups = []
                            all_counts = self.tracker.get_all_counts()

                            for gid, users in all_counts.items():
                                if str(user_id) in users or user_id in users:
                                    self.tracker.reset_count(int(gid), user_id)
                                    reset_groups.append(gid)

                                    try:
                                        await self.client.send_message(
                                            int(gid),
                                            f"✅ تخلفات @{username} صفر شد"
                                        )
                                    except Exception as send_err:
                                        self.logger.log_error(
                                            f"خطای ارسال پیام صفر کردن در گروه {gid}: {send_err}"
                                        )

                            if not reset_groups:
                                await event.reply("❌ این کاربر هیچ تخلف ثبت شده‌ای ندارد")
                                self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='if not reset_groups:' chat_id={_sd_chat} message_id={_sd_mid}")
                                return

                            await event.reply("✅ انجام شد")

                        except Exception as e:
                            self.logger.log_error(
                                f"خطای صفر کردن از پیوی: {e}"
                            )
                        self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1328' chat_id={_sd_chat} message_id={_sd_mid}")
                        return

                    # پیام خصوصی پس از route اختصاصی هرگز وارد handler گروهی نمی‌شود.
                    self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1331' chat_id={_sd_chat} message_id={_sd_mid}")
                    return

            
                    # اجرای دستورات مدیریتی
                    if text.startswith(("!", "/", ".")):
                        try:
                            sender = await event.get_sender()
                            await handle_admin_commands(
                                self,
                                event,
                                text,
                                getattr(sender, "id", 0),
                                event.chat_id
                            )
                            self.debug_message_log(f"SPAM DEBUG EARLY RETURN reason='core_line_1345' chat_id={_sd_chat} message_id={_sd_mid}")
                            return
                        except Exception as e:
                            self.logger.log_error(f"خطای اجرای دستور مدیر: {e}")

                started = time.perf_counter()
                if is_name_family_trace_message:
                    self.logger.log_info(
                        "NAME FAMILY TRACE CORE_DISPATCH "
                        f"chat_id={event.chat_id} message_id={getattr(event.message, 'id', None)} "
                        f"line_count={len(text.splitlines())}"
                    )
                await handle_new_message(self, event)
                elapsed = time.perf_counter() - started
                if self.config_manager.get("debug_message_pipeline", False) and elapsed >= 0.25:
                    # ``started`` از time.perf_counter می‌آمد که یک ساعتِ
                    # monotonic دلخواه است (مثلاً ثانیه‌های از بوت) و در لاگ
                    # به‌صورت «receive=363650» گمراه‌کننده دیده می‌شد. فقط
                    # مدتِ واقعی پردازش و شناسهٔ پیام گزارش می‌شود.
                    self.logger.log_info(
                        "MESSAGE PROCESS TIME "
                        f"total={elapsed:.4f}s "
                        f"message_id={getattr(getattr(event, 'message', None), 'id', None)} "
                        f"chat_id={event.chat_id} text={text!r}"
                    )
            except Exception as handler_error:
                import traceback as _tb
                self.logger.log_error(
                    "MESSAGE HANDLER CRASHED "
                    f"chat_id={getattr(event, 'chat_id', None)} "
                    f"error={handler_error!r}\n{_tb.format_exc()}"
                )
            finally:
                total_message_ms = (
                    time.perf_counter() - started_message_handler
                ) * 1000
                monitor = getattr(self, "performance_monitor", None)
                if monitor is not None:
                    handler_name = "process_incoming_message"
                    stage_result = getattr(
                        event, "_bot_performance_result", None
                    )
                    if isinstance(stage_result, dict):
                        slowest_stage = stage_result.get("slowest_stage")
                        if slowest_stage:
                            handler_name += f":{str(slowest_stage).lower()}"
                    monitor.record(
                        total_ms=total_message_ms,
                        chat_id=getattr(event, "chat_id", None),
                        message_id=getattr(
                            getattr(event, "message", None), "id", None
                        ),
                        handler=handler_name,
                    )


        # ── minimal entry gate: one processing per (chat_id, message_id) ──
        # The same group update can be handed to this handler twice
        # (NewMessage then MessageEdited with the same id, or a replay).
        # Only the first delivery may enter the pipeline; repeats inside the
        # short TTL are dropped here, before any routing/queueing. Private
        # chats and different messages are untouched, and a real later edit
        # of the same message (after the TTL) is still processed.
        from collections import OrderedDict as _entry_od
        import time as _entry_time
        _entry_seen = _entry_od()
        _entry_ttl_s = 5.0
        _entry_max = 4096

        def _entry_new(chat_id, message_id):
            now = _entry_time.monotonic()
            cutoff = now - _entry_ttl_s
            while _entry_seen:
                _oldest_key, _oldest_t = next(iter(_entry_seen.items()))
                if len(_entry_seen) <= _entry_max and _oldest_t >= cutoff:
                    break
                _entry_seen.popitem(last=False)
            key = (chat_id, message_id)
            if key in _entry_seen:
                return False
            _entry_seen[key] = now
            return True

        @self.client.on(events.NewMessage())
        @self.client.on(events.MessageEdited())
        async def new_message_handler(event):
            """Light-detect first, then enqueue heavy work.

            Returning immediately lets SPlusthon keep delivering other chats
            while this chat's worker processes its own queue.
            """
            try:
                _last_event_at[0] = time.monotonic()
            except Exception:
                pass
            # Entry gate: the same group message may arrive twice (NewMessage
            # then MessageEdited / replay); only the first delivery proceeds.
            try:
                if not getattr(event, "is_private", False):
                    _g_chat = getattr(event, "chat_id", None)
                    _g_msg = getattr(getattr(event, "message", None), "id", None)
                    if _g_chat is not None and _g_msg is not None and not _entry_new(_g_chat, _g_msg):
                        return
            except Exception:
                pass
            try:
                if await try_handle_private_start(self, event):
                    return
            except Exception as private_start_error:
                self.logger.log_error(
                    "PRIVATE START FAILED "
                    f"error={private_start_error!r}"
                )
            raw_text = ""
            try:
                message = getattr(event, "message", None)
                raw_text = (
                    getattr(message, "message", None)
                    or getattr(message, "caption", None)
                    or ""
                ) if message is not None else ""
            except Exception:
                raw_text = ""
            chat_id = getattr(event, "chat_id", None)
            priority, kind = classify_priority(raw_text, event)

            # فرمان‌های کاربر در نسخهٔ اولیه مستقیماً از همان کلاینت اصلی
            # اجرا می‌شدند. عبور آن‌ها از ingest → GroupDispatcher → صف
            # ارسال باعث شد در عمل بعضی updateهای userbot فقط moderation را
            # اجرا کنند ولی به «راهنما» و بازی‌ها نرسند. فرمان را دوباره روی
            # مسیر مستقیم و تک‌کلاینتی اجرا کن؛ این مسیر reply را هم مستقیم
            # با همان self.client می‌فرستد.
            if kind in {"admin", "command"}:
                await process_priority_command(event)
                return

            try:
                decision = ingest_event(self, event)
            except Exception:
                decision = None
            if decision is not None and decision.skip_heavy:
                return
            # فقط ترافیک عادی/ضداسپم در صف جدا می‌ماند تا موج اسپم event
            # loop را اشغال نکند.
            try:
                if getattr(self, "outgoing_sender", None) is not None:
                    install_event_wrapper(event, self.outgoing_sender)
            except Exception:
                pass
            self.group_dispatcher.submit(
                chat_id,
                lambda ev=event: process_incoming_message(ev),
                priority=priority,
                kind=kind,
                on_overflow=lambda ev=event: self._overflow_message(ev),
            )

        register_private_handlers(self)

        # ⏰ Watchdog: اگر ۵ دقیقه هیچ پیامی نیامد، هشدار در ترمینال —
        # پروس زنده است ولی چیزی نمی‌بیند (اجرای همزمان دو instance
        # با همان session، یا قطع شبکه/MTProto).
        _last_event_at = [time.monotonic()]

        async def _bot_watchdog():
            while True:
                await asyncio.sleep(30)
                try:
                    idle = time.monotonic() - _last_event_at[0]
                    if idle >= 300:
                        print(
                            "⏰ BOT WATCHDOG: no incoming message for "
                            f"{int(idle)}s — check another running bot "
                            "instance with the same session "
                            "(ps aux | grep python) or network"
                        )
                        _last_event_at[0] = time.monotonic()
                except Exception:
                    pass

        try:
            asyncio.create_task(_bot_watchdog(), name="bot-watchdog")
        except Exception:
            pass

        # ⛑️ حلقهٔ اصلی: مالکِ بازسازی، supervisor است (با client_factory
        # که یک SoroushClient کاملاً جدید با سشن تازه می‌سازد و self.client
        # را عوض می‌کند). این حلقه فقط روی self.clientِ فعلی منتظر قطع شدن
        # می‌ماند؛ بعد از بازسازی، self.client توسط supervisor عوض شده و
        # حلقه روی کلاینتِ جدید ادامه می‌یابد.
        while True:
            try:
                # فقط وقتی «ربات فعال شد» نمایش داده می‌شود که اتصالِ فعلی
                # واقعاً سالم باشد: WebSocket وصل، یک RPC آزمایشی موفق، و
                # Receive Loop فعال.
                supervisor = getattr(self, "connection_supervisor", None)
                if supervisor is not None and await supervisor.verify():
                    print("✅ ربات فعال شد و منتظر پیام است")
                elif supervisor is None:
                    print("✅ ربات فعال شد و منتظر پیام است")
                await self.client.run_until_disconnected()
                raise ConnectionError("SPlusthon connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.log_error(
                    "SPLUS CONNECTION LOST "
                    f"reason={error!r} waiting for supervisor rebuild"
                )
                # درخواست‌های معلق را آزاد کن تا تسک‌های در انتظار، برای
                # همیشه بلاک نمانند.
                try:
                    freed = connection_guard.cancel_pending_requests(
                        self.client, f"reconnect: {error!r}"
                    )
                    if freed:
                        self.logger.log_info(
                            f"SPLUS CONNECTION LOST freed {freed} pending request(s)"
                        )
                except Exception:
                    pass
                # اگر supervisor هنوز بازسازی نکرده، اینجا خودمان rebuild را
                # صدا می‌زنیم تا قطعیِ پیام و RPC همگی آزاد شوند و کلاینتِ
                # تازه ساخته شود. rebuild خودش reentrancy-guard دارد.
                supervisor = getattr(self, "connection_supervisor", None)
                if supervisor is not None:
                    try:
                        ok = await supervisor.rebuild(
                            f"run_loop: {error!r}"
                        )
                        if ok:
                            self.logger.log_info(
                                "SPLUS RECONNECT SUCCESS (full client rebuild)"
                            )
                            continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as rebuild_error:
                        self.logger.log_error(
                            f"SPLUS RECONNECT FAILED: {rebuild_error!r}"
                        )
                    # rebuild False یعنی supervisor همین حالا در حالِ بازسازی
                    # است؛ منتظر می‌مانیم تا self.client به کلاینتِ جدیدِ
                    # سالم تغییر کند یا مهلت تمام شود.
                    old = self.client
                    for _ in range(60):  # حداکثر ~۶۰ ثانیه
                        await asyncio.sleep(1)
                        if self.client is not old:
                            break
                        is_conn = getattr(self.client, "is_connected", None)
                        if callable(is_conn) and is_conn():
                            break
                    continue
                # در غیر این صورت (بدون supervisor) یک استراحت کوتاه و تلاش
                # مجددِ ساده روی همان کلاینت.
                await asyncio.sleep(10)


    # ---------- SPAM HISTORY STORAGE ----------
    async def remember_spam_message(self, user_id, message_id):
        try:
            if not hasattr(self, "spammer_messages"):
                self.spammer_messages = {}

            if user_id not in self.spammer_messages:
                self.spammer_messages[user_id] = []

            self.spammer_messages[user_id].append(message_id)
            self._spammer_messages_touched[user_id] = self._state_now()

        except Exception as e:
            print("remember spam error:", e)


    async def delete_all_spam_messages(self, user_id):
        try:
            ids = []

            if hasattr(self, "spammer_messages"):
                ids = list(self.spammer_messages.get(user_id, []))

            if ids:
                await self.client.delete_messages(ids)

            if hasattr(self, "spammer_messages"):
                self.spammer_messages.pop(user_id, None)

        except Exception as e:
            print("delete spam error:", e)
