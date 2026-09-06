"""Central, safe paths for mutable runtime data.

The source tree may live on Android shared storage (``/storage/emulated/0``),
which is a poor place for databases, fsync-heavy state and logs.  On Termux
we therefore keep mutable state in the app-private home directory by default::

    ~/.local/share/soroush-bot

On non-Termux systems the historical project-local paths remain the default
for backwards compatibility.  Operators can opt in everywhere with
``SOROUSH_BOT_DATA_DIR``.

Legacy files are *copied*, fsynced and verified before the new path is used.
They are never deleted automatically, so rollback remains possible.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _instance_name() -> str:
    """نام instance از متغیر محیطی ``BOT_INSTANCE`` (پیش‌فرض: ``main``).

    برای اجرای همزمان چند instance ربات در یک دستگاه (مثلاً دو clone در
    یک Termux): instance اصلی مسیر تاریخی خود را حفظ می‌کند تا داده‌های
    موجود دست‌نخورده بمانند؛ هر instance دیگر (``BOT_INSTANCE=bot2``)
    در مجاورت همان مسیر، دایرکتوری مستقل می‌گیرد:
    ``~/.local/share/soroush-bot-<instance>/``
    """
    raw = os.environ.get("BOT_INSTANCE", "main").strip() or "main"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:32]
    return slug or "main"


INSTANCE_NAME = _instance_name()


def _is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    home = str(Path.home())
    return "com.termux" in prefix or "/data/data/com.termux/" in home


def _chosen_data_dir() -> Path:
    explicit = os.environ.get("SOROUSH_BOT_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if _is_termux():
        if INSTANCE_NAME == "main":
            # instance اصلی مسیر تاریخی را نگه می‌دارد (مهاجرت داده لازم نیست).
            return (Path.home() / ".local" / "share" / "soroush-bot").resolve()
        return (Path.home() / ".local" / "share" / f"soroush-bot-{INSTANCE_NAME}").resolve()
    if INSTANCE_NAME == "main":
        # Keep existing tests and ordinary Linux installs backwards compatible.
        return PROJECT_ROOT
    # instance غیراصلی روی سیستم غیر-Termux: دایرکتوری اختصاصی در home.
    return (Path.home() / ".local" / "share" / f"soroush-bot-{INSTANCE_NAME}").resolve()


DATA_DIR = _chosen_data_dir()
USING_PRIVATE_DATA_DIR = DATA_DIR != PROJECT_ROOT
CONFIG_DIR = DATA_DIR / "config" if USING_PRIVATE_DATA_DIR else PROJECT_ROOT / "config"
LOG_DIR = DATA_DIR / "logs" if USING_PRIVATE_DATA_DIR else PROJECT_ROOT / "logs"
DB_DIR = DATA_DIR / "db" if USING_PRIVATE_DATA_DIR else PROJECT_ROOT / "config"
BACKUP_DIR = DATA_DIR / "backups" if USING_PRIVATE_DATA_DIR else PROJECT_ROOT / "backups" / "runtime"
ARCHIVE_DIR = DATA_DIR / "archive" if USING_PRIVATE_DATA_DIR else PROJECT_ROOT / "config" / "archive"


def ensure_layout() -> Path:
    """Create private runtime directories and return ``DATA_DIR``.

    Directory mode is best-effort because Android/FUSE and Windows do not
    implement all POSIX permissions.  Failure to chmod is not fatal.
    """
    for directory in (DATA_DIR, CONFIG_DIR, LOG_DIR, DB_DIR, BACKUP_DIR, ARCHIVE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    return DATA_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_verified_copy(source: Path, target: Path) -> bool:
    """Copy ``source`` to ``target`` atomically and verify content hash."""
    if target.exists() or not source.exists() or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.migrate-", suffix=".tmp", dir=str(target.parent)
    )
    temp = Path(temp_name)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if _sha256(source) != _sha256(temp):
            raise OSError(f"runtime migration verification failed: {source}")
        # Another process may have completed migration while we copied.
        if target.exists():
            temp.unlink(missing_ok=True)
            return False
        os.replace(temp, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return True
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise


def runtime_config_file(name: str, *, migrate: bool = True) -> Path:
    """Path for a mutable config/state file, with safe legacy migration."""
    ensure_layout()
    target = CONFIG_DIR / name
    legacy = PROJECT_ROOT / "config" / name
    if migrate and USING_PRIVATE_DATA_DIR and target != legacy:
        _atomic_verified_copy(legacy, target)
    return target


def runtime_log_file(name: str, *, migrate: bool = False) -> Path:
    """Path for a runtime log.

    Logs are not copied by default: old logs stay as an archive and a fresh,
    bounded log starts in private storage.
    """
    ensure_layout()
    target = LOG_DIR / name
    legacy = PROJECT_ROOT / "logs" / name
    if migrate and USING_PRIVATE_DATA_DIR and target != legacy:
        _atomic_verified_copy(legacy, target)
    return target


def runtime_db_file(name: str = "bot.sqlite3") -> Path:
    ensure_layout()
    return DB_DIR / name


def runtime_backup_file(name: str) -> Path:
    ensure_layout()
    return BACKUP_DIR / name


def runtime_archive_file(name: str) -> Path:
    ensure_layout()
    return ARCHIVE_DIR / name


def legacy_config_file(name: str) -> Path:
    return PROJECT_ROOT / "config" / name


def legacy_log_file(name: str) -> Path:
    return PROJECT_ROOT / "logs" / name


def describe() -> dict:
    return {
        "instance": INSTANCE_NAME,
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(DATA_DIR),
        "config_dir": str(CONFIG_DIR),
        "log_dir": str(LOG_DIR),
        "db_dir": str(DB_DIR),
        "private": USING_PRIVATE_DATA_DIR,
        "termux": _is_termux(),
    }


def cleanup_stale_temp_files(
    directories: Iterable[Path] | None = None,
    *,
    older_than_seconds: float = 24 * 60 * 60,
) -> list[str]:
    """Remove only known stale temp files; never touch active state files.

    A file is eligible only when its name clearly identifies it as a temporary
    write created by this project and it is older than the safety window.
    """
    now = time.time()
    removed: list[str] = []
    roots = tuple(directories or (CONFIG_DIR, LOG_DIR, DB_DIR))
    safe_suffixes = (".tmp", ".tmp-wal", ".tmp-shm")
    for directory in roots:
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if not path.is_file():
                continue
            name = path.name
            safe_name = (
                name.startswith("tmp")
                or ".migrate-" in name
                or name.endswith(safe_suffixes)
            )
            if not safe_name:
                continue
            try:
                if now - path.stat().st_mtime < older_than_seconds:
                    continue
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue
    return removed
