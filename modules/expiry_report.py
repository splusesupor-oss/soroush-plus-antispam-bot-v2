"""📋 گزارش فقط-خواندنی انقضای گروه‌ها.

این ماژول هیچ فایل یا state جدیدی نمی‌سازد. اطلاعات گروه‌ها را از
``modules.group_storage`` و مهلت‌ها را از ``modules.group_expiry`` می‌خواند.
هر دو منبع cache وابسته به mtime دارند، پس هر فراخوان گزارش آخرین تغییر
فایل‌ها را می‌بیند.
"""
from datetime import datetime, timezone

from modules import group_expiry, group_storage

_HEADER = "📋 لیست انقضای گروه‌ها"
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _log_error(logger, message):
    if logger is None:
        return
    try:
        logger.log_error(message)
    except Exception:
        pass


def _digits(value):
    return str(value).translate(_PERSIAN_DIGITS)


def _remaining_text(expires_at, now):
    """Format an aware UTC expiry moment without timezone-dependent rounding."""
    seconds = int((expires_at - now).total_seconds())
    if seconds <= 0:
        return None
    days, remainder = divmod(seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{_digits(days)} روز")
    if hours or days:
        parts.append(f"{_digits(hours)} ساعت")
    if not days and not hours:
        parts.append(f"{_digits(minutes)} دقیقه")
    return " و ".join(parts)


def _sources(logger):
    try:
        groups = group_storage.load_groups()
        groups = groups if isinstance(groups, dict) else {}
    except Exception as error:
        _log_error(logger, f"EXPIRY REPORT GROUP LOAD FAILED error={error!r}")
        groups = {}
    try:
        expiry_records = group_expiry.all_records()
    except Exception as error:
        _log_error(logger, f"EXPIRY REPORT LOAD FAILED error={error!r}")
        expiry_records = {}
    return groups, expiry_records


def _moment(now):
    value = now or datetime.now(timezone.utc)
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def build_report(logger=None, now=None):
    """Build the detailed legacy expiry report (used by the existing private route)."""
    moment = _moment(now)
    groups, expiry_records = _sources(logger)
    if not groups and not expiry_records:
        return _HEADER + "\n\nℹ️ هیچ گروه ثبت‌شده‌ای وجود ندارد."

    # هر گروه فقط یک بار: کلیدهای هم‌ارز (123 و -100...123) یکی می‌شوند و
    # برای عنوان/وضعیت، رکورد فعال (active) بر رکورد کهنه ترجیح دارد.
    merged = {}
    order = []
    for group_id, group in groups.items():
        group = group if isinstance(group, dict) else {}
        key = group_expiry._group_key(group_id)
        current = merged.get(key)
        if current is None:
            merged[key] = {"group": group, "display_id": group_id}
            order.append(key)
        elif group.get("active") and not current["group"].get("active"):
            merged[key] = {"group": group, "display_id": group_id}
    # رکوردهای انقضایی که گروهشان در groups.json نیست هم باید دیده شوند؛
    # پنهان کردنشان همان باگ «تاریخ جدید در لیست نیست» بود.
    for expiry_key in expiry_records:
        key = group_expiry._group_key(expiry_key)
        if key not in merged:
            _log_error(logger, "EXPIRY REPORT ORPHAN RECORD "
                       f"group_id={expiry_key!r} reason=not_in_groups_storage")
            merged[key] = {"group": {}, "display_id": expiry_key}
            order.append(key)

    rows = [_HEADER]
    for index, key in enumerate(order, 1):
        entry = merged[key]
        group = entry["group"]
        record = group_expiry.get_record(key)
        title = (
            str(group.get("title") or "").strip()
            or str((record or {}).get("title") or "").strip()
            or "گروه بدون نام"
        )
        prefix = "❌" if record and group_expiry.is_expired(key, now=moment) else f"{_digits(index)}️⃣"
        lines = [f"{prefix} گروه: {title}", f"🆔 شناسه: {entry['display_id']}"]
        if not record:
            lines.append("⏳ وضعیت: تاریخ انقضا ثبت نشده")
        else:
            expires = group_expiry.expires_at(key)
            if expires is None:
                _log_error(logger, "EXPIRY REPORT INVALID RECORD "
                           f"group_id={key!r} record={record!r}")
                lines.append("⏳ وضعیت: تاریخ انقضا نامعتبر است")
            else:
                remaining = _remaining_text(expires, moment)
                lines.append("⏳ وضعیت: منقضی شده" if remaining is None
                             else f"⏳ باقی‌مانده: {remaining}")
        rows.append("\n".join(lines))
    return "\n\n".join(rows)


def _canonical_key(group_id):
    """کلید یکسان برای مقایسهٔ شناسه‌های هم‌ارز (123 و -100...123)."""
    return group_expiry._group_key(group_id)


def build_group_list(logger=None, now=None):
    """Build the compact owner-in-group list: group name and remaining time only.

    منبع اصلی *رکوردهای انقضا* هستند، نه groups.json — پس تاریخی که همین
    حالا ثبت/تمدید شده بلافاصله دیده می‌شود حتی اگر گروه هنوز (یا دیگر)
    در groups.json نباشد. groups.json فقط برای عنوان تازهٔ گروه استفاده
    می‌شود. کلیدهای هم‌ارز یک گروه فقط یک ردیف تولید می‌کنند.
    """
    moment = _moment(now)
    groups, expiry_records = _sources(logger)

    # نگاشت عنوان از groups.json با کلید نرمال؛ برای گروه‌های تکراری،
    # عنوان رکورد فعال ترجیح داده می‌شود.
    titles = {}
    for group_id, group in groups.items():
        group = group if isinstance(group, dict) else {}
        key = _canonical_key(group_id)
        title = str(group.get("title") or "").strip()
        if not title:
            continue
        if key not in titles or group.get("active"):
            titles[key] = title

    rows = [_HEADER]
    listed = 0
    seen = set()
    # ترتیب پایدار: اول گروه‌های ثبت‌شده (به ترتیب groups.json)، بعد
    # رکوردهای انقضایی که گروهشان ثبت نشده است.
    ordered_keys = []
    for group_id in groups:
        key = _canonical_key(group_id)
        if key not in ordered_keys:
            ordered_keys.append(key)
    for expiry_key in expiry_records:
        key = _canonical_key(expiry_key)
        if key not in ordered_keys:
            ordered_keys.append(key)

    for key in ordered_keys:
        if key in seen:
            continue
        seen.add(key)
        record = expiry_records.get(key) or group_expiry.get_record(key)
        if not record:
            continue
        expires = group_expiry.expires_at(key)
        if expires is None:
            _log_error(logger, "EXPIRY LIST INVALID RECORD "
                       f"group_id={key!r} record={record!r}")
            continue
        title = (titles.get(key)
                 or str(record.get("title") or "").strip()
                 or "گروه بدون نام")
        listed += 1
        remaining = _remaining_text(expires, moment)
        status = "منقضی شده" if remaining is None else f"{remaining} باقی مانده"
        rows.append(f"{listed}. {title}\n⏳ {status}")

    if not listed:
        return _HEADER + "\n\nℹ️ هیچ تاریخ انقضایی ثبت نشده است."
    return "\n\n".join(rows)
