"""Regression tests for the two edition limits.

1. Only four admins can be registered per group; cancelling one frees a slot.
2. The bulk «پاک N» cleanup may run once every five minutes per group,
   never back to back.
"""
from __future__ import annotations

import asyncio

import pytest

from handlers import message_handler
from modules import admin_storage, free_tier


def _set_free(monkeypatch):
    monkeypatch.setattr(free_tier, "PLAN", "free")


def _set_premium(monkeypatch):
    monkeypatch.setattr(free_tier, "PLAN", "premium")


# --------------------------------------------------------------------------
# 1) admin registration limit
# --------------------------------------------------------------------------


def test_free_edition_caps_admin_registration_at_four(monkeypatch):
    _set_free(monkeypatch)
    assert free_tier.admin_registration_limit() == 4
    for current in (0, 1, 2, 3):
        assert free_tier.admin_registration_allowed(current) is True
    for current in (4, 5, 99):
        assert free_tier.admin_registration_allowed(current) is False


def test_premium_edition_keeps_unlimited_admins(monkeypatch):
    _set_premium(monkeypatch)
    assert free_tier.admin_registration_limit() is None
    assert free_tier.admin_registration_allowed(4) is True
    assert free_tier.admin_registration_allowed(400) is True


def test_admin_limit_message_is_user_facing(monkeypatch):
    _set_free(monkeypatch)
    assert "۴ ادمین" in free_tier.ADMIN_LIMIT_MESSAGE
    assert "لغو ادمین" in free_tier.ADMIN_LIMIT_MESSAGE


def test_bad_counter_values_never_open_the_gate(monkeypatch):
    _set_free(monkeypatch)
    # A broken counter must behave like an empty group, not like "unlimited".
    assert free_tier.admin_registration_allowed(None) is True
    assert free_tier.admin_registration_allowed("x") is True
    assert free_tier.admin_registration_allowed("4") is False


def test_count_admins_tracks_add_and_remove(tmp_path, monkeypatch):
    _set_free(monkeypatch)
    monkeypatch.setattr(admin_storage, "FILE", tmp_path / "admins.json")
    monkeypatch.setattr(admin_storage, "_cache", None, raising=False)
    monkeypatch.setattr(admin_storage, "_cache_mtime", None, raising=False)

    group = -100
    assert admin_storage.count_admins(group) == 0
    for user_id in (1, 2, 3, 4):
        assert admin_storage.add_admin(group, user_id, f"u{user_id}") is True
    assert admin_storage.count_admins(group) == 4

    # Re-registering the same user is a no-op and does not consume a slot.
    assert admin_storage.add_admin(group, 4, "u4") is False
    assert admin_storage.count_admins(group) == 4

    # Cancelling one admin frees exactly one slot.
    assert admin_storage.remove_admin(group, 2) is True
    assert admin_storage.count_admins(group) == 3
    assert free_tier.admin_registration_allowed(
        admin_storage.count_admins(group)
    ) is True

    assert admin_storage.add_admin(group, 5, "u5") is True
    assert admin_storage.count_admins(group) == 4
    assert free_tier.admin_registration_allowed(
        admin_storage.count_admins(group)
    ) is False

    # Untouched groups keep their own independent quota.
    assert admin_storage.count_admins(-200) == 0


def test_full_group_rejects_a_new_admin_then_accepts_after_cancel(
    tmp_path, monkeypatch
):
    """The exact sequence the handler performs around ``add_admin``."""
    _set_free(monkeypatch)
    monkeypatch.setattr(admin_storage, "FILE", tmp_path / "admins.json")
    monkeypatch.setattr(admin_storage, "_cache", None, raising=False)
    monkeypatch.setattr(admin_storage, "_cache_mtime", None, raising=False)

    group = -500
    for user_id in (10, 20, 30, 40):
        admin_storage.add_admin(group, user_id, None)

    def try_register(user_id):
        if not admin_storage.is_admin(group, user_id, None):
            if not free_tier.admin_registration_allowed(
                admin_storage.count_admins(group)
            ):
                return "limit"
        return "ok" if admin_storage.add_admin(group, user_id, None) else "already"

    assert try_register(50) == "limit"
    # An already-registered admin still gets the old "already" answer, never
    # the limit message.
    assert try_register(40) == "already"

    admin_storage.remove_admin(group, 10)
    assert try_register(50) == "ok"
    assert admin_storage.count_admins(group) == 4
    assert try_register(60) == "limit"


