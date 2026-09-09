"""🔌 اتصال واقعی اقتصاد به سیستم فرمان ربات.

این تست از *همان* هندلری استفاده می‌کند که در زمان اجرا ثبت می‌شود:
``new_message_handler`` که داخل ``SoroushAntiSpamBot.run()`` تعریف و با
``@client.on(events.NewMessage())`` رجیستر می‌گردد.

چرا این تست لازم است: تست‌های قبلی مستقیماً ``handle_new_message`` را صدا
می‌زدند و کل مسیر core (گیت فعال بودن گروه، مسیر پیوی، گیت broadcast) را
دور می‌زدند. بنابراین اگر route در core شکسته بود، هیچ تستی آن را
نمی‌گرفت.

    python tests/test_economy_routing.py
"""
import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import economy
import economy.shop.store as store
import economy.storage as storage
import handlers.economy_handler as eco_handler
from economy.ui import balance_menu, shop_menu
import modules.group_storage as group_storage

PASSED = FAILED = 0
CHAT = -1009999888877
OTHER_CHAT = -100555444333


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


# ---------------------------------------------------------------------------
# ساخت ربات و گرفتن هندلر واقعی
# ---------------------------------------------------------------------------
class FakeClient:
    """کلاینتی که فقط هندلرها را ثبت می‌کند و شبکه ندارد."""

    def __init__(self, captured):
        self.captured = captured
        self.me = types.SimpleNamespace(id=555, username="aifox")
        self.sent = []

    def on(self, event):
        def decorator(fn):
            self.captured.append(fn)
            return fn
        return decorator

    async def connect(self):
        return None

    async def get_me(self):
        return self.me

    async def send_message(self, target, text, **kwargs):
        self.sent.append((target, text))
        return True

    async def run_until_disconnected(self):
        raise SystemExit

    def add_event_handler(self, *args, **kwargs):
        return None


class Logger:
    def __init__(self):
        self.info, self.errors = [], []

    def log_info(self, message):
        self.info.append(message)

    def log_error(self, message):
        self.errors.append(message)

    def has(self, needle):
        return any(needle in m for m in self.info + self.errors)


class ConfigManager:
    def get(self, key, default=None):
        return default


class Tracker:
    def get_count(self, *args):
        return 0

    def get_all_counts(self):
        return {}


class Detector:
    """آشکارساز اسپم خنثی: هیچ پیامی را اسپم نمی‌داند."""

    def is_spam(self, *args, **kwargs):
        return False, None

    def check_message(self, *args, **kwargs):
        return False, None

    def check_banned_words(self, *args, **kwargs):
        # هم‌امضا با SpamDetector واقعی؛ پیش‌بررسی کلمات ممنوعه خنثی.
        return False, None

    def has_public_username(self, *args, **kwargs):
        # هم‌امضا با SpamDetector واقعی؛ هیچ متنی یوزرنیم عمومی ندارد.
        return False


class Chat:
    def __init__(self, chat_id=CHAT, title="گروه تست"):
        self.id = chat_id
        self.title = title


class Message:
    _next = 1000

    def __init__(self, text):
        Message._next += 1
        self.message = text
        self.id = Message._next
        self.entities = None
        self.file = None


class User:
    def __init__(self, uid, name="علی", username=None):
        self.id = uid
        self.first_name = name
        self.last_name = None
        self.username = username


class Event:
    """رویداد پیام گروهی، مثل چیزی که splusthon می‌سازد."""

    def __init__(self, text, user_id, chat_id=CHAT, reply_target=None):
        self.message = Message(text)
        self.chat_id = chat_id
        self.is_private = False
        self.out = False
        self.replies = []
        self._user = User(user_id)
        self._chat_id = chat_id
        self.reply_to = reply_target is not None
        self._reply_target = reply_target

    async def get_chat(self):
        return Chat(self._chat_id)

    async def get_sender(self):
        return self._user

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return None

    async def respond(self, text, **kwargs):
        self.replies.append(text)
        return None

    async def get_reply_message(self):
        if self._reply_target is None:
            return None
        return _ReplyMessage(self._reply_target)

    def said(self, needle):
        return any(needle in m for m in self.replies)


class _ReplyMessage:
    def __init__(self, user):
        self._user = user

    async def get_sender(self):
        return self._user


