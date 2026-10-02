"""تست‌های فیلتر دستی نام، بدون اتصال شبکه یا session."""
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from handlers import ad_name_filter_handler as handler
from modules import ad_name_detector as detector


class Event:
    def __init__(self, private=False):
        self.is_private = private
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append((text, kwargs.get("formatting_entities") or []))
        return SimpleNamespace(id=len(self.replies))


def user(first_name, last_name=None, username=None):
    return SimpleNamespace(
        id=10,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )


@pytest.fixture
def isolated_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(detector, "FILTER_FILE", tmp_path / "ad_name_filters.json")
    detector.reset_filter_cache()
    yield
    detector.reset_filter_cache()


def test_text_filter_is_grouped_and_uses_display_name(isolated_filters):
    assert detector.add_name_filter(100, "حسین") is True
    assert detector.list_name_filters(100) == ["حسین"]
    assert detector.list_name_filters(200) == []

    assert detector.reason(user("حسین", "رضایی", "ordinary_user"), 100)
    # فیلتر دستی فقط روی نام نمایشی است؛ username مسیر global قبلی خودش را دارد.
    assert detector.reason(user("علی", "رضایی", "حسین"), 100) is None
    assert detector.reason(user("حسین", "رضایی"), 200) is None


def test_emoji_filter_and_shared_normalization(isolated_filters):
    long_group_id = -1000000000123
    assert detector.add_name_filter(long_group_id, "🍆") is True
    # -100… و شناسه کوتاه متناظر، طبق normalize_group_id یک گروه‌اند.
    assert detector.reason(user("🍆 VIP"), 123) is not None
    assert detector.remove_name_filter(123, "🍆") is True
    assert detector.reason(user("🍆 VIP"), long_group_id) is None


def test_handler_permission_add_list_remove_and_exact_entities(
    isolated_filters, monkeypatch
):
    monkeypatch.setattr(handler.admin_tools, "has_admin_permission", lambda *args: True)
    sender = user("مدیر")
    event = Event()

    import asyncio

    async def scenario():
        assert await handler.handle(
            None, event, 55, 10, sender, "فیلتر اسم حسین"
        ) is True
        assert await handler.handle(
            None, event, 55, 10, sender, "لیست فیلتر اسم"
        ) is True
        assert await handler.handle(
            None, event, 55, 10, sender, "حذف فیلتر اسم حسین"
        ) is True
        assert await handler.handle(
            None, event, 55, 10, sender, "فیلتر اسم 🍆"
        ) is True
        assert await handler.handle(
            None, event, 55, 10, sender, "لغو اسم 🍆"
        ) is True

    asyncio.run(scenario())

    assert event.replies[0][0] == "نام : حسین فیلتر شد"
    assert event.replies[1][0] == "📋 فیلترهای اسم این گروه:\n1. حسین"
    assert event.replies[2][0] == "نام : حسین از فیلتر خارج شد"
    assert event.replies[3][0] == "نام : 🍆 فیلتر شد"
    assert event.replies[4][0] == "نام : 🍆 از فیلتر خارج شد"

    for text, entities in (event.replies[0], event.replies[2], event.replies[3], event.replies[4]):
        assert len(entities) == 2
        expected_length = len(text.encode("utf-16-le")) // 2
        assert {(type(entity).__name__) for entity in entities} == {
            "MessageEntityBold", "MessageEntityBlockquote"
        }
        assert all(entity.offset == 0 and entity.length == expected_length for entity in entities)


def test_handler_denies_regular_user_for_every_management_command(
    isolated_filters, monkeypatch
):
    monkeypatch.setattr(handler.admin_tools, "has_admin_permission", lambda *args: False)
    event = Event()
    import asyncio

    async def scenario():
        for command in (
            "فیلتر اسم حسین",
            "حذف فیلتر اسم حسین",
            "لغو اسم حسین",
            "لیست فیلتر اسم",
        ):
            assert await handler.handle(None, event, 77, 20, user("کاربر"), command)

    asyncio.run(scenario())
    assert len(event.replies) == 4
    assert all("فقط مالک ثبت‌شده" in text for text, _entities in event.replies)
    assert detector.list_name_filters(77) == []


def test_filter_command_is_not_swallowed_by_ad_name_guard():
    """فرمان کامل، permission را می‌گیرد و enforcement روی همان فرمان اجرا نمی‌شود."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "handlers" / "message_handler.py").read_text(
        encoding="utf-8"
    )
    assert "ad_name_detector.reason(sender, chat_id)" in source
    assert "handle_ad_name_filter_command" in source
    assert "or is_ad_name_filter_command(message_text)" in source


def test_filter_commands_use_protected_admin_dispatch_lane():
    from modules.group_dispatch import LANE_ADMIN, classify_priority

    for command in (
        "فیلتر اسم حسین",
        "حذف فیلتر اسم حسین",
        "لغو اسم 🍆",
        "لیست فیلتر اسم",
    ):
        priority, lane = classify_priority(command)
        assert lane == LANE_ADMIN
        assert priority == 0


def test_help_block_has_exact_lines_and_real_entity_coverage():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "handlers" / "ad_name_filter_handler.py").read_text(
        encoding="utf-8"
    )
    assert "برای فیلتر اسم یک کاربر بنویسید فیلتر اسم بعد نام را بنویسید\\n" in source
    assert "برای لغو بنویسید لغو اسم بعد اسم را بنویسید" in source
    assert "برای دیدن لیست اسم ها" in source
    assert "لیست فیلتر اسم" in source
    assert "AD_NAME_FILTER_HELP_BLOCK" in (
        Path(__file__).parents[1] / "handlers" / "message_handler.py"
    ).read_text(encoding="utf-8")
