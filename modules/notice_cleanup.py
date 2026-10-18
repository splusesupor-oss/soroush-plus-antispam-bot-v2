"""Per-group auto-cleanup of bot system notices after a fixed TTL.

Only automatic moderation/spam notices belong here. Command replies, manual
admin warnings and ordinary chat are never scheduled.

Each group has its own worker and expiry heap, so a flood of notices in
group A cannot delay the 60-second delete in group B.  The incoming-message
dispatcher is never used: ``schedule`` is synchronous and only wakes that
group's worker.  Persistence is flushed by the worker, not the sender.
"""
import asyncio
import json
import os
import tempfile
import time

from modules import free_tier

DEFAULT_TTL_SECONDS = 60
MAX_PER_CHAT = 500
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 2


def _chat_key(chat_id):
    if chat_id is None:
        return "0"
    for attr in ("channel_id", "chat_id", "user_id", "id"):
        try:
            val = getattr(chat_id, attr, None)
            if isinstance(val, int):
                try:
                    from modules.group_id import normalize_group_id
                    return normalize_group_id(val)
                except Exception:
                    return str(val)
            if val is not None:
                try:
                    ival = int(val)
                    try:
                        from modules.group_id import normalize_group_id
                        return normalize_group_id(ival)
                    except Exception:
                        return str(ival)
                except Exception:
                    return str(val)
        except Exception:
            continue
    try:
        ival = int(chat_id)
        try:
            from modules.group_id import normalize_group_id
            return normalize_group_id(ival)
        except Exception:
            return str(ival)
    except Exception:
        pass
    try:
        return str(chat_id)
    except Exception:
        return "0" 


def _chat_id_for_rpc(value):
    """Turn persisted short channel IDs back into SPlusthon's -100 form."""
    try:
        chat_id = int(value)
    except (TypeError, ValueError):
        return value
    # notice cleanup is only used for group notices.  A positive persisted key
    # is the normalized channel ID, not a private-user ID; passing it directly
    # makes SPlusthon issue GetUsersRequest and retry a doomed delete.
    if chat_id > 0:
        try:
            from modules.group_id import CHANNEL_ID_OFFSET
            return -(CHANNEL_ID_OFFSET + chat_id)
        except Exception:
            return -1_000_000_000_000 - chat_id
    return chat_id


def extract_sent_id(sent):
    """Read a Soroush/SPlusthon send/reply result as a positive message id."""
    if sent is None or isinstance(sent, bool):
        return None
    if isinstance(sent, int):
        return sent if sent > 0 else None
    for attr in ("id", "message_id"):
        value = getattr(sent, attr, None)
        if isinstance(value, int) and value > 0:
            # Skip peer/channel objects whose .id is not this message.
            if attr == "id" and getattr(sent, "message", None) is sent:
                continue
            cls_name = type(sent).__name__
            if attr == "id" and ("Peer" in cls_name or "User" in cls_name or "Channel" in cls_name or "Chat" in cls_name):
                continue
            if cls_name.endswith("Message") or attr == "message_id" or hasattr(sent, "peer_id") or hasattr(sent, "out"):
                return value
            if cls_name == "SimpleNamespace":
                return value
    inner = getattr(sent, "message", None)
    if inner is not None and inner is not sent:
        found = extract_sent_id(inner)
        if found:
            return found
    if isinstance(sent, (list, tuple)):
        for item in sent:
            found = extract_sent_id(item)
            if found:
                return found
    updates = getattr(sent, "updates", None)
    if updates:
        for update in updates:
            found = extract_sent_id(getattr(update, "message", update))
            if found:
                return found
    update = getattr(sent, "update", None)
    if update is not None:
        found = extract_sent_id(getattr(update, "message", update))
        if found:
            return found
    # Last resort: a plain object with a positive .id that looks like a message.
    value = getattr(sent, "id", None)
    if isinstance(value, int) and value > 0 and not hasattr(sent, "access_hash"):
        return value
    return None


