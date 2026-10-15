"""💣 بازی مین یاب — تختهٔ ۳×۳، یک مین تصادفی، سهمیهٔ روزانه با ریست ۰۰:۰۰ تهران.

این ماژول کاملاً مستقل است:

* هیچ بازی موجودی را تغییر نمی‌دهد و state خودش را جدا نگه می‌دارد.
* هر کاربر در هر گروه بازی مستقل خودش را دارد؛ کلید ``(chat_id, user_id)``.
  پس چند نفر می‌توانند هم‌زمان بازی کنند و پاسخ یکی روی بازی دیگری اثر ندارد.
* جای مین در «هر دور» از نو و تصادفی انتخاب می‌شود (``SystemRandom``).
* هر کاربر **۲ شانس در روز** دارد و شمارنده دقیقاً ساعت ۰۰:۰۰ به وقت
  تهران صفر می‌شود (نه پنجرهٔ لغزان ۲۴ ساعته). منبع زمان تنها
  ``modules.time_utils.now_local`` است.
* سهمیه روی دیسک (``config/fox_minesweeper.json``) ذخیره می‌شود تا
  ری‌استارت ربات آن را صفر نکند.

جایزه/کسر سکه اینجا پرداخت نمی‌شود؛ روتر بازی‌ها آن را از راه
``economy`` انجام می‌دهد. مقدارها از همین‌جا خوانده می‌شوند:

    برد  → ``REWARD_GAME`` («minesweeper» در ``economy/rewards.py``)
    باخت → ``PENALTY`` سکه از *همان نوع سکهٔ این بازی* کسر می‌شود
    (``economy.rewards.coin_for(REWARD_GAME)``) — متن پیام جریمه هم از
    همان منبع خوانده می‌شود تا پیام و کسر واقعی هم‌خوان باشند.
"""
import asyncio
import json
import random
import time
from datetime import timedelta
from pathlib import Path

from modules.runtime_paths import runtime_config_file
from modules.atomic_write import write_json

from modules.time_utils import now_local
from modules.fox_games.session_core import (
    log,
    parse_int,
    to_persian_digits,
)

GAME = "minesweeper"
GAME_NAME = GAME
COMMAND = "مین یاب"

# شناسهٔ بازی در جدول جایزهٔ اقتصاد (economy/rewards.py).
REWARD_GAME = "minesweeper"
# سکهٔ کسرشده وقتی کاربر روی مین می‌رود.
PENALTY = 10

CELL_COUNT = 9
DAILY_CHANCES = 2
PICK_TIMEOUT = 60

# ۱️⃣ تا ۹️⃣ — دقیقاً همان چیدمانی که در صورت مسئله خواسته شده.
CELL_EMOJI = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
              "6️⃣", "7️⃣", "8️⃣", "9️⃣")
SAFE_EMOJI = "✅"
MINE_EMOJI = "💣"

STATE_FILE = runtime_config_file("fox_minesweeper.json")

_ACTIVE = {}      # (chat_id, user_id) -> state
_TASKS = {}       # (chat_id, user_id) -> timer task
_RANDOM = random.SystemRandom()
_QUOTA = None

ALREADY_RUNNING = "💣 شما یک مین یاب باز دارید؛ اول همان را تمام کنید."


# ---------------------------------------------------------------------------
# تختهٔ بازی
# ---------------------------------------------------------------------------
def board_text(revealed=None, safe_cell=None, is_win=None):
    """تختهٔ ۳×۳ را می‌سازد.

    ``revealed`` مجموعهٔ خانه‌های بازشده، ``safe_cell`` شمارهٔ خانه امن
    و ``is_win`` نشان‌دهندهٔ برد (True) یا باخت (False) است.
    اگر داده نشوند، تختهٔ دست‌نخورده برگردانده می‌شود.
    """
    revealed = set(revealed or ())
    cells = []
    for number in range(1, CELL_COUNT + 1):
        if number in revealed:
            cells.append(SAFE_EMOJI if is_win else MINE_EMOJI)
        else:
            cells.append(CELL_EMOJI[number - 1])
    return "\n".join("".join(cells[row:row + 3]) for row in (0, 3, 6))


BOARD = board_text()


