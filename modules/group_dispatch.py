"""Per-group incoming-message dispatcher with isolated lanes.

SPlusthon starts a task for every NewMessage.  A spam wave in one chat then
spawns hundreds of concurrent handlers that all fight for the same RPC
sender, so admin commands stall.

This dispatcher keeps **isolated workers per (chat_id, lane)**:

* ``admin``     — owner/moderation commands; never dropped; 1 worker per chat (serial, preserves order)
* ``command``   — public/user commands (help, games, shop); never dropped; 1 worker per chat
* ``normal``    — ordinary chat / spam; capped by ``max_pending_normal``; **6 concurrent workers per chat** by default

Lanes of the same group run at the same time, so mute/ban/lock do not wait
for a heavy normal job.  Different chats stay independent.
Normal lane uses multiple workers per chat so a burst in one chat
(15×150ms) is absorbed in roughly 400ms instead of ~2200ms.

Heavy background work (spam cleanup, moderation callbacks, notice expiry,
delete batches, flush) never goes through this dispatcher; each has its
own per-chat queue/worker and is fire-and-forget via ``asyncio.create_task``
so it cannot fill the normal message queue.

Classification is text-only: no await, no RPC, no file I/O.
"""
import asyncio
import contextvars
import inspect
import os
import time

try:
    from modules.outgoing_sender import DISPATCH_ACTIVE_VAR
    _HAS_OUTGOING = True
except ImportError:
    _HAS_OUTGOING = False
    DISPATCH_ACTIVE_VAR = contextvars.ContextVar("fallback", default=False)

try:
    from modules.group_id import normalize_group_id
    _HAS_NORMALIZE = True
except ImportError:
    _HAS_NORMALIZE = False
    def normalize_group_id(v):
        try:
            return str(int(v))
        except Exception:
            return str(v)

def _chat_key(chat_id):
    """Hashable key for chat. Never use InputPeer directly as dict key."""
    if chat_id is None:
        return "0"
    # Try to extract numeric id from InputPeerChannel etc.
    for attr in ("channel_id", "chat_id", "user_id", "id"):
        try:
            val = getattr(chat_id, attr, None)
            if isinstance(val, int):
                return normalize_group_id(val) if _HAS_NORMALIZE else str(val)
            if val is not None:
                try:
                    ival = int(val)
                    return normalize_group_id(ival) if _HAS_NORMALIZE else str(ival)
                except Exception:
                    return str(val)
        except Exception:
            continue
    try:
        ival = int(chat_id)
        return normalize_group_id(ival) if _HAS_NORMALIZE else str(ival)
    except Exception:
        pass
    try:
        from splusthon import utils as _sutils
        peer = _sutils.get_peer_id(chat_id)
        if peer is not None:
            try:
                return normalize_group_id(peer) if _HAS_NORMALIZE else str(int(peer))
            except Exception:
                return str(peer)
    except Exception:
        pass
    try:
        return str(chat_id)
    except Exception:
        return "0"

def _key_for_dict(chat_id):
    return _chat_key(chat_id)

PRIORITY_ADMIN = 0
PRIORITY_COMMAND = 1
PRIORITY_NORMAL = 2

LANE_ADMIN = "admin"
LANE_COMMAND = "command"
LANE_NORMAL = "normal"

# Exact Persian admin/owner commands.
_ADMIN_EXACT = frozenset({
    "بن", "اخراج", "قفل", "باز", "پاک",
    "سکوت", "رفع سکوت", "آزاد", "اخطار",
    "ثبت ادمین", "لغو ادمین", "برکناری ادمین",
    "فعال", "غیر فعال", "فعال سازی",
    "ثبت گروه", "حذف گروه", "ثبت مالک", "لغو مالک", "برکناری مالک",
    "لیست انقضا", "مهلت گروه", "صفر",
    "هوش مصنوعی فعال", "هوش مصنوعی خاموش",
    "مجاز", "غیرمجاز", "غیر مجاز", "لیست هوش مصنوعی",
    "پاکسازی خودکار", "لاگ مدیریتی",
    "ثبت قوانین", "حذف قوانین",
    "ریست آمار", "ریست اخراجی ها",
    "حذف اخطار", "حذف اخطارها",
    "اطلاع رسانی", "تایید", "✅ تایید", "لغو", "❌ لغو",
    "لیست ادمین", "لیست ادمینی",
    "سنجاق",
    "فعال کلمات ممنوعه", "لغو کلمات ممنوعه",
    "سابقه ها", "سابقه‌ها",
    "تغییر اخطار", "تغییر مجازات",
    # دستور تشخیصی مالک باید حتی زیر بار سنگین از لاین admin برود.
    "وضعیت ربات", "پینگ ربات",
    # Clipboard management is a protected admin lane so it never waits
    # behind ordinary spam traffic.
    "کپی بورد", "کپی",
    # فیلتر اسم هم مثل بقیهٔ دستورات مدیریتی باید در لاین محافظت‌شده بماند.
    "لیست فیلتر اسم",
})

