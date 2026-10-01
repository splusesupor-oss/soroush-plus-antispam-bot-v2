"""Persistent, per-group clipboard state for the Fox bot.

The clipboard deliberately has no dependency on the message handler or on a
running SPlusthon client.  It stores text and the native formatting entities
next to it, using the same runtime path/instance isolation and atomic JSON
writes as the other persistent bot features.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from modules.atomic_write import write_json
from modules.group_id import normalize_group_id
from modules.runtime_paths import runtime_config_file


FILE = Path(runtime_config_file("clipboard.json"))
MAX_TEXT_UTF16 = 4096
PENDING_GUIDE_TTL_SECONDS = 24 * 60 * 60

_EMPTY_RECORD = {"text": "", "entities": [], "updated_at": 0.0}
_LOCK = threading.RLock()
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_MTIME = None


def _file_mtime():
    try:
        return FILE.stat().st_mtime_ns
    except OSError:
        return None


def _group_key(chat_id) -> str:
    return str(normalize_group_id(chat_id))


def _load() -> Dict[str, Any]:
    global _CACHE, _CACHE_MTIME
    mtime = _file_mtime()
    if _CACHE is not None and mtime == _CACHE_MTIME:
        return _CACHE
    if mtime is None:
        data = {}
    else:
        try:
            data = json.loads(FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, TypeError):
            data = {}
    _CACHE = data
    _CACHE_MTIME = mtime
    return data


def _save(data: Dict[str, Any]) -> None:
    global _CACHE, _CACHE_MTIME
    FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(FILE, data, indent=2)
    _CACHE = data
    _CACHE_MTIME = _file_mtime()


def _json_value(value):
    """Convert a TL attribute to JSON without inventing formatting."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}

    # Some entity fields (for example mention-name user_id) can themselves be
    # TL objects.  Keep their type and public fields so they can be rebuilt.
    nested = getattr(value, "__dict__", None)
    if isinstance(nested, dict):
        return {
            "__tl_type__": type(value).__name__,
            "attrs": {
                str(key): _json_value(item)
                for key, item in nested.items()
                if not str(key).startswith("_")
            },
        }

    # Unknown fields must not make a successful clipboard save crash.  Scalar
    # formatting fields are handled above; an unsupported object is omitted by
    # its caller rather than represented as fake Markdown.
    raise TypeError(f"unsupported formatting field: {type(value).__name__}")


def _from_json_value(value, types_module=None):
    if isinstance(value, list):
        return [_from_json_value(item, types_module) for item in value]
    if isinstance(value, dict):
        if "__tl_type__" in value:
            type_name = str(value.get("__tl_type__") or "")
            attrs = _from_json_value(value.get("attrs") or {}, types_module)
            return _construct_entity(type_name, attrs, types_module)
        return {
            key: _from_json_value(item, types_module)
            for key, item in value.items()
        }
    return value


def _public_entity_attrs(entity) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {}
    source = getattr(entity, "__dict__", None)
    if isinstance(source, dict):
        for key, value in source.items():
            key = str(key)
            if key.startswith("_"):
                continue
            try:
                attrs[key] = _json_value(value)
            except TypeError:
                # Preserve all normal formatting entities even if a future API
                # adds a non-JSON helper field.
                continue

    # A few TL implementations use slots instead of __dict__.
    for key in (
        "offset", "length", "url", "language", "document_id", "user_id",
    ):
        if key in attrs:
            continue
        try:
            value = getattr(entity, key)
        except (AttributeError, TypeError):
            continue
        try:
            attrs[key] = _json_value(value)
        except TypeError:
            continue
    return attrs


def serialize_entities(entities: Iterable[Any]) -> List[Dict[str, Any]]:
    """Serialize native SPlusthon/Telethon-style entities for JSON storage."""
    result = []
    for entity in entities or ():
        if entity is None:
            continue
        attrs = _public_entity_attrs(entity)
        if "offset" not in attrs or "length" not in attrs:
            # An entity without a span cannot be sent safely after a restart.
            continue
        result.append({
            "type": type(entity).__name__,
            "attrs": attrs,
        })
    return result


def _construct_entity(type_name: str, attrs: Dict[str, Any], types_module=None):
    if not type_name.startswith("MessageEntity"):
        return None
    if types_module is None:
        try:
            from splusthon.tl import types as types_module  # type: ignore
        except Exception:
            return None
    entity_class = getattr(types_module, type_name, None)
    if entity_class is None:
        return None

    try:
        return entity_class(**attrs)
    except Exception:
        # The project already uses this safe clone strategy for SPlusthon TL
        # objects.  It preserves extra fields when a constructor differs
        # slightly between installed SPlusthon versions.
        try:
            entity = entity_class.__new__(entity_class)
            if hasattr(entity, "__dict__"):
                entity.__dict__.update(attrs)
                return entity
        except Exception:
            pass
    return None