# --------------------------------------------------------------------------
# 2) bulk delete cooldown
# --------------------------------------------------------------------------


def test_bulk_delete_cooldown_window(monkeypatch):
    _set_free(monkeypatch)
    assert free_tier.bulk_delete_cooldown_seconds() == 300
    _set_premium(monkeypatch)
    assert free_tier.bulk_delete_cooldown_seconds() == 0


def _run(coro):
    return asyncio.run(coro)


def test_second_bulk_delete_is_blocked_until_five_minutes_pass(monkeypatch):
    _set_free(monkeypatch)
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()
    chat_id = -777

    async def scenario():
        loop = asyncio.get_running_loop()
        fake_now = {"t": 1_000.0}
        monkeypatch.setattr(loop, "time", lambda: fake_now["t"])

        # First run is allowed and arms the cooldown.
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) == 0
        message_handler._bulk_delete_cooldown_mark(chat_id)

        # Immediately after, and anywhere inside the window, it is blocked.
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) > 0
        fake_now["t"] += 1            # 1s elapsed
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) == 299
        fake_now["t"] += 170          # 171s elapsed
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) == 129
        fake_now["t"] += 128          # 299s elapsed
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) == 1

        # Exactly at five minutes it opens again.
        fake_now["t"] += 1            # 300s elapsed
        assert message_handler._bulk_delete_cooldown_remaining(chat_id) == 0

    _run(scenario())
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()


def test_cooldown_is_per_group_and_not_armed_by_a_rejected_command(monkeypatch):
    _set_free(monkeypatch)
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()

    async def scenario():
        loop = asyncio.get_running_loop()
        fake_now = {"t": 500.0}
        monkeypatch.setattr(loop, "time", lambda: fake_now["t"])

        message_handler._bulk_delete_cooldown_mark(-1)
        assert message_handler._bulk_delete_cooldown_remaining(-1) > 0
        # Another group is unaffected.
        assert message_handler._bulk_delete_cooldown_remaining(-2) == 0
        # Reading the remaining time must never arm the cooldown by itself,
        # otherwise an invalid «پاک abc» would burn the five-minute slot.
        assert message_handler._bulk_delete_cooldown_remaining(-2) == 0
        assert -2 not in message_handler.BULK_DELETE_COMMAND_COOLDOWNS

    _run(scenario())
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()


def test_premium_has_no_bulk_cooldown(monkeypatch):
    _set_premium(monkeypatch)
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()

    async def scenario():
        message_handler._bulk_delete_cooldown_mark(-9)
        assert message_handler._bulk_delete_cooldown_remaining(-9) == 0
        assert message_handler.BULK_DELETE_COMMAND_COOLDOWNS == {}

    _run(scenario())


def test_reply_delete_keeps_its_own_five_second_window(monkeypatch):
    """«پاک» با ریپلای نباید وارد پنجرهٔ ۵ دقیقه‌ای شود."""
    _set_free(monkeypatch)
    message_handler.DELETE_COMMAND_COOLDOWNS.clear()
    message_handler.BULK_DELETE_COMMAND_COOLDOWNS.clear()

    async def scenario():
        loop = asyncio.get_running_loop()
        fake_now = {"t": 10.0}
        monkeypatch.setattr(loop, "time", lambda: fake_now["t"])

        assert message_handler._delete_cooldown_allowed(-3) is True
        assert message_handler._delete_cooldown_allowed(-3) is False
        fake_now["t"] += 5
        assert message_handler._delete_cooldown_allowed(-3) is True
        # The single-message path never arms the bulk cooldown.
        assert message_handler.BULK_DELETE_COMMAND_COOLDOWNS == {}

    _run(scenario())
    message_handler.DELETE_COMMAND_COOLDOWNS.clear()


@pytest.mark.parametrize(("seconds", "expected"), [
    (1, "１ ثانیه"),
    (59, "５９ ثانیه"),
    (60, "１ دقیقه"),
    (61, "１ دقیقه و １ ثانیه"),
    (300, "５ دقیقه"),
])
def test_wait_message_is_formatted_in_persian_style(seconds, expected):
    assert message_handler._format_cooldown_wait(seconds) == expected
