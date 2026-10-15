"""تست یکپارچهٔ چهار قابلیت جدید: مین‌یاب، ساخت جمله، سابقه‌ها، سطح گروه.

مسیر واقعی را شبیه‌سازی می‌کند: فرمان → روتر بازی‌ها → ماژول بازی → اقتصاد.

    python -m pytest tests/test_four_new_features_e2e.py -q
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# اقتصاد را از دیتابیس واقعی ایزوله کن (مثل بقیهٔ تست‌ها) تا اجرای تست
# هیچ‌وقت موجودی واقعی کاربر را دست نزند.
import economy.storage as _eco_storage
_ECO_TMP = tempfile.mkdtemp(prefix="four_features_e2e_")
_eco_storage.use_file(Path(_ECO_TMP) / "economy.json")

import handlers.fox_games_router as router
from modules.fox_games import minesweeper as ms
from modules.fox_games import sentence_guess as sg
from modules import user_history as uh
from modules import group_level as gl
from economy import get_balance, reset_all as reset_economy
import economy
from economy import rewards as economy_rewards

CHAT = -100777


class User:
    def __init__(self, uid, name=None, username=None):
        self.id = uid
        self.first_name = name or f"user{uid}"
        self.last_name = None
        self.username = username


class Event:
    def __init__(self, chat_id, sender):
        self.chat_id = chat_id
        self.sender = sender
        self.out = []

    async def reply(self, text, **kwargs):
        self.out.append(text)
        return None

    def said(self, needle):
        return any(needle in m for m in self.out)


class Logger:
    def __init__(self):
        self.info = []
        self.errors = []

    def log_info(self, m):
        self.info.append(m)

    def log_error(self, m):
        self.errors.append(m)


class Bot:
    """فقط چیزی که روتر لازم دارد: logger.

    عمداً متد award_coins ندارد تا روتر از مسیرِ واقعیِ اقتصاد
    (economy.award_game / economy.spend) استفاده کند — همان‌طور که در
    ربات واقعی اتفاق می‌افتد.
    """
    def __init__(self):
        self.logger = Logger()


_LOOP = None


def run(coro):
    """اجرای coroutine روی حلقهٔ خصوصی همین فایل تست.

    ``asyncio.get_event_loop()`` در پایتون ۳٫۱۳ وقتی تست دیگری در همان worker
    حلقه‌اش را بسته باشد RuntimeError می‌دهد؛ در اجرای کل سوییت همین باعث
    پنج شکست بی‌ربط در این فایل می‌شد (تنها اجرا سالم بود).
    """
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


# ---------------------------------------------------------------------------
# ۱) مین‌یاب
# ---------------------------------------------------------------------------
def test_minesweeper_command_and_board():
    ms.reset_all(clear_quota=True)
    bot = Bot()
    u1 = User(1001, "علی", "ali")
    ev = Event(CHAT, u1)
    consumed = run(router.handle(bot, ev, CHAT, 1001, u1, "مین یاب", bot.logger))
    assert consumed is True
    assert ev.said("1️⃣2️⃣3️⃣") and ev.said("7️⃣8️⃣9️⃣")
    assert ev.said("🎟")
    assert ms.is_active(CHAT, 1001)


def test_minesweeper_reward_penalty_and_quota():
    reset_economy()
    ms.reset_all(clear_quota=True)
    bot = Bot()
    u1 = User(1001, "علی", "ali")
    # مقدار و نوع سکه از همان جدول واحد اقتصاد خوانده می‌شود؛ تست نباید عدد
    # ثابت داشته باشد تا با تغییر موجودی/نوع سکه بی‌دلیل نشکند.
    coin = economy_rewards.coin_for(ms.REWARD_GAME)
    reward = economy_rewards.amount_for(ms.REWARD_GAME)

    # دور ۱: برد → جایزهٔ همین بازی
    run(router.handle(bot, Event(CHAT, u1), CHAT, 1001, u1, "مین یاب", bot.logger))
    state = ms._ACTIVE.get((str(CHAT), "1001"))
    assert state is not None
    # قرارداد فعلی ماژول: «safe» خانهٔ امن/برنده است (نام قدیمی «mine»).
    ev = Event(CHAT, u1)
    run(router.handle(bot, ev, CHAT, 1001, u1, str(state["safe"]), bot.logger))
    assert ev.said("جان سالم به در برد")
    assert ev.said("سکه")
    assert get_balance(CHAT, 1001)[coin] == reward

    # موجودی کافی تا جریمهٔ دور دوم واقعاً کسر شود (spend با کمبود موجودی
    # خطا می‌دهد و پیام «نداری» می‌آید).
    economy.award(CHAT, 1001, ms.PENALTY, coin, reference="test-fund-minesweeper")
    before = get_balance(CHAT, 1001)[coin]

    # دور ۲: باخت → کسر PENALTY از همان سکه، و پیام هم باید همان سکه را بگوید
    run(router.handle(bot, Event(CHAT, u1), CHAT, 1001, u1, "مین یاب", bot.logger))
    state = ms._ACTIVE.get((str(CHAT), "1001"))
    losing_cell = next(c for c in range(1, 10) if c != state["safe"])
    ev = Event(CHAT, u1)
    run(router.handle(bot, ev, CHAT, 1001, u1, str(losing_cell), bot.logger))
    assert ev.said("مین منفجر شد")
    assert ev.said(economy_rewards.coin_name(coin)), ev.out
    assert get_balance(CHAT, 1001)[coin] == before - ms.PENALTY

    # شانس‌ها: ۲ بازی امروز → سومی مسدود
    ev = Event(CHAT, u1)
    run(router.handle(bot, ev, CHAT, 1001, u1, "مین یاب", bot.logger))
    assert ev.said("شانس‌های امروز شما تمام شد")


def test_minesweeper_per_user_independent():
    ms.reset_all(clear_quota=True)
    bot = Bot()
    u1 = User(1001, "علی", "ali")
    u2 = User(1002, "رضا", "reza")
    ev = Event(CHAT, u2)
    run(router.handle(bot, ev, CHAT, 1002, u2, "مین یاب", bot.logger))
    assert ev.said("1️⃣2️⃣3️⃣")
    assert ms.is_active(CHAT, 1002)
    # بازی u1 جدا است و با شروع بازی u2 تداخل ندارد
    assert not ms.is_active(CHAT, 1001)


# ---------------------------------------------------------------------------
# ۲) ساخت جمله
# ---------------------------------------------------------------------------
def test_sentence_guess_command_and_isolation():
    sg.reset_all()
    bot = Bot()
    ua = User(2001, "سارا", "sara")
    ub = User(2002, "مهدی", "mehdi")

    eva = Event(CHAT, ua)
    run(router.handle(bot, eva, CHAT, 2001, ua, "ساخت جمله", bot.logger))
    evb = Event(CHAT, ub)
    run(router.handle(bot, evb, CHAT, 2002, ub, "ساخت جمله", bot.logger))
    assert len(eva.out) > 0 and len(evb.out) > 0

    qa = sg.current(CHAT, 2001)
    qb = sg.current(CHAT, 2002)
    assert qa is not None and qb is not None
    assert qa["question"] != qb["question"] or qa["answer"] != qb["answer"]

    # پاسخ درستِ b روی a اثر نمی‌گذارد
    assert sg.answer(CHAT, qb["answer"], user_id=2001) is None
    assert sg.is_active(CHAT, 2001)


def test_sentence_guess_reward_and_no_repeat():
    reset_economy()
    sg.reset_all()
    bot = Bot()
    ua = User(2001, "سارا", "sara")
    run(router.handle(bot, Event(CHAT, ua), CHAT, 2001, ua, "ساخت جمله", bot.logger))
    q = sg.current(CHAT, 2001)
    ev = Event(CHAT, ua)
    run(router.handle(bot, ev, CHAT, 2001, ua, q["answer"], bot.logger))
    assert ev.said("پاسخ درست داد")
    assert get_balance(CHAT, 2001)["bronze"] == 3

    # بانک حداقل ۳۰۰ جمله و عدم تکرار در ۳۰ دور متوالی
    assert len(sg.PUZZLES) >= 300
    seen = set()
    for _ in range(30):
        run(router.handle(bot, Event(CHAT, ua), CHAT, 2001, ua,
                          "ساخت جمله", bot.logger))
        q = sg.current(CHAT, 2001)
        if q is None:
            break
        seen.add(q["answer"])
        run(router.handle(bot, Event(CHAT, ua), CHAT, 2001, ua,
                          q["answer"], bot.logger))
    assert len(seen) >= 29, f"تکرار در {len(seen)} جمله"


# ---------------------------------------------------------------------------
# ۳) سابقه‌ها
# ---------------------------------------------------------------------------
def test_user_history_format_and_24h_reset():
    uh.reset()
    import time

    class Sender:
        def __init__(self, i, u):
            self.id = i
            self.username = u

    uh.add_kick(CHAT, Sender(3001, "kicked_user"), "ارسال لینک تبلیغاتی")
    uh.add_mute(CHAT, Sender(3002, "muted_user"), "تکرار پیام")
    uh.add_warn(CHAT, Sender(3003, "warned_user"), "کلمهٔ نامناسب")
    text, entities = uh.format_history(CHAT)
    assert "「 @kicked_user 」" in text
    assert "🚫 اخراج شده" in text
    assert "🔇 سکوت شده" in text
    assert "⚠️ اخطار گرفته" in text
    assert "📝 دلیل: ارسال لینک تبلیغاتی" in text

    # ریست واقعی بعد از ۲۴ ساعت (با پیرکردن رکوردها)
    data = uh._load()
    for chat in data.values():
        for entry in chat.values():
            for rec in entry["records"]:
                rec["_ts"] = time.time() - 25 * 3600
    uh._save(data)
    text2, _ = uh.format_history(CHAT)
    assert uh.NO_HISTORY in text2
    uh.reset()


# ---------------------------------------------------------------------------
# ۴) سطح گروه
# ---------------------------------------------------------------------------
def test_group_level_calculation_and_format():
    gl.reset()
    # قرارداد فعلی ماژول (نسخهٔ ۲، کلید _level_system_version در group_level):
    # هر ۱۰۰۰ پیام = یک سطح، از صفر شمرده می‌شود و سقف ۲۰ است؛ یعنی سطح ۲۰
    # در ۲۰۰۰۰ پیام به دست می‌آید.
    assert gl.level_for(0) == 0
    assert gl.level_for(999) == 0
    assert gl.level_for(1000) == 1
    assert gl.level_for(19999) == 19
    assert gl.level_for(20000) == 20
    assert gl.level_for(10 ** 9) == gl.MAX_LEVEL  # سقف
    text = gl.format_level(CHAT)
    assert "سطح فعلی" in text and "فعال‌ترین عضو" in text
    gl.reset()
