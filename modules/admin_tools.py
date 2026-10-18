"""🔐 ابزارهای مدیریتی جدید — لاگ مدیریتی + پاکسازی خودکار + کمکی‌ها.

این ماژول کاملاً مستقل است و فقط از سیستم‌های موجود (admin_storage،
owner_check، group_actions) استفاده می‌کند؛ چیزی از معماری قبلی را تغییر
نمی‌دهد.

دو دادهٔ ماندگار دارد:
  - ``config/admin_log.json``   → لاگِ اقداماتِ مدیریتی به تفکیکِ گروه.
  - ``config/auto_cleanup.json`` → تنظیماتِ پاکسازیِ خودکار به تفکیکِ گروه.

قانونِ حریم خصوصی: در هیچ خروجیِ قابلِ مشاهده، شناسهٔ عددیِ کاربر
نمایش داده نمی‌شود؛ همیشه از @username یا نامِ نمایشی یا «کاربر ناشناس»
استفاده می‌شود.
"""
import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from modules.runtime_paths import CONFIG_DIR
from modules import runtime_db
from modules.atomic_write import write_json
from modules import free_tier

# منبعِ مرکزیِ زمان و timezone پروژه (تهران).
from modules.time_utils import TEHRAN, now_local

# نامِ داخلیِ هم‌نامِ قبلی برای سازگاری با ارجاع‌های موجود و تست‌ها.
_TEHRAN = TEHRAN

from modules.owner_check import is_global_owner
from modules.admin_storage import is_admin
from modules.group_storage import get_group_owner
from modules.user_display import format_user
from modules.group_id import normalize_group_id

_BASE = CONFIG_DIR
_ADMIN_LOG_FILE = _BASE / "admin_log.json"
_CLEANUP_FILE = _BASE / "auto_cleanup.json"

# حداکثر تعداد لاگِ نگه‌داشته‌شده برای هر گروه (تا فایل بی‌نهایت رشد نکند).
MAX_LOG_PER_GROUP = 200
# لاگ فقط برای ۲۴ ساعت نگه داشته می‌شود؛ قدیمی‌ترها خودکار حذف می‌شوند.
LOG_TTL_SECONDS = 24 * 60 * 60
_USE_SQLITE_LOG = runtime_db.SQLITE_ENABLED


# ---------------------------------------------------------------------------
#  نمایشِ امنِ کاربر (هرگز شناسهٔ عددی)
# ---------------------------------------------------------------------------
def display_name(user):
    """نمایشِ عمومیِ کاربر با اولویت username و بدون ID عددی."""
    return format_user(user)


def has_admin_permission(chat_id, user_id, username=None):
    """مالک اصلی ربات، مالک گروه، یا ادمینِ ثبت‌شدهٔ گروه."""
    if is_global_owner(user_id):
        return True
    owner = get_group_owner(chat_id)
    if owner is not None and str(user_id) == str(owner):
        return True
    return is_admin(chat_id, user_id, username)


def has_zero_permission(chat_id, user_id):
    """«صفر» فقط برای مالک اصلی ربات و مالک گروه؛ نه ادمینِ عادی."""
    if is_global_owner(user_id):
        return True
    owner = get_group_owner(chat_id)
    return owner is not None and str(user_id) == str(owner)


# ---------------------------------------------------------------------------
#  لاگ مدیریتی — ماندگار، به تفکیک گروه
#
# ⚡️ کش + نوشتن غیرمسدودکننده: قبلاً «هر» اقدام مدیریتی (بن/سکوت/اخطار/
# حذف) فایل چند صد کیلوبایتی را می‌خواند و با indent دوباره همگام روی
# حلقهٔ رویداد می‌نوشت؛ در طوفان مجازات‌ها همین، ربات را تکه‌تکه بلاک
# می‌کرد و با رشد فایل در طول روز بدتر می‌شد. حالا:
#   - خواندن با کش mtime (مثل admin_storage)
#   - serialize فشرده و نوشتن اتمیک در نخ نویسندهٔ تک‌نخی (FIFO)
# منطق لاگ/TTL هیچ تغییری نکرده است.
# ---------------------------------------------------------------------------
import os as _os
import tempfile as _tempfile
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor

_ADMIN_LOG_WRITER = _ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="admin-log-save")
_admin_log_cache = None
_admin_log_mtime = None
# تا وقتی نوشتنی معلق است کش مرجع است (جلوگیری از بازخوانی دیسک عقب‌مانده).
_admin_log_pending_writes = 0


def _admin_log_file_mtime():
    try:
        return _ADMIN_LOG_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _load_admin_log():
    global _admin_log_cache, _admin_log_mtime
    if _admin_log_cache is not None and _admin_log_pending_writes > 0:
        return _admin_log_cache
    mtime = _admin_log_file_mtime()
    if _admin_log_cache is not None and mtime == _admin_log_mtime:
        return _admin_log_cache
    try:
        if _ADMIN_LOG_FILE.exists():
            data = json.loads(_ADMIN_LOG_FILE.read_text(encoding="utf-8"))
            _admin_log_cache = data if isinstance(data, dict) else {}
        else:
            _admin_log_cache = {}
    except (OSError, ValueError):
        _admin_log_cache = {}
    _admin_log_mtime = mtime
    return _admin_log_cache


