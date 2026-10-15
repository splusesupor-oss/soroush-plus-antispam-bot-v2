"""Bounded, non-blocking, redacting logging for the Soroush bot.

Producers only enqueue small records.  Formatting, JSON encoding, console and
rotating-file I/O all happen on listeners, never on the message/RPC worker.

What this layer guarantees
--------------------------
1. **Isolation** — every path comes from :mod:`modules.runtime_paths`, so B1,
   B2 and B3 write to their own data directory and nowhere else.
2. **Bounded size** — each log rotates at ``BOT_LOG_MAX_BYTES`` (default 5 MiB)
   and keeps ``BOT_LOG_BACKUPS`` (default 5) rotated files.
3. **Bounded age** — rotated files older than ``BOT_LOG_RETENTION_DAYS``
   (default 7) are deleted by a sweep that runs once per process and then at
   most hourly.
4. **No duplicate handlers** — the runtime is a process-wide singleton and
   :meth:`BotLogger.__init__` never leaves two handlers on one record.
5. **No secrets** — every handler carries :class:`secret_guard.RedactingFilter`.
6. **Short terminal** — the console handler shows WARNING+ plus a small
   allow-list of lifecycle lines, so ``bot.log`` keeps the detail.
7. **Never fatal** — logging failures are swallowed; a broken log file must not
   take the bot down.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import re
import time
from datetime import datetime, timedelta
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Optional

from modules import log_policy
from modules.log_policy import NOISY_PREFIXES, VERBOSE
from modules.runtime_paths import runtime_log_file
from modules.secret_guard import install_on_handler

_FALLBACK_MAX_BYTES = 5 * 1024 * 1024
_FALLBACK_BACKUPS = 5
_FALLBACK_RETENTION_DAYS = 7.0
_SWEEP_INTERVAL_SECONDS = 3600.0


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(str(os.environ.get(name, "")).strip() or default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(str(os.environ.get(name, "")).strip() or default))
    except (TypeError, ValueError):
        return default


_MAX_LOG_BYTES = _env_int("BOT_LOG_MAX_BYTES", _FALLBACK_MAX_BYTES,
                          minimum=256 * 1024)
_LOG_BACKUPS = _env_int("BOT_LOG_BACKUPS", _FALLBACK_BACKUPS)
_LOG_RETENTION_DAYS = _env_float("BOT_LOG_RETENTION_DAYS",
                                 _FALLBACK_RETENTION_DAYS)
_CONSOLE_LEVEL_NAME = str(
    os.environ.get("BOT_CONSOLE_LOG_LEVEL", "WARNING") or "WARNING"
).strip().upper()
_CONSOLE_LEVEL = getattr(logging, _CONSOLE_LEVEL_NAME, logging.WARNING)

#: Files written by this layer.  ``tools/log_health.py`` reports these.
MANAGED_LOGS = ("bot.log", "deleted_messages.log", "actions.log")
_ROTATED_RE = re.compile(r"\.\d{4}-\d{2}-\d{2}(_\d+)?$|\.\d+$")


class _DroppingQueueHandler(QueueHandler):
    """Never block the bot when the logging queue is saturated."""

    dropped = 0

    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            type(self).dropped += 1


class _ConsoleFilter(logging.Filter):
    """Keep the terminal short: warnings/errors plus lifecycle allow-list."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= _CONSOLE_LEVEL:
            return True
        try:
            return log_policy.is_always_console(str(record.getMessage()))
        except Exception:
            return False


def _rotate_time_suffix(date: datetime, index: int) -> str:
    return f"{date:%Y-%m-%d}_{index:02d}"