_ADMIN_PREFIXES = (
    "پاک ", "بن ", "اخراج ", "سکوت ",
    "ثبت ادمین", "لغو ادمین", "برکناری ادمین",
    "فیلتر اسم", "حذف فیلتر اسم", "لغو اسم",
    "مجاز ", "غیر مجاز", "غیرمجاز",
    "!", "/", ".",
)

# Public / user commands.  Checked only after admin so «ثبت ادمین» stays admin.
_COMMAND_EXACT = frozenset({
    "راهنما", "help",
    "لیست بازی", "لیست بازی ها", "لیست بازی‌ها", "بازی ها", "بازی‌ها",
    "لیست کاربران",
    "موجودی", "فروشگاه", "انتقال سکه",
    "رتبه ها", "رتبه‌ها", "امتیاز من", "راهنمای امتیاز",
    "آمارم", "آمار گپ", "آمار گروه",
    "بیوگرافی", "جک", "دانستنی", "ترجمه", "یاد آوری",
    "حافظه من", "حذف اسم", "قوانین",
    "حدس ایموجی", "حدس جمله", "ساخت جمله", "معما", "حدس پرچم",
    "مین یاب", "بهترین جواب", "نبرد", "بخند یا بباز",
    "جعبه شانسی", "خون آشام", "خون‌آشام",
    "اسم فامیل", "چهار گزینه ای", "جای خالی", "چیستان", "تصحیح کلمات",
    "جرعت", "جرات", "جرئت", "حقیقت", "حقیقت بگو",
    "ربات", "روباه",
    "سطح گروه", "پیام سنجاق",
    "تست دکمه", "دانلود عکس",
    "ثبت اصل", "اصلم",
})

_COMMAND_PREFIXES = (
    "ثبت اسم ", "شخصیت ", "فونت ", "جستجو ",
)

_LINK_MARKERS = (
    "http://", "https://", "www.", "t.me/", "telegram.me/",
    "splus.ir", "sapp.ir", "soroush.ir",
)


def normalize_dispatch_text(text):
    if not text:
        return ""
    value = str(text).replace("\u200c", " ").replace("\u200f", "").replace("\u200e", "")
    value = value.replace("ي", "ی").replace("ك", "ک")
    return " ".join(value.split())


def classify_priority(text, event=None):
    """Return ``(priority, kind)`` from the message text alone."""
    raw = normalize_dispatch_text(text)
    if not raw:
        return PRIORITY_NORMAL, LANE_NORMAL
    if raw in _ADMIN_EXACT:
        return PRIORITY_ADMIN, LANE_ADMIN
    if raw.startswith(_ADMIN_PREFIXES):
        return PRIORITY_ADMIN, LANE_ADMIN
    if raw in _COMMAND_EXACT:
        return PRIORITY_COMMAND, LANE_COMMAND
    # فراخوانی مستقیم روباه نباید پشت موج پیام‌های عادی بماند.
    if raw.startswith(("روباه ", "روباه،", "روباه,", "ربات ", "ربات،", "ربات,")):
        return PRIORITY_COMMAND, LANE_COMMAND
    if raw.startswith(_COMMAND_PREFIXES):
        return PRIORITY_COMMAND, LANE_COMMAND
    return PRIORITY_NORMAL, LANE_NORMAL


def lane_for(priority, kind=None):
    if kind == LANE_ADMIN or int(priority) <= PRIORITY_ADMIN:
        return LANE_ADMIN
    if kind == LANE_COMMAND or int(priority) == PRIORITY_COMMAND:
        return LANE_COMMAND
    return LANE_NORMAL


def looks_like_link(text):
    value = str(text or "").lower()
    if any(marker in value for marker in _LINK_MARKERS):
        return True
    return any(ext in value for ext in (".com/", ".ir/", ".net/", ".org/"))


