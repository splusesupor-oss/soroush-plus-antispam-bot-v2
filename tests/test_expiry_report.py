from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import group_expiry, group_storage
from modules.expiry_report import build_group_list, build_report


def _use_files(monkeypatch, tmp_path):
    groups_file = tmp_path / "groups.json"
    expiry_file = tmp_path / "group_expiry.json"
    monkeypatch.setattr(group_storage, "FILE", groups_file)
    monkeypatch.setattr(group_expiry, "FILE", expiry_file)
    group_storage._cache = group_storage._cache_mtime = None
    group_expiry._cache = group_expiry._cache_mtime = None
    return groups_file


def test_report_uses_current_group_and_expiry_storage(monkeypatch, tmp_path):
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps({
        "11": {"title": "گروه فعال", "active": True},
        "12": {"title": "گروه تمام", "active": False},
        "13": {"title": "بدون مهلت", "active": True},
    }, ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(11, group_expiry.FIVE_DAYS, now=now - timedelta(days=3, hours=18))
    group_expiry.set_expiry(12, group_expiry.ONE_WEEK, now=now - timedelta(days=8))

    report = build_report(now=now)
    assert "گروه فعال" in report
    assert "۱ روز و ۶ ساعت" in report
    assert "❌ گروه: گروه تمام" in report
    assert "منقضی شده" in report
    assert "بدون مهلت" in report
    assert "تاریخ انقضا ثبت نشده" in report


def test_group_list_is_compact_and_uses_existing_storage(monkeypatch, tmp_path):
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps({
        "31": {"title": "گروه اول"},
        "32": {"title": "بدون تاریخ"},
    }, ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(31, group_expiry.FIVE_DAYS, now=now - timedelta(days=4, hours=21))

    report = build_group_list(now=now)
    assert "1. گروه اول" in report
    assert "۳ ساعت باقی مانده" in report
    assert "بدون تاریخ" not in report
    assert "شناسه" not in report


def test_report_survives_invalid_expiry_data(monkeypatch, tmp_path):
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps({"44": {"title": "گروه خراب"}}, ensure_ascii=False), encoding="utf-8")
    group_expiry.FILE.write_text(json.dumps({"44": {"expires_at": "not-a-date"}}, ensure_ascii=False), encoding="utf-8")
    group_expiry._cache = group_expiry._cache_mtime = None

    report = build_report(now=datetime.now(timezone.utc))
    assert "گروه خراب" in report
    assert "تاریخ انقضا نامعتبر است" in report


# ---------------------------------------------------------------------------
# 🐛 رگرسیون: «لیست انقضا» باید همیشه دادهٔ زنده و جدیدترین رکورد را نشان دهد
# ---------------------------------------------------------------------------
def test_new_expiry_shows_immediately_even_without_group_record(monkeypatch, tmp_path):
    """ثبت تاریخ برای گروهی که در groups.json نیست باید فوراً در لیست بیاید."""
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps(
        {"11": {"title": "Group fox", "active": True}}, ensure_ascii=False),
        encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(11, group_expiry.FIVE_DAYS,
                            now=now - timedelta(days=4, hours=13))
    group_expiry.set_expiry(22, group_expiry.ONE_WEEK, title="گروه تازه", now=now)

    report = build_group_list(now=now)
    assert "گروه تازه" in report
    assert "Group fox" in report


def test_renewal_updates_list_immediately(monkeypatch, tmp_path):
    """تمدید یک گروه موجود باید بلافاصله تاریخ جدید را نشان دهد (نه snapshot قبلی)."""
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps(
        {"41": {"title": "گروه من", "active": True}}, ensure_ascii=False),
        encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(41, group_expiry.FIVE_DAYS, now=now - timedelta(days=4))
    before = build_group_list(now=now)
    assert "۱ روز" in before

    # تمدید همین حالا
    group_expiry.set_expiry(41, group_expiry.ONE_MONTH, now=now)
    after = build_group_list(now=now)
    assert "۲۹ روز" in after or "۲۸ روز" in after
    assert "۱ روز و" not in after


def test_equivalent_keys_show_single_row(monkeypatch, tmp_path):
    """کلیدهای هم‌ارز (123 و -100...123) نباید دو ردیف بسازند."""
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps({
        "123": {"title": "نام قدیمی", "active": False},
        "-1000000000123": {"title": "نام جدید", "active": True},
    }, ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(-1000000000123, group_expiry.ONE_WEEK, now=now)

    report = build_group_list(now=now)
    import re
    assert len(re.findall(r"^\d+\.", report, re.M)) == 1
    assert "نام جدید" in report

    detailed = build_report(now=now)
    assert detailed.count("گروه:") == 1


def test_legacy_stale_record_does_not_shadow_renewal(monkeypatch, tmp_path):
    """رکورد کهنهٔ منقضی با کلید legacy نباید گروه تازه‌تمدیدشده را ببندد."""
    _use_files(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.FILE.write_text(json.dumps({
        "-1000000000123": {
            "command": "۵ روز", "days": 5,
            "activated_at": (now - timedelta(days=20)).isoformat(),
            "expires_at": (now - timedelta(days=15)).isoformat(),
            "notified": False,
        }
    }, ensure_ascii=False), encoding="utf-8")
    group_expiry._cache = group_expiry._cache_mtime = None
    group_expiry.set_expiry(-1000000000123, group_expiry.ONE_WEEK, now=now)

    assert group_expiry.due_groups(now=now) == []
    assert not group_expiry.is_expired(123, now=now)
    assert not group_expiry.is_expired(-1000000000123, now=now)
    # دادهٔ خام حفظ شده — هیچ رکوردی حذف نشده است.
    raw = json.loads(group_expiry.FILE.read_text(encoding="utf-8"))
    assert "-1000000000123" in raw and "123" in raw


def test_shorter_renewal_wins_over_older_longer_record(monkeypatch, tmp_path):
    """تمدید کوتاه‌ترِ جدید (activated_at جدیدتر) باید معتبر باشد."""
    _use_files(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(55, group_expiry.ONE_MONTH, now=now - timedelta(days=1))
    group_expiry.set_expiry(55, group_expiry.FIVE_DAYS, now=now)
    record = group_expiry.get_record(55)
    assert record["days"] == 5


def test_expiry_and_notification_with_legacy_duplicate(monkeypatch, tmp_path):
    """mark_notified باید همهٔ کلیدهای هم‌ارز را علامت بزند تا اعلان تکرار نشود."""
    _use_files(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.FILE.write_text(json.dumps({
        "-1000000000321": {
            "command": "۵ روز", "days": 5,
            "activated_at": (now - timedelta(days=10)).isoformat(),
            "expires_at": (now - timedelta(days=5)).isoformat(),
            "notified": False,
        },
        "321": {
            "command": "۵ روز", "days": 5,
            "activated_at": (now - timedelta(days=9)).isoformat(),
            "expires_at": (now - timedelta(days=4)).isoformat(),
            "notified": False,
        },
    }, ensure_ascii=False), encoding="utf-8")
    group_expiry._cache = group_expiry._cache_mtime = None

    due = group_expiry.due_groups(now=now)
    assert [key for key, _ in due] == ["321"]
    assert group_expiry.mark_notified("321") is True
    # هر دو رکورد علامت خورده‌اند؛ دور بعدی watcher دوباره نمی‌بندد.
    assert group_expiry.due_groups(now=now) == []
    assert group_expiry.mark_notified("321") is False


def test_report_reads_live_file_after_restart_simulation(monkeypatch, tmp_path):
    """پاک شدن cache (ری‌استارت) نباید داده را عوض کند؛ فایل منبع حقیقت است."""
    groups_file = _use_files(monkeypatch, tmp_path)
    groups_file.write_text(json.dumps(
        {"77": {"title": "پایدار", "active": True}}, ensure_ascii=False),
        encoding="utf-8")
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    group_expiry.set_expiry(77, group_expiry.TWO_WEEKS, now=now)
    before = build_group_list(now=now)

    # شبیه‌سازی ری‌استارت: cache حافظه پاک می‌شود
    group_expiry._cache = group_expiry._cache_mtime = None
    group_storage._cache = group_storage._cache_mtime = None
    after = build_group_list(now=now)
    assert before == after
    assert "پایدار" in after
