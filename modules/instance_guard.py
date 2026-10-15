"""Hard isolation guard between bot instances (B1/main, B2/bot2, B3/bot3).

Why this module exists
----------------------
Before this guard, the *only* thing deciding which runtime directory a clone
used was the ``BOT_INSTANCE`` environment variable.  Three concrete failure
modes were reproducible from the repositories:

* ``run.sh`` / ``run_bot.sh`` never set ``BOT_INSTANCE``; they exec
  ``watchdog.py`` directly.  On a B2 clone with no ``.bot_instance`` marker the
  launcher therefore resolved to ``main`` and wrote into the **B1** runtime
  directory.
* The sibling clone shipped ``bot2.py`` (the B2 launcher) inside the B1
  repository, and the B3 repository shipped *both* ``bot2.py`` and ``bot3.py``.
  Running either of those from the wrong clone silently creates/uses the other
  bot's runtime directory.
* An environment variable could contradict the clone's own marker with no
  warning at all.

The guard makes the *clone* itself authoritative through a small marker file,
and turns any contradiction into a loud, early failure.

Rules
-----
1. A clone declares the instance it owns in ``.bot_instance`` next to
   ``main.py`` (one line, no whitespace significance).
2. ``BOT_INSTANCE`` may be set by a launcher, but it must never *contradict*
   the marker.  Contradiction => :class:`InstanceConflict`.
3. A missing marker is only accepted for the implicit ``main`` instance, or
   when the caller explicitly asks to bootstrap it.  Launchers never stamp a
   marker silently; ``b2.sh`` does it once, on purpose, as an operator action.
4. This module never reads, writes or deletes another instance's data.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKER_NAME = ".bot_instance"
_ENV_KEY = "BOT_INSTANCE"
_BOOTSTRAP_KEY = "BOT_INSTANCE_BOOTSTRAP"

#: Instance names we know about.  Anything else is still accepted but is
#: normalised defensively (see :func:`normalize`).
KNOWN_INSTANCES = ("main", "bot2", "bot3")

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")


class InstanceConflict(RuntimeError):
    """Raised when the requested instance contradicts the clone's marker."""


def normalize(value: str) -> str:
    """Return a filesystem-safe instance slug (never empty)."""
    slug = _SLUG_RE.sub("_", str(value or "").strip())[:32]
    return slug or "main"


def marker_path() -> Path:
    """Absolute path of this clone's instance marker."""
    return PROJECT_ROOT / MARKER_NAME


def read_marker() -> Optional[str]:
    """Return the declared instance name, or ``None`` when there is no marker."""
    try:
        text = marker_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return normalize(text) if text else None


def write_marker(instance: str, *, overwrite: bool = False) -> bool:
    """Stamp this clone as ``instance``.

    Returns ``True`` when the marker was written.  Refuses to overwrite a
    different existing marker unless ``overwrite`` is requested explicitly, so
    a stray launcher can never re-home an already-stamped clone.
    """
    current = read_marker()
    name = normalize(instance)
    if current == name:
        return False
    if current is not None and not overwrite:
        raise InstanceConflict(
            f"this clone is already stamped as '{current}'; refusing to "
            f"re-stamp it as '{name}' (marker: {marker_path()})"
        )
    path = marker_path()
    try:
        path.write_text(name + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return True
    except OSError as error:  # pragma: no cover - read-only checkout
        raise InstanceConflict(f"cannot write instance marker {path}: {error!r}")


def requested() -> str:
    """Instance explicitly requested through the environment ('' when unset)."""
    return str(os.environ.get(_ENV_KEY, "") or "").strip()


def _bootstrap_allowed() -> bool:
    return str(os.environ.get(_BOOTSTRAP_KEY, "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _conflict_message(env_name: str, marker_name: str) -> str:
    return (
        "\n"
        "=" * 62 + "\n"
        " ⛔ INSTANCE CONFLICT — refusing to start\n"
        f"    BOT_INSTANCE={env_name}\n"
        f"    .bot_instance={marker_name}\n"
        f"    marker file: {marker_path()}\n"
        "    Running with the wrong instance would read/write another\n"
        "    bot's data directory.  Fix the marker or unset BOT_INSTANCE.\n"
        "=" * 62
    )


def resolve(entry: str, *, instance: Optional[str] = None,
            bootstrap: bool = False) -> str:
    """Resolve the instance for a launcher and verify it is consistent.

    Parameters
    ----------
    entry:
        Name of the launcher, used only in error messages
        (e.g. ``"bot2.py"``).
    instance:
        The instance the launcher *wants*.  ``None`` means "whatever this
        clone is", which is what ``main.py`` wants.
    bootstrap:
        When ``True`` a missing marker may be created for ``entry``.  Only
        interactive shell launchers pass ``True``.

    Raises
    ------
    InstanceConflict
        When the environment, the launcher and the marker disagree.
    """
    env_name = requested()
    marker = read_marker()

    if instance is not None:
        want = normalize(instance)
        if env_name and normalize(env_name) != want:
            raise InstanceConflict(
                f"{entry} must run as '{want}' but BOT_INSTANCE={env_name}"
            )
        if marker is not None and marker != want:
            raise InstanceConflict(_conflict_message(want, marker))
        if marker is None:
            allowed = bootstrap or _bootstrap_allowed()
            if not allowed:
                raise InstanceConflict(
                    f"{entry}: this clone has no {MARKER_NAME} marker.\n"
                    f"    Run './b2.sh direct' once (it stamps the clone), or\n"
                    f"    create the marker on purpose:\n"
                    f"      printf '{want}\\n' > {marker_path()}\n"
                    f"    Nothing was started, so no other bot's data was touched."
                )
            write_marker(want)
        instance_name = want
    else:
        instance_name = normalize(env_name) if env_name else (marker or "main")
        if env_name and marker and normalize(env_name) != marker:
            raise InstanceConflict(_conflict_message(normalize(env_name), marker))

    # Defence in depth: point the environment at the resolved instance so every
    # child process (watchdog -> main.py -> tools) inherits the same decision.
    os.environ[_ENV_KEY] = instance_name
    return instance_name


def assert_data_dir_is_own(instance: str, data_dir: str) -> None:
    """Fail when ``data_dir`` clearly belongs to a *different* instance.

    Only the well-known ``soroush-bot[-<instance>]`` naming scheme is checked;
    operator-chosen custom directories are never second-guessed.
    """
    name = Path(data_dir).name
    known = {normalize(item) for item in KNOWN_INSTANCES}
    if not name.startswith("soroush-bot"):
        return
    owner = "main"
    if name != "soroush-bot":
        suffix = name.split("soroush-bot", 1)[1].lstrip("-_")
        if suffix:
            owner = normalize(suffix)
    if owner != normalize(instance) and owner in known:
        raise InstanceConflict(
            f"data directory {data_dir} belongs to instance '{owner}' "
            f"but this process runs as '{instance}'"
        )


def describe() -> dict:
    """Small diagnostic snapshot (never contains secrets)."""
    marker = read_marker()
    env_name = requested()
    try:
        from modules.runtime_paths import INSTANCE_NAME, DATA_DIR
        effective = INSTANCE_NAME
        data_dir = str(DATA_DIR)
    except Exception:  # pragma: no cover - import-time diagnostics only
        effective = normalize(env_name or marker or "main")
        data_dir = "<unavailable>"
    return {
        "marker": marker,
        "env": env_name,
        "effective": effective,
        "project_root": str(PROJECT_ROOT),
        "data_dir": data_dir,
    }
