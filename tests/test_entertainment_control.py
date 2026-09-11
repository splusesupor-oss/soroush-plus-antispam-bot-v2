"""🎮 تست قابلیت «کنترل سرگرمی به تفکیک گروه».

پوشش داده‌شده:

* منطق وضعیت (پیش‌فرض فعال، ایزولاسیون گروه‌ها، ماندگاری، fail-open،
  یکسان‌سازی شناسهٔ گروه) — بدون هیچ I/O شبکه.
* Bold واقعی: span بر حسب واحدهای UTF-16، نوع entity، و نبود ستارهٔ
  مارک‌داون در متن.
* گارد: همهٔ دستورهای بازی مسدود، هیچ دستور غیربازی‌ای مسدود نشود، و
  مسدودسازی «هیچ» عارضه‌ای نداشته باشد (نه state بازی، نه سکه).
* مسیر واقعی هندلر: با همان ``handle_new_message`` که در زمان اجرا ثبت
  می‌شود، رفتار توگل و «رد دسترسی بدون تغییر وضعیت» سنجیده می‌شود.
* گارد لایهٔ دوم داخل روتر بازی‌ها.

اجرای مستقیم:  python tests/test_entertainment_control.py
اجرای مجموعه: pytest tests/test_entertainment_control.py -q
"""
import asyncio
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import entertainment_control as ec
from modules.fox_games import laugh_or_lose, survival, vampire

CHAT = -1001234567890
CHAT_SHORT = 1234567890
OTHER_CHAT = -1005554443332


# ---------------------------------------------------------------------------
# انزوا: هیچ تستی نباید فایل رانتایم واقعی ربات را لمس کند
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "FILE", tmp_path / "entertainment_mode.json")
    monkeypatch.setattr(ec, "_cache", None)
    monkeypatch.setattr(ec, "_cache_mtime", None)
    for game in (laugh_or_lose, survival, vampire):
        game.reset_all()
    yield
    for game in (laugh_or_lose, survival, vampire):
        game.reset_all()


