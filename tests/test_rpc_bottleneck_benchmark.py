"""Reproduce live 1–5s stalls without touching production files.

    python tests/test_rpc_bottleneck_benchmark.py

Models the current architecture:
  NewMessage → GroupDispatcher (serial per chat+lane)
  deletes    → MessageDeleteQueue (serial per chat)
  mute/ban   → ModerationQueue (serial per chat)
  all RPCs   → one shared SPlusthon-like sender lock

Does not import SPlusthon and does not change robot logic.
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.group_dispatch import (
    PRIORITY_ADMIN,
    PRIORITY_COMMAND,
    PRIORITY_NORMAL,
    GroupDispatcher,
)
from modules.message_delete_queue import MessageDeleteQueue
from modules.moderation_queue import ModerationQueue

PASSED = FAILED = 0

# Live log magnitudes: delete 1644–4579, send 1652–4901, reply 4442.
RPC_MS = 1600
SLOW_RPC_MS = 4500


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label} {detail}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


class Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, message):
        self.infos.append(message)

    def log_error(self, message):
        self.errors.append(message)


class SharedSender:
    """Single-connection sender: one write at a time, like MTProtoSender."""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.traces = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.seq = 0

    async def call(self, operation, *, rpc_ms, pre_ms=0.0, post_ms=0.0):
        self.seq += 1
        request_id = f"{operation}-{self.seq}"
        queued = time.perf_counter()
        if pre_ms:
            await asyncio.sleep(pre_ms / 1000.0)
        pre_done = time.perf_counter()
        async with self.lock:
            start = time.perf_counter()
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(rpc_ms / 1000.0)
            finally:
                self.in_flight -= 1
            returned = time.perf_counter()
        if post_ms:
            await asyncio.sleep(post_ms / 1000.0)
        ended = time.perf_counter()
        trace = {
            "request_id": request_id,
            "operation": operation,
            "pre_rpc_ms": (pre_done - queued) * 1000,
            "connection_wait_ms": (start - pre_done) * 1000,
            "rpc_wait_ms": (returned - start) * 1000,
            "post_rpc_ms": (ended - returned) * 1000,
            "total_ms": (ended - queued) * 1000,
            "result": "success",
        }
        self.traces.append(trace)
        print(
            "RPC TRACE\n"
            f"request_id={trace['request_id']}\n"
            f"operation={trace['operation']}\n"
            f"pre_rpc_ms={trace['pre_rpc_ms']:.1f}\n"
            f"connection_wait_ms={trace['connection_wait_ms']:.1f}\n"
            f"rpc_wait_ms={trace['rpc_wait_ms']:.1f}\n"
            f"post_rpc_ms={trace['post_rpc_ms']:.1f}\n"
            f"total_ms={trace['total_ms']:.1f}\n"
            f"result={trace['result']}"
        )
        return trace


def parse_queue_waits(infos):
    waits = []
    for line in infos:
        if not line.startswith("QUEUE WAIT TIME"):
            continue
        for part in line.split():
            if part.startswith("queue_wait_ms="):
                waits.append(float(part.split("=", 1)[1]))
    return waits


def test_same_lane_rpc_blocks_next_job():
    print("\n### 1) RPC کند همان lane/worker را برای پیام بعدی قفل می‌کند")

    async def scenario():
        sender = SharedSender()
        logger = Logger()
        dispatcher = GroupDispatcher(logger=logger, debug_timing=True)
        marks = {}

        async def first():
            marks["first_start"] = time.perf_counter()
            await sender.call("reply", rpc_ms=SLOW_RPC_MS)
            marks["first_end"] = time.perf_counter()

        async def second():
            marks["second_start"] = time.perf_counter()
            await sender.call("reply", rpc_ms=80)

        t0 = time.perf_counter()
        dispatcher.submit(-1, first, priority=PRIORITY_COMMAND, kind="command")
        await asyncio.sleep(0)
        dispatcher.submit(-1, second, priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=8)
        return {
            "second_queue_ms": (marks["second_start"] - t0) * 1000,
            "gap_ms": (marks["second_start"] - marks["first_end"]) * 1000,
            "waits": parse_queue_waits(logger.infos),
            "traces": sender.traces,
        }

    result = asyncio.run(scenario())
    print(
        f"    second_queue_ms={result['second_queue_ms']:.1f} "
        f"gap_after_first={result['gap_ms']:.1f} waits={result['waits']}"
    )
    check(
        "پیام دوم ~4.5s پشت reply اول ماند",
        4300 <= result["second_queue_ms"] <= 4900,
        f"-> {result['second_queue_ms']:.1f}ms",
    )
    check(
        "بعد از تمام شدن job اول سربار داخلی < 40ms است",
        0 <= result["gap_ms"] < 40,
        f"-> {result['gap_ms']:.1f}ms",
    )
    check("queue_wait لاگ‌شده همان انتظار داخلی است",
          result["waits"] and max(result["waits"]) >= 4300,
          f"-> {result['waits']}")


def test_deletes_stall_reply_on_shared_sender():
    print("\n### 2) deleteهای متعدد reply/send را روی sender مشترک معطل می‌کنند")

    async def scenario():
        sender = SharedSender()
        logger = Logger()

        class Client:
            async def delete_messages(self, chat_id, ids):
                await sender.call("delete_message", rpc_ms=RPC_MS)

            async def send_message(self, chat_id, text):
                return await sender.call("send_message", rpc_ms=RPC_MS)

            async def reply(self, text):
                return await sender.call("reply", rpc_ms=SLOW_RPC_MS)

        client = Client()
        deletes = MessageDeleteQueue(client, logger, batch_size=15, inter_batch_delay=0)
        reply_started = []
        reply_trace = {}

        async def flood_deletes():
            fut = deletes.enqueue(-10, list(range(1, 46)), priority=1)
            await asyncio.wrap_future(fut)

        async def later_reply():
            reply_started.append(time.perf_counter())
            reply_trace["t"] = await client.reply("ok")

        t0 = time.perf_counter()
        flood = asyncio.create_task(flood_deletes())
        await asyncio.sleep(0.05)
        reply = asyncio.create_task(later_reply())
        await asyncio.gather(flood, reply)
        return {
            "reply_start_ms": (reply_started[0] - t0) * 1000,
            "reply_total": reply_trace["t"]["total_ms"],
            "reply_conn": reply_trace["t"]["connection_wait_ms"],
            "reply_rpc": reply_trace["t"]["rpc_wait_ms"],
            "max_in_flight": sender.max_in_flight,
            "n_traces": len(sender.traces),
        }

    result = asyncio.run(scenario())
    print(
        f"    reply_conn={result['reply_conn']:.1f} "
        f"reply_rpc={result['reply_rpc']:.1f} "
        f"reply_total={result['reply_total']:.1f} "
        f"max_in_flight={result['max_in_flight']} deletes={result['n_traces']-1}"
    )
    check(
        "sender همزمان بیش از یک RPC نمی‌فرستد",
        result["max_in_flight"] == 1,
        f"-> {result['max_in_flight']}",
    )
    check(
        "connection_wait reply تقریباً بقیهٔ deleteهاست (نه صفر)",
        result["reply_conn"] >= 1400,
        f"-> {result['reply_conn']:.1f}ms",
    )
    check(
        "rpc_wait خود reply همان 4500ms سروش است",
        4400 <= result["reply_rpc"] <= 4700,
        f"-> {result['reply_rpc']:.1f}ms",
    )


def test_all_ops_share_one_sender():
    print("\n### 3) send / reply / delete / mute / ban روی یک sender سریال می‌شوند")

    async def scenario():
        sender = SharedSender()
        logger = Logger()

        class Client:
            async def delete_messages(self, chat_id, ids):
                await sender.call("delete_message", rpc_ms=400)

            async def send_message(self, *a, **k):
                await sender.call("send_message", rpc_ms=400)

        client = Client()
        deletes = MessageDeleteQueue(client, logger, batch_size=15, inter_batch_delay=0)
        mods = ModerationQueue(logger)
        started = time.perf_counter()
        order = []

        async def mute():
            order.append("mute_start")
            await sender.call("mute", rpc_ms=400)
            order.append("mute_end")
            return True

        async def ban():
            order.append("ban_start")
            await sender.call("ban", rpc_ms=400)
            order.append("ban_end")
            return True

        async def reply():
            order.append("reply_start")
            await sender.call("reply", rpc_ms=400)
            order.append("reply_end")

        deletes.enqueue(-20, [1, 2, 3], priority=1)
        mods.enqueue(-20, "mute", mute, user_id=1)
        mods.enqueue(-20, "ban", ban, user_id=2)
        dispatcher = GroupDispatcher(logger=logger, debug_timing=True)
        dispatcher.submit(-20, reply, priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=5)
        await asyncio.sleep(2.2)
        wall = (time.perf_counter() - started) * 1000
        return wall, sender.max_in_flight, [t["operation"] for t in sender.traces], order

    wall, inflight, ops, order = asyncio.run(scenario())
    print(f"    wall={wall:.1f} inflight={inflight} ops={ops}")
    check("همهٔ ۵ عملیات روی یک sender رفتند",
          set(ops) == {"delete_message", "mute", "ban", "reply"} or len(ops) >= 4,
          f"-> {ops}")
    check("هیچ موازی‌سازی واقعی روی sender نبود", inflight == 1, f"-> {inflight}")
    check("زمان دیوار تقریباً جمع RPCهاست نه max آن‌ها",
          wall >= 1500, f"-> {wall:.1f}ms")


def test_busy_group_does_not_block_other_group_until_sender():
    print("\n### 4) گروه شلوغ worker گروه دیگر را قفل نمی‌کند؛ sender قفل می‌کند")

    async def scenario():
        sender = SharedSender()
        dispatcher = GroupDispatcher(logger=Logger())
        b_started = []

        async def busy_a():
            await sender.call("delete_message", rpc_ms=SLOW_RPC_MS)

        async def command_b():
            b_started.append(time.perf_counter())
            return await sender.call("reply", rpc_ms=80)

        t0 = time.perf_counter()
        dispatcher.submit(-100, busy_a, priority=PRIORITY_NORMAL, kind="normal")
        await asyncio.sleep(0)
        dispatcher.submit(-200, command_b, priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=8)
        return {
            "b_start_ms": (b_started[0] - t0) * 1000,
            "b_conn": sender.traces[1]["connection_wait_ms"],
            "b_rpc": sender.traces[1]["rpc_wait_ms"],
        }

    result = asyncio.run(scenario())
    print(
        f"    B_handler_start={result['b_start_ms']:.1f} "
        f"B_connection_wait={result['b_conn']:.1f} B_rpc={result['b_rpc']:.1f}"
    )
    check("handler گروه B فوری شروع شد (صف پایتون قفلش نکرد)",
          result["b_start_ms"] < 50, f"-> {result['b_start_ms']:.1f}ms")
    check("ولی reply گروه B پشت RPC گروه A روی sender ماند",
          result["b_conn"] >= 4300, f"-> {result['b_conn']:.1f}ms")


def test_queue_wait_is_internal_not_soroush():
    print("\n### 5) queue_wait_ms ۳–۹ ثانیه از صف داخلی است، نه از پاسخ سروش این RPC")

    async def scenario():
        sender = SharedSender()
        logger = Logger()
        dispatcher = GroupDispatcher(logger=logger, debug_timing=True)
        traces_by_job = []

        def make_job(name):
            async def job():
                traces_by_job.append(await sender.call(name, rpc_ms=SLOW_RPC_MS))
            return job

        dispatcher.submit(-7, make_job("reply"), priority=PRIORITY_COMMAND, kind="command")
        dispatcher.submit(-7, make_job("send_message"), priority=PRIORITY_COMMAND, kind="command")
        dispatcher.submit(-7, make_job("reply"), priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=16)
        return parse_queue_waits(logger.infos), traces_by_job

    waits, traces = asyncio.run(scenario())
    print(f"    queue_waits={['%.0f' % w for w in waits]}")
    print(
        "    per-rpc connection_wait="
        + ", ".join(f"{t['connection_wait_ms']:.0f}" for t in traces)
    )
    check("دو job بعدی queue_wait حدود 4.5s و 9s دارند",
          len(waits) >= 2 and max(waits) >= 8500,
          f"-> {waits}")
    check("rpc_wait هر کدام جداگانه ~4500 است (سروش)",
          all(4400 <= t["rpc_wait_ms"] <= 4700 for t in traces),
          f"-> {[round(t['rpc_wait_ms']) for t in traces]}")
    check("pre_rpc و post_rpc نزدیک صفرند (کد ربات بعد از await گیر نیست)",
          all(t["pre_rpc_ms"] < 20 and t["post_rpc_ms"] < 20 for t in traces),
          f"-> pre={[round(t['pre_rpc_ms'],1) for t in traces]} "
          f"post={[round(t['post_rpc_ms'],1) for t in traces]}")


def test_split_explains_live_logs():
    print("\n### 6) تفسیر لاگ زنده: RPC TIME داخل await است؛ queue_wait صف lane است")

    async def scenario():
        sender = SharedSender()
        logger = Logger()
        dispatcher = GroupDispatcher(logger=logger, debug_timing=True)

        async def command_with_reply():
            # handler itself is cheap; the await reply is the 4.4s.
            await sender.call("reply", rpc_ms=4442)

        dispatcher.submit(-8, command_with_reply, priority=PRIORITY_COMMAND, kind="command")
        dispatcher.submit(-8, command_with_reply, priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=12)
        return sender.traces, parse_queue_waits(logger.infos)

    traces, waits = asyncio.run(scenario())
    first, second = traces
    print(
        f"    first total={first['total_ms']:.0f} "
        f"second conn={second['connection_wait_ms']:.0f} "
        f"second rpc={second['rpc_wait_ms']:.0f} "
        f"queue_wait={waits}"
    )
    check("لاگ RPC TIME فعلی = connection_wait + rpc_wait (جدا نمی‌شود)",
          abs((first["connection_wait_ms"] + first["rpc_wait_ms"]) - first["total_ms"]) < 5)
    check("queue_wait پیام دوم ≈ RPC کامل پیام اول",
          waits and abs(waits[-1] - first["total_ms"]) < 80,
          f"-> wait={waits[-1]:.0f} first={first['total_ms']:.0f}")


def test_detach_reply_would_drop_queue_wait():
    print("\n### 7) اگر reply از worker جدا شود queue_wait داخلی از بین می‌رود")

    async def scenario():
        sender = SharedSender()
        logger = Logger()
        dispatcher = GroupDispatcher(logger=logger, debug_timing=True)
        started = []

        async def fire_and_forget_reply():
            started.append(time.perf_counter())
            asyncio.create_task(sender.call("reply", rpc_ms=SLOW_RPC_MS))

        t0 = time.perf_counter()
        dispatcher.submit(-9, fire_and_forget_reply, priority=PRIORITY_COMMAND, kind="command")
        dispatcher.submit(-9, fire_and_forget_reply, priority=PRIORITY_COMMAND, kind="command")
        await dispatcher.join(timeout=2)
        handler_gap = (started[1] - started[0]) * 1000
        await asyncio.sleep(SLOW_RPC_MS * 2 / 1000.0 + 0.05)
        return handler_gap, parse_queue_waits(logger.infos), sender.max_in_flight

    gap, waits, inflight = asyncio.run(scenario())
    print(f"    handler_gap={gap:.1f} waits={waits} inflight={inflight}")
    check("هر دو handler بلافاصله اجرا شدند", gap < 30, f"-> {gap:.1f}ms")
    check("queue_wait چندثانیه‌ای ساخته نشد",
          not waits or max(waits) < 50, f"-> {waits}")
    check("sender همچنان سریال است (Soroush سریع‌تر نمی‌شود)",
          inflight == 1, f"-> {inflight}")


def main():
    test_same_lane_rpc_blocks_next_job()
    test_deletes_stall_reply_on_shared_sender()
    test_all_ops_share_one_sender()
    test_busy_group_does_not_block_other_group_until_sender()
    test_queue_wait_is_internal_not_soroush()
    test_split_explains_live_logs()
    test_detach_reply_would_drop_queue_wait()
    print(f"\npassed={PASSED} failed={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