class _BootRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler whose *existing* oversized file is rotated first.

    A bot that died after writing a huge ``bot.log`` must not keep growing that
    file until the next rollover trigger; this rotates it once at startup.
    """

    def _open(self):  # pragma: no cover - exercised through the runtime
        if self.mode == "a" and os.path.exists(self.baseFilename):
            try:
                if os.path.getsize(self.baseFilename) >= self.maxBytes:
                    stamp = datetime.now()
                    for index in range(1, self.backupCount + 1):
                        candidate = Path(
                            f"{self.baseFilename}.{_rotate_time_suffix(stamp, index)}"
                        )
                        if not candidate.exists():
                            os.rename(self.baseFilename, candidate)
                            break
            except OSError:
                pass
        return super()._open()


def _make_handler(path: Path, formatter: logging.Formatter,
                  level: int = logging.NOTSET) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _BootRotatingFileHandler(
        str(path),
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_LOG_BACKUPS,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)
    return install_on_handler(handler)


def purge_old_logs(directory: Optional[Path] = None, *,
                   older_than_days: Optional[float] = None) -> list:
    """Delete rotated log files older than the retention window.

    Only files this layer created are considered: they must end in a rotation
    suffix (``.1``, ``.2026-10-15_03``, …) or in ``.log`` for stale copies whose
    base name is no longer produced.  Active log files are never touched.
    """
    days = _LOG_RETENTION_DAYS if older_than_days is None else older_than_days
    if days <= 0:
        return []
    target = Path(directory) if directory is not None else runtime_log_file("bot.log").parent
    if not target.exists():
        return []
    cutoff = time.time() - days * 86400
    removed = []
    for path in sorted(target.iterdir()):
        try:
            if not path.is_file():
                continue
            name = path.name
            is_rotated = bool(_ROTATED_RE.search(name)) or name.endswith(".log")
            if not is_rotated:
                continue
            if name in MANAGED_LOGS or name in ("watchdog.log",):
                continue  # active file
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                continue
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


class _LogRuntime:
    """Process-wide singleton owning both queue listeners."""

    def __init__(self):
        self.queue = queue.Queue(maxsize=10_000)
        self.created_at = time.time()
        self.last_sweep = 0.0
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(logging.NOTSET)
        console.addFilter(_ConsoleFilter())
        self.console = install_on_handler(console)
        self.bot_file = _make_handler(runtime_log_file("bot.log"), formatter)
        self.listener = QueueListener(
            self.queue, self.console, self.bot_file, respect_handler_level=True
        )

        # Moderation audit trail keeps its own bounded handler.
        self.deleted_queue = queue.Queue(maxsize=10_000)
        self.deleted_file = _make_handler(
            runtime_log_file("deleted_messages.log"),
            logging.Formatter("%(message)s"),
        )
        self.deleted_listener = QueueListener(
            self.deleted_queue, self.deleted_file, respect_handler_level=True
        )
        self.sweep()
        self.listener.start()
        self.deleted_listener.start()

    def sweep(self, force: bool = False) -> list:
        now = time.time()
        if not force and (now - self.last_sweep) < _SWEEP_INTERVAL_SECONDS:
            return []
        self.last_sweep = now
        try:
            return purge_old_logs()
        except Exception:  # pragma: no cover - cleanup must never be fatal
            return []

    def stop(self):
        for listener in (getattr(self, "listener", None),
                         getattr(self, "deleted_listener", None)):
            try:
                if listener is not None:
                    listener.stop()
            except Exception:
                pass


_RUNTIME = None
_RUNTIME_LOCK = Lock()


def _runtime() -> _LogRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = _LogRuntime()
            atexit.register(_RUNTIME.stop)
        return _RUNTIME


def _build_json_logger(name: str, filename: str):
    """Independent, bounded, redacting JSON logger (used for the audit trail)."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = _make_handler(
            runtime_log_file(filename), logging.Formatter("%(message)s")
        )
        logger.addHandler(handler)
    return logger