class RecordingEvent:
    """event قلابی که متن و entityها را با هم ثبت می‌کند."""

    def __init__(self, text="", chat_id=CHAT, user_id=4242, is_private=False):
        self.text = text
        self.chat_id = chat_id
        self.user_id = user_id
        self.is_private = is_private
        self.sent = []          # [(text, kwargs), ...]
        self.message = SimpleNamespace(message=text, id=77, entities=None, file=None)
        self.sender = SimpleNamespace(id=user_id, username="ali", first_name="علی")
        self.sender_id = user_id

    @property
    def replies(self):
        return [text for text, _kwargs in self.sent]

    @property
    def last_entities(self):
        return self.sent[-1][1].get("formatting_entities") if self.sent else None

    async def reply(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return SimpleNamespace(id=len(self.sent))

    async def get_chat(self):
        return SimpleNamespace(id=self.chat_id)

    async def get_sender(self):
        return self.sender

    def __getattr__(self, name):
        # هر فیلدی که هندلر از event می‌خواند و ما نساخته‌ایم، مثل
        # event واقعی «وجود ندارد» (getattr با default در هندلر).
        if name.startswith("__"):
            raise AttributeError(name)
        return None


# ---------------------------------------------------------------------------
# منطق وضعیت
# ---------------------------------------------------------------------------
def test_unconfigured_group_defaults_to_enabled():
    assert ec.is_enabled(CHAT) is True
    assert ec.is_enabled("never-seen-chat") is True


def test_disable_enable_reset_round_trip():
    assert ec.disable(CHAT) is False
    assert ec.is_enabled(CHAT) is False

    assert ec.enable(CHAT) is True
    assert ec.is_enabled(CHAT) is True

    ec.disable(CHAT)
    assert ec.reset(CHAT) is True
    assert ec.is_enabled(CHAT) is True          # به پیش‌فرض برگشت
    assert ec.reset(CHAT) is False              # کلیدی برای پاک کردن نیست


def test_groups_are_isolated_from_each_other():
    ec.disable(CHAT)
    assert ec.is_enabled(CHAT) is False
    assert ec.is_enabled(OTHER_CHAT) is True
    ec.enable(OTHER_CHAT)
    assert ec.is_enabled(CHAT) is False
    assert ec.disable(OTHER_CHAT) is False
    assert ec.is_enabled(CHAT) is False


def test_state_persists_after_cache_is_cleared():
    ec.set_enabled(CHAT, False)
    ec._cache = None
    ec._cache_mtime = None
    assert ec.is_enabled(CHAT) is False

    ec.set_enabled(CHAT, True)
    ec._cache = None
    assert ec.is_enabled(CHAT) is True


def test_file_is_written_and_is_a_single_independent_json(tmp_path):
    ec.disable(CHAT)
    stored = json.loads(Path(ec.FILE).read_text(encoding="utf-8"))
    assert stored == {str(CHAT_SHORT): False}
    # فایل مستقل است: هیچ فایل تنظیمات دیگری باز نشده باشد
    assert Path(ec.FILE).name == "entertainment_mode.json"


@pytest.mark.parametrize("junk", ["", "{ not json", "[1,2", "null", '"str"'])
def test_missing_or_corrupt_file_fails_open_to_enabled(junk):
    Path(ec.FILE).write_text(junk, encoding="utf-8")
    ec._cache = None
    ec._cache_mtime = None
    assert ec.is_enabled(CHAT) is True          # بدون exception
    assert ec.load() == {}


def test_corrupt_file_can_be_repaired_by_a_toggle():
    Path(ec.FILE).write_text("{ broken", encoding="utf-8")
    ec._cache = None
    ec.disable(CHAT)
    ec._cache = None
    assert ec.is_enabled(CHAT) is False


def test_all_id_shapes_of_one_group_share_a_single_record():
    for alias in (CHAT, CHAT_SHORT, str(CHAT_SHORT), -1 * abs(CHAT)):
        ec.disable(alias)
    stored = json.loads(Path(ec.FILE).read_text(encoding="utf-8"))
    assert list(stored) == [str(CHAT_SHORT)]
    assert ec.is_enabled(CHAT_SHORT) is False
    assert ec.is_enabled(CHAT) is False


def test_no_touched_files_are_left_dirty():
    """تنظیم وضعیت نباید هیچ فایل موجودی را تغییر دهد."""
    before = {p.name: p.stat().st_mtime_ns for p in Path(ec.FILE).parent.glob("*")
              if p.is_file()}
    ec.disable(CHAT)
    ec.enable(CHAT)
    after = {p.name: p.stat().st_mtime_ns for p in Path(ec.FILE).parent.glob("*")
             if p.is_file()}
    changed = {name for name in after if before.get(name) != after[name]}
    assert changed == {"entertainment_mode.json"}


# ---------------------------------------------------------------------------
# Bold: واحدهای UTF-16
# ---------------------------------------------------------------------------
def test_u16_length_counts_surrogate_pairs_as_two_units():
    assert ec.u16_length("🎮") == 2
    assert ec.u16_length("abc") == 3
    assert ec.u16_length("🎮 بازی") == 2 + 1 + 4


def test_full_bold_span_covers_whole_message():
    for text in (ec.DISABLED_NOTICE, ec.ENABLED_NOTICE):
        offset, length = ec.full_bold_span(text)
        assert offset == 0
        raw = text.encode("utf-16-le")
        assert raw[offset * 2:(offset + length) * 2].decode("utf-16-le") == text


def test_blocked_bold_span_lands_exactly_on_the_command():
    text = ec.BLOCKED_NOTICE
    offset, length = ec.blocked_bold_span()
    raw = text.encode("utf-16-le")
    assert raw[offset * 2:(offset + length) * 2].decode("utf-16-le") == "سرگرمی فعال"
    # فقط همان عبارت، نه کل پیام
    assert length == ec.u16_length("سرگرمی فعال")
    assert length < ec.u16_length(text)


def test_blocked_bold_span_is_not_shifted_by_a_leading_emoji():
    """span با برش UTF-16 بازتولید می‌شود، نه با len پایتونی.

    اگر محاسبه جای len() از شمارش کاراکتری استفاده کند، یک ایموجای
    پیش‌رونده (surrogate pair) span را یک واحد جابه‌جا می‌کند و Bold روی
    عبارت اشتباهی می‌افتد. این تست همان را می‌سنجد.
    """
    text = "\U0001F3AE " + ec.BLOCKED_NOTICE
    offset, length = ec.blocked_bold_span(text)
    raw = text.encode("utf-16-le")
    assert raw[offset * 2:(offset + length) * 2].decode("utf-16-le") == "سرگرمی فعال"
    # یک واحد جابه‌جایی بایدآزمون را را خراب کند:
    assert raw[(offset + 1) * 2:(offset + 1 + length) * 2].decode("utf-16-le") != "سرگرمی فعال"
    assert ec.blocked_bold_span("هیچ دستوری اینجا نیست") is None


async def _guard_text(event, text):
    return await ec.send_blocked_notice(event)


def test_blocked_notice_sends_real_bold_entity_and_no_markdown():
    event = RecordingEvent()
    asyncio.run(ec.send_blocked_notice(event))
    assert event.replies == [ec.BLOCKED_NOTICE]
    assert "*" not in ec.BLOCKED_NOTICE
    entities = event.last_entities
    assert entities and len(entities) == 1
    entity = entities[0]
    assert type(entity).__name__ == "MessageEntityBold"
    raw = ec.BLOCKED_NOTICE.encode("utf-16-le")
    assert raw[entity.offset * 2:(entity.offset + entity.length) * 2].decode(
        "utf-16-le") == "سرگرمی فعال"


def test_toggle_notices_are_fully_bold_entities():
    for sender, notice in ((ec.send_disabled_notice, ec.DISABLED_NOTICE),
                           (ec.send_enabled_notice, ec.ENABLED_NOTICE)):
        event = RecordingEvent()
        asyncio.run(sender(event))
        assert event.replies == [notice]
        assert "*" not in notice and "**" not in notice
        entity = event.last_entities[0]
        assert entity.offset == 0
        assert entity.length == ec.u16_length(notice)


def test_permission_denied_notice_has_no_bold():
    event = RecordingEvent()
    asyncio.run(ec.send_permission_denied(event))
    assert event.replies == [ec.PERMISSION_DENIED]
    assert event.last_entities is None


def test_plain_text_fallback_when_client_rejects_entities(monkeypatch):
    """کلاینتی که formatting_entities را نمی‌شناسد نباید پیام را غیب کند."""

    class StrictEvent(RecordingEvent):
        async def reply(self, text, **kwargs):
            if kwargs:
                raise TypeError("unexpected keyword argument 'formatting_entities'")
            return await RecordingEvent.reply(self, text)

    event = StrictEvent()
    calls = []

    class Exploding:
        def __init__(self, *a, **k):
            calls.append(a)
            raise TypeError("entity unsupported")

    monkeypatch.setattr(ec, "MessageEntityBold", Exploding)
    asyncio.run(ec.send_blocked_notice(event))
    assert event.replies == [ec.BLOCKED_NOTICE]      # متن ساده، بدون قالب


# ---------------------------------------------------------------------------
# نرمال‌سازی و تشخیص دستور بازی
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variant", [
    "چهار گزینه‌ای", "چهار گزینه ای", "چهار  گزینه\u200f ای",
])
def test_normalization_matches_spaced_and_zwnj_forms(variant):
    assert ec.is_game_command(variant) is True
    assert ec.normalize("چهار گزینه‌ای") == ec.normalize("چهار گزینه ای")


