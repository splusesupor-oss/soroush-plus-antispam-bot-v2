"""Focused delete-pressure and persistent notice retry regressions."""
import asyncio
import json
import time
from types import SimpleNamespace

from modules.message_delete_queue import MessageDeleteQueue
from modules.notice_cleanup import NoticeCleanup


class _Logger:
    def __init__(self):
        self.info = []
        self.errors = []

    def log_info(self, message):
        self.info.append(message)

    def log_error(self, message):
        self.errors.append(message)


class MessageIdInvalidError(Exception):
    pass


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__(f"flood wait {seconds}")
        self.seconds = seconds


class NotFoundError(Exception):
    pass


def test_entity_failure_does_not_amplify_into_per_id_rpcs():
    class Client:
        def __init__(self):
            self.calls = []

        async def delete_messages(self, chat_id, ids):
            self.calls.append((chat_id, list(ids)))
            raise IndexError("list index out of range")

    async def run():
        client = Client()
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        ids = list(range(1, 51))
        result = await queue._delete_ids(-10001, ids)
        return client.calls, result

    calls, result = asyncio.run(run())
    assert calls == [(-10001, list(range(1, 51)))]
    assert result == (0, list(range(1, 51)))


def test_getusers_not_found_is_one_entity_failure_not_three_retries():
    class Client:
        def __init__(self):
            self.calls = 0

        async def delete_messages(self, _chat_id, _ids):
            self.calls += 1
            raise NotFoundError(
                "RPCError 404: NOT_FOUND (caused by GetUsersRequest)"
            )

    async def run():
        client = Client()
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        result = await queue._delete_ids(23375191, [10, 11])
        return client.calls, result

    calls, result = asyncio.run(run())
    assert calls == 1
    assert result == (0, [10, 11])


def test_only_message_id_failure_is_isolated_and_partial_success_is_exact():
    class Client:
        def __init__(self):
            self.calls = []

        async def delete_messages(self, _chat_id, ids):
            ids = list(ids)
            self.calls.append(ids)
            if len(ids) > 1 or ids == [2]:
                raise MessageIdInvalidError("MESSAGE_ID_INVALID")
            return True

    async def run():
        client = Client()
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        result = await queue._delete_ids(-10, [1, 2, 3])
        return client.calls, result

    calls, result = asyncio.run(run())
    assert calls == [[1, 2, 3], [1], [2], [3]]
    assert result == (2, [2])


def test_transient_and_short_flood_wait_retry_batch_without_rpc_multiplication():
    class Client:
        def __init__(self, error):
            self.error = error
            self.calls = 0

        async def delete_messages(self, _chat_id, _ids):
            self.calls += 1
            if self.calls == 1:
                raise self.error
            return True

    async def run(error):
        client = Client(error)
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        real_sleep = asyncio.sleep

        async def quick_sleep(_delay):
            await real_sleep(0)

        # Patch only this module's shared asyncio attribute for this coroutine.
        original = asyncio.sleep
        asyncio.sleep = quick_sleep
        try:
            result = await queue._delete_ids(-10, [1, 2, 3])
        finally:
            asyncio.sleep = original
        return client.calls, result

    transient_calls, transient_result = asyncio.run(run(TimeoutError("temporary")))
    flood_calls, flood_result = asyncio.run(run(FloodWaitError(2)))
    assert transient_calls == 2 and transient_result == (3, [])
    assert flood_calls == 2 and flood_result == (3, [])


def test_long_flood_wait_is_returned_without_sleep_or_per_id_calls():
    class Client:
        def __init__(self):
            self.calls = 0

        async def delete_messages(self, _chat_id, _ids):
            self.calls += 1
            raise FloodWaitError(90)

    async def run():
        client = Client()
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        result = await queue._delete_ids(-10, [1, 2, 3])
        return client.calls, result

    calls, result = asyncio.run(run())
    assert calls == 1
    assert result == (0, [1, 2, 3])