def extract_sent_peer(sent):
    """Return a resolved RPC peer retained on a sent message, when available."""
    if sent is None or isinstance(sent, (bool, int, str, bytes)):
        return None
    for attr in ("_input_chat", "input_chat"):
        try:
            peer = getattr(sent, attr, None)
        except Exception:
            peer = None
        if peer is not None:
            return peer
    inner = getattr(sent, "message", None)
    if inner is not None and inner is not sent:
        peer = extract_sent_peer(inner)
        if peer is not None:
            return peer
    if isinstance(sent, (list, tuple)):
        for item in sent:
            peer = extract_sent_peer(item)
            if peer is not None:
                return peer
    updates = getattr(sent, "updates", None)
    if updates:
        for update in updates:
            peer = extract_sent_peer(getattr(update, "message", update))
            if peer is not None:
                return peer
    update = getattr(sent, "update", None)
    if update is not None:
        return extract_sent_peer(getattr(update, "message", update))
    return None


def _message_id(value):
    return extract_sent_id(value)


def capture_sent(bot, chat_id, sent):
    """Schedule a just-sent automatic notice. Never awaits."""
    if not free_tier.is_enabled("notice_ttl_delete"):
        return False
    cleanup = getattr(bot, "notice_cleanup", None)
    if cleanup is None:
        return False
    return cleanup.schedule(chat_id, sent)