# ---------------------------------------------------------------------------
# سهمیهٔ روزانه — ریست واقعی ساعت ۰۰:۰۰ به وقت تهران
# ---------------------------------------------------------------------------
def today_key():
    """کلید روز جاری به وقت تهران؛ با گذشتن از نیمه‌شب عوض می‌شود."""
    return now_local().strftime("%Y-%m-%d")


def _load_quota():
    global _QUOTA
    if _QUOTA is not None:
        return _QUOTA
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        _QUOTA = data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        _QUOTA = {}
    return _QUOTA


def _save_quota():
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json(STATE_FILE, _QUOTA or {})
    except OSError:
        pass


def _used_today(user_id):
    """تعداد شانس‌های مصرف‌شدهٔ امروزِ این کاربر (روزِ تهران)."""
    quota = _load_quota()
    record = quota.get(str(user_id))
    if not isinstance(record, dict) or record.get("date") != today_key():
        return 0
    try:
        return max(0, int(record.get("count", 0)))
    except (TypeError, ValueError):
        return 0


def remaining_chances(user_id):
    return max(0, DAILY_CHANCES - _used_today(user_id))


def _consume_chance(user_id):
    quota = _load_quota()
    quota[str(user_id)] = {"date": today_key(), "count": _used_today(user_id) + 1}
    # رکوردهای روزهای گذشته پاک می‌شوند تا فایل بی‌نهایت رشد نکند.
    for key in [k for k, v in quota.items()
                if not isinstance(v, dict) or v.get("date") != today_key()]:
        quota.pop(key, None)
    _save_quota()
    return remaining_chances(user_id)


def seconds_until_reset():
    """ثانیهٔ باقی‌مانده تا ۰۰:۰۰ فردا به وقت تهران."""
    now = now_local()
    tomorrow = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1))
    return max(0, int((tomorrow - now).total_seconds()))


