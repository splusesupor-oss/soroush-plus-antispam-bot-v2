"""⚡ گاردهای کارایی — جلوگیری از بازگشت «کند شدن به مرور زمان».

سه نشتی که با اندازه‌گیری واقعی پیدا شدند و اینجا قفل می‌شوند:

۱. RPC تایم‌اوت‌خورده در ``sender._pending_state`` جا می‌ماند
   (``asyncio.wait_for`` فقط انتظار را لغو می‌کند، نه خود درخواست).
   نتیجه: رشد بی‌پایان حافظه + کند شدن ``_pop_states`` که پیمایش خطی
   روی همان جدول است + بازفرستادن همهٔ زامبی‌ها در هر reconnect.

۲. ``mark_seen`` / ``mark_recent`` بعد از هر ثبت، کل ``economy.json``
   را به صورت همگام روی دیسک می‌نوشتند و حلقهٔ رویداد را بلاک
   می‌کردند. هزینه با اندازهٔ فایل خطی رشد می‌کرد.

۳. ``snapshot()`` برای خواندن یک سطل کوچک، کل فایل را deepcopy
   می‌کرد. همان رشد خطی.

    python tests/test_performance_regression.py
"""
import asyncio
import gc
import sys
import threading
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ⚠️ پیش از import هر بازی، وگرنه روی دادهٔ زندهٔ کاربران نوشته می‌شود.
import economy.storage as _storage  # noqa: E402

_STORE_DIR = Path(tempfile.mkdtemp())
_storage.use_file(_STORE_DIR / "economy.json")

import modules.multiple_choice as mc  # noqa: E402
from economy import game_progress as progress  # noqa: E402
from modules import connection_guard as cg  # noqa: E402

PASSED = FAILED = 0


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


# ===========================================================================
# ۱ — نشتی RPC
# ===========================================================================
class FakeSender:
    """مثل MTProtoSender: درخواست را در _pending_state نگه می‌دارد."""

    def __init__(self):
        self._pending_state = {}
        self._n = 0

    def send(self, request, ordered=False):
        self._n += 1
        future = asyncio.get_running_loop().create_future()
        self._pending_state[self._n] = type(
            "S", (), {"future": future, "request": request,
                      "msg_id": self._n, "container_id": None})()
        return future


class FakeClient:
    def __init__(self):
        self._sender = FakeSender()

    async def _call(self, sender, request, ordered=False,
                    flood_sleep_threshold=None):
        return await sender.send(request)

    def is_connected(self):
        return True


class Req:
    pass


def test_timed_out_rpcs_do_not_accumulate():
    print("\n### 🧹 RPC تایم‌اوت‌خورده در حافظه نمی‌ماند")

    async def scenario():
        client = FakeClient()
        cg.install_rpc_timeout(client, timeout=0.05)
        for _ in range(40):
            try:
                await client._call(client._sender, Req())
            except cg.RpcTimeout:
                pass
        await asyncio.sleep(0)
        return client

    client = asyncio.run(scenario())
    left = len(client._sender._pending_state)
    check("۴۰ درخواست ارسال شد", client._sender._n == 40)
    # فقط آخرین درخواستِ در پرواز ممکن است باقی باشد.
    check("جدول معلق‌ها انباشته نشد", left <= 1, f"-> {left}")
    check("جدول زمان‌ها هم پاک شد",
          len(getattr(client._sender, "_guard_seen_at", {})) <= 1)


