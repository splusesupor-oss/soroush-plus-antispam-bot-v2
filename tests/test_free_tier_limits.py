"""No-network regression tests for the free-tier execution barriers."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import free_tier
from handlers import message_handler, fox_games_router, private_handler
from modules import (
    admin_tools,
    clipboard_storage,
    entertainment_control,
    font_converter,
    notice_cleanup,
    punishment_mode,
    vip_storage,
    warning_threshold,
    web_search,
)


class FakeLogger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, message):
        self.infos.append(str(message))

    def log_error(self, message):
        self.errors.append(str(message))


class FakeEvent:
    def __init__(self, text="", *, user_id=100, reply_to_id=None, is_private=False):
        self.is_private = is_private
        self.chat_id = 9001
        self.sender_id = user_id
        self.sender = SimpleNamespace(id=user_id, username="operator")
        self.message = SimpleNamespace(
            message=text,
            caption=text,
            id=12,
            file=None,
            entities=[],
            reply_to=(SimpleNamespace(reply_to_msg_id=reply_to_id)
                      if reply_to_id is not None else None),
            reply_to_msg_id=reply_to_id,
        )
        self.reply_to = self.message.reply_to
        self.replies = []
        self.data = None

    async def reply(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(id=1000 + len(self.replies))

    async def answer(self, text=None, **kwargs):
        self.replies.append((text, kwargs))
        return True


class FakeBot:
    def __init__(self):
        self.logger = FakeLogger()
        self.client = SimpleNamespace()
        self.awards = []

    def award_coins(self, *args, **kwargs):
        self.awards.append((args, kwargs))


def _set_free(monkeypatch):
    monkeypatch.setattr(free_tier, "PLAN", "free")


@pytest.mark.parametrize("text", [
    "لیست بازی", "لیست بازی ها", "لیست بازی‌ها", "بازی‌ها",
])
def test_game_list_aliases_remain_free(text, monkeypatch):
    _set_free(monkeypatch)
    assert free_tier.feature_for_text(text) is None
    event = FakeEvent()
    assert asyncio.run(entertainment_control.guard(event, 9001, text)) is False
    assert event.replies == []


@pytest.mark.parametrize(("text", "feature", "enabled"), [
    ("اسم فامیل", "games", False),
    ("چهار گزینه‌ای", "games", False),
    ("بخند یا بباز", "games", False),
    ("شروع دوباره حدس ایموجی", "games", False),
    ("ریست حدس ایموجی", "games", False),
    ("تغییر اخطار", "warning_settings", False),
    ("تغییر مجازات", "punishment_settings", False),
    ("کپی بورد", "clipboard", True),
    ("کپی", "clipboard", True),
    ("هوش مصنوعی فعال", "ai", True),
    ("مجاز @example", "ai", True),
    ("لیست هوش مصنوعی", "ai", True),
    ("لاگ مدیریتی", "admin_log_view", False),
    ("آزاد @example", "unban_by_username", False),
    ("پاک ۵۰۱", "bulk_delete_over_500", False),
    ("پاک ۷۰۰", "bulk_delete_over_500", False),
    ("پاک ۹۹۹۹", "bulk_delete_over_500", False),
    ("پاکسازی خودکار", "auto_cleanup", False),
    ("vip", "vip", False),
    ("لغو vip", "vip", False),
    ("لیست vip", "vip", False),
    ("جستجو دانلود آهنگ", "search", True),
    ("جستجو مطالب", "search", True),
    ("فونت متن شما", "font_creation", True),
])
def test_live_command_names_are_mapped_to_their_entitlement(
    text, feature, enabled, monkeypatch
):
    _set_free(monkeypatch)
    assert free_tier.feature_for_text(text) == feature
    assert free_tier.is_enabled(feature) is enabled


def test_free_delete_range_and_invalid_values_are_parsed_before_execution(monkeypatch):
    _set_free(monkeypatch)
    for count in (1, 2, 500):
        assert free_tier.parse_bulk_delete_count(f"پاک {count}") == ("free", count)
    assert free_tier.parse_bulk_delete_count("پاک ۵۰۰") == ("free", 500)
    assert free_tier.parse_bulk_delete_count("پاک 501") == ("premium", 501)
    assert free_tier.parse_bulk_delete_count("پاک -1") == ("invalid", -1)
    assert free_tier.parse_bulk_delete_count("پاک 0") == ("invalid", 0)
    assert free_tier.parse_bulk_delete_count("پاک یک") == ("invalid", None)
    assert free_tier.feature_for_text("پاک 500") is None
    assert free_tier.feature_for_text("پاک 501") == "bulk_delete_over_500"


def test_reply_unban_stays_free_while_every_username_form_is_paid(monkeypatch):
    _set_free(monkeypatch)
    reply_event = FakeEvent("آزاد", reply_to_id=77)
    assert free_tier.feature_for_event("آزاد", reply_event, 9001, 100) is None
    assert free_tier.feature_for_text("آزاد") is None
    assert free_tier.feature_for_text("آزاد @user") == "unban_by_username"
    assert free_tier.feature_for_text("آزاد@user") == "unban_by_username"
    # The real handler treats any non-empty argument as its username lookup.
    assert free_tier.feature_for_text("آزاد user") == "unban_by_username"


@pytest.mark.parametrize("text", [
    "اسم فامیل", "تغییر اخطار", "تغییر مجازات", "لاگ مدیریتی",
    "آزاد @user", "پاک 501", "پاکسازی خودکار", "vip",
])
@pytest.mark.parametrize("user_id", [11, 22, 33])  # owner/admin/ordinary IDs

def test_real_message_handler_answers_paywall_before_any_feature_work(text, user_id, monkeypatch):
    _set_free(monkeypatch)
    event = FakeEvent(text, user_id=user_id)
    bot = FakeBot()
    asyncio.run(message_handler.handle_new_message(bot, event))
    assert [reply for reply, _kwargs in event.replies] == [free_tier.PAYWALL_MESSAGE]
    # The early guard returns before resolving entities, sending requests,
    # editing settings, deleting messages, or invoking any bot-side action.
    assert bot.awards == []
    assert not hasattr(bot.client, "get_messages")
    assert not hasattr(bot.client, "delete_messages")


def test_clipboard_is_not_restricted_by_the_confirmed_free_tier_list(
    tmp_path, monkeypatch
):
    _set_free(monkeypatch)
    monkeypatch.setattr(clipboard_storage, "FILE", tmp_path / "clipboard.json")
    clipboard_storage.reset_cache()
    assert free_tier.is_enabled("clipboard") is True
    assert clipboard_storage.set_pending_guide(9001, 88) is True
    assert clipboard_storage.save(9001, "free clipboard", []) == (True, None)
    assert clipboard_storage.get_raw(9001)["text"] == "free clipboard"


def test_game_router_blocks_before_session_or_reward_creation(monkeypatch):
    _set_free(monkeypatch)
    fox_games_router.reset_all()
    event = FakeEvent("بخند یا بباز")
    bot = FakeBot()
    handled = asyncio.run(fox_games_router.handle(
        bot, event, 9001, 100, event.sender, "بخند یا بباز", bot.logger
    ))
    assert handled is True
    assert [reply for reply, _ in event.replies] == [free_tier.PAYWALL_MESSAGE]
    assert fox_games_router.any_active(9001) is False
    assert bot.awards == []


def test_free_notice_ttl_does_not_start_schedule_or_delete_announcements(tmp_path, monkeypatch):
    _set_free(monkeypatch)
    path = tmp_path / "notice_cleanup.json"
    path.write_text('{"9001":[{"message_id":7,"expires_at":0}]}', encoding="utf-8")
    before = path.read_bytes()

    class DeleteQueue:
        def __init__(self):
            self.calls = []

        async def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return 1, []

    queue = DeleteQueue()
    cleanup = notice_cleanup.NoticeCleanup(str(path), delete_queue=queue)
    assert cleanup.pending(9001) == []  # old timer rows are not replayed
    assert cleanup.start() is False
    assert cleanup._started is False
    assert cleanup.schedule(9001, 88) is False
    bot = SimpleNamespace(notice_cleanup=cleanup)
    assert notice_cleanup.capture_sent(bot, 9001, 89) is False
    assert queue.calls == []
    assert path.read_bytes() == before  # saved state was not erased or rewritten


@pytest.mark.parametrize("method", [
    "set_cleanup", "clear_cleanup", "mark_cleanup_run",
    "execute_cleanup", "run_cleanup_watcher",
])
def test_auto_cleanup_settings_and_jobs_are_inert_but_saved_data_survives(
    method, tmp_path, monkeypatch
):
    _set_free(monkeypatch)
    path = tmp_path / "auto_cleanup.json"
    original = '{"9001":{"scheduled_at":"2000-01-01T00:00:00+03:30","count":7}}'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(admin_tools, "_BASE", tmp_path)
    monkeypatch.setattr(admin_tools, "_CLEANUP_FILE", path)

    class NoDeleteBot:
        def __init__(self):
            self.calls = []
            self.client = SimpleNamespace(delete_messages=lambda *a, **k: self.calls.append("delete"))
            self.group_actions = SimpleNamespace(
                lock_group=lambda *a, **k: self.calls.append("lock"),
                unlock_group=lambda *a, **k: self.calls.append("unlock"),
            )

    bot = NoDeleteBot()
    if method == "set_cleanup":
        assert admin_tools.set_cleanup(9001, "today", "12:30", 10) is None
    elif method == "clear_cleanup":
        assert admin_tools.clear_cleanup(9001) is False
    elif method == "mark_cleanup_run":
        assert admin_tools.mark_cleanup_run(9001, "now") is False
    elif method == "execute_cleanup":
        assert asyncio.run(admin_tools.execute_cleanup(bot, 9001, 7)) is False
    else:
        assert asyncio.run(admin_tools.run_cleanup_watcher(bot)) is None
    assert path.read_text(encoding="utf-8") == original
    assert bot.calls == []


def test_warning_and_punishment_storage_mutators_cannot_change_saved_settings(
    tmp_path, monkeypatch
):
    _set_free(monkeypatch)
    warning_path = tmp_path / "warning_threshold.json"
    warning_original = '{"9001":8}'
    warning_path.write_text(warning_original, encoding="utf-8")
    monkeypatch.setattr(warning_threshold, "_BASE", tmp_path)
    monkeypatch.setattr(warning_threshold, "_FILE", warning_path)
    monkeypatch.setattr(warning_threshold, "_cache", None)
    monkeypatch.setattr(warning_threshold, "_cache_mtime", None)
    monkeypatch.setattr(warning_threshold, "_pending", {})
    assert warning_threshold.begin_change(9001, 22) is False
    assert warning_threshold.set_threshold(9001, 3) is None
    assert warning_path.read_text(encoding="utf-8") == warning_original

    punishment_path = tmp_path / "punishment_mode.json"
    punishment_original = '{"9001":"mute"}'
    punishment_path.write_text(punishment_original, encoding="utf-8")
    monkeypatch.setattr(punishment_mode, "_BASE", tmp_path)
    monkeypatch.setattr(punishment_mode, "_FILE", punishment_path)
    monkeypatch.setattr(punishment_mode, "_cache", None)
    monkeypatch.setattr(punishment_mode, "_cache_mtime", None)
    monkeypatch.setattr(punishment_mode, "_pending", {})
    assert punishment_mode.begin_change(9001, 22) is False
    assert punishment_mode.toggle(9001) == punishment_mode.MODE_MUTE
    assert punishment_path.read_text(encoding="utf-8") == punishment_original


def test_vip_commands_and_existing_vip_effect_are_off_without_deleting_records(
    tmp_path, monkeypatch
):
    _set_free(monkeypatch)
    path = tmp_path / "vip_users.json"
    original = '{"9001":["55"]}'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(vip_storage, "FILE", path)
    monkeypatch.setattr(vip_storage, "_cache", None)
    monkeypatch.setattr(vip_storage, "_cache_mtime", None)
    assert vip_storage.add_vip(9001, 66) is False
    assert vip_storage.remove_vip(9001, 55) is False
    assert vip_storage.is_vip(9001, 55) is False
    assert vip_storage.list_vips(9001) == []
    assert path.read_text(encoding="utf-8") == original


def test_admin_log_view_and_clear_are_blocked_without_erasing_audit_data(
    tmp_path, monkeypatch
):
    _set_free(monkeypatch)
    path = tmp_path / "admin_log.json"
    original = '{"9001":[{"action":"test"}]}'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(admin_tools, "_USE_SQLITE_LOG", False)
    monkeypatch.setattr(admin_tools, "_ADMIN_LOG_FILE", path)
    monkeypatch.setattr(admin_tools, "_admin_log_cache", None)
    monkeypatch.setattr(admin_tools, "_admin_log_mtime", None)
    monkeypatch.setattr(
        admin_tools, "_load_admin_log",
        lambda: pytest.fail("free plan must not read admin log records"),
    )
    assert admin_tools.format_log(9001)[0] == free_tier.PAYWALL_MESSAGE
    assert admin_tools.get_log(9001) == []
    assert admin_tools.export_admin_log_json(tmp_path / "export.json") is None
    assert admin_tools.clear_log(9001) is False
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "export.json").exists()


def test_search_and_font_services_remain_available_in_free_plan(monkeypatch, tmp_path):
    _set_free(monkeypatch)
    search_path = tmp_path / "search_cooldown.json"
    monkeypatch.setattr(web_search, "FILE", search_path)

    class Response:
        status_code = 200
        text = '<html><a class="result__a" href="https://example.test">Example result</a></html>'

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(web_search, "_search_session", Session)
    assert free_tier.is_enabled("search") is True
    assert web_search.can_search(22) == (True, 0)
    assert "Example result" in web_search.search_web("test")
    assert search_path.exists()
    assert free_tier.is_enabled("font_creation") is True
    assert len(font_converter.make_fonts("Hello")) == 14


def test_ai_stays_free_while_paid_callback_payload_uses_shared_paywall(monkeypatch):
    _set_free(monkeypatch)
    assert free_tier.feature_for_text("هوش مصنوعی فعال") == "ai"
    assert free_tier.is_enabled("ai") is True

    callback = FakeEvent(is_private=False)
    callback.data = b"vip"
    handled = asyncio.run(private_handler.handle_private_callback(FakeBot(), callback))
    assert handled is True
    assert callback.replies[-1][0] == free_tier.PAYWALL_MESSAGE


def test_premium_plan_restores_entitlements_without_code_rewrites(monkeypatch):
    monkeypatch.setattr(free_tier, "PLAN", "premium")
    for feature in free_tier.FEATURES:
        assert free_tier.is_enabled(feature) is True
    assert free_tier.feature_for_text("بخند یا بباز") == "games"