class BotLogger:
    """Facade used across the project.  ``log_file`` is kept for compatibility."""

    verbose_logs = VERBOSE

    def __init__(self, log_file: str = "logs/deleted_messages.log",
                 console_log: bool = True):
        self.log_file = str(runtime_log_file(Path(log_file).name))
        runtime = _runtime()
        runtime.sweep()

        self.logger = logging.getLogger("SoroushAntiSpam")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not any(isinstance(h, _DroppingQueueHandler)
                   for h in self.logger.handlers):
            for stale in list(self.logger.handlers):
                self.logger.removeHandler(stale)
            self.logger.addHandler(_DroppingQueueHandler(runtime.queue))

        self._deleted_logger = logging.getLogger("SoroushAntiSpam.deleted")
        self._deleted_logger.setLevel(logging.INFO)
        self._deleted_logger.propagate = False
        if not any(isinstance(h, _DroppingQueueHandler)
                   for h in self._deleted_logger.handlers):
            for stale in list(self._deleted_logger.handlers):
                self._deleted_logger.removeHandler(stale)
            self._deleted_logger.addHandler(
                _DroppingQueueHandler(runtime.deleted_queue)
            )

        self._actions_logger = _build_json_logger(
            "SoroushAntiSpam.actions", "actions.log"
        )

    # ------------------------------------------------------------------ writes
    def log_deleted_message(self, user_id: int, username: Optional[str],
                            group_id: int, group_title: Optional[str],
                            original_text: str, reason: str,
                            message_id: Optional[int] = None):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "username": username,
            "group_id": group_id,
            "group_title": group_title,
            "message_id": message_id,
            # Keep enough context for moderation without creating an unlimited
            # copy of users' messages.  Rotation bounds the total size.
            "original_text": str(original_text or "")[:500],
            "reason": reason,
        }
        try:
            self._deleted_logger.info(
                json.dumps(log_entry, ensure_ascii=False, separators=(",", ":"))
            )
        except Exception:
            pass
        if VERBOSE:
            self.logger.info(
                "🗑️ حذف شد | گروه: %s(%s) | کاربر: %s(%s) | دلیل: %s",
                group_title, group_id, username, user_id, reason,
            )

    def log_action(self, action: str, user_id: int, group_id: int,
                   details: str = ""):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "user_id": user_id,
            "group_id": group_id,
            "details": details,
        }
        try:
            self._actions_logger.info(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
            )
        except Exception:
            pass
        self.logger.warning(
            "⚙️ اقدام مدیریتی | %s | کاربر %s در گروه %s | %s",
            action, user_id, group_id, details,
        )

    def log_info(self, message: str):
        text = str(message)
        if log_policy.is_noisy(text):
            return
        self.logger.info(text)

    def log_notice(self, message: str):
        """Important lifecycle line: always shown on the terminal.

        Uses the allow-listed prefixes from ``log_policy`` so it stays cheap.
        """
        text = str(message)
        if not log_policy.is_always_console(text):
            text = "INSTANCE " + text
        self.logger.info(text)

    def log_error(self, message: str):
        self.logger.error(str(message))

    @staticmethod
    def dropped_records() -> int:
        return int(_DroppingQueueHandler.dropped)


# ---------------------------------------------------------------- diagnostics
def health() -> dict:
    """Report duplicate handlers, oversized/rotated files and wrong paths.

    Used by ``tools/log_health.py`` and by tests.  Read-only.
    """
    from modules.runtime_paths import LOG_DIR, INSTANCE_NAME
    expected_dir = Path(LOG_DIR).resolve()
    report = {
        "instance": INSTANCE_NAME,
        "expected_log_dir": str(expected_dir),
        "max_bytes": _MAX_LOG_BYTES,
        "backups": _LOG_BACKUPS,
        "retention_days": _LOG_RETENTION_DAYS,
        "console_level": _CONSOLE_LEVEL_NAME,
        "verbose": VERBOSE,
        "problems": [],
        "files": [],
        "loggers": {},
    }

    seen = {}
    for name, obj in list(logging.Logger.manager.loggerDict.items()):
        if not isinstance(obj, logging.Logger):
            continue
        handlers = list(obj.handlers)
        if not handlers:
            continue
        report["loggers"][name] = {
            "level": logging.getLevelName(obj.level),
            "propagate": bool(obj.propagate),
            "handlers": [type(h).__name__ for h in handlers],
        }
        counts = {}
        for handler in handlers:
            key = (type(handler).__name__, getattr(handler, "baseFilename", ""))
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            if count > 1:
                report["problems"].append(
                    f"duplicate handler on '{name}': {key[0]} x{count}"
                )
        for handler in handlers:
            base = getattr(handler, "baseFilename", None)
            if not base:
                continue
            signature = (name, str(Path(base).resolve()))
            if signature in seen:
                report["problems"].append(
                    f"same file handled twice: {base} on '{name}'"
                )
            seen[signature] = True

    for path in sorted(expected_dir.glob("*")) if expected_dir.exists() else []:
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        info = {
            "name": path.name,
            "size": size,
            "rotated": bool(_ROTATED_RE.search(path.name)),
        }
        report["files"].append(info)
        if size > _MAX_LOG_BYTES * (1.5 if info["rotated"] else 1.0):
            report["problems"].append(f"oversized log: {path.name} = {size} bytes")

    if not expected_dir.exists():
        report["problems"].append(f"log directory missing: {expected_dir}")

    stray = Path(runtime_log_file("bot.log")).resolve().parent
    if stray != expected_dir:
        report["problems"].append(
            f"log path mismatch: handler dir {stray} != {expected_dir}"
        )
    return report