async def build_handler():
    """ربات را بدون شبکه بالا می‌آورد و هندلر واقعی پیام را برمی‌گرداند."""
    import core.bot_working_split_ok as core

    captured = []
    bot = core.SoroushAntiSpamBot.__new__(core.SoroushAntiSpamBot)
    bot.client = FakeClient(captured)
    bot.logger = Logger()
    bot.config_manager = ConfigManager()
    bot.tracker = Tracker()
    bot.group_timer_tasks = {}
    bot.bot_account_id = 555
    bot.punished_users = set()
    bot.spam_burst_messages = {}
    bot.spammer_messages = {}
    bot.spam_burst_users = set()
    bot.detector = Detector()

    async def _noop(*args, **kwargs):
        return None

    bot.initialize_client = _noop

    try:
        await asyncio.wait_for(bot.run(), timeout=3)
    except (SystemExit, asyncio.TimeoutError):
        pass
    except Exception:
        pass

    handlers = [fn for fn in captured
                if getattr(fn, "__name__", "") == "new_message_handler"]
    return bot, (handlers[0] if handlers else None)


def fresh():
    temp = Path(tempfile.mkdtemp())
    storage.use_file(temp / "economy.json")
    store.ITEMS_FILE = temp / "shop.json"
    store._cache = None
    store._cache_mtime = None
    eco_handler.reset_all()
    group_storage.activate_group(CHAT, "گروه تست")
    return temp


# ===========================================================================
# ثبت شدن route
# ===========================================================================
def test_handler_is_registered():
    print("\n### 🔌 هندلر پیام واقعاً ثبت می‌شود")
    bot, handler = asyncio.run(build_handler())
    check("new_message_handler ثبت شد", handler is not None)
    check("هندلر async است",
          handler is not None and asyncio.iscoroutinefunction(handler))


def test_balance_command_routed():
    print("\n### 🔌 «موجودی» از مسیر واقعی فرمان")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        event = Event("موجودی", 777)
        await handler(event)
        return bot, event

    bot, event = asyncio.run(scenario())
    check("ربات پاسخ داد", bool(event.replies),
          "*** هیچ پاسخی نیامد ***")
    check("منوی کیف پول باز شد", event.said("کیف پول شما"))
    check("برنز نمایش داده شد", event.said("🥉 برنز:"))
    check("نقره نمایش داده شد", event.said("🥈 نقره:"))
    check("طلا نمایش داده شد", event.said("🥇 طلا:"))
    check("ارزش کل نمایش داده شد", event.said("ارزش کل"))
    check("همهٔ گزینه‌ها در همین منو هستند",
          all(event.said(x) for x in
              ("تبدیل برنز به نقره", "تبدیل نقره به طلا", "انتقال برنز",
               "انتقال نقره", "انتقال طلا", "تاریخچه", "جایزه روزانه")))
    check("route در لاگ ثبت شد", bot.logger.has("ECONOMY BALANCE MENU"))


def test_shop_command_routed():
    print("\n### 🔌 «فروشگاه» از مسیر واقعی فرمان")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        event = Event("فروشگاه", 777)
        await handler(event)
        return bot, event

    bot, event = asyncio.run(scenario())
    check("ربات پاسخ داد", bool(event.replies),
          "*** هیچ پاسخی نیامد ***")
    check("منوی فروشگاه باز شد", event.said("🛒 فروشگاه"))
    check("گزینهٔ لیست آیتم‌ها هست", event.said("لیست آیتم‌ها"))
    check("گزینهٔ خرید هست", event.said("خرید"))
    check("route در لاگ ثبت شد", bot.logger.has("ECONOMY SHOP MENU"))


# ===========================================================================
# عملیات واقعی روی دیتابیس
# ===========================================================================
def test_conversion_writes_to_database():
    print("\n### 💾 تبدیل واقعاً روی دیتابیس می‌نشیند")
    fresh()
    economy.add_bronze(CHAT, 777, 250)
    economy.add_silver(CHAT, 777, 100)
    before = economy.get_balance(CHAT, 777)

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("موجودی", 777))
        first = Event("1", 777)
        await handler(first)
        second = Event("2", 777)
        await handler(second)
        return first, second

    first, second = asyncio.run(scenario())
    check("تبدیل برنز پاسخ داد", first.said("تبدیل شد"))
    check("تبدیل نقره پاسخ داد", second.said("تبدیل شد"))

    after = economy.get_balance(CHAT, 777)
    check("برنز واقعاً کم شد",
          after[economy.BRONZE] == before[economy.BRONZE] - 100,
          f"-> {after[economy.BRONZE]}")
    check("طلا واقعاً اضافه شد", after[economy.GOLD] == 10,
          f"-> {after[economy.GOLD]}")

    # اثبات نوشته شدن روی دیسک، نه فقط حافظه
    raw = json.loads(storage.DATA_FILE.read_text(encoding="utf-8"))
    stored = raw["users"][economy.user_key(CHAT, 777)]
    check("مقدار روی دیسک ذخیره شد",
          stored["gold"] == 10 and stored["bronze"] == 150,
          f"-> {stored['gold']}/{stored['bronze']}")
    check("ارزش کل روی دیسک بازمحاسبه شد",
          stored["total_coin_value"] == after["total_coin_value"])
    check("تراکنش‌ها روی دیسک ثبت شدند",
          len(stored["transactions"]) >= 2)