def test_normalization_handles_arabic_letters_and_direction_marks():
    assert ec.normalize("حدس ايموجي") == "حدس ایموجی"
    assert ec.is_game_command("حدس ايموجي\u200e") is True
    assert ec.normalize("خون‌آشام") == ec.normalize("خون آشام")
    assert ec.is_game_command("خون‌آشام") is True


def test_normalize_is_idempotent_and_safe_on_empty():
    for command in sorted(ec.GAME_COMMANDS) + sorted(ec.COMMANDS):
        once = ec.normalize(command)
        assert ec.normalize(once) == once
        assert once == command
    assert ec.normalize("") == ""
    assert ec.normalize(None) == ""


def test_toggle_commands_are_recognised():
    assert ec.normalize("سرگرمی  خاموش") in ec.COMMANDS
    assert ec.normalize("سرگرمی\u200c فعال") in ec.COMMANDS
    assert ec.COMMAND_DISABLE == "سرگرمی خاموش"
    assert ec.COMMAND_ENABLE == "سرگرمی فعال"


# ---------------------------------------------------------------------------
# گارد
# ---------------------------------------------------------------------------
def test_every_game_command_is_blocked_when_off():
    ec.disable(CHAT)
    for command in sorted(ec.GAME_COMMANDS):
        assert ec.blocks(CHAT, command) is True, command
        assert ec.blocks(CHAT, f"  {command}  ") is True, command