def _write_admin_log_payload(payload):
    """نوشتن اتمیک؛ فقط داخل نخ نویسنده اجرا می‌شود."""
    global _admin_log_mtime, _admin_log_pending_writes
    temp_path = None
    try:
        _BASE.mkdir(parents=True, exist_ok=True)
        handle, temp_path = _tempfile.mkstemp(
            dir=str(_BASE), suffix=".tmp")
        with _os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        _os.replace(temp_path, _ADMIN_LOG_FILE)
        temp_path = None
        _admin_log_mtime = _admin_log_file_mtime()
    except OSError:
        if temp_path is not None:
            try:
                _os.unlink(temp_path)
            except OSError:
                pass
    finally:
        _admin_log_pending_writes = max(0, _admin_log_pending_writes - 1)


def _save_admin_log(data):
    global _admin_log_cache, _admin_log_pending_writes
    _admin_log_cache = data
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    _admin_log_pending_writes += 1
    try:
        _ADMIN_LOG_WRITER.submit(_write_admin_log_payload, payload)
    except Exception:
        _write_admin_log_payload(payload)


def _prune_log(data):
    """لاگ‌های قدیمی‌تر از ۲۴ ساعت را از همهٔ گروه‌ها حذف و ذخیره می‌کند.

    برمی‌گرداند True اگر چیزی حذف شده باشد.
    """
    now = time.time()
    changed = False
    for key in list(data.keys()):
        bucket = data[key]
        if not isinstance(bucket, list):
            data.pop(key, None)
            changed = True
            continue
        kept = []
        for e in bucket:
            ts = e.get("_ts", 0)
            if ts and (now - ts) < LOG_TTL_SECONDS:
                kept.append(e)
            else:
                changed = True
        if kept:
            data[key] = kept
        else:
            data.pop(key, None)
            changed = True
    return changed