def test_daily_and_history_from_menu():
    print("\n### 💾 جایزه روزانه و تاریخچه از داخل منو")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("موجودی", 777))
        daily = Event("7", 777)
        await handler(daily)
        again = Event("7", 777)
        await handler(again)
        history = Event("6", 777)
        await handler(history)
        return daily, again, history

    daily, again, history = asyncio.run(scenario())
    check("جایزه روزانه پرداخت شد", daily.said("جایزه روزانه دریافت شد"))
    check("موجودی واقعاً بالا رفت",
          economy.get_balance(CHAT, 777)[economy.BRONZE] == 25,
          f"-> {economy.get_balance(CHAT, 777)[economy.BRONZE]}")
    check("دریافت دوباره رد شد", again.said("قبلاً دریافت"))
    check("موجودی دوباره اضافه نشد",
          economy.get_balance(CHAT, 777)[economy.BRONZE] == 25)
    check("تاریخچه نمایش داده شد", history.said("تاریخچه تراکنش"))
    check("تراکنش در دیتابیس هست",
          len(economy.transaction_history(CHAT, 777)) == 1)


def test_transfer_from_menu_writes_db():
    print("\n### 💾 انتقال از داخل منو روی دیتابیس")
    fresh()
    economy.add_bronze(CHAT, 777, 100)
    # انتقال با یوزرنیم انجام می‌شود، پس مقصد باید در دفترچه باشد.
    economy.directory.remember(CHAT, 888, "@hosein")
    storage.flush()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("موجودی", 777))
        prompt = Event("3", 777)
        await handler(prompt)
        await handler(Event("@hosein", 777))
        amount = Event("40", 777)
        await handler(amount)
        return prompt, amount

    prompt, amount = asyncio.run(scenario())
    check("راهنمای انتقال آمد", prompt.said("انتقال برنز"))
    check("یوزرنیم خواسته شد", prompt.said("یوزرنیم کاربر مقصد"))
    check("انتقال انجام شد", amount.said("منتقل شد"))
    check("از فرستنده واقعاً کم شد",
          economy.get_balance(CHAT, 777)[economy.BRONZE] == 60,
          f"-> {economy.get_balance(CHAT, 777)[economy.BRONZE]}")
    check("به گیرنده واقعاً رسید",
          economy.get_balance(CHAT, 888)[economy.BRONZE] == 40,
          f"-> {economy.get_balance(CHAT, 888)[economy.BRONZE]}")

    raw = json.loads(storage.DATA_FILE.read_text(encoding="utf-8"))
    check("هر دو طرف روی دیسک ذخیره شدند",
          raw["users"][economy.user_key(CHAT, 777)]["bronze"] == 60
          and raw["users"][economy.user_key(CHAT, 888)]["bronze"] == 40)


def test_shop_buy_from_menu_writes_db():
    print("\n### 💾 خرید از فروشگاه روی دیتابیس")
    fresh()
    economy.shop.add_item("badge", "نشان طلایی", 50, "bronze", stock=1)
    economy.add_bronze(CHAT, 777, 120)

    async def scenario():
        bot, handler = await build_handler()
        listing = Event("فروشگاه", 777)
        await handler(listing)
        prompt = Event("1", 777)
        await handler(prompt)
        await handler(Event("badge", 777))
        buy = Event("تایید", 777)
        await handler(buy)
        return listing, prompt, buy

    listing, prompt, buy = asyncio.run(scenario())
    check("آیتم در فهرست دیده شد", listing.said("نشان طلایی"))
    check("راهنمای خرید آمد", prompt.said("برای لغو"))
    check("خرید انجام شد", buy.said("خریداری شد"))
    check("سکه واقعاً کسر شد",
          economy.get_balance(CHAT, 777)[economy.BRONZE] == 70,
          f"-> {economy.get_balance(CHAT, 777)[economy.BRONZE]}")

    raw = json.loads(storage.DATA_FILE.read_text(encoding="utf-8"))
    check("خرید روی دیسک ثبت شد",
          len(raw["users"][economy.user_key(CHAT, 777)].get("purchases", [])) == 1)
    check("تراکنش خرید ثبت شد",
          economy.transaction_history(CHAT, 777)[0]["kind"] == "purchase")