def test_drop_stale_pending_is_precise():
    print("\n### 🎯 فقط زامبی‌ها پاک می‌شوند، نه درخواست تازه")

    async def scenario():
        sender = FakeSender()
        old_futures = [sender.send(Req()) for _ in range(3)]
        cg.note_pending(sender)
        boundary = time.monotonic()
        await asyncio.sleep(0.01)
        fresh_future = sender.send(Req())
        cg.note_pending(sender)

        dropped = cg.drop_stale_pending(sender, boundary)
        await asyncio.sleep(0)
        return dropped, sender, old_futures, fresh_future

    dropped, sender, old, fresh = asyncio.run(scenario())
    check("هر سه زامبی پاک شدند", dropped == 3, f"-> {dropped}")
    check("درخواست تازه دست‌نخورده ماند",
          len(sender._pending_state) == 1)
    check("futureهای زامبی لغو شدند", all(f.cancelled() for f in old))
    check("future تازه لغو نشد", not fresh.done())


def test_pop_states_stays_fast():
    """اثبات مکانیزم: جدول بزرگ = ``_pop_states`` کند."""
    print("\n### 📉 مکانیزم کندی: پیمایش خطی جدول معلق‌ها")

    class St:
        __slots__ = ("msg_id", "container_id")

        def __init__(self, m):
            self.msg_id = m
            self.container_id = None

    def pop_states(pending, msg_id):
        state = pending.pop(msg_id, None)
        if state:
            return [state]
        return [pending.pop(s.msg_id) for s in list(pending.values())
                if s.container_id == msg_id]

    def measure(size):
        pending = {i: St(i) for i in range(size)}
        rounds = 500
        started = time.perf_counter()
        for _ in range(rounds):
            pop_states(pending, -1)
        return (time.perf_counter() - started) / rounds * 1e6

    small, large = measure(0), measure(20000)
    check("جدول خالی تقریباً رایگان است", small < 20, f"-> {small:.1f}µs")
    check("جدول ۲۰هزارتایی به‌شدت کندتر است", large > small * 10,
          f"-> {small:.1f}µs vs {large:.1f}µs")
    print(f"        (خالی {small:.1f}µs — ۲۰هزار {large:.1f}µs)")


# ===========================================================================
# ۲ — نوشتن همگام روی دیسک
# ===========================================================================
def test_hot_path_does_not_block_event_loop():
    """در حلقهٔ رویداد — یعنی همان جایی که ربات واقعاً اجرا می‌شود —
    نوشتن روی دیسک نباید پردازش پیام را متوقف کند."""
    print("\n### 💾 مسیر داغ حلقهٔ رویداد را بلاک نمی‌کند")
    # 🔒 مسیر ذخیره را خودِ تست قطعی می‌کند: با پشتیبان JSON، نویسندهٔ همگام
    # واقعی «_json_write» است (نام قدیمی _write پس از بازنویسی SQLite عوض شد).
    # بدون این خط، اگر ماژول تست دیگری در همان پروسه پشتیبان را عوض کرده باشد،
    # این تست روی داده/مسیر دیگری کار می‌کرد.
    _storage.use_file(_STORE_DIR / "economy.json")
    blocking = {"n": 0}
    original = _storage._json_write
    main_thread = threading.get_ident()

    def counting(data):
        # فقط نوشتنی که *روی همان thread حلقهٔ رویداد* رخ دهد بلاک‌کننده است.
        if threading.get_ident() == main_thread:
            blocking["n"] += 1
        return original(data)

    async def scenario():
        _storage._json_write = counting
        try:
            mc.reset_all()
            blocking["n"] = 0
            for uid in range(10):
                item = mc.start_question(-9001, 6000 + uid)
                mc.answer_question(-9001, str(item["answer"]), 6000 + uid)
            await asyncio.sleep(0.05)   # فرصت به نوشتن پس‌زمینه
        finally:
            _storage._json_write = original

    asyncio.run(scenario())
    check("۱۰ سوال کامل هیچ نوشتن بلاک‌کننده‌ای نداشت", blocking["n"] == 0,
          f"-> {blocking['n']}")
    mc.reset_all()


