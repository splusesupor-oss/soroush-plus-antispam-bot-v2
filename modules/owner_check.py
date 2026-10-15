"""Single source of truth for global-owner authentication.

The canonical owner is deployment ``config/owner.json``.  Termux keeps mutable
runtime files in a private data directory, so an older copied ``owner.json``
may still exist there.  ``get_owner()`` always reads the deployment source and
atomically synchronizes any differing runtime copy.  No owner ID is embedded
in Python code and a stale runtime value is never used as a fallback.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from modules.atomic_write import write_json
from modules.runtime_paths import legacy_config_file, runtime_config_file


DEPLOYMENT_FILE = legacy_config_file("owner.json")
RUNTIME_FILE = runtime_config_file("owner.json", migrate=False)
# Backwards-compatible public name.  It now points at the canonical source.
FILE = DEPLOYMENT_FILE
_LOG = logging.getLogger(__name__)
_LOCK = threading.RLock()
_CACHE_SIGNATURE = None
_CACHE_OWNER: Optional[Dict[str, Any]] = None
_RUNTIME_SIGNATURE = None


def normalize_username(username):
    if username is None:
        return None
    normalized = str(username).strip().lstrip("@").strip().lower()
    return normalized or None


def _signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _read_owner_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("owner config root must be an object")
        user_id = int(data["user_id"])
        if user_id <= 0:
            raise ValueError("owner user_id must be a positive integer")
        return {
            "user_id": user_id,
            "username": normalize_username(data.get("username")),
        }
    except (OSError, KeyError, TypeError, ValueError) as error:
        _LOG.error("OWNER CONFIG READ FAILED file=%s error=%r", path, error)
        return None


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return str(first) == str(second)


def _sync_runtime_owner(owner: Dict[str, Any], runtime_file: Path) -> bool:
    """Replace any stale runtime owner with the canonical deployment owner."""
    global _RUNTIME_SIGNATURE
    if _same_path(DEPLOYMENT_FILE, runtime_file):
        _RUNTIME_SIGNATURE = _signature(runtime_file)
        return False

    signature = _signature(runtime_file)
    if runtime_file == RUNTIME_FILE and signature == _RUNTIME_SIGNATURE:
        return False
    runtime_owner = _read_owner_file(runtime_file) if signature is not None else None
    if runtime_owner == owner:
        if runtime_file == RUNTIME_FILE:
            _RUNTIME_SIGNATURE = signature
        return False

    write_json(runtime_file, owner, indent=2)
    try:
        runtime_file.chmod(0o600)
    except OSError:
        pass
    if runtime_file == RUNTIME_FILE:
        _RUNTIME_SIGNATURE = _signature(runtime_file)
    _LOG.warning(
        "OWNER RUNTIME CONFIG MIGRATED source=%s runtime=%s "
        "previous_user_id=%s current_user_id=%s",
        DEPLOYMENT_FILE,
        runtime_file,
        (runtime_owner or {}).get("user_id"),
        owner["user_id"],
    )
    return True


def _get_owner_from_files(
    deployment_file: Path,
    runtime_file: Path,
) -> Dict[str, Any]:
    """Uncached implementation used by tests and the public loader."""
    owner = _read_owner_file(Path(deployment_file))
    if owner is None:
        # Fail closed.  A stale runtime file must never become owner authority.
        return {"user_id": None, "username": None}
    if not _same_path(Path(deployment_file), Path(runtime_file)):
        runtime_owner = _read_owner_file(Path(runtime_file))
        if runtime_owner != owner:
            write_json(Path(runtime_file), owner, indent=2)
            try:
                Path(runtime_file).chmod(0o600)
            except OSError:
                pass
    return dict(owner)


def get_owner():
    """Return the canonical global owner and migrate stale runtime state."""
    global _CACHE_SIGNATURE, _CACHE_OWNER
    with _LOCK:
        signature = _signature(DEPLOYMENT_FILE)
        if signature != _CACHE_SIGNATURE or _CACHE_OWNER is None:
            owner = _read_owner_file(DEPLOYMENT_FILE)
            _CACHE_SIGNATURE = signature
            _CACHE_OWNER = (
                dict(owner)
                if owner is not None
                else {"user_id": None, "username": None}
            )
        owner = dict(_CACHE_OWNER)
        if owner.get("user_id") is not None:
            try:
                _sync_runtime_owner(owner, RUNTIME_FILE)
            except Exception as error:
                # Authentication still uses the canonical source.  Migration
                # failure is visible but can never reactivate the stale owner.
                _LOG.error(
                    "OWNER RUNTIME CONFIG MIGRATION FAILED source=%s "
                    "runtime=%s user_id=%s error=%r",
                    DEPLOYMENT_FILE,
                    RUNTIME_FILE,
                    owner.get("user_id"),
                    error,
                )
        return owner


def owner_configured() -> bool:
    """True when a real owner is configured for this deployment.

    ``get_owner()`` keeps returning a dict with ``user_id=None`` for backwards
    compatibility and fails closed, which is safe but *silent*: the bot then
    accepts nobody as owner.  Call this at startup so the operator finds out
    immediately instead of after the first rejected command.
    """
    return get_owner().get("user_id") is not None


_OWNER_MISSING_WARNED = False


def warn_if_owner_missing(logger=None) -> bool:
    """Emit one loud warning when no owner is configured.  Never raises."""
    global _OWNER_MISSING_WARNED
    if owner_configured():
        return False
    if _OWNER_MISSING_WARNED:
        return True
    _OWNER_MISSING_WARNED = True
    message = (
        "CONFIG WARNING: no global owner configured — every owner-only command "
        f"will be rejected. Create {DEPLOYMENT_FILE} with "
        '{"user_id": <numeric id>, "username": "<username>"}'
    )
    _LOG.error(message)
    if logger is not None:
        try:
            logger.log_notice(message)
        except Exception:
            pass
    return True


def is_global_owner(user):
    """Only the user ID currently returned by ``get_owner()`` is accepted."""
    if user is None:
        return False
    user_id = getattr(user, "id", user)
    owner_id = get_owner().get("user_id")
    if owner_id is None:
        return False
    try:
        return int(user_id) == int(owner_id)
    except (TypeError, ValueError):
        return False


is_owner = is_global_owner