def test_game_reward_reaches_economy_via_real_route():
    print("\n### 💾 جایزهٔ بازی از مسیر واقعی به اقتصاد می‌رسد")
    fresh()
    import modules.emoji_guess as eg
    eg.reset_all()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("حدس ایموجی", 777))
        puzzle = eg.active_state(CHAT, 777)
        if puzzle is None:
            return None
        answer = Event(puzzle["answer"], 777)
        await handler(answer)
        return answer

    answer = asyncio.run(scenario())
    check("بازی از مسیر واقعی شروع شد", answer is not None)
    if answer is not None:
        check("پاسخ درست پذیرفته شد", answer.said("پاسخ صحیح"))
        balance = economy.get_balance(CHAT, 777)
        check("جایزه در اقتصاد ثبت شد",
              balance[economy.BRONZE] == eg.REWARD_BRONZE,
              f"-> {balance[economy.BRONZE]}")
        raw = json.loads(storage.DATA_FILE.read_text(encoding="utf-8"))
        check("جایزه روی دیسک ذخیره شد",
              raw["users"][economy.user_key(CHAT, 777)]["bronze"] == eg.REWARD_BRONZE)
    eg.reset_all()


# ===========================================================================
# رفتار درست در گروه غیرفعال
# ===========================================================================
def test_inactive_group_blocks():
    print("\n### 🚫 گروه غیرفعال: هیچ پاسخی داده نمی‌شود")
    fresh()
    group_storage.deactivate_group(CHAT, "گروه تست")

    async def scenario():
        bot, handler = await build_handler()
        event = Event("موجودی", 777)
        await handler(event)
        return event

    event = asyncio.run(scenario())
    check("در گروه غیرفعال پاسخی نمی‌آید", not event.replies,
          f"-> {event.replies}")
    group_storage.activate_group(CHAT, "گروه تست")


def test_unregistered_group_blocks():
    print("\n### 🚫 گروه ثبت‌نشده: هیچ پاسخی داده نمی‌شود")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        event = Event("موجودی", 777, chat_id=OTHER_CHAT)
        await handler(event)
        return event

    event = asyncio.run(scenario())
    check("در گروه ثبت‌نشده پاسخی نمی‌آید", not event.replies,
          f"-> {event.replies}")


def test_unrelated_text_passes_through():
    print("\n### 🔒 متن نامرتبط منو را خراب نمی‌کند")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("موجودی", 777))
        junk = Event("سلام بچه‌ها", 777)
        await handler(junk)
        menu = Event("موجودی", 777)
        await handler(menu)
        return junk, menu

    junk, menu = asyncio.run(scenario())
    check("پیام نامرتبط پاسخ اقتصادی نمی‌گیرد",
          not junk.said("کیف پول"), f"-> {junk.replies}")
    check("منو هنوز کار می‌کند", menu.said("کیف پول شما"))


# ===========================================================================
# لاگ تشخیصی و مقاومت در برابر خطا
# ===========================================================================
def test_diagnostic_logging():
    """مسیر کامل باید قابل ردیابی باشد: ورود، خواندن، رندر، ارسال."""
    print("\n### 🩺 لاگ تشخیصی کامل")
    fresh()
    economy.add_bronze(CHAT, 777, 152)
    economy.add_silver(CHAT, 777, 34)
    economy.add_gold(CHAT, 777, 8)

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("موجودی", 777))
        return bot

    bot = asyncio.run(scenario())
    for stage in ("ECONOMY HANDLER ENTER", "ECONOMY BALANCE READ",
                  "ECONOMY BALANCE RENDERED", "ECONOMY BALANCE MENU SENT"):
        check(f"لاگ «{stage}» ثبت شد", bot.logger.has(stage))

    read = [m for m in bot.logger.info if "ECONOMY BALANCE READ" in m]
    check("مقدار واقعی موجودی لاگ شد",
          read and "bronze=152" in read[0] and "gold=8" in read[0],
          f"-> {read[:1]}")
    check("ارزش کل لاگ شد",
          read and "total_coin_value=1292" in read[0])
    check("مسیر فایل دیتابیس لاگ شد",
          read and "db_file=" in read[0])


