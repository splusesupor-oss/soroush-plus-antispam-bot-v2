"""Per-group notice TTL. No network, no splusthon."""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.notice_cleanup import NoticeCleanup, capture_sent, extract_sent_id

PASSED = FAILED = 0


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


def _cleanup(path=None, ttl=60):
    if path is None:
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
    return NoticeCleanup(path, ttl_seconds=ttl), path


def test_schedule_is_per_group_and_not_due_yet():
    print("\n### صف هر گروه جداست و قبل از TTL due نیست")
    cleaner, path = _cleanup(ttl=60)
    try:
        now = 1_000_000.0
        check("schedule A", cleaner.schedule(-1, 11, now=now) is True)
        check("schedule B", cleaner.schedule(-2, 22, now=now) is True)
        check("A pending 1", len(cleaner.pending(-1)) == 1)
        check("B pending 1", len(cleaner.pending(-2)) == 1)
        check("A not due yet", cleaner.due_ids(-1, now=now + 59) == [])
        check("B not due yet", cleaner.due_ids(-2, now=now + 59) == [])
        check("A due after 60", cleaner.due_ids(-1, now=now + 60) == [11])
        check("B still isolated", cleaner.due_ids(-2, now=now + 59.9) == [])
    finally:
        if os.path.isfile(path):
            os.unlink(path)


def test_new_notice_waits_its_own_ttl():
    print("\n### اعلان بعدی TTL جدا دارد")
    cleaner, path = _cleanup(ttl=60)
    try:
        now = 2_000_000.0
        cleaner.schedule(-9, 1, now=now)
        cleaner.schedule(-9, 2, now=now + 30)
        check("first due at +60", cleaner.due_ids(-9, now=now + 60) == [1])
        check("second not due at +60", 2 not in cleaner.due_ids(-9, now=now + 60))
        check("second due at +90", 2 in cleaner.due_ids(-9, now=now + 90))
        popped = cleaner.pop_due(-9, now=now + 60)
        check("pop only first", popped == [1], f"-> {popped}")
        check("second still pending", [row["message_id"] for row in cleaner.pending(-9)] == [2])
    finally:
        if os.path.isfile(path):
            os.unlink(path)


def test_persist_survives_restart():
    print("\n### صف قدیمی replay نمی‌شود، اما فایل state حفظ می‌شود")
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    os.unlink(path)
    try:
        first = NoticeCleanup(path, ttl_seconds=60)
        first.schedule(-5, 77, now=3_000_000.0)
        first._persist()
        second = NoticeCleanup(path, ttl_seconds=60)
        pending = second.pending(-5)
        check("stale rows are not replayed", pending == [], f"-> {pending}")
        check("saved notice state is preserved", os.path.exists(path))
    finally:
        if os.path.isfile(path):
            os.unlink(path)


def test_extract_sent_id_from_splus_shapes():
    print("\n### استخراج message_id از شکل‌های پاسخ سروش")
    check("plain int", extract_sent_id(88) == 88)
    check("message.id", extract_sent_id(SimpleNamespace(id=12, out=True)) == 12)
    check(
        "updates.message.id",
        extract_sent_id(SimpleNamespace(updates=[
            SimpleNamespace(message=SimpleNamespace(id=33, out=True))
        ])) == 33,
    )
    check("none", extract_sent_id(None) is None)
    check("true is not an id", extract_sent_id(True) is None)


def test_capture_sent_uses_message_id():
    print("\n### capture_sent فقط از پیام خودکار id می‌گیرد")
    cleaner, path = _cleanup(ttl=10)
    try:
        bot = SimpleNamespace(notice_cleanup=cleaner)
        sent = SimpleNamespace(id=404)
        check("captured", capture_sent(bot, -8, sent) is True)
        check("stored", cleaner.pending(-8)[0]["message_id"] == 404)
        check("invalid skipped", capture_sent(bot, -8, None) is False)
        check("no cleanup is false", capture_sent(SimpleNamespace(), -8, sent) is False)
    finally:
        if os.path.isfile(path):
            os.unlink(path)