def test_progress_still_persists_after_flush():
    print("\n### 💾 داده با flush دوره‌ای واقعاً ذخیره می‌شود")
    mc.reset_all()
    item = mc.start_question(-9002, 6100)
    mc.clear_question(-9002, item["token"])
    saved = progress.flush_now()
    check("flush_now نوشت", saved is True)

    import json
    raw = json.loads((_STORE_DIR / "economy.json").read_text(encoding="utf-8"))
    # کلید گروه توسط ``accounts.chat_key`` نرمال می‌شود (منفی حذف
    # می‌شود)، پس نباید شناسهٔ خام را فرض کرد.
    chat_key = progress._chat(-9002)
    stored = (raw.get("game_progress", {})
                 .get(chat_key, {}).get("6100", {}).get(mc.GAME, []))
    check("پیشرفت روی دیسک هست", str(item["index"]) in stored,
          f"-> chat_key={chat_key} stored={stored}")
    mc.reset_all()


# ===========================================================================
# ۳ — خواندن ارزان
# ===========================================================================
def test_read_path_returns_correct_data():
    print("\n### 🔍 read_path داده را درست برمی‌گرداند")
    with _storage.transaction() as data:
        data.setdefault("probe", {})["a"] = {"b": [1, 2, 3]}

    check("مسیر موجود", _storage.read_path("probe", "a", "b") == [1, 2, 3])
    check("مسیر ناموجود default می‌دهد",
          _storage.read_path("probe", "zzz", default="x") == "x")
    check("مسیر عمیقِ ناموجود امن است",
          _storage.read_path("nope", "deep", "deeper") is None)

    copied = _storage.read_path("probe", "a", "b")
    copied.append(999)
    check("خروجی کپی است و کش را خراب نمی‌کند",
          _storage.read_path("probe", "a", "b") == [1, 2, 3])

    with _storage.transaction() as data:
        data.pop("probe", None)


def test_read_path_beats_snapshot_as_data_grows():
    print("\n### ⚡ read_path با رشد داده گران نمی‌شود")
    for chat in range(6):
        for user in range(40):
            for stage in range(40):
                progress.mark_seen(-9500 - chat, user, "emoji", stage)

    rounds = 300
    started = time.perf_counter()
    for _ in range(rounds):
        _storage.snapshot()
    snap = (time.perf_counter() - started) / rounds * 1000

    started = time.perf_counter()
    for _ in range(rounds):
        progress.recent(-9500, "emoji")
    scoped = (time.perf_counter() - started) / rounds * 1000

    check("خواندن محدود بسیار ارزان‌تر از snapshot است",
          scoped < snap / 5, f"-> snapshot {snap:.2f}ms / scoped {scoped:.2f}ms")
    print(f"        (snapshot {snap:.2f}ms — read_path {scoped:.3f}ms)")
    progress.reset_game_everywhere("emoji")


def test_question_cost_is_flat():
    """قلب گزارش کاربر: سرعت نباید با گذشت زمان افت کند."""
    print("\n### 📊 هزینهٔ هر سوال با رشد داده ثابت می‌ماند")
    # 🔒 همان دلیل تست مسیر داغ: مسیر ذخیره را خودِ تست تعیین می‌کند تا
    # اندازه‌گیری روی فایل همین تست انجام شود.
    _storage.use_file(_STORE_DIR / "economy.json")
    mc.reset_all()
    samples = []
    uid = 7000
    for grow in range(4):
        for chat in range(3):
            for user in range(30):
                for stage in range(40):
                    progress.mark_seen(-9600 - grow * 10 - chat, user,
                                       "emoji", stage)
        _storage.flush()
        store_file = _STORE_DIR / "economy.json"
        size = store_file.stat().st_size / 1024 if store_file.exists() else 0.0

        async def burst(start_uid):
            local = start_uid
            started = time.perf_counter()
            for _ in range(20):
                local += 1
                item = mc.start_question(-9600, local)
                mc.answer_question(-9600, str(item["answer"]), local)
            elapsed = (time.perf_counter() - started) / 20 * 1000
            await asyncio.sleep(0.05)
            return local, elapsed

        uid, per = asyncio.run(burst(uid))
        samples.append((size, per))

    for size, cost in samples:
        print(f"        {size:8.0f}KB -> {cost:6.3f}ms")

    first, last = samples[0][1], samples[-1][1]
    growth = (samples[-1][0] / samples[0][0]) if samples[0][0] else 1
    check("حجم داده واقعاً چند برابر شد", growth >= 3, f"-> ×{growth:.1f}")
    # پیش از اصلاح: ۳٫۰ms -> ۱۴٫۲ms (رشد ۴٫۷ برابری)
    check("زمان با رشد داده منفجر نمی‌شود", last < first * 2.5 + 0.5,
          f"-> {first:.3f}ms -> {last:.3f}ms")
    mc.reset_all()
    progress.reset_game_everywhere("emoji")