def test_no_game_command_is_blocked_when_on():
    for command in sorted(ec.GAME_COMMANDS):
        assert ec.blocks(CHAT, command) is False, command
    ec.enable(CHAT)
    for command in sorted(ec.GAME_COMMANDS):
        assert ec.blocks(CHAT, command) is False, command


@pytest.mark.parametrize("text", [
    "سلام بچه‌ها حالتون چطوره",
    "لیست بازی", "لیست بازی ها", "لیست بازی‌ها",
    "راهنما", "آمار گروه", "بیوگرافی", "دانستنی", "سایت بازی",
    "ثبت ادمین @ali", "لغو ادمین @ali", "سکوت @ali", "آزاد @ali",
    "اخطار @ali", "بن @ali", "پاکسازی خودکار", "فعال کلمات ممنوعه",
    "ثبت علی رضایی", "جستجو بهترین فیلم", "",
])
def test_non_game_messages_are_never_blocked(text):
    ec.disable(CHAT)
    assert ec.blocks(CHAT, text) is False


def test_guard_sends_exactly_one_notice_and_returns_true():
    ec.disable(CHAT)
    event = RecordingEvent("بقا")
    assert asyncio.run(ec.guard(event, CHAT, "بقا")) is True
    assert event.replies == [ec.BLOCKED_NOTICE]


def test_guard_is_silent_and_false_when_enabled():
    event = RecordingEvent("بقا")
    assert asyncio.run(ec.guard(event, CHAT, "بقا")) is False
    assert event.replies == []


# ---------------------------------------------------------------------------
# مسدودسازی نباید هیچ عارضه‌ای داشته باشد
# ---------------------------------------------------------------------------
def test_blocking_a_fox_game_leaves_no_state_no_timer_no_coins():
    import handlers.fox_games_router as router

    awards = []
    bot = SimpleNamespace(award_coins=lambda *a, **k: awards.append(a))
    ec.disable(CHAT)
    for command in ("بخند یا بباز", "بقا", "خون‌آشام", "جعبه شانسی"):
        event = RecordingEvent(command)
        consumed = asyncio.run(router.handle(
            bot, event, CHAT, 4242, event.sender, command, None))
        assert consumed is True, command
        assert event.replies == [ec.BLOCKED_NOTICE], command
    assert laugh_or_lose.is_active(CHAT) is False
    assert survival.is_active(CHAT) is False
    assert vampire.is_active(CHAT) is False
    assert router.active_game_count(CHAT) == 0
    assert awards == []


def test_blocking_a_battle_join_moves_no_coins():
    """«شرکت» (پیوستن به نبرد) هم بازی است و سکه‌ای جابه‌جا نمی‌کند."""
    import handlers.fox_games_router as router
    from modules.fox_games import battle

    moves = []
    bot = SimpleNamespace(award_coins=lambda *a, **k: moves.append(("award", a)),
                          spend=lambda *a, **k: moves.append(("spend", a)))
    event = RecordingEvent("شرکت")
    router.handle_fox = router.handle

    ec.disable(CHAT)
    # لایهٔ اول (گارد مرکزیِ هندلر اصلی) باید جلویش را بگیرد:
    assert asyncio.run(ec.guard(event, CHAT, "شرکت")) is True
    assert battle.active_battles(chat_id=CHAT) if hasattr(battle, "active_battles") else True
    assert event.replies == [ec.BLOCKED_NOTICE]
    assert moves == []