def test_delete_queue_uses_resolved_rpc_peer_but_stable_chat_queue_key():
    peer = object()

    class Client:
        def __init__(self):
            self.targets = []

        async def delete_messages(self, target, _ids):
            self.targets.append(target)
            return True

    async def run():
        client = Client()
        queue = MessageDeleteQueue(client, _Logger(), batch_size=100)
        result = queue.enqueue(-10001, [7], priority=0, rpc_peer=peer)
        assert await result == (1, [])
        await asyncio.gather(*list(queue._workers.values()), return_exceptions=True)
        return client.targets

    assert asyncio.run(run()) == [peer]


def test_delete_queue_resolves_short_group_id_from_shared_peer_cache():
    peer = object()

    class Client:
        def __init__(self):
            self.targets = []

        async def delete_messages(self, target, _ids):
            self.targets.append(target)
            return True

    async def run():
        client = Client()
        # The cache may have been warmed with the full -100... event form,
        # while a persisted notice still carries Soroush's short positive ID.
        peer_cache = {-1000023375191: peer}
        queue = MessageDeleteQueue(
            client, _Logger(), batch_size=100, peer_cache=peer_cache,
        )
        result = queue.enqueue(23375191, [7])
        assert await result == (1, [])
        await asyncio.gather(
            *list(queue._workers.values()), return_exceptions=True,
        )
        return client.targets

    assert asyncio.run(run()) == [peer]


def test_notice_cleanup_persists_unresolved_then_succeeds_on_retry(tmp_path):
    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue(self, chat_id, ids, *, priority=1, rpc_peer=None):
            self.calls.append((chat_id, list(ids), priority, rpc_peer))
            future = asyncio.get_running_loop().create_future()
            if len(self.calls) == 1:
                future.set_result((0, list(ids)))
            else:
                future.set_result((len(ids), []))
            return future

    async def run():
        queue = Queue()
        path = tmp_path / "notice.json"
        cleaner = NoticeCleanup(
            str(path), ttl_seconds=0.01, delete_queue=queue,
            retry_delay_seconds=0.01, max_retries=3,
        )
        cleaner.start()
        cleaner.schedule(-11, 501)
        await asyncio.sleep(0.12)
        idle_resources = (len(cleaner._workers), len(cleaner._events))
        cleaner.stop()
        return queue.calls, cleaner.pending(-11), path, idle_resources

    calls, pending, path, idle_resources = asyncio.run(run())
    assert len(calls) == 2
    assert pending == []
    assert idle_resources == (0, 0)
    assert json.loads(path.read_text(encoding="utf-8")) == {}


