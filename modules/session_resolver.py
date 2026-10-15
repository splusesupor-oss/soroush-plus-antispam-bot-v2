"""Session resolution with explicit, masked provenance.

Problem this replaces
---------------------
The old inline logic was::

    SOROUSH_SESSION_STRING_<INSTANCE> or SOROUSH_SESSION_STRING or config

The second and third branches were silent.  A B2 clone whose per-instance
variable was missing would quietly log in as **B1's account** — two processes
fighting over one account, and impossible to notice from the logs.

Rules now
---------
1. ``SOROUSH_SESSION_STRING_<INSTANCE>`` wins when present.
2. The generic ``SOROUSH_SESSION_STRING`` is still accepted (so existing
   deployments keep working) but is announced with a *masked* warning naming
   the source, and can be forbidden entirely with ``BOT_SESSION_STRICT=1``.
3. ``config_manager["session_string"]`` is the last resort, also announced.
4. Nothing present => :class:`SessionMissing`.  A random/empty/default session
   is **never** substituted.
5. The value itself is never returned to logs; use
   :meth:`SessionInfo.describe` / :func:`fingerprint`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

from modules.secret_guard import fingerprint, mask

STRICT_ENV = "BOT_SESSION_STRICT"
#: Values people put in ``.env`` to mean "no session"; treated as absent so the
#: error message stays honest instead of trying to use them.
_PLACEHOLDERS = {
    "", "none", "null", "disabled", "disable", "off", "false", "0",
    "changeme", "your_session_string", "session_string", "todo", "todo!",
}
_MIN_REASONABLE_LENGTH = 30


class SessionMissing(RuntimeError):
    """No usable session for this instance — the bot must not start."""


class SessionInvalid(RuntimeError):
    """A session value exists but is clearly not a session string."""


@dataclass
class SessionInfo:
    value: str
    source: str
    instance: str
    warnings: list = field(default_factory=list)

    @property
    def strict_ok(self) -> bool:
        """True when the value came from this instance's own variable."""
        return self.source.endswith(self.instance.upper())

    def describe(self) -> str:
        """Masked, log-safe description (never contains the session)."""
        return (f"SESSION SOURCE instance={self.instance} "
                f"key={self.source} {fingerprint(self.value)} "
                f"len={len(self.value)}")

    def announcement(self) -> Optional[str]:
        """Masked warning when the session did not come from this instance."""
        if self.strict_ok:
            return None
        return (
            f"SESSION SOURCE instance={self.instance} key={self.source} "
            f"{fingerprint(self.value)} — این سشن از متغیر اختصاصی همین ربات "
            f"نیامده است؛ برای ربات‌های مستقل "
            f"SOROUSH_SESSION_STRING_{self.instance.upper()} را ست کنید."
        )


def _clean(value) -> str:
    return str(value or "").strip()


def is_usable(value: str) -> bool:
    text = _clean(value)
    return text.lower() not in _PLACEHOLDERS


def strict_mode(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return _clean(env.get(STRICT_ENV)).lower() in {"1", "true", "yes", "on"}


def instance_key(instance: str) -> str:
    return "SOROUSH_SESSION_STRING_" + str(instance or "main").upper()


def resolve(instance: str,
            environ: Optional[Mapping[str, str]] = None,
            config_getter: Optional[Callable[[str, str], object]] = None,
            ) -> SessionInfo:
    """Resolve the session for ``instance`` or raise a clear, safe error."""
    env = dict(os.environ if environ is None else environ)
    instance = str(instance or "main")
    key = instance_key(instance)
    warnings = []

    candidates = [(key, env.get(key))]
    if not strict_mode(env):
        candidates.append(("SOROUSH_SESSION_STRING", env.get("SOROUSH_SESSION_STRING")))
    if config_getter is not None:
        try:
            candidates.append(("config_manager.session_string",
                               config_getter("session_string", "")))
        except Exception:
            pass

    seen_value = False
    for source, raw in candidates:
        if raw is None:
            continue
        text = _clean(raw)
        if not text:
            continue
        if not is_usable(text):
            seen_value = True
            warnings.append(f"{source} مقدار جای‌نگهدار دارد و نادیده گرفته شد")
            continue
        if len(text) < _MIN_REASONABLE_LENGTH:
            seen_value = True
            warnings.append(
                f"{source} کوتاه‌تر از حد یک سشن معتبر است و نادیده گرفته شد")
            continue
        info = SessionInfo(value=text, source=source, instance=instance,
                           warnings=warnings)
        return info

    detail = (
        f"SESSION ERROR instance={instance}: هیچ سشن معتبری پیدا نشد "
        f"(کلیدهای بررسی‌شده: {', '.join(k for k, _ in candidates)})"
    )
    if seen_value:
        detail += " — مقدار موجود معتبر نبود (محتوای مقدار ثبت نمی‌شود)"
    if strict_mode(env):
        detail += " — BOT_SESSION_STRICT=1 فعال است، پس fallback عمومی مجاز نیست"
    raise SessionMissing(mask(detail))


def resolve_or_error(instance: str, **kwargs) -> SessionInfo:
    """Same as :func:`resolve`; kept for symmetry with legacy call sites."""
    return resolve(instance, **kwargs)