def _message_bits(event):
    message = getattr(event, "message", None)
    chat_id = getattr(event, "chat_id", None)
    message_id = getattr(message, "id", None) if message is not None else None
    text = ""
    if message is not None:
        text = getattr(message, "message", None) or getattr(message, "caption", None) or ""
    user_id = getattr(event, "sender_id", None)
    if user_id is None:
        sender = getattr(event, "sender", None)
        user_id = getattr(sender, "id", None)
    return chat_id, message_id, user_id, text


class GroupDispatcher:
    """Independent admin / command / normal workers per chat."""

    # Do not park a ready job behind another lane of the same chat.
    # Admin / command / normal already have separate workers; extra
    # yield only added queue_wait after Soroush had already answered.
    HIGHER_LANE_WAIT_SECONDS = 0.0

    def __init__(self, *, max_pending_normal=None, logger=None,
                 normal_concurrency=None, debug_timing=False):
        if max_pending_normal is None:
            max_pending_normal = os.getenv("BOT_MAX_PENDING_NORMAL", "120")
        self.max_pending_normal = max(20, min(500, int(max_pending_normal)))
        if normal_concurrency is None:
            normal_concurrency = os.getenv(
                "BOT_NORMAL_WORKERS_PER_CHAT", "6"
            )
        try:
            self.normal_concurrency = min(
                8, max(1, int(normal_concurrency))
            )
        except (TypeError, ValueError):
            self.normal_concurrency = 6
        self.logger = logger
        # 📝 در حالت عادی فقط موارد به‌شدت کند ثبت می‌شوند تا نوشتن مکرر
        # روی دیسک، خودش عامل کندی نشود؛ در حالت debug (کلید
        # debug_message_pipeline در config) همان آستانه‌های قبلی کامل
        # ثبت می‌شوند. هیچ تغییری در منطق صف‌ها ایجاد نشده است.
        self.debug_timing = bool(debug_timing)
        self._queues = {}
        # key -> list[Task]  (normal lane may have up to normal_concurrency workers)
        self._workers = {}
        self._normal_pending = {}
        self._busy = set()
        self._busy_counts = {}
        self._seq = 0
        self._closed = False
        self.stats = {
            "submitted": 0,
            "admin": 0,
            "command": 0,
            "normal": 0,
            "dropped": 0,
            "processed": 0,
            "failed": 0,
        }

    def pending_normal(self, chat_id):
        return int(self._normal_pending.get(_chat_key(chat_id), 0))

    def queue_size(self, chat_id):
        total = 0
        key = _chat_key(chat_id)
        for (stored_chat, _lane), queue in self._queues.items():
            if stored_chat == key:
                total += queue.qsize()
        return total

    def worker_count(self):
        return sum(
            sum(1 for t in lst if t is not None and not t.done())
            for lst in self._workers.values()
        )

    def _lane_key(self, chat_id, lane):
        return (_chat_key(chat_id), lane)

    def _desired_concurrency(self, lane):
        if lane == LANE_NORMAL:
            return self.normal_concurrency
        return 1

    def _alive_workers(self, key):
        lst = self._workers.get(key)
        if not lst:
            return []
        return [t for t in lst if t is not None and not t.done()]

    def submit(self, chat_id, factory, *, priority=PRIORITY_NORMAL, kind="normal",
               on_overflow=None):
        """Enqueue ``factory()`` on the matching lane.  Never awaits."""
        if self._closed:
            return False
        if chat_id is None:
            chat_id = 0
        lane = lane_for(priority, kind)
        if lane == LANE_NORMAL:
            if self._normal_pending.get(_chat_key(chat_id), 0) >= self.max_pending_normal:
                self.stats["dropped"] += 1
                try:
                    from modules.observability import MetricsCollector
                    MetricsCollector.get_instance().record_overflow("group_dispatcher", chat_id)
                except Exception:
                    pass
                if self.logger is not None:
                    self.logger.log_info(
                        "GROUP DISPATCH OVERFLOW "
                        f"chat_id={chat_id} pending={self._normal_pending.get(_chat_key(chat_id), 0)}"
                    )
                if on_overflow is not None:
                    try:
                        on_overflow()
                    except Exception as error:
                        if self.logger is not None:
                            self.logger.log_error(
                                f"GROUP DISPATCH OVERFLOW CALLBACK FAILED "
                                f"chat_id={chat_id} error={error!r}"
                            )
                return False

        key = self._lane_key(chat_id, lane)
        queue = self._queues.get(key)
        if queue is None:
            queue = asyncio.PriorityQueue()
            self._queues[key] = queue
        self._seq += 1
        queue.put_nowait(
            (int(priority), self._seq, kind or lane, factory, time.perf_counter())
        )
        self.stats["submitted"] += 1
        if lane == LANE_ADMIN:
            self.stats["admin"] += 1
        elif lane == LANE_COMMAND:
            self.stats["command"] += 1
        else:
            self._normal_pending[_chat_key(chat_id)] = self._normal_pending.get(_chat_key(chat_id), 0) + 1
            self.stats["normal"] += 1

        # Ensure enough workers for this lane (normal: up to normal_concurrency)
        workers = self._workers.get(key)
        if workers is None:
            workers = []
            self._workers[key] = workers
        # Prune done workers
        workers[:] = [t for t in workers if not t.done()]
        desired = self._desired_concurrency(lane)
        alive = len(workers)
        # Spawn if we have fewer than desired and queue has work.
        # For normal lane this scales quickly under burst (15 messages → 3 workers).
        if alive < desired:
            # For normal, spawn one per submit until desired is reached;
            # for admin/command, spawn only if none alive.
            # Also, if queue depth exceeds alive, we may need more.
            needed = desired - alive
            # If queue is deep, spawn up to needed at once (not just 1)
            # but cap to 1 per submit to avoid thundering herd on first burst.
            # We spawn 1 per submit which converges in 3 submits for normal.
            workers.append(asyncio.create_task(
                self._worker(chat_id, lane, queue)
            ))
            # If the burst enqueued 15 at once before any worker started,
            # the first worker will see a deep queue; it could still benefit
            # from extra workers, but the next submits will spawn them.
            # To handle a single bulk submit, check depth:
            if lane == LANE_NORMAL and queue.qsize() > len(workers) * 2 and len(workers) < desired:
                # Queue is still deep after spawning one, spawn one more immediately
                # (up to desired). This handles the case where 15 were enqueued
                # with a single submit loop that reuses same event loop tick.
                while len(workers) < desired and queue.qsize() > len(workers):
                    workers.append(asyncio.create_task(
                        self._worker(chat_id, lane, queue)
                    ))
        elif not workers:
            workers.append(asyncio.create_task(
                self._worker(chat_id, lane, queue)
            ))
        return True

    async def _worker(self, chat_id, lane, queue):
        if self.logger is not None:
            self.logger.log_info(
                f"GROUP DISPATCH WORKER START chat_id={chat_id} lane={lane}"
            )
        key = self._lane_key(chat_id, lane)
        try:
            while True:
                try:
                    item = await queue.get()
                except asyncio.CancelledError:
                    raise
                if len(item) == 5:
                    priority, _seq, kind, factory, enqueued_at = item
                else:
                    priority, _seq, kind, factory = item
                    enqueued_at = time.perf_counter()
                if lane == LANE_NORMAL:
                    current = self._normal_pending.get(_chat_key(chat_id), 1)
                    self._normal_pending[_chat_key(chat_id)] = max(0, current - 1)
                yield_ms = await self._yield_to_higher_lanes(chat_id, lane)
                started = time.perf_counter()
                queue_wait_ms = (started - enqueued_at) * 1000
                try:
                    from modules.observability import MetricsCollector
                    MetricsCollector.get_instance().record_queue_wait(f"dispatcher_{lane}", queue_wait_ms)
                except Exception:
                    pass
                # Track busy counts for accurate _lane_busy with concurrency
                self._busy.add(key)
                self._busy_counts[key] = self._busy_counts.get(key, 0) + 1
                # Mark that we are inside a GroupDispatcher worker so that
                # outgoing_sender can enqueue send_message/reply instead of awaiting RPC.
                # Store the priority (0=admin,1=command,2=normal) so outgoing_sender
                # can give admin/command the highest send priority.
                _dispatch_token = None
                if _HAS_OUTGOING:
                    # priority is already defined in this loop's item
                    _dispatch_token = DISPATCH_ACTIVE_VAR.set(int(priority))
                try:
                    result = factory() if factory is not None else None
                    if inspect.isawaitable(result):
                        await result
                    self.stats["processed"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.stats["failed"] += 1
                    if self.logger is not None:
                        self.logger.log_error(
                            "GROUP DISPATCH JOB FAILED "
                            f"chat_id={chat_id} lane={lane} kind={kind} error={error!r}"
                        )
                finally:
                    if _HAS_OUTGOING and _dispatch_token is not None:
                        try:
                            DISPATCH_ACTIVE_VAR.reset(_dispatch_token)
                        except Exception:
                            pass
                    cnt = self._busy_counts.get(key, 1) - 1
                    if cnt <= 0:
                        self._busy_counts.pop(key, None)
                        self._busy.discard(key)
                    else:
                        self._busy_counts[key] = cnt
                    queue.task_done()
                    if self.logger is not None:
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        if self.debug_timing:
                            queue_wait_threshold = 50.0
                            handler_threshold = 100.0
                        else:
                            # Production timing is reported by the silent
                            # aggregate monitor; terminal timing logs are debug-only.
                            queue_wait_threshold = float("inf")
                            handler_threshold = float("inf")
                        if queue_wait_ms >= queue_wait_threshold:
                            self.logger.log_info(
                                "QUEUE WAIT TIME "
                                f"chat_id={chat_id} lane={lane} kind={kind} "
                                f"queue_wait_ms={queue_wait_ms:.1f} "
                                f"yield_ms={yield_ms:.1f}"
                            )
                        if elapsed_ms >= handler_threshold or (
                            self.debug_timing and lane != LANE_NORMAL
                        ):
                            self.logger.log_info(
                                "HANDLER TIME "
                                f"chat_id={chat_id} lane={lane} kind={kind} "
                                f"handler_ms={elapsed_ms:.1f}"
                            )
                            self.logger.log_info(
                                "GROUP DISPATCH JOB "
                                f"chat_id={chat_id} lane={lane} kind={kind} "
                                f"priority={priority} ms={elapsed_ms:.1f}"
                            )
                if queue.empty():
                    # Give a tiny window for a burst that is still being
                    # enqueued in this same tick.  Without this, a 15-message
                    # burst enqueued in a tight loop would be seen as empty
                    # by the first worker after its first item, causing it to
                    # exit before the remaining 14 are drained by the extra
                    # workers (which would then also exit early).
                    await asyncio.sleep(0)
                    if queue.empty():
                        return
        finally:
            # Remove this worker from the list
            lst = self._workers.get(key)
            if lst is not None:
                try:
                    cur_task = asyncio.current_task()
                except RuntimeError:
                    cur_task = None
                if cur_task is not None:
                    try:
                        lst.remove(cur_task)
                    except ValueError:
                        pass
                if not lst:
                    self._workers.pop(key, None)
                    # Only pop queue if truly empty (another worker may have just enqueued)
                    if queue.empty():
                        self._queues.pop(key, None)
                        if lane == LANE_NORMAL:
                            self._normal_pending.pop(_chat_key(chat_id), None)
                    elif not self._closed:
                        # Queue still has items: respawn worker immediately
                        try:
                            loop = asyncio.get_running_loop()
                            if loop.is_running():
                                self._workers[key] = [loop.create_task(
                                    self._worker(chat_id, lane, queue)
                                )]
                        except RuntimeError:
                            pass
            self._busy.discard(key)
            self._busy_counts.pop(key, None)

    def _lane_busy(self, chat_id, lane):
        key = self._lane_key(chat_id, lane)
        if key in self._busy:
            return True
        queue = self._queues.get(key)
        return bool(queue is not None and queue.qsize() > 0)

    async def _yield_to_higher_lanes(self, chat_id, lane):
        """Kept for log compatibility. Never sleeps; workers stay independent."""
        return 0.0

    async def join(self, timeout=None):
        """Wait until every queued job has finished (tests / shutdown)."""
        async def _wait():
            while True:
                queues = [queue for queue in self._queues.values() if queue.qsize()]
                workers = []
                for lst in self._workers.values():
                    workers.extend([t for t in lst if not t.done()])
                if not queues and not workers:
                    return
                for queue in list(self._queues.values()):
                    await queue.join()
                if workers:
                    await asyncio.gather(*workers, return_exceptions=True)
                await asyncio.sleep(0)

        if timeout is None:
            await _wait()
            return True
        try:
            await asyncio.wait_for(_wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def close(self):
        self._closed = True
        workers = []
        for lst in self._workers.values():
            workers.extend(lst)
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
        self._normal_pending.clear()
        self._busy.clear()
        self._busy_counts.clear()

    def reset_for_tests(self):
        self._queues.clear()
        self._workers.clear()
        self._normal_pending.clear()
        self._busy.clear()
        self._busy_counts.clear()
        self._seq = 0
        self._closed = False
        for key in self.stats:
            self.stats[key] = 0