async def _wait_until(predicate, *, timeout=2.0, interval=0.01):
    """انتظار تا برقرار شدن یک شرط، به‌جای خواب ثابت.

    دو تست زیر پنجرهٔ زمانی کوچکی داشتند (۰٫۰۶ ثانیه) و در اجرای موازی کل
    سوییت به‌خاطر بار CPU به‌صورت تصادفی می‌شکستند.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


def test_notice_cleanup_keeps_inflight_ids_persisted_until_rpc_finishes(tmp_path):
    class Queue:
        def __init__(self):
            self.started = asyncio.Event()
            self.future = None

        def enqueue(self, _chat_id, _ids, *, priority=1, rpc_peer=None):
            self.started.set()
            self.future = asyncio.get_running_loop().create_future()
            return self.future

    async def run(path):
        queue = Queue()
        cleaner = NoticeCleanup(
            str(path), ttl_seconds=0.01, delete_queue=queue,
        )
        cleaner.start()
        cleaner.schedule(-14, 801)
        await asyncio.wait_for(queue.started.wait(), timeout=2.0)

        # The worker is awaiting the unresolved RPC at this point: the ID must
        # already be on disk. شرط را می‌سنجیم نه اینکه به زمان اطمینان کنیم.
        def persisted():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False
            return bool(data.get("-14"))

        assert await _wait_until(persisted), "شناسه روی دیسک ثبت نشد"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        cleaner.stop()
        await asyncio.sleep(0)
        return on_disk

    path = tmp_path / "inflight-notice.json"
    payload = asyncio.run(run(path))
    assert payload["-14"][0]["message_id"] == 801

    # 🔁 ری‌استارت عمداً این شناسه‌ها را بازپخش نمی‌کند: کامیت 66f053d
    # («جلوگیری از طوفان RPC هنگام استارت») بارگذاری را از «بازیابی» به «دور
    # ریختن» تغییر داد، چون حذف‌های کهنه پس از قطع/وصل روی پیام‌های نامعتبر
    # اجرا می‌شدند و استارت ربات را عقب می‌انداختند. پس فایل کهنه دور ریخته
    # می‌شود و هیچ شناسه‌ای به ارث نمی‌رسد.
    reloaded = NoticeCleanup(str(path), ttl_seconds=1)
    assert reloaded.pending(-14) == []
    assert not path.exists(), "فایل کهنهٔ notice باید هنگام بارگذاری دور ریخته شود"


def test_notice_cleanup_retry_rows_are_recorded_but_not_replayed(tmp_path):
    class Queue:
        def __init__(self):
            self.calls = 0

        def enqueue(self, _chat_id, ids, *, priority=1, rpc_peer=None):
            self.calls += 1
            future = asyncio.get_running_loop().create_future()
            future.set_result((0, list(ids)))
            return future

    async def run(path):
        queue = Queue()
        cleaner = NoticeCleanup(
            str(path), ttl_seconds=0.01, delete_queue=queue,
            retry_delay_seconds=10, max_retries=3,
        )
        cleaner.start()
        cleaner.schedule(-12, 601)

        def retry_row_persisted():
            rows = cleaner.pending(-12)
            return bool(rows) and int(rows[0].get("attempts", 0)) == 1

        assert await _wait_until(retry_row_persisted), "ردیف تلاش دوباره ثبت نشد"
        cleaner.stop()
        return queue.calls

    path = tmp_path / "persisted-notice.json"
    assert asyncio.run(run(path)) == 1

    # در همان پروسه، ردیفِ تلاش دوباره با شمارندهٔ درست روی دیسک ثبت شده است…
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["-12"][0]["message_id"] == 601
    assert stored["-12"][0]["attempts"] == 1

    # …ولی ری‌استارت آن را بازپخش نمی‌کند (منطق عمدی کامیت 66f053d). این
    # تست خودِ خاصیت مهم را می‌سنجد: هیچ RPC کهنه‌ای هنگام استارت زده نشود.
    class CountingQueue:
        def __init__(self):
            self.calls = 0

        def enqueue(self, _chat_id, ids, *, priority=1, rpc_peer=None):
            self.calls += 1
            future = asyncio.get_running_loop().create_future()
            future.set_result((len(list(ids)), []))
            return future

    async def restart():
        queue = CountingQueue()
        reloaded = NoticeCleanup(str(path), ttl_seconds=0.01,
                                 delete_queue=queue)
        reloaded.start()
        await asyncio.sleep(0.05)
        reloaded.stop()
        return queue.calls, reloaded.pending(-12)

    calls, pending = asyncio.run(restart())
    assert calls == 0, "پس از ری‌استارت نباید هیچ حذفِ کهنه‌ای اجرا شود"
    assert pending == []


def test_notice_cleanup_abandons_after_bounded_retries_and_retains_peer(tmp_path):
    peer = object()

    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue(self, chat_id, ids, *, priority=1, rpc_peer=None):
            self.calls.append((chat_id, list(ids), rpc_peer))
            future = asyncio.get_running_loop().create_future()
            future.set_result((0, list(ids)))
            return future

    async def run():
        queue = Queue()
        cleaner = NoticeCleanup(
            str(tmp_path / "bounded.json"), ttl_seconds=0.01,
            delete_queue=queue, retry_delay_seconds=0.01, max_retries=2,
        )
        cleaner.start()
        sent = SimpleNamespace(id=701, _input_chat=peer)
        cleaner.schedule(-13, sent)
        await asyncio.sleep(0.18)
        cleaner.stop()
        return queue.calls, cleaner.pending(-13)

    calls, pending = asyncio.run(run())
    assert len(calls) == 3  # Initial attempt plus two persisted retries.
    assert all(call[2] is peer for call in calls)
    assert pending == []
