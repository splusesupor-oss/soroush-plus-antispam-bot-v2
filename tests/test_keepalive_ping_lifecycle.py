"""Keepalive PingRequest lifecycle: send, pong, stale, cancel, exception.

    python -m pytest tests/test_keepalive_ping_lifecycle.py -q
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

from modules import connection_guard as cg
from modules.outgoing_profiler import instrument_client, pending_rpc_snapshot
from modules.rpc_governor import (
    P0_CRITICAL,
    P1_DELETE,
    P2_SEND,
    P3_HEAVY,
    RpcAdmission,
    RpcGovernor,
    classify_request,
    is_keepalive_request,
)


class Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, message):
        self.infos.append(str(message))

    def log_error(self, message):
        self.errors.append(str(message))


class SendMessageRequest:
    def __init__(self, peer=1):
        self.peer = peer


class DeleteMessagesRequest:
    def __init__(self, peer=1):
        self.peer = peer


class PingRequest:
    def __init__(self, ping_id=None):
        self.ping_id = ping_id


class MsgsAck:
    def __init__(self, ids=None):
        self.ids = ids or []


class HttpWait:
    def __init__(self, max_delay=0):
        self.max_delay = max_delay


class RequestState:
    def __init__(self, request, future, msg_id):
        self.request = request
        self.future = future
        self.msg_id = msg_id
        self.container_id = None


class PingSender:
    PONG = object()

    def __init__(self):
        self._pending_state = {}
        self._n = 0
        self._ping = None
        self._user_connected = True
        self._reconnecting = False
        self.pings = []
        self.reconnects = []
        self.fail_next = False
        self._handlers = {self.PONG: self._handle_pong}

    def put(self, request, *, done=False, age=0.0, ping_id=None):
        if ping_id is not None and getattr(request, "ping_id", None) is None:
            try:
                request.ping_id = ping_id
            except Exception:
                pass
        self._n += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        if done:
            future.set_result("ok")
        state = RequestState(request, future, self._n)
        self._pending_state[self._n] = state
        cg._seen_at(self)[self._n] = time.monotonic() - float(age)
        return state

    def _keepalive_ping(self, rnd_id):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("ping send failed")
        if self._ping is None:
            self._ping = rnd_id
            self.pings.append(("sent", rnd_id))
            self.put(PingRequest(rnd_id), ping_id=rnd_id)
            return rnd_id
        self.pings.append(("timeout", self._ping, rnd_id))
        self._start_reconnect(None)
        return None

    async def _handle_pong(self, message):
        pong = getattr(message, "obj", message)
        if self._ping == getattr(pong, "ping_id", None):
            self._ping = None
        # Intentionally do not complete the PingRequest future.
        return "pong-ok"

    def _start_reconnect(self, error):
        if self._user_connected and not self._reconnecting:
            self._reconnecting = True
            self.reconnects.append(error)

    async def _reconnect(self, last_error):
        await asyncio.sleep(0)
        self._user_connected = True
        self._reconnecting = False
        return "reconnected"


class PingClient:
    def __init__(self):
        self._sender = PingSender()

    async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        return "ok"


def _states(logger):
    return [
        line for line in logger.infos
        if line.startswith("KEEPALIVE PING STATE")
    ]


def _has_state(logger, ping_id, state):
    token = f"ping_id={ping_id} state={state}"
    return any(token in line for line in _states(logger))


def _keepalive_pending(sender):
    return [
        state for state in sender._pending_state.values()
        if type(getattr(state, "request", None)).__name__ == "PingRequest"
    ]


def test_successful_ping_pong_clears_pending_even_if_future_not_done():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender._keepalive_ping(11)
        before = pending_rpc_snapshot(sender)
        await sender._handlers[PingSender.PONG](SimpleNamespace(
            obj=SimpleNamespace(ping_id=11, msg_id=99),
        ))
        after = pending_rpc_snapshot(sender)
        return logger, before, after, sender

    logger, before, after, sender = asyncio.run(scenario())
    assert before["sender_pending_keepalive"] == 1
    assert after["sender_pending_keepalive"] == 0, after
    assert after["sender_pending"] == 0
    assert cg.live_keepalive_count(sender) == 0
    assert _keepalive_pending(sender) == []
    assert _has_state(logger, 11, "CREATED")
    assert _has_state(logger, 11, "QUEUED")
    assert _has_state(logger, 11, "SENT")
    assert _has_state(logger, 11, "RESPONSE")
    assert _has_state(logger, 11, "CLEANED")
    assert sender._ping is None


def test_duplicate_ping_is_skipped_while_healthy_inflight():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender._keepalive_ping(21)
        first_pending = len(_keepalive_pending(sender))
        # SPlusthon pong cleared _ping but left future_done=0 in pending.
        sender._ping = None
        sender._keepalive_ping(22)
        return logger, first_pending, sender, pending_rpc_snapshot(sender)

    logger, first_pending, sender, snap = asyncio.run(scenario())
    assert first_pending == 1
    assert len(_keepalive_pending(sender)) == 1
    assert snap["sender_pending_keepalive"] == 1
    assert cg.live_keepalive_count(sender) == 1
    texts = "\n".join(logger.infos)
    assert "KEEPALIVE PING SKIPPED" in texts
    assert sender.pings == [("sent", 21)]


def test_stale_ping_is_cleaned_without_reconnect():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender.put(PingRequest(7), age=17.0, ping_id=7)
        sender._ping = None
        before = pending_rpc_snapshot(sender)
        live_before = cg.live_keepalive_count(sender)
        sender._keepalive_ping(88)
        after = pending_rpc_snapshot(sender)
        return logger, before, after, live_before, sender

    logger, before, after, live_before, sender = asyncio.run(scenario())
    assert before["sender_pending_keepalive"] == 1
    assert live_before == 0
    assert sender.reconnects == []
    # Stale row is gone. A replacement ping may occupy the single live slot.
    leftover = _keepalive_pending(sender)
    assert len(leftover) <= 1, leftover
    assert cg.live_keepalive_count(sender) <= 1
    stale_logs = [line for line in logger.infos if line.startswith("STALE SENDER PENDING")]
    assert stale_logs
    assert "future_done=0" in stale_logs[0]
    assert "keepalive=1" in stale_logs[0]
    assert any("state=TIMEOUT" in line or "state=CLEANED" in line for line in _states(logger))
    assert "RECONNECT START" not in "\n".join(logger.infos)


def test_stale_cleanup_leaves_zero_when_no_replacement():
    async def scenario():
        logger = Logger()
        sender = PingSender()
        sender.put(PingRequest(3), age=20.0, ping_id=3)
        dropped = cg.reclaim_dead_pending(sender, logger=logger)
        snap = pending_rpc_snapshot(sender)
        return dropped, snap, cg.live_keepalive_count(sender), sender, logger

    dropped, snap, live, sender, logger = asyncio.run(scenario())
    assert dropped == 1
    assert snap["sender_pending_keepalive"] == 0
    assert snap["sender_pending"] == 0
    assert live == 0
    assert _keepalive_pending(sender) == []
    assert _has_state(logger, 3, "TIMEOUT")
    assert _has_state(logger, 3, "CLEANED")


def test_young_ping_is_not_cut_short():
    async def scenario():
        sender = PingSender()
        live = sender.put(PingRequest(4), age=6.0, ping_id=4)
        dropped = cg.reclaim_dead_pending(sender)
        return dropped, live, cg.live_keepalive_count(sender), sender

    dropped, live, count, sender = asyncio.run(scenario())
    assert dropped == 0
    assert count == 1
    assert not live.future.done()
    assert len(_keepalive_pending(sender)) == 1


def test_ping_exception_clears_pending():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender.fail_next = True
        raised = None
        try:
            sender._keepalive_ping(31)
        except RuntimeError as error:
            raised = error
        return logger, raised, pending_rpc_snapshot(sender), sender

    logger, raised, snap, sender = asyncio.run(scenario())
    assert raised is not None
    assert snap["sender_pending_keepalive"] == 0
    assert cg.live_keepalive_count(sender) == 0
    assert _has_state(logger, 31, "EXCEPTION")


def test_ping_cancellation_clears_pending():
    async def scenario():
        logger = Logger()
        sender = PingSender()
        state = sender.put(PingRequest(41), ping_id=41)
        state.future.cancel()
        dropped = cg.drop_completed_pending(sender)
        if cg.unanswered_keepalive_count(sender):
            dropped += cg.complete_keepalive_pending(
                sender, ping_id=41, logger=logger, reason="CANCELLED",
            )
        snap = pending_rpc_snapshot(sender)
        return dropped, snap, sender, logger

    dropped, snap, sender, logger = asyncio.run(scenario())
    assert snap["sender_pending_keepalive"] == 0
    assert cg.live_keepalive_count(sender) == 0
    assert _keepalive_pending(sender) == []
    assert dropped >= 1


def test_connection_state_change_drops_keepalive_not_send():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        send = sender.put(SendMessageRequest(9), age=2.0)
        sender.put(PingRequest(5), age=8.0, ping_id=5)
        sender._start_reconnect("net")
        # Hooked start reconnect runs when _ping is set through keepalive timeout.
        # Directly exercise the reconnect-start cleanup used by the hook.
        cg.drop_keepalive_pending(sender, logger=logger, reason="CLEANED")
        left = [type(state.request).__name__ for state in sender._pending_state.values()]
        return send, left, pending_rpc_snapshot(sender), sender

    send, left, snap, sender = asyncio.run(scenario())
    assert left == ["SendMessageRequest"], left
    assert not send.future.done()
    assert snap["sender_pending_keepalive"] == 0
    assert cg.live_keepalive_count(sender) == 0
    assert snap["sender_pending"] == 1


def test_pong_timeout_reconnects_only_for_stuck_rpc():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender._keepalive_ping(11)
        sender._keepalive_ping(22)
        return logger, sender

    logger, sender = asyncio.run(scenario())
    texts = "\n".join(logger.infos)
    # Previous PingRequest is still in sender pending: do not build a new one.
    assert "KEEPALIVE PING SKIPPED" in texts
    assert any("action=skip" in line for line in _states(logger))
    assert len(_keepalive_pending(sender)) == 1
    assert cg.live_keepalive_count(sender) == 1
    assert sender.pings == [("sent", 11)]
    assert "RECONNECT START" not in texts
    assert sender.reconnects == []


def test_tracker_leftover_timeout_does_not_reconnect():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender._keepalive_ping(11)
        sender._pending_state.clear()
        cg._seen_at(sender).clear()
        sender._keepalive_ping(22)
        return logger, sender

    logger, sender = asyncio.run(scenario())
    texts = "\n".join(logger.infos)
    assert "KEEPALIVE PONG TIMEOUT" in texts
    assert "KEEPALIVE PONG TIMEOUT IGNORED" in texts
    assert "RECONNECT START" not in texts
    assert sender.reconnects == []
    assert cg.live_keepalive_count(sender) <= 1


def test_governor_limits_and_p0_p1_order():
    # 🔒 مقادیر محافظه‌کارانهٔ پیش‌فرض را خودِ تست تعیین می‌کند؛ وگرنه نتیجه به
    # .env همان دستگاه وابسته می‌شد (روی دستگاه مالک BOT_RPC_TOTAL_LIMIT=3 است و
    # تست با انتظار ۲ می‌شکست). فقط متغیرهای محیطی همین تست عوض می‌شوند و در
    # پایان به حالت قبل برمی‌گردند.
    limits = {
        "BOT_RPC_TOTAL_LIMIT": "2",
        "BOT_RPC_DELETE_LIMIT": "1",
        "BOT_RPC_SEND_LIMIT": "1",
        "BOT_RPC_HEAVY_LIMIT": "1",
        "BOT_RPC_NONCRITICAL_LIMIT": "2",
    }
    previous = {name: os.environ.get(name) for name in limits}
    os.environ.update(limits)

    async def scenario():
        governor = RpcGovernor.from_environment()
        assert governor.total_limit == 2
        assert governor.class_limits["delete"] == 1
        assert governor.class_limits["send"] == 1
        heavy = await governor.acquire(
            RpcAdmission(P3_HEAVY, "heavy", "GetParticipantsRequest", "g1")
        )
        started = time.perf_counter()
        delete = await asyncio.wait_for(
            governor.acquire(
                RpcAdmission(P1_DELETE, "delete", "DeleteMessagesRequest", "g2")
            ),
            timeout=0.05,
        )
        p1_wait_ms = (time.perf_counter() - started) * 1000.0
        p3_task = asyncio.create_task(
            governor.acquire(
                RpcAdmission(P3_HEAVY, "heavy", "GetHistoryRequest", "g4")
            )
        )
        p0_task = asyncio.create_task(
            governor.acquire(
                RpcAdmission(P0_CRITICAL, "critical", "GetChannelDifferenceRequest", "g5")
            )
        )
        await asyncio.sleep(0.01)
        p0_waiting = not p0_task.done()
        p3_waiting = not p3_task.done()
        heavy.release()
        p0 = await asyncio.wait_for(p0_task, timeout=0.05)
        still_p3 = not p3_task.done()
        p0.release()
        delete.release()
        p3_task.cancel()
        try:
            await p3_task
        except (asyncio.CancelledError, Exception):
            pass
        return p1_wait_ms, p0_waiting, p3_waiting, still_p3, governor.snapshot()

    try:
        p1_wait_ms, p0_waiting, p3_waiting, still_p3, snap = asyncio.run(scenario())
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert p1_wait_ms < 50.0, p1_wait_ms
    assert p0_waiting is True
    assert p3_waiting is True
    assert still_p3 is True
    assert snap["active"] == 0


def test_keepalive_bypasses_governor():
    assert is_keepalive_request(PingRequest())
    classified = classify_request(PingRequest())
    assert classified.priority == P0_CRITICAL


def test_live_pings_ignore_stale_bookkeeping():
    async def scenario():
        sender = PingSender()
        sender.put(PingRequest(1), age=18.0, ping_id=1)
        stale = cg.live_keepalive_count(sender)
        unanswered = cg.unanswered_keepalive_count(sender)
        sender.put(PingRequest(2), age=2.0, ping_id=2)
        live = cg.live_keepalive_count(sender)
        return stale, unanswered, live

    stale, unanswered, live = asyncio.run(scenario())
    assert stale == 0
    assert unanswered == 1
    assert live == 1

def test_msgsack_does_not_supersede_live_ping():
    async def scenario():
        logger = Logger()
        sender = PingSender()
        ping = sender.put(PingRequest(1), age=2.0, ping_id=1)
        ack = sender.put(MsgsAck([1]), age=0.5)
        live = cg.live_keepalive_count(sender)
        unanswered = cg.unanswered_keepalive_count(sender)
        dropped = cg.reclaim_superseded_keepalive(
            sender, keep_newest=1, logger=logger,
        )
        left = [type(state.request).__name__ for state in sender._pending_state.values()]
        return logger, ping, ack, live, unanswered, dropped, left

    logger, ping, ack, live, unanswered, dropped, left = asyncio.run(scenario())
    assert live == 1
    assert unanswered == 1
    assert dropped == 0
    assert left.count("PingRequest") == 1
    assert left.count("MsgsAck") == 1
    assert not ping.future.done()
    assert not ack.future.done()
    texts = "\n".join(logger.infos)
    assert "KEEPALIVE SUPERSEDED" not in texts
    assert "kept=0" not in texts


def test_supersede_never_drops_last_live_ping():
    async def scenario():
        logger = Logger()
        sender = PingSender()
        ping = sender.put(PingRequest(9), ping_id=9)
        dropped = cg.reclaim_superseded_keepalive(
            sender, keep_newest=0, logger=logger,
        )
        return logger, ping, dropped, cg.live_keepalive_count(sender), sender

    logger, ping, dropped, live, sender = asyncio.run(scenario())
    assert dropped == 0
    assert live == 1
    assert not ping.future.done()
    assert len(_keepalive_pending(sender)) == 1
    assert "kept=0" not in "\n".join(logger.infos)


def test_no_new_ping_while_previous_live_even_if_tracker_set():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        sender._keepalive_ping(21)
        assert sender._ping == 21
        sender._keepalive_ping(22)
        snap = pending_rpc_snapshot(sender)
        return logger, sender, snap

    logger, sender, snap = asyncio.run(scenario())
    assert sender.pings == [("sent", 21)]
    assert len(_keepalive_pending(sender)) == 1
    assert snap["sender_pending_keepalive"] == 1
    assert cg.live_keepalive_count(sender) == 1
    texts = "\n".join(logger.infos)
    assert "KEEPALIVE PING SKIPPED" in texts
    assert "KEEPALIVE SUPERSEDED" not in texts
    assert "kept=0" not in texts
    skip_states = [line for line in _states(logger) if "action=skip" in line]
    assert skip_states
    assert "future_done=0" in skip_states[0]
    assert "in_sender_pending=1" in skip_states[0]


def test_supersede_cancels_old_future_keeps_newest():
    async def scenario():
        logger = Logger()
        sender = PingSender()
        old = sender.put(PingRequest(1), age=5.0, ping_id=1)
        newest = sender.put(PingRequest(2), age=1.0, ping_id=2)
        dropped = cg.reclaim_superseded_keepalive(
            sender, keep_newest=1, logger=logger,
        )
        left = [type(state.request).__name__ for state in sender._pending_state.values()]
        return logger, old, newest, dropped, left, sender

    logger, old, newest, dropped, left, sender = asyncio.run(scenario())
    assert dropped == 1
    assert old.future.done()
    assert old.future.cancelled()
    assert not newest.future.done()
    assert left == ["PingRequest"]
    assert cg.live_keepalive_count(sender) == 1
    superseded = [line for line in logger.infos if line.startswith("KEEPALIVE SUPERSEDED")]
    assert superseded
    assert "dropped=1" in superseded[0]
    assert "kept=1" in superseded[0]
    assert "kept=0" not in superseded[0]


def test_complete_pong_does_not_touch_msgsack_or_httpwait():
    async def scenario():
        sender = PingSender()
        ack = sender.put(MsgsAck([7]), age=0.2)
        wait = sender.put(HttpWait(1), age=0.2)
        ping = sender.put(PingRequest(5), ping_id=5)
        removed = cg.complete_keepalive_pending(
            sender, ping_id=5, reason="RESPONSE",
        )
        left = [type(state.request).__name__ for state in sender._pending_state.values()]
        return removed, left, ack, wait, ping, sender

    removed, left, ack, wait, ping, sender = asyncio.run(scenario())
    assert removed == 1
    assert sorted(left) == ["HttpWait", "MsgsAck"]
    assert not ack.future.done()
    assert not wait.future.done()
    assert ping.future.done()
    assert cg.live_keepalive_count(sender) == 0
    assert pending_rpc_snapshot(sender)["sender_pending_keepalive"] == 0


def test_max_one_live_ping_across_repeated_sends():
    async def scenario():
        logger = Logger()
        client = PingClient()
        instrument_client(client, logger)
        sender = client._sender
        for ping_id in (1, 2, 3, 4, 5):
            sender._keepalive_ping(ping_id)
            assert cg.live_keepalive_count(sender) <= 1
            assert len(_keepalive_pending(sender)) <= 1
        return logger, sender

    logger, sender = asyncio.run(scenario())
    assert cg.live_keepalive_count(sender) == 1
    assert len(_keepalive_pending(sender)) == 1
    assert sender.pings == [("sent", 1)]
    assert "kept=0" not in "\n".join(logger.infos)