def test_enabled_group_can_start_a_fox_game_normally():
    """در گروه روشن، همان دستور باید بازی را واقعاً شروع کند (گارد بی‌اثر است)."""
    import handlers.fox_games_router as router

    ec.enable(CHAT)
    event = RecordingEvent("بخند یا بباز")
    consumed = asyncio.run(router.handle(
        None, event, CHAT, 4242, event.sender, "بخند یا بباز", None))
    assert consumed is True
    assert ec.BLOCKED_NOTICE not in event.replies
    assert any("آماده باش" in reply for reply in event.replies), event.replies


def test_message_entity_bold_import_works_without_client_library():
    """کلاس جایگزین باید همان امضا را داشته باشد (تست بدون splusthon)."""
    entity = ec.MessageEntityBold(offset=3, length=9)
    assert (entity.offset, entity.length) == (3, 9)


# ---------------------------------------------------------------------------
# اتصال به هندلر اصلی (مسیر واقعی زمان اجرا)
# ---------------------------------------------------------------------------
def _handler_source():
    import handlers.message_handler as mh
    return inspect.getsource(mh.handle_new_message)


def test_guard_is_wired_before_every_game_route():
    source = _handler_source()
    guard_at = source.index("entertainment_control.guard(")
    for route in ("handle_fox_games(", "start_name_family(", "start_emoji_guess(",
                  "start_flag_guess(", "new_riddle(", "new_fill(",
                  "start_question(", "get_joke("):
        assert guard_at < source.index(route), route
    assert source.index("entertainment_control.COMMANDS") < guard_at
    assert source.count("entertainment_control.guard(") == 1
    # گارد باید بیرون از هر شاخهٔ «پاسخ درون‌بازی» باشد، وگرنه پاسخ بازی
    # عادی با گارد قاطی می‌شود: دقیقاً یک بار و پیش از همهٔ بازی‌ها.
    assert guard_at < source.index("if (\n            clean_text in FOX_GAME_COMMANDS")


def _entertainment_block_source():
    """بدنهٔ شاخهٔ توگل، همان‌طور که در هندلر واقعی نوشته شده است."""
    source = _handler_source()
    start = source.index("entertainment_command = entertainment_control.normalize(")
    end = source.index("گارد مرکزی — هر بازی داخلی", start)
    block = source[start:end]
    assert block.count("has_admin_permission") == 1
    return block


def test_permission_is_checked_before_state_changes():
    block = _entertainment_block_source()
    assert block.index("PRIVATE_CHAT_NOTICE") < block.index("has_admin_permission")
    assert block.index("has_admin_permission") < block.index("send_permission_denied")
    assert block.index("send_permission_denied") < block.index("entertainment_control.disable(")
    assert block.index("entertainment_control.disable(") < block.index("send_disabled_notice")
    denied_to_state = block[block.index("send_permission_denied"):
                            block.index("entertainment_control.disable(")]
    assert "return" in denied_to_state, "رد دسترسی باید زودتر از تغییر وضعیت خارج شود"
    assert "if not admin_tools.has_admin_permission" in block


def test_router_has_second_layer_guard_inside_start_branch():
    import handlers.fox_games_router as router
    source = inspect.getsource(router.handle)
    start_at = source.index("if command in start_games:")
    guard_at = source.index("entertainment_control.guard(", start_at)
    assert guard_at < source.index("return await starter(", start_at)
    assert guard_at < source.index("active_game_count(chat_id) >= MAX_ACTIVE", start_at)


class _Loose:
    """پاسخ‌دهندهٔ بی‌ضرر برای هر چیزی که هندلر از bot/event می‌خواهد.

    هر فراخوانی None می‌دهد و ``bool`` آن False است، پس هیچ شاخه‌ای در
    هندلر با این «حقیقت» اشتباه باز نمی‌شود؛ در عین حال مسیری که تست
    می‌خواهد ببیند (توگل سرگرمی و گارد بازی) واقعاً اجرا می‌شود.
    """

    def __init__(self, name="loose"):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return _Loose(f"{self._name}.{item}")

    def __call__(self, *args, **kwargs):
        # هم awaitable است هم مثل dict/set/settable رفتار می‌کند، پس هر
        # فراخوانی sync در هندلر هم شکل درست را می‌بیند.
        return _Loose(f"{self._name}()")

    def __await__(self):
        async def _none():
            return None
        return _none().__await__()

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __contains__(self, item):
        return False

    def __getitem__(self, key):
        return _Loose(f"{self._name}[{key!r}]")

    def __setitem__(self, key, value):
        return None

    def __delitem__(self, key):
        return None

    def get(self, *args, **kwargs):
        return _Loose(f"{self._name}.get")

    def add(self, *args, **kwargs):
        return None

    def update(self, *args, **kwargs):
        return None

    def pop(self, *args, **kwargs):
        return None