# ===========================================================================
# نشتی تسک و منابع
# ===========================================================================
def test_no_task_leak_on_repeated_rpc_timeouts():
    print("\n### 🧵 timeoutهای پیاپی تسک نشت نمی‌دهند")

    async def scenario():
        client = FakeClient()
        cg.install_rpc_timeout(client, timeout=0.02)
        baseline = len([t for t in asyncio.all_tasks() if not t.done()])
        for _ in range(30):
            try:
                await client._call(client._sender, Req())
            except cg.RpcTimeout:
                pass
        await asyncio.sleep(0.05)
        alive = len([t for t in asyncio.all_tasks() if not t.done()])
        return baseline, alive

    baseline, alive = asyncio.run(scenario())
    check("تعداد تسک‌ها بعد از ۳۰ timeout نمی‌ترکد",
          alive <= baseline + 2, f"-> {baseline} -> {alive}")


def test_supervisor_counters_are_bounded():
    print("\n### 📈 شمارنده‌های ناظر بی‌نهایت رشد نمی‌کنند")
    client = FakeClient()
    supervisor = cg.ConnectionSupervisor(client, window=0.05)
    for _ in range(500):
        supervisor.note_rpc_timeout()
    time.sleep(0.08)
    supervisor.timeouts.count()
    check("پنجرهٔ زمانی رویدادهای کهنه را دور می‌ریزد",
          len(supervisor.timeouts._events) == 0,
          f"-> {len(supervisor.timeouts._events)}")

    tracker = cg.StaleSessionTracker(window=0.05)
    for _ in range(500):
        tracker.record()
    time.sleep(0.08)
    check("شمارندهٔ قاب کهنه هم محدود می‌ماند", tracker.recent() == 0)


def test_no_reference_cycles_left_behind():
    print("\n### ♻️ چیزی برای جمع‌آوری زباله جا نمی‌ماند")

    async def scenario():
        client = FakeClient()
        cg.install_rpc_timeout(client, timeout=0.02)
        for _ in range(20):
            try:
                await client._call(client._sender, Req())
            except cg.RpcTimeout:
                pass
        return client

    client = asyncio.run(scenario())
    gc.collect()
    survivors = sum(1 for obj in gc.get_objects()
                    if isinstance(obj, Req))
    check("اشیای درخواست انباشته نمی‌شوند", survivors <= 2,
          f"-> {survivors}")
    del client
    gc.collect()


# ===========================================================================
def main():
    test_timed_out_rpcs_do_not_accumulate()
    test_drop_stale_pending_is_precise()
    test_pop_states_stays_fast()

    test_hot_path_does_not_block_event_loop()
    test_progress_still_persists_after_flush()

    test_read_path_returns_correct_data()
    test_read_path_beats_snapshot_as_data_grows()
    test_question_cost_is_flat()

    test_no_task_leak_on_repeated_rpc_timeouts()
    test_supervisor_counters_are_bounded()
    test_no_reference_cycles_left_behind()

    print(f"\npassed={PASSED} failed={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