def test_shop_diagnostic_logging():
    print("\n### 🩺 لاگ تشخیصی فروشگاه")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("فروشگاه", 777))
        return bot

    bot = asyncio.run(scenario())
    check("لاگ ورود ثبت شد", bot.logger.has("ECONOMY HANDLER ENTER"))
    check("لاگ خواندن فروشگاه ثبت شد", bot.logger.has("ECONOMY SHOP READ"))
    check("لاگ ارسال ثبت شد", bot.logger.has("ECONOMY SHOP MENU SENT"))


def test_entity_rejection_falls_back_to_plain():
    """اگر سرور entity را نپذیرد، متن ساده فرستاده می‌شود، نه هیچ."""
    print("\n### 🛡️ پاسخ حتی وقتی سرور entity را رد کند")
    fresh()
    economy.add_bronze(CHAT, 777, 152)

    class RejectingEvent(Event):
        async def reply(self, text, **kwargs):
            if kwargs.get("formatting_entities"):
                raise ValueError("ENTITY_BOUNDS_INVALID")
            self.replies.append(text)

    async def scenario():
        bot, handler = await build_handler()
        event = RejectingEvent("موجودی", 777)
        await handler(event)
        return bot, event

    bot, event = asyncio.run(scenario())
    check("کاربر همچنان پاسخ می‌گیرد", bool(event.replies),
          "*** هیچ خروجی نیامد ***")
    check("متن کامل منو ارسال شد",
          event.said("کیف پول شما") and event.said("۱۵۲"))
    check("بازگشت به متن ساده لاگ شد",
          bot.logger.has("retrying plain"))


def test_unexpected_error_is_reported():
    """هر خطای غیرمنتظره باید هم لاگ شود هم به کاربر گفته شود."""
    print("\n### 🛡️ خطای غیرمنتظره بی‌صدا نمی‌ماند")
    fresh()
    import economy.ui.balance_menu as bm
    original = bm.render_menu

    def boom(user_id):
        raise RuntimeError("db unavailable")

    bm.render_menu = boom
    try:
        async def scenario():
            bot, handler = await build_handler()
            event = Event("موجودی", 777)
            await handler(event)
            return bot, event

        bot, event = asyncio.run(scenario())
        check("خطا در لاگ ثبت شد",
              bot.logger.has("ECONOMY BALANCE MENU FAILED"))
        check("traceback ثبت شد", bot.logger.has("Traceback"))
        check("به کاربر اطلاع داده شد", event.said("خطا در نمایش موجودی"))
    finally:
        bm.render_menu = original


def test_repeated_command_not_swallowed():
    """ارسال پیاپی «موجودی» نباید توسط ضداسپم بلعیده شود."""
    print("\n### 🔁 ارسال پیاپی دستور")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        results = []
        for _ in range(5):
            event = Event("موجودی", 777)
            await handler(event)
            results.append(bool(event.replies))
        return results

    results = asyncio.run(scenario())
    check("هر ۵ بار پاسخ داده شد", all(results), f"-> {results}")


def test_owner_outgoing_message_works():
    """در userbot، پیام خود مالک event.out=True دارد."""
    print("\n### 👤 پیام خروجی مالک در حالت userbot")
    fresh()
    import modules.owner_check as oc
    owner_id = oc.get_owner()["user_id"]

    async def scenario():
        bot, handler = await build_handler()
        event = Event("موجودی", owner_id)
        event.out = True
        event._user = User(owner_id, "osine1", username="osine1")
        await handler(event)
        return event

    event = asyncio.run(scenario())
    check("پیام خروجی مالک هم پاسخ می‌گیرد", bool(event.replies),
          "*** هیچ خروجی نیامد ***")
    check("منو باز شد", event.said("کیف پول شما"))


# ===========================================================================
# پیوی — این دستورها فقط در گروه کار می‌کنند
# ===========================================================================
class PrivateEvent(Event):
    """پیام خصوصی: is_private=True و peer یک کاربر است، نه گروه."""

    def __init__(self, text, user_id, reply_target=None):
        super().__init__(text, user_id, chat_id=user_id,
                         reply_target=reply_target)
        self.is_private = True

    async def get_chat(self):
        return User(self._chat_id)