def test_worker_deletes_only_that_group():
    print("\n### worker فقط گروه خودش را حذف می‌کند")

    class _Queue:
        def __init__(self):
            self.calls = []

        def enqueue(self, chat_id, ids, *, priority=1):
            self.calls.append((chat_id, list(ids), priority))
            return True

    async def run():
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        queue = _Queue()
        cleaner = NoticeCleanup(path, ttl_seconds=0.05, delete_queue=queue)
        try:
            cleaner.schedule(-11, 501, now=time.time())
            cleaner.schedule(-12, 502, now=time.time() + 10)
            cleaner.start()
            await asyncio.sleep(0.2)
            return queue.calls, cleaner.pending(-11), cleaner.pending(-12)
        finally:
            cleaner.stop()
            if os.path.isfile(path):
                os.unlink(path)

    calls, left_a, left_b = asyncio.run(run())
    check("deleted group A only", any(call[0] == -11 and 501 in call[1] for call in calls), f"-> {calls}")
    check("group B not deleted", not any(502 in call[1] for call in calls), f"-> {calls}")
    check("A drained", left_a == [], f"-> {left_a}")
    check("B still waiting", len(left_b) == 1, f"-> {left_b}")


def test_persisted_short_group_id_is_restored_before_delete_rpc():
    print("\n### شناسهٔ کوتاه ذخیره‌شده به -100 برای RPC برمی‌گردد")
    class _Queue:
        def __init__(self): self.calls = []
        def enqueue(self, chat_id, ids, *, priority=1, rpc_peer=None):
            self.calls.append((chat_id, list(ids), priority))
            future = asyncio.get_running_loop().create_future()
            future.set_result((len(ids), []))
            return future

    async def run():
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            queue = _Queue()
            cleaner = NoticeCleanup(path, ttl_seconds=1, delete_queue=queue)
            cleaner._enqueue_delete(9429374, [9], rpc_chat=9429374)
            await asyncio.sleep(0)
            return queue.calls
        finally:
            if os.path.isfile(path): os.unlink(path)

    calls = asyncio.run(run())
    check("RPC chat is -100 form", calls and calls[0][0] == -1000009429374, f"-> {calls}")


def test_notice_timer_burst_retires_workers():
    print("\\n### ۱۲ اعلان موقت worker را leak نمی‌کند")

    class _Queue:
        def enqueue(self, chat_id, ids, *, priority=1, rpc_peer=None):
            future = asyncio.get_running_loop().create_future()
            future.set_result((len(ids), []))
            return future

    async def run():
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        cleaner = NoticeCleanup(path, ttl_seconds=0.05, delete_queue=_Queue())
        try:
            cleaner.start()
            now = time.time()
            for index in range(12):
                cleaner.schedule(-(100 + index), 1000 + index, now=now)
            during = sum(1 for task in cleaner._workers.values() if not task.done())
            await asyncio.sleep(0.25)
            leftover_workers = sum(
                1 for task in cleaner._workers.values() if not task.done()
            )
            leftover_items = sum(len(rows) for rows in cleaner._items.values())
            return during, leftover_workers, leftover_items
        finally:
            cleaner.stop()
            if os.path.isfile(path):
                os.unlink(path)

    during, leftover_workers, leftover_items = asyncio.run(run())
    check("burst started workers", during >= 12, f"-> {during}")
    check("workers retired after TTL", leftover_workers == 0, f"-> {leftover_workers}")
    check("notice rows drained", leftover_items == 0, f"-> {leftover_items}")


if __name__ == "__main__":
    test_schedule_is_per_group_and_not_due_yet()
    test_new_notice_waits_its_own_ttl()
    test_persist_survives_restart()
    test_extract_sent_id_from_splus_shapes()
    test_capture_sent_uses_message_id()
    test_worker_deletes_only_that_group()
    test_persisted_short_group_id_is_restored_before_delete_rpc()
    test_notice_timer_burst_retires_workers()
    print(f"\n{PASSED} passed, {FAILED} failed")
    raise SystemExit(1 if FAILED else 0)
