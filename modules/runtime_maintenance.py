"""Low-frequency health, retention and backup tasks for runtime storage."""
from __future__ import annotations

import os
import time
from pathlib import Path

from economy import storage as economy_storage
from modules import runtime_db
from modules.runtime_paths import (
    BACKUP_DIR,
    INSTANCE_NAME,
    cleanup_stale_temp_files,
)

BACKUP_INTERVAL_SECONDS = int(
    os.environ.get("BOT_BACKUP_INTERVAL_SECONDS", str(24 * 60 * 60))
)
BACKUP_KEEP = int(os.environ.get("BOT_BACKUP_KEEP", "14"))
# هیچ بکاپی که از این مدت تازه‌تر است حذف نمی‌شود (ضدِ اشتباه‌تنظیمیِ keep).
BACKUP_MIN_AGE_SECONDS = int(
    os.environ.get("BOT_BACKUP_MIN_AGE_SECONDS", str(60 * 60))
)
ECONOMY_ARCHIVE_DAYS = int(os.environ.get("BOT_ECONOMY_ARCHIVE_DAYS", "365"))
_BACKUP_META_KEY = "runtime_last_verified_backup"


def _last_backup_time():
    if runtime_db.SQLITE_ENABLED:
        try:
            return float(runtime_db.meta_get(_BACKUP_META_KEY, "0") or 0)
        except (TypeError, ValueError):
            return 0.0
    candidates = list(BACKUP_DIR.glob("bot-*.json"))
    return max((path.stat().st_mtime for path in candidates), default=0.0)


def _prune_backups(keep=None):
    """Apply a hard file-count cap only to routine backups.

    Pre-migration/rollback backups use other prefixes and are deliberately
    never removed here. A candidate is removed only when it is both beyond the
    count cap *and* older than ``BACKUP_MIN_AGE_SECONDS``.
    """
    keep = max(1, int(BACKUP_KEEP if keep is None else keep))
    candidates = sorted(
        [*BACKUP_DIR.glob("bot-*.sqlite3"), *BACKUP_DIR.glob("bot-*.json")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cutoff = time.time() - max(0, BACKUP_MIN_AGE_SECONDS)
    removed = []
    for path in candidates[keep:]:
        try:
            # فقط بکاپی که هم از سقف تعداد گذشته و هم کهنه است حذف می‌شود؛
            # یک بکاپ تازه‌ساخته هرگز به‌خاطر keep اشتباه پاک نمی‌شود.
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


def run(*, force_backup=False):
    """Run health checks and bounded maintenance outside the event loop.

    Corrupt primary storage raises immediately. Backup failure is reported in
    the returned diagnostics without making an otherwise healthy bot vanish.
    """
    result = {
        "temporary_removed": cleanup_stale_temp_files(),
        "economy_integrity": economy_storage.integrity_check(),
        "backup": None,
        "backup_error": None,
    }
    if result["economy_integrity"] != "ok":
        raise RuntimeError(
            "economy storage integrity check failed: "
            + str(result["economy_integrity"])
        )

    result["economy_maintenance"] = economy_storage.maintenance(
        archive_days=ECONOMY_ARCHIVE_DAYS
    )
    if runtime_db.SQLITE_ENABLED:
        result["runtime_integrity"] = runtime_db.integrity_check()
        if result["runtime_integrity"] != "ok":
            raise RuntimeError(
                "runtime database integrity check failed: "
                + str(result["runtime_integrity"])
            )
        result["runtime_maintenance"] = runtime_db.maintenance()

    now = time.time()
    due = force_backup or now - _last_backup_time() >= max(
        60, BACKUP_INTERVAL_SECONDS
    )
    if due:
        try:
            if runtime_db.SQLITE_ENABLED:
                backup = runtime_db.backup_to()
                runtime_db.meta_set(_BACKUP_META_KEY, str(now))
            else:
                backup = economy_storage.backup_to()
            result["backup"] = str(backup)
        except Exception as error:
            result["backup_error"] = repr(error)
    result["backups_removed"] = _prune_backups()
    return result