def test_private_is_blocked():
    """دستورهای اقتصاد فقط مخصوص گروه‌اند و در پیوی نباید کار کنند."""
    print("\n### 🚫 اقتصاد در پیوی کار نمی‌کند")
    fresh()
    economy.add_bronze(CHAT, 777, 152)

    async def scenario(text):
        bot, handler = await build_handler()
        event = PrivateEvent(text, 777)
        await handler(event)
        return event

    for text in ("موجودی", "فروشگاه"):
        event = asyncio.run(scenario(text))
        check(f"«{text}» در پیوی پاسخی نمی‌دهد", not event.replies,
              f"-> {event.replies}")

    check("هیچ session ای در پیوی باز نشد",
          not balance_menu.is_open(777, 777)
          and not shop_menu.is_open(777, 777))


def test_group_still_works():
    """همان دستورها در گروه باید کار کنند."""
    print("\n### ✅ اقتصاد فقط در گروه کار می‌کند")
    fresh()
    economy.add_bronze(CHAT, 777, 152)

    async def scenario(text):
        bot, handler = await build_handler()
        event = Event(text, 777)
        await handler(event)
        return event

    balance = asyncio.run(scenario("موجودی"))
    check("«موجودی» در گروه کار می‌کند", balance.said("کیف پول شما"))
    shop = asyncio.run(scenario("فروشگاه"))
    check("«فروشگاه» در گروه کار می‌کند", shop.said("🛒 فروشگاه"))


def test_ranking_display_format():
    """«رتبه ها» باید شمارهٔ رتبه را با ایموجی عددی نشان دهد، نه مدال."""
    print("\n### 🏆 قالب نمایش برترین کاربران")
    fresh()
    economy.award(CHAT, 101, 700, name="@user_a")
    economy.award(CHAT, 102, 200, name="@user_b")
    economy.award(CHAT, 103, 50, name="@user_c")

    async def scenario():
        bot, handler = await build_handler()
        event = Event("رتبه ها", 424242, chat_id=CHAT)
        await handler(event)
        return event

    event = asyncio.run(scenario())
    check("پاسخ داده شد", bool(event.replies))
    text = event.replies[0] if event.replies else ""

    check("شمارهٔ رتبه با ایموجی عددی است",
          "1️⃣" in text and "2️⃣" in text and "3️⃣" in text, f"-> {text[:60]}")

    # مدال نباید به عنوان «شمارهٔ رتبه» در ابتدای خط بیاید
    rank_lines = [l for l in text.splitlines() if "—" in l]
    check("هیچ خط رتبه‌ای با مدال شروع نمی‌شود",
          not any(l.strip().startswith(("🥇", "🥈", "🥉")) for l in rank_lines),
          f"-> {rank_lines[:1]}")
    check("خط رتبه با ایموجی عددی شروع می‌شود",
          rank_lines and rank_lines[0].strip().startswith("1️⃣"))

    # مدال‌ها فقط برای نوع سکه در خط دوم می‌مانند
    check("مدال‌ها فقط کنار مقدار سکه‌ها هستند",
          "🥉" in text and "🥈" in text and "🥇" in text)

    # سکه‌های قدیمی باید برنز باشند و 💎 برابر برنز
    digits = str.maketrans("𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵", "0123456789")
    plain = text.translate(digits)
    check("کاربر ۷۰۰ سکه‌ای، ۷۰۰ برنز دارد", "🥉 700" in plain, f"-> {plain[:120]}")
    check("ارزش کل برابر برنز است", "💎 700" in plain)
    check("نقره و طلا صفرند", "🥈 0" in plain and "🥇 0" in plain)


def test_legacy_coin_migration():
    """سکه‌های سیستم قدیمی باید به برنز تبدیل شوند و دوباره اضافه نشوند."""
    print("\n### 🪙 انتقال سکه‌های قدیمی به برنز")
    fresh()
    import tools.migrate_legacy_coins as mig

    original = mig.LEGACY_FILE
    temp = Path(tempfile.mkdtemp()) / "coins.json"
    temp.write_text(json.dumps({"users": {
        str(economy.chat_key(CHAT)): {
            "501": {"coins": 800, "wins": 4, "name": "@a"},
            "502": {"coins": 28, "wins": 0, "name": "@b"}},
    }}, ensure_ascii=False), encoding="utf-8")
    mig.LEGACY_FILE = temp
    try:
        mig.migrate()
        first = economy.get_balance(CHAT, 501)
        check("سکهٔ چند گروه جمع شد", first[economy.BRONZE] == 800,
              f"-> {first[economy.BRONZE]}")
        check("ارزش کل برابر برنز است",
              first["total_coin_value"] == 800)
        check("نقره و طلا دست‌نخورده صفرند",
              first[economy.SILVER] == 0 and first[economy.GOLD] == 0)
        check("کاربر ۲۸ سکه‌ای درست منتقل شد",
              economy.get_balance(CHAT, 502)[economy.BRONZE] == 28)
        check("بردها منتقل شدند", economy.get_profile(CHAT, 501)["wins"] == 4)

        mig.migrate()
        check("اجرای دوباره سکه را دو برابر نمی‌کند",
              economy.get_balance(CHAT, 501)[economy.BRONZE] == 800,
              f"-> {economy.get_balance(CHAT, 501)[economy.BRONZE]}")
        check("فایل قدیمی حذف نشد", temp.exists())
    finally:
        mig.LEGACY_FILE = original