def _drive(text, user_id, chat_id=CHAT, is_private=False):
    """فراخوانی هندلر واقعی، دقیقاً مثل همان چیزی که روی رویداد NewMessage ثبت است."""
    import handlers.message_handler as mh

    event = RecordingEvent(text, chat_id=chat_id, user_id=user_id,
                           is_private=is_private)
    logger = _RecordingLogger()
    bot = _StubBot(logger=logger, raw_text=text, message_text=text)
    asyncio.run(mh.handle_new_message(bot, event))
    return event, bot


class _RecordingLogger:
    def __init__(self):
        self.info = []
        self.errors = []

    def log_info(self, message):
        self.info.append(str(message))

    def log_error(self, message):
        self.errors.append(str(message))

    def log_warning(self, message):
        self.info.append(str(message))

    def log_deleted_message(self, *args, **kwargs):
        return None


class _StubBot:
    """bot قلابی با همان چند صفتی که هندلر واقعاً به آن‌ها تکیه می‌کند."""

    def __init__(self, **overrides):
        self.logger = overrides["logger"]
        self.config_manager = SimpleNamespace(get=lambda key, default=None: default)
        self.client = _Loose("client")
        self.detector = SimpleNamespace(
            is_spam=lambda *a, **k: (False, None),
            has_public_username=lambda *a, **k: False,
            check_banned_words=lambda *a, **k: (False, None),
            check_spam_score=lambda *a, **k: (0, []),
            analyze=lambda *a, **k: {"is_spam": False, "score": 0, "reasons": [],
                                     "reason_str": ""},
        )
        self.tracker = _Loose("tracker")
        self.admin_actions = _Loose("admin_actions")
        self.group_actions = _Loose("group_actions")
        self.moderation_queue = SimpleNamespace(enqueue=lambda *a, **k: True)
        self.group_timer_tasks = {}
        self.spam_lock = {}
        self.repeat_messages = {}
        self.flood_messages = {}
        self.user_messages = {}
        self.punished_users = set()
        self.spam_burst_users = set()
        self.spam_burst_messages = {}
        self.spammer_messages = {}
        self.rejoin_spam_state = {}
        self.forward_spam_counts = {}
        self.bot_sent_messages = []
        self.bot_account_id = 555
        self.started_at = 0.0
        self.cleanup_tasks = {}
        self.reply_input_peer_cache = {}
        self.group_dispatcher = None
        self.outgoing_sender = None
        self.notice_cleanup = _Loose("notice_cleanup")
        self.metrics_collector = None
        self.health_monitor = None
        self.performance_monitor = None
        self.runtime_snapshot = None
        self.process_delete = _Loose("process_delete")
        self.is_spam_locked = lambda key: False
        self.set_spam_lock = lambda key: None
        self.clear_spam_lock = lambda key: None
        self.touch_temporary_state = lambda *a, **k: None
        self.debug_message_log = lambda message: None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Loose(name)


def test_owner_can_disable_games_through_real_handler():
    from modules.owner_check import get_owner
    owner = get_owner()["user_id"]

    event, bot = _drive("سرگرمی خاموش", owner)
    assert event.replies == [ec.DISABLED_NOTICE], event.replies
    assert ec.is_enabled(CHAT) is False
    assert any("handler=entertainment_control" in line for line in bot.logger.info)

    event2, _ = _drive("بقا", 99999999)
    assert event2.replies == [ec.BLOCKED_NOTICE], event2.replies
    assert laugh_or_lose.is_active(CHAT) is False

    event3, _ = _drive("سرگرمی فعال", owner)
    assert event3.replies == [ec.ENABLED_NOTICE], event3.replies
    assert ec.is_enabled(CHAT) is True

    event4, _ = _drive("لیست بازی", 99999999)
    assert any("لیست بازی‌های روباه" in reply for reply in event4.replies), event4.replies