def _ensure_admin_log_sqlite():
    if not _USE_SQLITE_LOG:
        return
    marker = "admin_log_json_import_v1"
    if runtime_db.meta_get(marker):
        return
    existing = runtime_db.query_one("SELECT COUNT(*) FROM admin_events")[0]
    if existing:
        runtime_db.meta_set(marker, "existing-db")
        return
    data = _load_admin_log()
    cutoff = time.time() - LOG_TTL_SECONDS
    with runtime_db.transaction() as conn:
        for group_id, entries in data.items():
            if not isinstance(entries, list):
                continue
            for entry in entries[-MAX_LOG_PER_GROUP:]:
                if not isinstance(entry, dict):
                    continue
                try:
                    event_ts = float(entry.get("_ts", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if event_ts < cutoff:
                    continue
                conn.execute(
                    "INSERT INTO admin_events(group_id,actor_id,actor,action,"
                    "target,note,event_time,event_ts) VALUES(?,?,?,?,?,?,?,?)",
                    (str(group_id), entry.get("actor_id"),
                     str(entry.get("actor") or "کاربر ناشناس"),
                     str(entry.get("action") or ""), entry.get("target"),
                     str(entry.get("note") or ""),
                     str(entry.get("time") or ""), event_ts),
                )
        conn.execute(
            "INSERT OR REPLACE INTO storage_meta(key,value) VALUES(?,?)",
            (marker, "ok"),
        )


def _sqlite_log_entry(row):
    return {
        "time": row["event_time"], "_ts": float(row["event_ts"]),
        "actor_id": row["actor_id"], "actor": row["actor"],
        "action": row["action"], "target": row["target"],
        "note": row["note"] or "",
    }


def log_action(chat_id, actor, action, target=None, note=""):
    """یک اقدامِ مدیریتی را در لاگِ گروه ثبت می‌کند.

    ``actor``/``target`` می‌توانند شیءِ کاربر یا dict باشند.
    """
    key = str(chat_id)
    actor_id = None
    if isinstance(actor, dict):
        actor_id = actor.get("id", actor.get("user_id"))
    elif actor is not None:
        actor_id = getattr(actor, "id", getattr(actor, "user_id", None))
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "_ts": time.time(),
        # Stable grouping key; display text is deliberately separate because
        # usernames and display names can change.
        "actor_id": str(actor_id) if actor_id is not None else None,
        "actor": display_name(actor),
        "action": action,
        "target": display_name(target) if target is not None else None,
        "note": note or "",
    }
    if _USE_SQLITE_LOG:
        _ensure_admin_log_sqlite()
        with runtime_db.transaction() as conn:
            conn.execute(
                "INSERT INTO admin_events(group_id,actor_id,actor,action,"
                "target,note,event_time,event_ts) VALUES(?,?,?,?,?,?,?,?)",
                (key, entry["actor_id"], entry["actor"], entry["action"],
                 entry["target"], entry["note"], entry["time"], entry["_ts"]),
            )
            conn.execute(
                "DELETE FROM admin_events WHERE event_ts < ?",
                (entry["_ts"] - LOG_TTL_SECONDS,),
            )
            conn.execute(
                "DELETE FROM admin_events WHERE group_id=? AND id NOT IN ("
                "SELECT id FROM admin_events WHERE group_id=? "
                "ORDER BY event_ts DESC,id DESC LIMIT ?)",
                (key, key, MAX_LOG_PER_GROUP),
            )
        return entry

    data = _load_admin_log()
    bucket = data.setdefault(key, [])
    bucket.append(entry)
    if len(bucket) > MAX_LOG_PER_GROUP:
        del bucket[:-MAX_LOG_PER_GROUP]
    # پس از افزودن، لاگ‌های قدیمی را هم پاک کن (خودکار).
    _prune_log(data)
    _save_admin_log(data)
    return entry


def get_log(chat_id, limit=30):
    """آخرین لاگ‌های ۲۴ ساعتِ اخیرِ این گروه (جدیدترین‌ها اول)."""
    if not free_tier.is_enabled("admin_log_view"):
        return []
    if _USE_SQLITE_LOG:
        _ensure_admin_log_sqlite()
        cutoff = time.time() - LOG_TTL_SECONDS
        runtime_db.execute("DELETE FROM admin_events WHERE event_ts < ?", (cutoff,))
        rows = runtime_db.query_all(
            "SELECT * FROM admin_events WHERE group_id=? AND event_ts>=? "
            "ORDER BY event_ts DESC,id DESC LIMIT ?",
            (str(chat_id), cutoff, max(0, int(limit))),
        )
        return [_sqlite_log_entry(row) for row in rows]
    data = _load_admin_log()
    if _prune_log(data):
        _save_admin_log(data)
    bucket = data.get(str(chat_id), [])
    return list(reversed(bucket[-limit:]))


def clear_log(chat_id):
    # The free edition may not alter retained admin audit records.
    if not free_tier.is_enabled("admin_log_view"):
        return False
    if _USE_SQLITE_LOG:
        _ensure_admin_log_sqlite()
        runtime_db.execute(
            "DELETE FROM admin_events WHERE group_id=?", (str(chat_id),)
        )
        return True
    data = _load_admin_log()
    data.pop(str(chat_id), None)
    _save_admin_log(data)
    return True


def export_admin_log_json(path=None):
    """Export retained admin events for an emergency JSON rollback.

    Returns ``None`` in the free plan and does not read or write the log store.
    """
    if not free_tier.is_enabled("admin_log_view"):
        return None
    target = Path(path) if path else _ADMIN_LOG_FILE
    if _USE_SQLITE_LOG:
        _ensure_admin_log_sqlite()
        cutoff = time.time() - LOG_TTL_SECONDS
        payload = {}
        rows = runtime_db.query_all(
            "SELECT * FROM admin_events WHERE event_ts>=? "
            "ORDER BY group_id,event_ts,id", (cutoff,)
        )
        for row in rows:
            payload.setdefault(str(row["group_id"]), []).append(
                _sqlite_log_entry(row)
            )
    else:
        payload = _load_admin_log()
        _prune_log(payload)
    write_json(target, payload)
    if json.loads(target.read_text(encoding="utf-8")) != payload:
        raise OSError(f"admin log JSON rollback export failed: {target}")
    return target


def _u16_len(value):
    return len((value or "").encode("utf-16-le")) // 2


def format_log(chat_id, limit=30):
    """لاگ را به متنِ مرتب و خوانا + entityهای قالب‌بندی برمی‌گرداند.

    عملیاتِ پشتِ‌سرهمِ یک ادمین در یک «بخش» گروه‌بندی می‌شوند: نامِ ادمین
    فقط یک بار (داخلِ نقل‌قولِ شیشه‌ای) نمایش داده می‌شود و همهٔ عملیاتِ
    همان ادمین زیرِ همان بخش به‌صورتِ ردیفی می‌آیند. اگر ادمین عوض شد،
    بخشِ جدیدی ساخته می‌شود.

    خروجی ``(text, entities)``.
    """
    if not free_tier.is_enabled("admin_log_view"):
        return free_tier.PAYWALL_MESSAGE, []
    try:
        from splusthon.tl.types import MessageEntityBlockquote, MessageEntityBold
    except ImportError:
        class MessageEntityBlockquote:
            def __init__(self, offset=0, length=0):
                self.offset = offset
                self.length = length

        class MessageEntityBold:
            def __init__(self, offset=0, length=0):
                self.offset = offset
                self.length = length

    entries = get_log(chat_id, limit)
    if not entries:
        return "📭 هنوز اقدامی در این گروه ثبت نشده است.", []

    # get_log جدیدترین‌ها را اول برمی‌گرداند؛ برایِ نمایشِ قدیمی‌ترین‌ها اول
    # (مطابقِ قالبِ خواسته‌شده) آن را برمی‌گردانیم.
    entries = list(reversed(entries))

    # Group by stable actor_id across the whole daily window, not only when
    # entries are adjacent. Older records without actor_id are kept readable
    # and fall back to their stored display value.
    sections = []  # [(actor_key, actor_display, [(action, note)])]
    section_by_actor = {}
    for e in entries:
        actor_display = e.get("actor", "کاربر ناشناس")
        actor_key = e.get("actor_id") or f"legacy:{actor_display}"
        when = e.get("time", "")
        action = e.get("action", "")
        note = e.get("note", "")
        target = e.get("target")
        action_text = f"{action} {target}" if target else action
        section_index = section_by_actor.get(actor_key)
        if section_index is None:
            section_by_actor[actor_key] = len(sections)
            sections.append([actor_key, actor_display, [(action_text, note)]])
        else:
            # Keep the newest known username/name for display while retaining
            # the stable numeric actor_id for grouping.
            sections[section_index][1] = actor_display or sections[section_index][1]
            sections[section_index][2].append((action_text, note))

    lines = ["🧾 لاگ مدیریتی گروه:\n"]
    entities = []
    for idx, (_actor_key, actor, actions) in enumerate(sections, 1):
        lines.append(f"{idx}.\n")
        # نامِ ادمین فقط یک بار، داخلِ نقل‌قولِ شیشه‌ای
        actor_line = f"👤 {actor}\n"
        actor_start = _u16_len("".join(lines))
        lines.append(actor_line)
        entities.append(MessageEntityBlockquote(
            offset=actor_start, length=_u16_len(actor_line)))
        # همهٔ عملیاتِ همین ادمین، ردیفی (خارج از نقل‌قول)
        for action, note in actions:
            lines.append(f"→ {action}\n")
            if note:
                lines.append(f"📝 {note}\n")
        lines.append("\n")

    # Footer Bold
    footer = "⏳ این لاگ‌ها هر ۲۴ ساعت به‌صورت خودکار ریست می‌شوند."
    footer_start = _u16_len("".join(lines))
    lines.append(footer)
    entities.append(MessageEntityBold(
        offset=footer_start, length=_u16_len(footer)))

    return "".join(lines), entities


# ---------------------------------------------------------------------------
#  پاکسازی خودکار — تنظیماتِ ماندگار + جریانِ مرحله‌به‌مرحله
# ---------------------------------------------------------------------------
# جریانِ مرحله‌به‌مرحله (در حافظه): chat_id -> مرحلهٔ انتظار
#   step: "day" | "time" | "count"
_PENDING_CLEANUP = {}  # chat_id -> {"step": ..., "day": "today"|"tomorrow",
#                       "time": "HH:MM", "user_id": ...}


def _load_cleanups():
    try:
        if _CLEANUP_FILE.exists():
            data = json.loads(_CLEANUP_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _save_cleanups(data):
    try:
        _BASE.mkdir(parents=True, exist_ok=True)
        write_json(_CLEANUP_FILE, data, indent=2)
    except OSError:
        pass


def format_jalali(date):
    """تاریخِ میلادی را به شمسی به‌صورت «۱۴۰۵/۰۵/۱۵» برمی‌گرداند.

    الگوریتمِ استانداردِ تبدیلِ میلادی→شمسی.
    """
    g_y = date.year
    g_m = date.month
    g_d = date.day

    g_days_in_month = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    j_days_in_month = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)

    gy = g_y - 1600
    gm = g_m - 1
    gd = g_d - 1

    g_day_no = (365 * gy + (gy + 3) // 4 - (gy + 99) // 100
                + (gy + 399) // 400)
    for i in range(gm):
        g_day_no += g_days_in_month[i]
    if gm > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        # leap year
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            break
        j_day_no -= j_days_in_month[i]
    jm = i + 1
    jd = j_day_no + 1
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def valid_day(value):
    """«امروز» یا «فردا» را تشخیص می‌دهد."""
    norm = (value or "").strip().replace("‌", "")
    if norm in ("امروز", "امرز", "اموز"):
        return "today"
    if norm in ("فردا", "فرداه", "فر دا"):
        return "tomorrow"
    return None


def valid_time(value):
    """بررسیِ ساعتِ معتبر به شکل HH:MM."""
    value = (value or "").strip()
    try:
        hour, minute = value.split(":")
        hour, minute = int(hour), int(minute)
    except (ValueError, AttributeError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def time_of_day(hour):
    """برچسبِ بخشِ روز بر اساسِ ساعتِ واقعی: صبح/ظهر/عصر/شب.

    بازه‌ها: ۰۰-۰۵ شب ، ۰۵-۱۱ صبح ، ۱۲-۱۴ ظهر ، ۱۵-۱۷ عصر ، ۱۸-۲۴ شب.
    برچسب فقط بر اساسِ بازهٔ واقعیِ ساعت ساخته می‌شود، نه یک mapping ثابت.
    """
    if hour < 5:
        return "شب"
    if hour < 12:
        return "صبح"
    if hour < 15:
        return "ظهر"
    if hour < 18:
        return "عصر"
    return "شب"


def _fa_digits(value):
    """ارقامِ فارسی/عربی را به انگلیسی تبدیل می‌کند."""
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    en = "0123456789"
    for f, e in zip(fa + ar, en + en):
        value = value.replace(f, e)
    return value


# ساعتِ نمایندهٔ بخشِ روز وقتی عددی وارد نشده باشد.
_DAY_PART_DEFAULT_HOUR = {"morning": 7, "noon": 12, "afternoon": 17, "night": 21}


def _explicit_day_part_hour(day_part, hour):
    """ساعتِ ۲۴ساعتهٔ صریح برای یک بخشِ روز و یک عددِ ۱ تا ۱۲.

    عددِ None → ساعتِ نمایندهٔ همان بخشِ روز.
    """
    if hour is None:
        return _DAY_PART_DEFAULT_HOUR.get(day_part)
    if day_part == "morning":
        return hour                      # ۷ صبح = ۷
    if day_part == "noon":
        return 12 if hour == 12 else hour + 12   # ۱۲ ظهر=۱۲ ، ۱ ظهر=۱۳
    if day_part == "afternoon":
        return hour if hour >= 12 else hour + 12  # ۵ عصر=۱۷
    if day_part == "night":
        return 0 if hour == 12 else hour + 12    # ۷ شب=۱۹ ، ۱۲ شب=۰۰
    return hour


def _resolve_ambiguous(hour, minute, now):
    """ساعتِ مبهمِ ۱ تا ۱۱ را با نزدیک‌ترینِ زمانِ آینده (AM/PM) حل می‌کند.

    دو کاندیدِ امروز: ``hour:minute`` و ``hour+12:minute``. نزدیک‌ترینِ
    کاندیدی که هنوز نرسیده انتخاب می‌شود؛ اگر هر دو گذشته باشند، زودترینِ
    کاندید برای فردا برمی‌گردد (تا ``compute_scheduled_at`` آن را به فردا
    منتقل کند).
    """
    candidates = [(hour, minute), (hour + 12, minute)]
    base = now.replace(second=0, microsecond=0)
    future = []
    for h, m in candidates:
        if h > 23:
            continue
        dt = base.replace(hour=h, minute=m)
        if dt >= now:
            future.append(dt)
    if future:
        best = min(future)
        return f"{best.hour:02d}:{best.minute:02d}"
    # همهٔ کاندیدهای امروز گذشته → زودترینِ کاندید برای فردا
    best_h, best_m = min(candidates)
    return f"{best_h:02d}:{best_m:02d}"


def parse_time(value, now=None):
    """تفسیرِ ساعتِ فارسی/انگلیسی به فرمتِ HH:MM (۲۴ساعته).

    قواعد:
      - «15:30» / «19:00» / «19» / «۱۹» / «19:5» → ساعتِ صریحِ ۲۴ساعته
        (بدونِ حدسِ AM/PM).
      - «12:00» / «12» → 12:00 (ظهرِ پیش‌فرض).
      - «۷ صبح» → 07:00 ، «۷ شب» → 19:00 ، «۵ عصر» → 17:00 ، «۱۲ ظهر» → 12:00 ،
        «۱۲ شب» → 00:00. عبارتِ بخشِ روز صراحتاً اولویت دارد.
      - «صبح»/«ظهر»/«عصر»/«شب» بدونِ عدد → ساعتیِ نمایندهٔ همان بخشِ روز.
      - «۷» / «7:00» / «ساعت ۷» (عددِ مبهمِ ۱ تا ۱۱ بدونِ بخشِ روز) →
        بینِ AM و PM بر اساسِ زمانِ فعلی و نزدیک‌ترینِ زمانِ آینده انتخاب می‌شود.

    خروجی: رشتهٔ ``"HH:MM"`` یا ``None`` اگر نامعتبر.
    """
    if now is None:
        now = now_local()
    raw = _fa_digits((value or "").strip())
    if not raw:
        return None
    raw = raw.replace("\u200c", " ").strip()
    raw = re.sub(r"\s*ساعت\s*", " ", raw).strip()

    # کلمهٔ بخشِ روز (صریح، اولویت‌دار)
    parts = {"صبح": "morning", "ظهر": "noon", "عصر": "afternoon", "شب": "night"}
    day_part = None
    for word, key in parts.items():
        if word in raw:
            day_part = key
            raw = raw.replace(word, " ").strip()
            break

    # استخراجِ عدد/ساعت و دقیقه (با یا بدونِ «:»)
    colon = re.search(r"(\d{1,2})\s*:\s*(\d{1,2})", raw)
    if colon:
        hour = int(colon.group(1))
        minute = int(colon.group(2))
    else:
        nums = re.findall(r"\d{1,2}", raw)
        hour = int(nums[0]) if nums else None
        minute = 0

    if minute is not None and not (0 <= minute <= 59):
        return None

    # بخشِ روزِ صریح → بدونِ حدس
    if day_part is not None:
        h24 = _explicit_day_part_hour(day_part, hour)
        if h24 is None:
            return None
        return f"{h24:02d}:{minute:02d}"

    if hour is None:
        return None

    # ساعتِ صریحِ ۰ (نیمه‌شب) → 00:MM
    if hour == 0:
        return f"00:{minute:02d}"

    # ساعتِ صریحِ ۱۳ تا ۲۳ → ۲۴ساعته بدونِ حدس
    if 13 <= hour <= 23:
        return f"{hour:02d}:{minute:02d}"

    # ۱۲ → ظهرِ پیش‌فرض (مگر با بخشِ روزِ «شب» که بالا رسیدگی شد)
    if hour == 12:
        return f"12:{minute:02d}"

    # ۱ تا ۱۱ بدونِ بخشِ روز → مبهم → نزدیک‌ترینِ زمانِ آینده (AM/PM)
    if 1 <= hour <= 11:
        return _resolve_ambiguous(hour, minute, now)

    return None


def compute_scheduled_at(day, time_str, now=None):
    """زمانِ دقیقِ اجرایِ پاکسازی را محاسبه می‌کند.

    ``day``: "today" یا "tomorrow"؛ ``time_str``: "HH:MM".
    اگر زمانِ «امروز» گذشته باشد، به «فردا» منتقل می‌شود.
    خروجی: datetime (منطقهٔ زمانیِ تهران) یا None اگر نامعتبر.
    """
    if now is None:
        now = now_local()
    t = valid_time(time_str)
    if t is None:
        return None
    hour, minute = int(t.split(":")[0]), int(t.split(":")[1])

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day == "tomorrow":
        target = target + timedelta(days=1)
    else:
        # «امروز» اما اگر ساعت گذشته → فردا
        if target <= now:
            target = target + timedelta(days=1)
    return target


def set_cleanup(chat_id, day, time_str, count, *, scheduled_at=None, now=None):
    """تنظیماتِ پاکسازی را با همان زمانِ تأییدشده ذخیره می‌کند.

    ``scheduled_at`` زمانِ ساخته‌شده در مرحلهٔ انتخاب ساعت است. نگه‌داشتن
    همان مقدار مانعِ تغییر تصمیم «امروز/فردا» بین مرحلهٔ ساعت و شمارش،
    خصوصاً نزدیک نیمه‌شب، می‌شود.
    """
    if not free_tier.is_enabled("auto_cleanup"):
        return None
    now = now_local() if now is None else now
    if scheduled_at is None:
        scheduled_at = compute_scheduled_at(day, time_str, now)
    elif isinstance(scheduled_at, str):
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at)
        except (TypeError, ValueError):
            return None
    if scheduled_at is None:
        return None
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=_TEHRAN)
    data = _load_cleanups()
    data[str(chat_id)] = {
        "set_at": now.isoformat(timespec="seconds"),
        "scheduled_at": scheduled_at.isoformat(timespec="seconds"),
        "time": time_str,
        "day": day,
        "count": int(count),
        "last_run": None,
    }
    _save_cleanups(data)
    return data[str(chat_id)]


def get_cleanup(chat_id):
    return _load_cleanups().get(str(chat_id))


def clear_cleanup(chat_id):
    if not free_tier.is_enabled("auto_cleanup"):
        return False
    data = _load_cleanups()
    existed = data.pop(str(chat_id), None) is not None
    if existed:
        _save_cleanups(data)
    return existed


def all_cleanups():
    return _load_cleanups()


def mark_cleanup_run(chat_id, scheduled_at):
    if not free_tier.is_enabled("auto_cleanup"):
        return False
    data = _load_cleanups()
    rec = data.get(str(chat_id))
    if rec:
        rec["last_run"] = scheduled_at
        _save_cleanups(data)


def valid_count(value):
    """تعدادِ پیام: بین ۱ تا ۳۰۰۰."""
    try:
        n = int(str(value or "").strip().replace(",", "").replace("٬", ""))
    except (ValueError, AttributeError):
        return None
    if 1 <= n <= 3000:
        return n
    return None


def format_cleanup(chat_id):
    """نمایشِ خوانای تنظیماتِ پاکسازیِ این گروه.

    مثال:
      🕐 زمان تنظیم: امروز ساعت ۱۳:۳۰
      🧹 زمان پاکسازی: فردا ساعت ۰۱:۳۰
      🗑️ تعداد پیام: ۱۰۰
    """
    rec = get_cleanup(chat_id)
    if not rec:
        return "🧹 پاکسازی خودکاری برای این گروه تنظیم نشده است."

    try:
        set_at = datetime.fromisoformat(rec.get("set_at", ""))
    except (ValueError, TypeError):
        set_at = None
    try:
        sched = datetime.fromisoformat(rec.get("scheduled_at", ""))
    except (ValueError, TypeError):
        sched = None

    today = now_local()
    if set_at is not None:
        set_day = set_at.date() == today.date()
        set_label = f"{'امروز' if set_day else format_jalali(set_at.date())} " \
                    f"ساعت {set_at.strftime('%H:%M')}"
    else:
        set_label = "-"

    if sched is not None:
        diff_days = (sched.date() - today.date()).days
        if diff_days <= 0:
            day_label = "امروز"
        elif diff_days == 1:
            day_label = "فردا"
        else:
            day_label = format_jalali(sched.date())
        tod = time_of_day(sched.hour)
        sched_label = (f"{day_label} ساعت {sched.strftime('%H:%M')} "
                       f"({tod})")
    else:
        sched_label = "-"

    count = rec.get("count", 0)
    return (
        f"🧹 پاکسازی خودکار:\n\n"
        f"🕐 زمان تنظیم: {set_label}\n"
        f"🧹 زمان پاکسازی: {sched_label}\n"
        f"🗑️ تعداد پیام: {count}"
    )


# قفلِ مشترکِ per-group برایِ پاکسازی (دستی و خودکار با هم تداخل نکنند).
_GROUP_DELETE_LOCKS = {}
_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def _fullwidth_digits(value):
    return str(value).translate(_FULLWIDTH_DIGITS)


def get_group_lock(chat_id):
    lock = _GROUP_DELETE_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _GROUP_DELETE_LOCKS[chat_id] = lock
    return lock


def _cleanup_rpc_targets(bot, chat_id):
    """Prefer a resolved event InputPeer, then safe full/legacy ID forms."""
    targets = []
    wanted = normalize_group_id(chat_id)
    cache = getattr(bot, "reply_input_peer_cache", {}) or {}
    direct = cache.get(chat_id)
    if direct is not None:
        targets.append(direct)
    for cached_id, peer in list(cache.items()):
        if peer is not None and normalize_group_id(cached_id) == wanted:
            targets.append(peer)
            break

    candidate_factory = getattr(
        getattr(bot, "group_actions", None), "_peer_id_candidates", None
    )
    if callable(candidate_factory):
        targets.extend(candidate_factory(chat_id))
    targets.append(chat_id)

    unique = []
    markers = set()
    for target in targets:
        marker = repr(target)
        if marker in markers:
            continue
        markers.add(marker)
        unique.append(target)
    return unique


async def _snapshot_cleanup_message_ids(bot, chat_id, count, log):
    """Freeze existing IDs, distinguishing an empty group from RPC failure."""
    iterator_factory = getattr(bot.client, "iter_messages", None)
    errors = []
    for target in _cleanup_rpc_targets(bot, chat_id):
        ids = []
        try:
            if callable(iterator_factory):
                async for message in iterator_factory(target, limit=count):
                    message_id = getattr(message, "id", None)
                    if isinstance(message_id, int) and message_id > 0:
                        ids.append(message_id)
            else:
                # Compatibility fallback for older clients. It may return fewer
                # than requested, which is still a completed snapshot.
                messages = await bot.client.get_messages(target, limit=count)
                ids = [getattr(message, "id", None) for message in messages]
                ids = [message_id for message_id in ids
                       if isinstance(message_id, int) and message_id > 0]
        except Exception as error:
            errors.append(error)
            log(
                f"SNAPSHOT RETRY chat_id={chat_id} "
                f"target_type={type(target).__name__} error={error!r}"
            )
            continue

        # History pages can overlap after reconnect; delete every ID once.
        ids = list(dict.fromkeys(ids))
        log(
            f"SNAPSHOT chat_id={chat_id} requested={count} found={len(ids)} "
            f"target_type={type(target).__name__}"
        )
        return ids

    last_error = errors[-1] if errors else RuntimeError("no cleanup target")
    log(f"SNAPSHOT FAILED chat_id={chat_id} error={last_error!r}")
    return None


async def execute_cleanup(bot, chat_id, count, logger=None):
    """اجرای پاکسازیِ خودکار برای یک گروه.

    ترتیب: قفل → اعلام → حذفِ دسته‌ای (۱۰۰تایی) → بازکردن → اعلامِ پایان.
    همه در یک تسکِ پس‌زمینه انجام می‌شود تا حلقهٔ پیام بلاک نشود.
    """
    if not free_tier.is_enabled("auto_cleanup"):
        return False

    def _log(msg):
        try:
            if logger is not None:
                logger.log_info(f"AUTO CLEANUP {msg}")
        except Exception:
            pass

    lock = get_group_lock(chat_id)
    if lock.locked():
        _log(f"SKIP chat_id={chat_id} reason=delete_in_progress")
        return False
    async with lock:
        _log(f"START chat_id={chat_id} count={count}")
        try:
            # Freeze the complete pre-cleanup history *before* our own lock/
            # notice messages are sent.  The delete phase receives this fixed
            # list and therefore can never wait for or consume new messages.
            ids = await _snapshot_cleanup_message_ids(bot, chat_id, count, _log)
            if ids is None:
                # Never mark a failed history lookup as a successful zero-item
                # cleanup. The watcher retains the schedule for a later retry.
                _log(f"ABORT chat_id={chat_id} reason=snapshot_failed")
                return False

            # ۱) قفلِ گروه
            try:
                await bot.group_actions.lock_group(chat_id)
            except Exception as e:
                _log(f"LOCK FAILED chat_id={chat_id} error={e!r}")
            try:
                await bot.client.send_message(
                    chat_id,
                    "🔒 گروه برای پاکسازی خودکار قفل شد.\n\n🧹 آغاز پاکسازی...",
                )
            except Exception:
                pass

            # ۲) Delete only the frozen snapshot.  The common delete queue
            # keeps this background job from monopolising message handlers.
            deleted = 0
            remaining = []
            queue = getattr(bot, "message_delete_queue", None)
            if ids and queue is not None:
                deleted, remaining = await queue.enqueue(chat_id, ids)
            elif ids:
                for start in range(0, len(ids), 100):
                    batch = ids[start:start + 100]
                    try:
                        await bot.client.delete_messages(chat_id, batch)
                        deleted += len(batch)
                    except Exception as e:
                        remaining.extend(batch)
                        _log(f"DELETE FAILED chat_id={chat_id} error={e!r}")
                    await asyncio.sleep(0)
            if remaining:
                _log(f"DELETE INCOMPLETE chat_id={chat_id} deleted={deleted} remaining={len(remaining)}")

            # ۳) بازکردنِ گروه
            try:
                await bot.group_actions.unlock_group(chat_id)
            except Exception as e:
                _log(f"UNLOCK FAILED chat_id={chat_id} error={e!r}")

            # ۴) اعلامِ پایان (با تعدادِ واقعیِ پیام‌های حذف‌شده در همین اجرا)
            try:
                await bot.client.send_message(
                    chat_id,
                    "🔓 پاکسازی به پایان رسید و گروه دوباره باز شد.\n"
                    f"🗑️ تعداد پیام‌های پاک‌شده: {_fullwidth_digits(deleted)}",
                )
            except Exception:
                pass

            log_action(chat_id, {"username": "system"},
                       "پاکسازی خودکار",
                       note=f"{deleted} پیام حذف شد")
            _log(f"DONE chat_id={chat_id} deleted={deleted}")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(f"FAILED chat_id={chat_id} error={e!r}")
            try:
                await bot.group_actions.unlock_group(chat_id)
            except Exception:
                pass
            return False


async def run_cleanup_watcher(bot, logger=None, interval=None):
    """حلقهٔ پس‌زمینه: دقیقاً در زمانِ ذخیره‌شده، پاکسازیِ هر گروه را اجرا می‌کند.

    هر ``interval`` ثانیه (پیش‌فرض ۳۰) بررسی می‌کند؛ اگر زمانِ اجرا رسیده و
    هنوز اجرا نشده باشد (``last_run`` برابرِ آن زمان نباشد)، اجرا می‌شود.
    """
    if not free_tier.is_enabled("auto_cleanup"):
        return
    import asyncio
    delay = 30 if interval is None else interval
    while True:
        try:
            now = now_local()
            for key, rec in list(all_cleanups().items()):
                sched = rec.get("scheduled_at")
                if not sched:
                    continue
                try:
                    sched_dt = datetime.fromisoformat(sched)
                    # داده‌های قدیمیِ بدونِ منطقهٔ زمانی → تهران
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=_TEHRAN)
                except (ValueError, TypeError):
                    continue
                # اگر هنوز زمان نرسیده → رد
                if now < sched_dt:
                    continue
                # اگر قبلاً اجرا شده → رد
                if rec.get("last_run") == sched:
                    continue
                try:
                    chat_id = int(key)
                except (TypeError, ValueError):
                    chat_id = key
                # Do not mark before the job succeeds: a transient RPC or
                # task failure must leave the durable schedule eligible for
                # retry on the next scheduler pass.
                active_tasks = getattr(bot, "cleanup_tasks", {}).get(chat_id, set())
                if any(not existing.done() for existing in active_tasks):
                    continue
                task = asyncio.create_task(
                    execute_cleanup(
                        bot, chat_id, int(rec.get("count", 0)),
                        logger=logger))

                def _cleanup_finished(done_task, group_id=chat_id, scheduled=sched):
                    try:
                        getattr(bot, "cleanup_tasks", {}).get(group_id, set()).discard(done_task)
                    except Exception:
                        pass
                    try:
                        succeeded = done_task.result()
                        if succeeded:
                            mark_cleanup_run(group_id, scheduled)
                            if logger is not None:
                                logger.log_info(
                                    f"AUTO CLEANUP SCHEDULE COMMITTED "
                                    f"chat_id={group_id} scheduled_at={scheduled}"
                                )
                        elif logger is not None:
                            logger.log_error(
                                f"AUTO CLEANUP SCHEDULE RETAINED "
                                f"chat_id={group_id} scheduled_at={scheduled}"
                            )
                    except asyncio.CancelledError:
                        if logger is not None:
                            logger.log_error(
                                f"AUTO CLEANUP TASK CANCELLED chat_id={group_id}"
                            )
                    except Exception as task_error:
                        if logger is not None:
                            logger.log_error(
                                f"AUTO CLEANUP TASK CRASHED chat_id={group_id} "
                                f"error={task_error!r}"
                            )

                task.add_done_callback(_cleanup_finished)
                try:
                    getattr(bot, "cleanup_tasks", {}).setdefault(
                        chat_id, set()).add(task)
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            try:
                if logger is not None:
                    logger.log_error(f"AUTO CLEANUP WATCHER FAILED {error!r}")
            except Exception:
                pass
        await asyncio.sleep(delay)