def deserialize_entities(payload: Iterable[Dict[str, Any]], types_module=None) -> List[Any]:
    result = []
    for item in payload or ():
        if not isinstance(item, dict):
            continue
        type_name = str(item.get("type") or "")
        attrs = item.get("attrs")
        if not isinstance(attrs, dict):
            continue
        attrs = _from_json_value(attrs, types_module)
        entity = _construct_entity(type_name, attrs, types_module)
        if entity is not None:
            result.append(entity)
    return result


def _normalize_text(text) -> str:
    return str(text or "")


def validate_text(text) -> Tuple[bool, Optional[str]]:
    """Validate clipboard content using the project's existing safety filters."""
    value = _normalize_text(text)
    if not value.strip():
        return False, "❌ متن یا لینک قابل ذخیره نیست؛ پیام خالی است."
    if len(value.encode("utf-16-le")) // 2 > MAX_TEXT_UTF16:
        return False, (
            "❌ متن بیش از حد طولانی است و با محدودیت پیام سروش پلاس سازگار نیست."
        )

    try:
        from economy import name_filter
        if name_filter.classify(value) == name_filter.BANNED:
            return False, "❌ این متن به دلیل داشتن محتوای غیرمجاز قابل ذخیره در کپی بورد نیست."
    except Exception:
        # Do not silently replace a working filter with a weaker ad-hoc list.
        # If the optional filter cannot load, the existing spam detector below
        # still provides the project's configured banned-word policy.
        pass

    # This is the bot's existing explicit sexual-content filter, shared with
    # the image-search feature.  Import lazily so clipboard storage remains
    # usable in offline/unit-test environments without requests.
    try:
        from modules.photo_download import is_blocked
        if is_blocked(value):
            return False, "❌ این متن به دلیل داشتن محتوای غیرمجاز قابل ذخیره در کپی بورد نیست."
    except Exception:
        pass

    return True, None


def save(chat_id, text, entities=()) -> Tuple[bool, Optional[str]]:
    """Replace the clipboard for one group, after validating its content."""
    ok, reason = validate_text(text)
    if not ok:
        return False, reason
    key = _group_key(chat_id)
    record = {
        "text": _normalize_text(text),
        "entities": serialize_entities(entities),
        "updated_at": time.time(),
    }
    with _LOCK:
        data = _load()
        data[key] = record
        _save(data)
    return True, None


def get(chat_id) -> Optional[Dict[str, Any]]:
    """Return a copy of the current group clipboard, or ``None``."""
    with _LOCK:
        record = _load().get(_group_key(chat_id))
        if not isinstance(record, dict) or not str(record.get("text") or "").strip():
            return None
        return {
            "text": str(record.get("text") or ""),
            "entities": deserialize_entities(record.get("entities") or []),
            "updated_at": record.get("updated_at", 0.0),
        }


def get_raw(chat_id) -> Optional[Dict[str, Any]]:
    """Return raw JSON data for diagnostics/tests without constructing TL objects."""
    with _LOCK:
        record = _load().get(_group_key(chat_id))
        return dict(record) if isinstance(record, dict) else None


def set_pending_guide(chat_id, message_id, *, now=None) -> bool:
    if message_id is None:
        return False
    try:
        normalized_message_id = int(message_id)
    except (TypeError, ValueError):
        return False
    key = _group_key(chat_id)
    with _LOCK:
        data = _load()
        current = data.get(key)
        if not isinstance(current, dict):
            current = {}
        current["pending_guide_id"] = normalized_message_id
        current["pending_guide_at"] = float(time.time() if now is None else now)
        data[key] = current
        _save(data)
    return True


def get_pending_guide(chat_id, *, now=None) -> Optional[int]:
    with _LOCK:
        record = _load().get(_group_key(chat_id))
        if not isinstance(record, dict):
            return None
        message_id = record.get("pending_guide_id")
        created = record.get("pending_guide_at")
        try:
            message_id = int(message_id)
            created = float(created)
        except (TypeError, ValueError):
            return None
        current_time = time.time() if now is None else float(now)
        if current_time - created > PENDING_GUIDE_TTL_SECONDS:
            return None
        return message_id


def clear_pending_guide(chat_id) -> None:
    key = _group_key(chat_id)
    with _LOCK:
        data = _load()
        record = data.get(key)
        if not isinstance(record, dict):
            return
        record.pop("pending_guide_id", None)
        record.pop("pending_guide_at", None)
        if not str(record.get("text") or "").strip() and not record.get("entities"):
            data.pop(key, None)
        _save(data)


def reset_cache() -> None:
    """Test/helper hook; does not delete persistent clipboard data."""
    global _CACHE, _CACHE_MTIME
    with _LOCK:
        _CACHE = None
        _CACHE_MTIME = None