def format_wait(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    if hours and minutes:
        return (f"{to_persian_digits(hours)} ساعت و "
                f"{to_persian_digits(minutes)} دقیقه دیگر")
    if hours:
        return f"{to_persian_digits(hours)} ساعت دیگر"
    if minutes:
        return f"{to_persian_digits(minutes)} دقیقه دیگر"
    return "کمتر از یک دقیقه دیگر"


def quota_message(user_id):
    return (
        "⏳ شانس‌های امروز شما تمام شد.\n\n"
        f"هر روز {to_persian_digits(DAILY_CHANCES)} شانس دارید.\n"
        "شانس تازه ساعت ۰۰:۰۰ به وقت ایران:\n"
        f"{format_wait(seconds_until_reset())}"
    )


# ---------------------------------------------------------------------------
# چرخهٔ بازی
# ---------------------------------------------------------------------------
def _key(chat_id, user_id):
    return (str(chat_id), str(user_id))


def is_active(chat_id, user_id=None):
    """با ``user_id`` یعنی «آیا همین کاربر بازی باز دارد»؛ بدون آن یعنی گروه."""
    if user_id is not None:
        return _key(chat_id, user_id) in _ACTIVE
    chat = str(chat_id)
    return any(k[0] == chat for k in _ACTIVE)


def start(chat_id, user_id, logger=None):
    """یک دور تازه شروع می‌کند.

    خروجی ``(session, error)``؛ ``error`` یکی از ``"active"`` یا ``"quota"``.
    """
    key = _key(chat_id, user_id)
    if key in _ACTIVE:
        return None, "active"
    if remaining_chances(user_id) <= 0:
        log(logger, f"MINESWEEPER QUOTA BLOCK chat_id={chat_id} "
                    f"user_id={user_id}")
        return None, "quota"

    # در هر دور یک خانه امن تصادفی انتخاب می‌شود و بقیه مین دارند.
    safe = _RANDOM.randint(1, CELL_COUNT)
    session = {
        "chat_id": chat_id,
        "user_id": user_id,
        "safe": safe,
        "session_id": f"{int(time.time() * 1000)}:{_RANDOM.randrange(10 ** 6)}",
        "created_at": time.monotonic(),
        "finished": False,
    }
    _ACTIVE[key] = session
    remaining = remaining_chances(user_id)
    log(logger, f"MINESWEEPER START chat_id={chat_id} user_id={user_id} "
                f"session_id={session['session_id']} safe={session['safe']} "
                f"remaining={remaining}")
    result = dict(session)
    result["remaining"] = remaining
    return result, None


def pick(chat_id, user_id, text, logger=None):
    """انتخاب یک خانه. فقط صاحب بازی و فقط یک بار.

    خروجی ``(result, error)``؛ ``error`` در ``{"bad_number", "done"}``.
    اگر این کاربر بازی بازی نداشته باشد ``(None, None)`` برمی‌گردد تا پیام
    به بقیهٔ مسیرها برسد.
    """
    key = _key(chat_id, user_id)
    session = _ACTIVE.get(key)
    if not session:
        return None, None
    number = parse_int(text)
    if number is None or not 1 <= number <= CELL_COUNT:
        return None, "bad_number"
    if session.get("finished"):
        return None, "done"

    session["finished"] = True
    _cancel_task(key)
    _ACTIVE.pop(key, None)

    safe_cell = session["safe"]
    is_win = (number == safe_cell)
    is_lose = (number != safe_cell)
    remaining = _consume_chance(user_id)
    log(logger, f"MINESWEEPER PICK chat_id={chat_id} user_id={user_id} "
                f"cell={number} safe_cell={safe_cell} win={is_win}")
    return {
        "cell": number,
        "safe_cell": safe_cell,
        "safe": is_win,
        "board": board_text({number}, safe_cell, is_win),
        "session_id": session["session_id"],
        "remaining": remaining,
    }, None


def abandon(chat_id, user_id, session_id=None, logger=None):
    """پایان زمان: بازی این کاربر بسته می‌شود."""
    key = _key(chat_id, user_id)
    session = _ACTIVE.get(key)
    if not session:
        return None
    if session_id is not None and session["session_id"] != session_id:
        return None
    task = _TASKS.get(key)
    current = asyncio.current_task()
    if task is not None and task is not current and not task.done():
        task.cancel()
    _TASKS.pop(key, None)
    _ACTIVE.pop(key, None)
    remaining = _consume_chance(user_id)
    log(logger, f"MINESWEEPER TIMEOUT chat_id={chat_id} user_id={user_id}")
    safe_cell = session.get("safe")
    return {
        "mine": safe_cell,
        "board": board_text({safe_cell}, safe_cell, True),
        "session_id": session["session_id"],
        "remaining": remaining,
    }


def _cancel_task(key):
    task = _TASKS.pop(key, None)
    if task is not None and not task.done():
        task.cancel()


async def run_timeout(chat_id, user_id, session_id, on_timeout, logger=None,
                      timeout=None):
    limit = PICK_TIMEOUT if timeout is None else timeout
    try:
        await asyncio.sleep(limit)
    except asyncio.CancelledError:
        raise
    finally:
        result = abandon(chat_id, user_id, session_id, logger)
        if result:
            try:
                await on_timeout(result)
            except Exception:
                pass


def schedule(chat_id, user_id, session_id, on_timeout, logger=None,
             timeout=None):
    key = _key(chat_id, user_id)
    _cancel_task(key)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(run_timeout(
        chat_id, user_id, session_id, on_timeout, logger, timeout))
    _TASKS[key] = task

    def _cleanup(done):
        if _TASKS.get(key) is done:
            _TASKS.pop(key, None)

    task.add_done_callback(_cleanup)
    return task


def reset_all(chat_id=None, user_id=None, clear_quota=False):
    """پاک‌سازی — برای ری‌استارت و تست."""
    global _QUOTA
    if chat_id is None:
        for task in list(_TASKS.values()):
            if not task.done():
                task.cancel()
        _TASKS.clear()
        _ACTIVE.clear()
    elif user_id is not None:
        key = _key(chat_id, user_id)
        _cancel_task(key)
        _ACTIVE.pop(key, None)
    else:
        chat = str(chat_id)
        for key in [k for k in _ACTIVE if k[0] == chat]:
            _cancel_task(key)
            _ACTIVE.pop(key, None)
    if clear_quota:
        _QUOTA = {}
        _save_quota()