def test_runtime_data_is_not_tracked_by_git():
    """گارد: فایل‌های دادهٔ کاربران نباید در گیت باشند.

    اگر config/economy.json ردیابی شود، هر pull موجودی واقعی کاربران روی
    گوشی را با نسخهٔ مخزن بازنویسی یا merge را متوقف می‌کند.
    """
    print("\n### 🔒 دادهٔ کاربران در گیت ردیابی نمی‌شود")
    import subprocess

    for name in ("config/economy.json", "config/economy_shop.json",
                 "config/economy_settings.json"):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", name],
            cwd=ROOT, capture_output=True, text=True).returncode == 0
        check(f"{name} ردیابی نمی‌شود", not tracked)

        ignored = subprocess.run(
            ["git", "check-ignore", name],
            cwd=ROOT, capture_output=True, text=True).returncode == 0
        check(f"{name} در gitignore هست", ignored)


def test_migration_merges_into_existing_wallets():
    """انتقال باید به موجودی فعلی «اضافه» کند، نه جایگزین."""
    print("\n### 🪙 انتقال، دادهٔ موجود گوشی را حفظ می‌کند")
    fresh()
    import tools.migrate_legacy_coins as mig

    # کیف پول‌هایی که از قبل روی دستگاه هستند
    economy.add_bronze(CHAT, 501, 5000)
    economy.add_silver(CHAT, 501, 40)
    economy.add_gold(CHAT, 501, 7)
    economy.award(CHAT, 777, 250, name="@untouched")

    original = mig.LEGACY_FILE
    temp = Path(tempfile.mkdtemp()) / "coins.json"
    temp.write_text(json.dumps({"users": {str(economy.chat_key(CHAT)): {
        "501": {"coins": 700, "wins": 2, "name": "@a"},
        "888": {"coins": 28, "wins": 0, "name": "@b"},
    }}}, ensure_ascii=False), encoding="utf-8")
    mig.LEGACY_FILE = temp
    try:
        mig.migrate()
        merged = economy.get_balance(CHAT, 501)
        check("برنز قبلی حفظ و جمع شد",
              merged[economy.BRONZE] == 5700, f"-> {merged[economy.BRONZE]}")
        check("نقرهٔ موجود دست‌نخورد", merged[economy.SILVER] == 40)
        check("طلای موجود دست‌نخورد", merged[economy.GOLD] == 7)
        check("کاربر بی‌ارتباط دست‌نخورد",
              economy.get_balance(CHAT, 777)[economy.BRONZE] == 250)
        check("کاربر جدید اضافه شد",
              economy.get_balance(CHAT, 888)[economy.BRONZE] == 28)
    finally:
        mig.LEGACY_FILE = original


def test_handler_never_drops_message_silently():
    """گارد: هر استثنا در هندلر باید لاگ شود، نه اینکه پیام بی‌صدا بیفتد."""
    print("\n### ⛑️ نگهبان سراسری هندلر پیام")
    fresh()
    import core.bot_working_split_ok as core

    async def scenario():
        bot, handler = await build_handler()
        original = core.normalize_command_text
        core.normalize_command_text = lambda t: (_ for _ in ()).throw(
            RuntimeError("injected failure"))
        escaped = False
        try:
            await handler(Event("سلام", 424242, chat_id=CHAT))
        except Exception:
            escaped = True
        finally:
            core.normalize_command_text = original
        # بعد از خطا، ربات باید همچنان کار کند
        ok = Event("موجودی", 424242, chat_id=CHAT)
        await handler(ok)
        return bot, escaped, ok

    bot, escaped, ok = asyncio.run(scenario())
    check("استثنا از هندلر بیرون نمی‌زند", not escaped)
    check("خطا در لاگ ثبت می‌شود",
          any("MESSAGE HANDLER CRASHED" in e for e in bot.logger.errors))
    check("traceback ثبت می‌شود",
          any("Traceback" in e for e in bot.logger.errors))
    check("ربات بعد از خطا همچنان پاسخ می‌دهد", bool(ok.replies))