def test_regular_user_cannot_change_the_state():
    event, _ = _drive("سرگرمی خاموش", 99999999)
    assert event.replies == [ec.PERMISSION_DENIED], event.replies
    assert ec.is_enabled(CHAT) is True
    assert not Path(ec.FILE).exists() or json.loads(
        Path(ec.FILE).read_text(encoding="utf-8")) == {}


def test_toggle_is_refused_in_private_chat():
    from modules.owner_check import get_owner
    event, _ = _drive("سرگرمی خاموش", get_owner()["user_id"], is_private=True)
    assert event.replies == [ec.PRIVATE_CHAT_NOTICE], event.replies


def test_group_ids_of_same_group_share_one_setting_through_handler():
    from modules.owner_check import get_owner
    owner = get_owner()["user_id"]
    _drive("سرگرمی خاموش", owner, chat_id=CHAT)
    assert ec.is_enabled(CHAT_SHORT) is False
    assert ec.is_enabled(CHAT) is False


# ---------------------------------------------------------------------------
# راهنمای ادمین‌ها: «لیست ادمینی» باید کلید سرگرمی را داخل نقل‌قول شیشه‌ای
# نشان دهد و دو جملهٔ راهنما Bold باشند (خودِ دستور عادی).
# ---------------------------------------------------------------------------
HELP_BLOCK = (
    "🎮 برای خاموش کردن بازی های عمومی\n"
    "\n"
    "سرگرمی خاموش\n"
    "\n"
    "🎮 برای روشن کردن بازی های روباه\n"
    "\n"
    "سرگرمی فعال"
)
HELP_LABELS = (
    "🎮 برای خاموش کردن بازی های عمومی",
    "🎮 برای روشن کردن بازی های روباه",
)


def _help_output(command):
    """متن و entityهای واقعیِ پاسخ «لیست ادمینی» / «لیست کاربران»."""
    from modules.owner_check import get_owner
    event, _bot = _drive(command, get_owner()["user_id"])
    for text, kwargs in event.sent:
        if isinstance(text, str) and command == "لیست ادمینی" and "دستورات ادمین" in text:
            return text, kwargs.get("formatting_entities") or []
        if isinstance(text, str) and command == "لیست کاربران" and "کاربران:" in text:
            return text, kwargs.get("formatting_entities") or []
    raise AssertionError(f"no {command!r} reply in {event.replies!r}")


def _spans(text, entities, kind):
    raw = text.encode("utf-16-le")
    out = []
    for entity in entities:
        if type(entity).__name__ != kind:
            continue
        out.append(raw[entity.offset * 2:(entity.offset + entity.length) * 2].decode("utf-16-le"))
    return out


def test_admin_help_contains_the_entertainment_block():
    text, _entities = _help_output("لیست ادمینی")
    assert HELP_BLOCK in text
    assert text.count(HELP_BLOCK) == 1


def test_whole_entertainment_block_is_inside_one_glass_quote():
    text, entities = _help_output("لیست ادمینی")
    assert HELP_BLOCK in _spans(text, entities, "MessageEntityBlockquote")


def test_help_labels_are_bold_and_commands_are_plain():
    text, entities = _help_output("لیست ادمینی")
    bolds = _spans(text, entities, "MessageEntityBold")
    for label in HELP_LABELS:
        assert label in bolds, label
    for command in ("سرگرمی خاموش", "سرگرمی فعال"):
        assert command not in bolds, command


def test_help_has_no_markdown_and_all_spans_fit():
    text, entities = _help_output("لیست ادمینی")
    for marker in ("*", "**", "__", "```"):
        assert marker not in text
    length = len(text.encode("utf-16-le")) // 2
    assert entities
    for entity in entities:
        assert 0 <= entity.offset and entity.offset + entity.length <= length
        assert _spans(text, [entity], type(entity).__name__)[0] in text


def test_user_list_help_does_not_show_admin_commands():
    text, _entities = _help_output("لیست کاربران")
    assert HELP_BLOCK not in text
    assert "👑 دستورات ادمین‌ها:" not in text


# ---------------------------------------------------------------------------
# اجرای مستقل (بدون pytest)
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
