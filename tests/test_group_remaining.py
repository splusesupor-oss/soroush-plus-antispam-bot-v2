"""⏳ تست‌های «مهلت گروه» و هم‌سان‌سازی «لیست انقضا».

پوشش:
  • ``remaining_status`` روی تاریخ انقضای واقعی گروه (فعال/منقضی/بدون رکورد).
  • ``build_remaining_message`` — قالب دقیق و اینکه فقط «گروه» و
    «مهلت باقی مانده» Bold باشند و هیچ نقل‌قول شیشه‌ای وجود نداشته باشد.
  • ``update_title`` — به‌روزرسانی نامِ گروه با ID ثابت (بدون ساختن رکورد
    جدید و بدون تغییر تاریخ انقضا).
  • ``sync_records`` — یکسان‌سازی کلیدهای legacy بدون حذف هیچ گروهی.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import group_expiry


def _use_file(monkeypatch, tmp_path):
    monkeypatch.setattr(group_expiry, "FILE", tmp_path / "group_expiry.json")
    group_expiry._cache = group_expiry._cache_mtime = None


def _decode(text, offset, length):
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


def test_remaining_status_uses_real_expiry(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(123, group_expiry.ONE_WEEK, now=now - timedelta(days=4))
    state, text = group_expiry.remaining_status(123, now=now)
    assert state == "active"
    assert "۳ روز" in text  # ۷ - ۴ = ۳ روز باقی مانده


def test_remaining_status_expired(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(123, group_expiry.FIVE_DAYS, now=now - timedelta(days=10))
    state, text = group_expiry.remaining_status(123, now=now)
    assert state == "expired"
    assert text == group_expiry.REMAINING_EXPIRED_TEXT


def test_remaining_status_no_record(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    state, text = group_expiry.remaining_status(999)
    assert state is None and text is None


def test_remaining_status_short_and_long_id_match(monkeypatch, tmp_path):
    """شکل کوتاه و -۱۰۰... باید به یک گروه اشاره کنند (شناسایی با ID)."""
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(-1000000000123, group_expiry.ONE_MONTH, now=now)
    assert (group_expiry.remaining_status(123, now=now)
            == group_expiry.remaining_status(-1000000000123, now=now))


def test_build_remaining_message_format_and_bold():
    text, spans = group_expiry.build_remaining_message("گروه من", "۳ روز و ۲ ساعت")
    assert text == (
        "↻- گروه : گروه من\n"
        "مهلت باقی مانده : ۳ روز و ۲ ساعت\n"
        "برای تمدید اشتراک : 𝄞 @aifox_bot"
    )
    # فقط دو span و هر دو Bold؛ هیچ نقل‌قول شیشه‌ای (blockquote) نباشد.
    assert [k for k, _, _ in spans] == ["bold", "bold"]
    fragments = [_decode(text, o, l) for _, o, l in spans]
    assert fragments == ["گروه", "مهلت باقی مانده"]


def test_build_remaining_message_blank_title():
    text, spans = group_expiry.build_remaining_message("", "منقضی شده")
    assert "↻- گروه : بدون نام" in text
    assert [_decode(text, o, l) for _, o, l in spans] == ["گروه", "مهلت باقی مانده"]


def test_update_title_only_changes_existing(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(500, group_expiry.ONE_WEEK, title="نام قدیمی", now=now)
    before_expiry = group_expiry.expires_at(500)

    assert group_expiry.update_title(500, "نام جدید") is True
    assert group_expiry.get_record(500)["title"] == "نام جدید"
    # تاریخ انقضا نباید تغییر کند.
    assert group_expiry.expires_at(500) == before_expiry
    # نوشتن دوباره با همان نام هیچ تغییری ندارد.
    assert group_expiry.update_title(500, "نام جدید") is False
    # برای گروه بدون رکورد هیچ چیزی ساخته نمی‌شود.
    assert group_expiry.update_title(777, "چیزی") is False
    assert not group_expiry.has_expiry(777)


def test_update_title_updates_equivalent_keys(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    # دو کلید هم‌ارز به یک گروه اشاره می‌کنند.
    group_expiry.FILE.write_text(json.dumps({
        "-1000000000123": {
            "command": "۵ روز", "days": 5,
            "activated_at": now.isoformat(),
            "expires_at": (now + timedelta(days=5)).isoformat(),
            "notified": False, "title": "قدیمی",
        },
        "123": {
            "command": "۵ روز", "days": 5,
            "activated_at": now.isoformat(),
            "expires_at": (now + timedelta(days=5)).isoformat(),
            "notified": False, "title": "قدیمی",
        },
    }, ensure_ascii=False), encoding="utf-8")
    group_expiry._cache = group_expiry._cache_mtime = None

    assert group_expiry.update_title(123, "تازه") is True
    raw = json.loads(group_expiry.FILE.read_text(encoding="utf-8"))
    assert raw["-1000000000123"]["title"] == "تازه"
    assert raw["123"]["title"] == "تازه"


def test_sync_records_dedups_without_dropping_groups(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.FILE.write_text(json.dumps({
        # کلید legacy کهنه + کلید کوتاه تازه‌تر برای همان گروه
        "-1000000000123": {
            "command": "۵ روز", "days": 5,
            "activated_at": (now - timedelta(days=20)).isoformat(),
            "expires_at": (now - timedelta(days=15)).isoformat(),
            "notified": False,
        },
        "123": {
            "command": "یک ماه", "days": 29,
            "activated_at": now.isoformat(),
            "expires_at": (now + timedelta(days=29)).isoformat(),
            "notified": False, "title": "تمدیدشده",
        },
        # یک گروهِ منقضیِ دیگر که باید باقی بماند.
        "777": {
            "command": "۵ روز", "days": 5,
            "activated_at": (now - timedelta(days=10)).isoformat(),
            "expires_at": (now - timedelta(days=5)).isoformat(),
            "notified": True, "title": "منقضی",
        },
    }, ensure_ascii=False), encoding="utf-8")
    group_expiry._cache = group_expiry._cache_mtime = None

    count = group_expiry.sync_records()
    assert count == 2  # دو گروهِ یکتا

    raw = json.loads(group_expiry.FILE.read_text(encoding="utf-8"))
    # کلید legacy تکراری حذف شده و فقط کلید یکسان مانده است.
    assert set(raw.keys()) == {"123", "777"}
    # رکورد تازه‌تمدیدشده نگه داشته شد (نه کهنهٔ منقضی).
    assert raw["123"]["days"] == 29
    # گروهِ منقضی هنوز در لیست است تا وضعیت درست نشان داده شود.
    assert raw["777"]["title"] == "منقضی"
    # دومین اجرا idempotent است — چیزی تغییر نمی‌کند.
    assert group_expiry.sync_records() == 2
    raw2 = json.loads(group_expiry.FILE.read_text(encoding="utf-8"))
    assert raw2 == raw