def test_per_group_isolation():
    """گروه A و گروه B باید کیف پول و رتبه‌بندی کاملاً جدا داشته باشند."""
    print("\n### 🔒 جدا بودن اقتصاد هر گروه")
    fresh()
    GROUP_A = -1001111111111
    GROUP_B = -1002222222222
    group_storage.activate_group(GROUP_A, "A")
    group_storage.activate_group(GROUP_B, "B")

    economy.award(GROUP_A, 1001, 100, name="user1")
    economy.award(GROUP_B, 1002, 50, name="user2")

    check("user1 در گروه A صد سکه دارد",
          economy.get_balance(GROUP_A, 1001)[economy.BRONZE] == 100)
    check("user1 در گروه B صفر است",
          economy.get_balance(GROUP_B, 1001)[economy.BRONZE] == 0)
    check("user2 در گروه B پنجاه سکه دارد",
          economy.get_balance(GROUP_B, 1002)[economy.BRONZE] == 50)
    check("user2 در گروه A صفر است",
          economy.get_balance(GROUP_A, 1002)[economy.BRONZE] == 0)

    a_ids = [r["user_id"] for r in economy.leaderboard(GROUP_A, 5)]
    b_ids = [r["user_id"] for r in economy.leaderboard(GROUP_B, 5)]
    check("رتبهٔ گروه A فقط user1", a_ids == ["1001"], f"-> {a_ids}")
    check("رتبهٔ گروه B فقط user2", b_ids == ["1002"], f"-> {b_ids}")

    check("رتبهٔ user1 در گروه A یک است",
          economy.get_rank(GROUP_A, 1001) == 1)
    check("user1 در گروه B رتبه ندارد",
          economy.get_rank(GROUP_B, 1001) is None)

    async def scenario(group):
        bot, handler = await build_handler()
        event = Event("رتبه ها", 1001, chat_id=group)
        await handler(event)
        return event

    a_out = asyncio.run(scenario(GROUP_A))
    b_out = asyncio.run(scenario(GROUP_B))
    check("خروجی «رتبه ها» گروه A فقط user1",
          a_out.said("user1") and not a_out.said("user2"))
    check("خروجی «رتبه ها» گروه B فقط user2",
          b_out.said("user2") and not b_out.said("user1"))

    # جایزه، تبدیل و انتقال هم باید per-group باشند
    economy.add_bronze(GROUP_A, 1001, 100)
    economy.convert_bronze(GROUP_A, 1001)
    check("تبدیل فقط روی گروه A اثر گذاشت",
          economy.get_balance(GROUP_A, 1001)[economy.SILVER] == 12
          and economy.get_balance(GROUP_B, 1001)[economy.SILVER] == 0)

    economy.award(GROUP_A, 1003, 30, name="user3")
    economy.transfer(GROUP_A, 1003, 1001, economy.BRONZE, 10)
    check("انتقال داخل گروه A انجام شد",
          economy.get_balance(GROUP_A, 1003)[economy.BRONZE] == 20)
    check("گروه B از انتقال متاثر نشد",
          economy.get_balance(GROUP_B, 1003)[economy.BRONZE] == 0)


def main():
    test_handler_is_registered()
    test_balance_command_routed()
    test_shop_command_routed()
    test_conversion_writes_to_database()
    test_daily_and_history_from_menu()
    test_transfer_from_menu_writes_db()
    test_shop_buy_from_menu_writes_db()
    test_game_reward_reaches_economy_via_real_route()
    test_inactive_group_blocks()
    test_unregistered_group_blocks()
    test_unrelated_text_passes_through()
    test_diagnostic_logging()
    test_shop_diagnostic_logging()
    test_entity_rejection_falls_back_to_plain()
    test_unexpected_error_is_reported()
    test_repeated_command_not_swallowed()
    test_owner_outgoing_message_works()
    test_private_is_blocked()
    test_group_still_works()
    test_ranking_display_format()
    test_legacy_coin_migration()
    test_runtime_data_is_not_tracked_by_git()
    test_migration_merges_into_existing_wallets()
    test_handler_never_drops_message_silently()
    test_per_group_isolation()

    print("\n" + "=" * 52)
    print(f"passed={PASSED} failed={FAILED}")
    print("=" * 52)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
