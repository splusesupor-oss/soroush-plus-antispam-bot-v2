"""Cheap logging policy — no filesystem access, no project imports.

This module decides *what* is worth writing.  ``logger_module`` decides *where*
it goes.  Keeping the policy separate means every worker, queue and detector can
ask the same question without importing (or initialising) the logging runtime.

Environment switches
--------------------
``BOT_VERBOSE_LOGS=1``
    Restore every hot-path diagnostic line (one or more lines per ordinary
    message).  Intended for incident investigation only.
``BOT_VERBOSE_LOGS=0`` (default)
    Production: hot-path traces are dropped, errors and lifecycle events stay.
"""
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}

VERBOSE = os.environ.get("BOT_VERBOSE_LOGS", "").strip().lower() in _TRUTHY

#: Prefixes that describe normal, high-frequency activity.  They are dropped in
#: production so the file and the terminal stay small and readable, and they
#: come back with ``BOT_VERBOSE_LOGS=1``.
NOISY_PREFIXES = (
    "GROUP DISPATCH WORKER START",
    "GROUP DISPATCH JOB",
    "OUTGOING SEND WORKER START",
    "KEEPALIVE PING SENT",
    "KEEPALIVE PONG RECEIVED",
    "BANNED WORD SKIP strict_off",
    "EXPIRY CHECK due_count=0",
    "RPC TRACE",
    "RPC TIME",
    "OUTGOING SEND TIME",
    "OUTGOING SEND QUEUE_WAIT",
    "OUTGOING RPC GATE",
    "OUTGOING RPC SLOW",
    "DELETE TASK START",
    "BATCH DELETE START",
    "DELETE MESSAGE RPC TIME",
    "BATCH DELETE FINISHED",
    "DELETE QUEUE SIZE",
    "NOTICE CLEANUP DUE",
    "NOTICE CLEANUP QUEUED",
    "NOTICE CLEANUP DELETED",
    "NOTICE CLEANUP START",
    "SPAM HISTORY SWEEP SKIPPED",
    "SPAM HISTORY SNAPSHOT",
    "FILTER WORD DETECTED",
    "BANNED WORD HIT",
    "SPAM DETECTED",
    "SPAM DETECT TIME",
    "SPAM CLEANUP QUEUED",
    "SPAM LOCK SET",
    "FORWARD DETECTED",
    "PUNISHMENT TRIGGERED",
    "BIG SPAM BAN QUEUED",
    "BIG SPAM BAN CONFIRMED",
    "DUPLICATE FLOOD DETECTED",
    "DUPLICATE GIF DETECTED",
    "GIF DELETE SCHEDULED",
    "FAST MODERATION QUEUED",
    "HANDLER CALLED",
    "MODERATION QUEUE ENQUEUED",
    "MODERATION QUEUE DUPLICATE SKIPPED",
    "MODERATION WORKER START",
    "MODERATION RPC START",
    "MODERATION RPC FINISHED",
    "AUTO_NOTICE_CREATED",
    "AUTO_NOTICE_TIMER_STARTED",
    "AUTO_NOTICE_DELETE_TRIGGERED",
    "AUTO_NOTICE_DELETE_RESULT",
    "OWNER PRIVATE PEER CAPTURED",
    "GROUP DISPATCH OVERFLOW",
    "CONN TRACE",
    "GOVERNOR WAIT",
    "GOVERNOR ACQUIRE",
    "GOVERNOR DRAIN",
    "GOVERNOR RELEASE",
    "RPC GOVERNOR WAIT",
    "QUEUE WAIT TIME",
    "PERFORMANCE SNAPSHOT",
    "HEALTH_HEARTBEAT_REPORT",
    "NAME FAMILY ",
    "GROUP MEMORY ",
    "CACHE ",
    "🗑️ حذف شد",
)

#: Lines that must remain visible on the terminal even though ordinary INFO is
#: demoted.  They answer "what did the bot just do?" without scrolling.
ALWAYS_CONSOLE_PREFIXES = (
    "BOT START",
    "BOT STOP",
    "BOT INSTANCE",
    "INSTANCE ",
    "SESSION SOURCE",
    "SESSION ERROR",
    "SESSION MISSING",
    "BACKUP",
    "RESTORE",
    "WATCHDOG",
    "CONFIG LOAD FAILED",
    "CONNECTED",
    "DISCONNECTED",
    "RECONNECT",
    "SHUTDOWN",
    "STARTUP",
    "RUNTIME MAINTENANCE",
    "CONNECTION GUARD",
    "WEBSOCKET RESET",
    "MEDIA_UPLOAD_PATCH",
)


def is_noisy(text: str) -> bool:
    """True when ``text`` is a hot-path diagnostic suppressed in production."""
    if VERBOSE:
        return False
    return str(text).startswith(NOISY_PREFIXES)


def is_always_console(text: str) -> bool:
    """True when a line must reach the terminal regardless of log level."""
    return str(text).startswith(ALWAYS_CONSOLE_PREFIXES)


class _Adapter:
    """Minimal protocol used by modules that accept either a BotLogger or None."""

    __slots__ = ("verbose_logs",)

    def __init__(self, verbose_logs: bool = True):
        self.verbose_logs = bool(verbose_logs)


def diagnostics_enabled(logger) -> bool:
    """BotLogger opts out of diagnostics; legacy adapters keep their protocol."""
    return logger is not None and bool(getattr(logger, "verbose_logs", True))
