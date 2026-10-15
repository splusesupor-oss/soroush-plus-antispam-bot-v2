"""Central redaction for deployment secrets (session, tokens, API keys).

Design goals
------------
* **No dependencies.**  This module is imported by the earliest bootstrap code
  (``main.py``, ``b2.sh`` helpers, ``watchdog.py``) and by tests, so it must not
  import anything from the project.
* **Value based, not heuristic.**  Real secrets are registered explicitly (from
  the environment and from ``.env``); redaction then replaces the *exact*
  values.  Guessing with regexes alone would miss unusual session strings, so
  both mechanisms are used: registered values first, then well-known token
  shapes as a safety net.
* **Stable fingerprints instead of values.**  ``fingerprint()`` returns a short
  SHA-256 prefix.  Diagnostics can then say *which* secret was used (session A
  vs session B) without ever printing it.

Nothing in this module writes to disk or to the network.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from typing import Dict, Iterable, Optional

#: Environment keys whose values are secrets.  Keys are matched exactly, and
#: any key matching ``_SECRET_KEY_RE`` is picked up as well (covers per-instance
#: variants such as ``SOROUSH_SESSION_STRING_BOT2``).
SECRET_KEYS = (
    "SOROUSH_SESSION_STRING",
    "BOT_TOKEN",
    "SOROUSH_BOT_TOKEN",
    "API_HASH",
    "TELEGRAM_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)
_SECRET_KEY_RE = re.compile(
    r"(SESSION|TOKEN|SECRET|PASSWORD|PASSWD|API_HASH|PRIVATE_KEY)", re.IGNORECASE
)

PLACEHOLDER = "<redacted>"
MIN_SECRET_LEN = 12

#: Safety net for values that were never registered (for example a session
#: pasted straight into a traceback by a third-party library).
_PATTERNS = (
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<redacted-github-token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<redacted-github-token>"),
    (
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
        "<redacted-bot-token>",
    ),
    # MTProto / SPlusthon string sessions: long URL-safe base64, usually with
    # padding.  Never shorter than 40 characters in practice.
    (re.compile(r"\b[A-Za-z0-9_-]{60,}={0,2}\b"), "<redacted-session-like>"),
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "<redacted-hex-key>"),
)

_LOCK = threading.RLock()
_REGISTERED: Dict[str, str] = {}   # value -> label
_LABELS: Dict[str, str] = {}       # label -> value (for fingerprints)


def fingerprint(value: str) -> str:
    """Short, non-reversible identifier for a secret value."""
    if not value:
        return "empty"
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def register(value: Optional[str], label: str = "secret") -> None:
    """Register an exact secret value for redaction (idempotent, thread safe)."""
    if not value:
        return
    text = str(value)
    if len(text) < MIN_SECRET_LEN:
        return
    with _LOCK:
        _REGISTERED[text] = label


def register_from_env(environ: Optional[Dict[str, str]] = None) -> int:
    """Register every secret-looking environment variable.  Returns the count."""
    env = os.environ if environ is None else environ
    count = 0
    for key, value in list(env.items()):
        if not value:
            continue
        if key in SECRET_KEYS or _SECRET_KEY_RE.search(key):
            register(value, key)
            count += 1
    return count


def register_from_dotenv(path) -> int:
    """Register secrets from a ``.env`` file without importing dotenv."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return 0
    count = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not value:
            continue
        if key in SECRET_KEYS or _SECRET_KEY_RE.search(key):
            register(value, key)
            count += 1
    return count


def registered_count() -> int:
    with _LOCK:
        return len(_REGISTERED)


def mask(text) -> str:
    """Return ``text`` with every known/obvious secret replaced."""
    if text is None:
        return ""
    out = str(text)
    with _LOCK:
        items = sorted(_REGISTERED.items(), key=lambda kv: len(kv[0]), reverse=True)
    for value, label in items:
        if value and value in out:
            out = out.replace(value, f"<redacted:{label}>")
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def mask_mapping(mapping: Dict[str, object]) -> Dict[str, object]:
    """Redact every string value of a mapping (for diagnostic dumps)."""
    masked: Dict[str, object] = {}
    for key, value in mapping.items():
        if isinstance(value, str):
            masked[key] = mask(value)
        elif isinstance(value, dict):
            masked[key] = mask_mapping(value)
        else:
            masked[key] = value
    return masked


def describe(value: Optional[str], label: str = "secret") -> str:
    """Safe one-line description of a secret: label, length, fingerprint."""
    if not value:
        return f"{label}=<absent>"
    text = str(value)
    return f"{label}: len={len(text)} fp={fingerprint(text)}"


class RedactingFilter(logging.Filter):
    """Logging filter that redacts messages and string arguments."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            if isinstance(record.msg, str):
                record.msg = mask(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = mask_mapping(record.args)
                else:
                    record.args = tuple(
                        mask(arg) if isinstance(arg, str) else arg
                        for arg in record.args
                    )
            if record.exc_text:
                record.exc_text = mask(record.exc_text)
        except Exception:  # pragma: no cover - logging must never crash the bot
            pass
        return True


def install_on_handler(handler: logging.Handler) -> logging.Handler:
    """Attach a :class:`RedactingFilter` to ``handler`` (never duplicated)."""
    if not any(isinstance(f, RedactingFilter) for f in handler.filters):
        handler.addFilter(RedactingFilter())
    return handler


#: Set to ``True`` once the bootstrap has registered real values.
_BOOTSTRAPPED = False


def bootstrap(project_root=None) -> Dict[str, object]:
    """Register secrets from the environment and the clone's ``.env``.

    Safe to call repeatedly; the work is done once per process.
    """
    global _BOOTSTRAPPED
    with _LOCK:
        if _BOOTSTRAPPED:
            return {"env": 0, "dotenv": 0, "registered": registered_count()}
        _BOOTSTRAPPED = True
        env_count = register_from_env()
        dotenv_count = 0
        if project_root is not None:
            dotenv_count = register_from_dotenv(os.path.join(project_root, ".env"))
    return {
        "env": env_count,
        "dotenv": dotenv_count,
        "registered": registered_count(),
    }


def assert_clean(text, where: str = "output") -> str:
    """Return ``text`` masked, and note the event for diagnostics."""
    masked = mask(text)
    if masked != "" and masked != str(text):
        _EVENTS.append((time.time(), where))
    return masked


_EVENTS = []