class NoticeCleanup:
    """Independent per-chat notice TTL workers."""

    def __init__(self, persist_path, logger=None, *, ttl_seconds=DEFAULT_TTL_SECONDS,
                 delete_queue=None, max_retries=DEFAULT_MAX_RETRIES,
                 retry_delay_seconds=DEFAULT_RETRY_DELAY_SECONDS):
        self.persist_path = persist_path
        self.logger = logger
        self.ttl_seconds = float(ttl_seconds)
        self.delete_queue = delete_queue
        self.max_retries = max(0, int(max_retries))
        self.retry_delay_seconds = max(0.01, float(retry_delay_seconds))
        self._items = {}
        # InputPeer/access-hash objects are process-local and intentionally not
        # serialized. They are retained from send results for reliable deletes.
        self._rpc_peers = {}
        self._workers = {}
        self._events = {}
        self._dirty = False
        self._started = False
        self._load()

    def bind_delete_queue(self, queue):
        self.delete_queue = queue

    def start(self):
        """Launch workers for any persisted notices. Safe to call once."""
        if not free_tier.is_enabled("notice_ttl_delete"):
            self._started = False
            return False
        self._started = True
        if self.logger is not None:
            self.logger.log_info(
                "NOTICE CLEANUP START "
                f"ttl_s={self.ttl_seconds:g} "
                f"pending_groups={len(self._items)}"
            )
        for chat_id, rows in list(self._items.items()):
            if rows:
                self._ensure_worker(chat_id)
        return True

    def stop(self):
        self._started = False
        for task in list(self._workers.values()):
            task.cancel()
        self._workers.clear()
        if self._dirty:
            self._persist()

    def schedule(self, chat_id, message_id, *, ttl=None, now=None):
        """Remember ``message_id`` for this chat. Returns True if stored."""
        if not free_tier.is_enabled("notice_ttl_delete"):
            return False
        raw = message_id
        message_id = _message_id(message_id)
        if chat_id is None or not isinstance(message_id, int) or message_id <= 0:
            if self.logger is not None:
                self.logger.log_error(
                    "NOTICE CLEANUP ID MISSING "
                    f"chat_id={chat_id} sent_type={type(raw).__name__} "
                    f"sent={raw!r}"
                )
            return False
        key = _chat_key(chat_id)
        rpc_peer = extract_sent_peer(raw)
        if rpc_peer is not None:
            self._rpc_peers[key] = rpc_peer
        ttl_s = float(self.ttl_seconds if ttl is None else ttl)
        expires_at = (time.time() if now is None else float(now)) + ttl_s
        rows = self._items.setdefault(key, [])
        for row in rows:
            if int(row["message_id"]) == message_id:
                row["expires_at"] = expires_at
                row["chat_id"] = chat_id
                row["attempts"] = 0
                break
        else:
            rows.append({
                "message_id": int(message_id),
                "expires_at": expires_at,
                "chat_id": chat_id,
                "attempts": 0,
            })
            if len(rows) > MAX_PER_CHAT:
                rows.sort(key=lambda item: item["expires_at"])
                del rows[:-MAX_PER_CHAT]
        self._dirty = True
        self._ensure_worker(key)
        event = self._events.get(key)
        if event is not None and not event.is_set():
            event.set()
        if self.logger is not None:
            self.logger.log_info(
                f"AUTO_NOTICE_CREATED chat_id={chat_id} message_id={message_id} "
                f"ttl_seconds={ttl_s:g} expires_at={expires_at:.2f}"
            )
            self.logger.log_info(
                f"AUTO_NOTICE_TIMER_STARTED chat_id={chat_id} message_id={message_id} "
                f"expires_at={expires_at:.2f} delay_seconds={ttl_s:g}"
            )
            self.logger.log_info(
                "NOTICE CLEANUP QUEUED "
                f"chat_id={chat_id} message_id={message_id} "
                f"expires_in_s={ttl_s:g} pending={len(rows)}"
            )
        return True

    def pending(self, chat_id):
        return list(self._items.get(_chat_key(chat_id), []))

    def due_ids(self, chat_id, now=None):
        now = time.time() if now is None else float(now)
        return [
            int(row["message_id"])
            for row in self._items.get(_chat_key(chat_id), [])
            if float(row["expires_at"]) <= now
        ]

    def pop_due(self, chat_id, now=None):
        """Remove and return expired IDs for one chat only."""
        key = _chat_key(chat_id)
        now = time.time() if now is None else float(now)
        rows = self._items.get(key, [])
        due = []
        kept = []
        for row in rows:
            if float(row["expires_at"]) <= now:
                due.append(int(row["message_id"]))
            else:
                kept.append(row)
        if due:
            if kept:
                self._items[key] = kept
            else:
                self._items.pop(key, None)
            self._dirty = True
        return due

    def next_expiry(self, chat_id, now=None):
        rows = self._items.get(_chat_key(chat_id), [])
        if not rows:
            return None
        return min(float(row["expires_at"]) for row in rows)

    def _ensure_worker(self, chat_id):
        if not free_tier.is_enabled("notice_ttl_delete") or not self._started:
            return
        key = _chat_key(chat_id)
        if key not in self._events:
            self._events[key] = asyncio.Event()
        worker = self._workers.get(key)
        if worker is None or worker.done():
            self._workers[key] = asyncio.create_task(
                self._worker(key), name=f"notice-cleanup-{key}"
            )

    def _enqueue_delete(self, chat_id, message_ids, rpc_chat=None):
        queue = self.delete_queue
        target = _chat_id_for_rpc(rpc_chat if rpc_chat is not None else chat_id)
        if queue is None:
            client = getattr(self, "client", None)
            if client is not None and hasattr(client, "delete_messages") and message_ids:
                async def _direct_delete():
                    try:
                        await client.delete_messages(target, list(message_ids))
                        return len(message_ids), []
                    except Exception as e:
                        if self.logger is not None:
                            self.logger.log_error(f"DIRECT NOTICE DELETE FAILED chat_id={chat_id} error={e!r}")
                        return 0, list(message_ids)
                return _direct_delete()
            return None
        if not message_ids:
            return None
        try:
            peer = self._rpc_peers.get(_chat_key(chat_id))
            try:
                return queue.enqueue(
                    target, message_ids, priority=1, rpc_peer=peer,
                )
            except TypeError as error:
                # Compatibility with a custom/legacy queue that predates the
                # optional resolved-peer keyword.
                if "rpc_peer" not in str(error):
                    raise
                return queue.enqueue(target, message_ids, priority=1)
        except Exception as error:
            if self.logger is not None:
                self.logger.log_error(
                    f"NOTICE CLEANUP ENQUEUE FAILED chat_id={chat_id} error={error!r}"
                )
            return None

    def _requeue_unresolved(self, chat_id, due_rows, remaining, *, now=None):
        """Persist unresolved notice IDs for bounded delayed retries."""
        key = _chat_key(chat_id)
        now = time.time() if now is None else float(now)
        source = {
            int(row["message_id"]): row for row in due_rows
            if isinstance(row.get("message_id"), int)
        }
        retry_rows = []
        abandoned = []
        for message_id in dict.fromkeys(remaining or ()):
            row = source.get(message_id, {"message_id": message_id})
            attempts = max(0, int(row.get("attempts", 0))) + 1
            if attempts > self.max_retries:
                abandoned.append(message_id)
                continue
            delay = min(60.0, self.retry_delay_seconds * (2 ** (attempts - 1)))
            retry_row = {
                "message_id": int(message_id),
                "expires_at": now + delay,
                "attempts": attempts,
            }
            if row.get("chat_id") is not None:
                retry_row["chat_id"] = row.get("chat_id")
            retry_rows.append(retry_row)

        if retry_rows:
            rows = self._items.setdefault(key, [])
            retry_ids = {row["message_id"] for row in retry_rows}
            rows[:] = [
                row for row in rows
                if int(row.get("message_id", 0)) not in retry_ids
            ]
            rows.extend(retry_rows)
            rows.sort(key=lambda row: float(row["expires_at"]))
            if len(rows) > MAX_PER_CHAT:
                del rows[:-MAX_PER_CHAT]
            self._dirty = True
            self._ensure_worker(key)
            event = self._events.get(key)
            if event is not None and not event.is_set():
                event.set()
        if self.logger is not None and (retry_rows or abandoned):
            if retry_rows:
                self.logger.log_error(
                    "NOTICE CLEANUP RETRY QUEUED "
                    f"chat_id={chat_id} remaining={len(retry_rows)} "
                    f"max_attempt={max(row['attempts'] for row in retry_rows)}"
                )
            if abandoned:
                self.logger.log_error(
                    "NOTICE CLEANUP ABANDONED "
                    f"chat_id={chat_id} message_ids={abandoned!r} "
                    f"max_retries={self.max_retries}"
                )
        return len(retry_rows), abandoned

    async def _worker(self, chat_id):
        if not free_tier.is_enabled("notice_ttl_delete"):
            return
        event = self._events[chat_id]
        if self.logger is not None:
            self.logger.log_info(f"NOTICE CLEANUP START chat_id={chat_id}")
        try:
            while self._started:
                rows = self._items.get(chat_id) or []
                if not rows:
                    # Retire idle per-chat tasks instead of retaining one task
                    # and Event for every group ever seen. schedule() starts a
                    # fresh worker synchronously when the next notice arrives.
                    return
                # Persist pending rows before sleeping or issuing the delete.
                # If the process dies while the RPC is in flight, the due IDs
                # therefore remain available for recovery after restart.
                if self._dirty:
                    self._persist()
                now = time.time()
                # Use the original stored chat ID (full -100... form) for RPC.
                # Due rows remain in memory and on disk until the result is
                # known, so cancellation or a process crash cannot lose them.
                rpc_chat = None
                for row in rows:
                    if row.get("chat_id") is not None:
                        rpc_chat = row.get("chat_id")
                        break
                due_rows = [
                    dict(row) for row in rows
                    if float(row["expires_at"]) <= now
                ]
                due = [int(row["message_id"]) for row in due_rows]
                if due:
                    if self.logger is not None:
                        self.logger.log_info(
                            f"AUTO_NOTICE_DELETE_TRIGGERED chat_id={chat_id} message_ids={due!r}"
                        )
                        self.logger.log_info(
                            "NOTICE CLEANUP DUE "
                            f"chat_id={chat_id} message_ids={due!r}"
                        )
                    result = self._enqueue_delete(chat_id, due, rpc_chat=rpc_chat)
                    deleted, remaining = 0, list(due)
                    try:
                        if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                            deleted, remaining = await result
                        elif result is not None and not isinstance(result, bool):
                            deleted, remaining = result
                        elif result:
                            deleted, remaining = len(due), []
                    except Exception as error:
                        if self.logger is not None:
                            self.logger.log_error(
                                "NOTICE CLEANUP DELETE FAILED "
                                f"chat_id={chat_id} message_ids={due!r} error={error!r}"
                            )
                    else:
                        if self.logger is not None:
                            self.logger.log_info(
                                f"AUTO_NOTICE_DELETE_RESULT chat_id={chat_id} message_ids={due!r} "
                                f"deleted={deleted} remaining={len(remaining or ())}"
                            )
                            self.logger.log_info(
                                "NOTICE CLEANUP DELETED "
                                f"chat_id={chat_id} message_ids={due!r} "
                                f"deleted={deleted} remaining={len(remaining or ())}"
                            )
                    due_set = set(due)
                    current_rows = self._items.get(chat_id, [])
                    kept_rows = [
                        row for row in current_rows
                        if int(row.get("message_id", 0)) not in due_set
                    ]
                    if kept_rows:
                        self._items[chat_id] = kept_rows
                    else:
                        self._items.pop(chat_id, None)
                    self._dirty = True
                    if remaining:
                        self._requeue_unresolved(
                            chat_id, due_rows, remaining, now=time.time(),
                        )
                    if self._dirty:
                        self._persist()
                    continue
                next_at = self.next_expiry(chat_id)
                if next_at is None:
                    continue
                delay = max(0.01, next_at - now)
                if self.logger is not None:
                    self.logger.log_info(
                        f"AUTO_NOTICE_TIMER_STARTED chat_id={chat_id} "
                        f"expires_at={next_at:.2f} delay_seconds={delay:.2f}"
                    )
                event.clear()
                try:
                    await asyncio.wait_for(event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self.logger is not None:
                self.logger.log_error(
                    f"NOTICE CLEANUP WORKER FAILED chat_id={chat_id} error={error!r}"
                )
        finally:
            if self._workers.get(chat_id) is asyncio.current_task():
                self._workers.pop(chat_id, None)
            if not self._items.get(chat_id):
                self._events.pop(chat_id, None)
                self._rpc_peers.pop(chat_id, None)
            if self._dirty:
                self._persist()

    def _load(self):
        """Restore only unexpired rows; never erase the saved state file.

        The free tier exits before loading any timer rows (and never starts a
        worker). On an entitled plan, only genuinely future expirations survive
        a restart; already-due cosmetic notices are not replayed as deletes.
        The serialized file is never unlinked during startup.
        """
        self._items = {}
        if not free_tier.is_enabled("notice_ttl_delete"):
            return
        path = self.persist_path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        restored = {}
        for key, rows in payload.items():
            if not isinstance(rows, list):
                continue
            keep = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    message_id = int(row.get("message_id", 0))
                    expires_at = float(row.get("expires_at", 0))
                    attempts = max(0, int(row.get("attempts", 0)))
                except (TypeError, ValueError, OverflowError):
                    continue
                if message_id <= 0 or expires_at <= now:
                    continue
                record = {
                    "message_id": message_id,
                    "expires_at": expires_at,
                    "attempts": attempts,
                }
                if row.get("chat_id") is not None:
                    record["chat_id"] = row["chat_id"]
                keep.append(record)
            if keep:
                restored[str(key)] = keep
        self._items = restored

    def _persist(self):
        path = self.persist_path
        if not path:
            self._dirty = False
            return
        payload = {
            key: list(rows) for key, rows in self._items.items() if rows
        }
        directory = os.path.dirname(path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            handle, tmp_path = tempfile.mkstemp(
                prefix="notice_cleanup.", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as tmp:
                    json.dump(payload, tmp, ensure_ascii=False)
                    tmp.write("\n")
                os.replace(tmp_path, path)
                self._dirty = False
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as error:
            if self.logger is not None:
                self.logger.log_error(
                    f"NOTICE CLEANUP SAVE FAILED error={error!r}"
                )
