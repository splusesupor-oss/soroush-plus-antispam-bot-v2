"""Burst soak: 40 groups, mixed send/delete, unanswered pings.

    python -m pytest tests/test_governor_pending_soak.py -q
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

from modules import connection_guard as cg
from modules.outgoing_profiler import instrument_client, pending_rpc_snapshot
from modules.outgoing_sender import install as install_outgoing_sender
from modules.rpc_governor import RpcGovernor, RpcAdmission, P1_DELETE, P2_SEND


class Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, message):
        self.infos.append(str(message))

    def log_error(self, message):
        self.errors.append(str(message))


class SendMessageRequest:
    def __init__(self, peer):
        self.peer = peer


class DeleteMessagesRequest:
    def __init__(self, peer):
        self.peer = peer


class PingRequest:
    pass


class RequestState:
    def __init__(self, request, future, msg_id):
        self.request = request
        self.future = future
        self.msg_id = msg_id
        self.container_id = None


class Sender:
    def __init__(self):
        self._pending_state = {}
        self._n = 0
        self._ping = None
        self._user_connected = True
        self._reconnecting = False

    def put(self, request):
        self._n += 1
        future = asyncio.get_running_loop().create_future()
        state = RequestState(request, future, self._n)
        self._pending_state[self._n] = state
        cg.note_pending(self)
        return state

    def _keepalive_ping(self, rnd_id):
        self._ping = rnd_id
        return rnd_id

    def _handle_pong(self, message):
        self._ping = None

    def _start_reconnect(self, error):
        return None


class Client:
    def __init__(self, rtt_ms=80.0):
        self._sender = Sender()
        self.rtt_ms = rtt_ms

    async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        state = sender.put(request)
        await asyncio.sleep(self.rtt_ms / 1000.0)
        if not state.future.done():
            state.future.set_result("ok")
        sender._pending_state.pop(state.msg_id, None)
        return "ok"

    async def send_message(self, entity, text, **kwargs):
        return await self._call(self._sender, SendMessageRequest(entity))

    async def delete_messages(self, entity, ids, **kwargs):
        return await self._call(self._sender, DeleteMessagesRequest(entity))


def _governor_waits(logger):
    waits = []
    for line in logger.infos + logger.errors:
        if "governor_wait_ms=" not in line:
            continue
        for part in line.split():
            if part.startswith("governor_wait_ms="):
                waits.append(float(part.split("=", 1)[1]))
    return waits


def test_forty_group_mixed_send_delete_and_pings():
    async def scenario():
        logger = Logger()
        client = Client(rtt_ms=80.0)
        bot = SimpleNamespace(logger=logger, rpc_governor=None)
        instrument_client(client, logger)
        cg.install_rpc_timeout(client, timeout=5.0, logger=logger)
        install_outgoing_sender(client, bot, logger)
        groups = 40

        async def one_group(gid):
            await client.send_message(-100000 - gid, f"notice-{gid}")
            await client.delete_messages(-100000 - gid, [gid])

        # Wave in batches of 8 so same-bucket send_limit=1 does not
        # invent a multi-second queue; the bug is cross-bucket locking.
        for start in range(0, groups, 8):
            await asyncio.gather(*[one_group(g) for g in range(start, min(start + 8, groups))])

        sender = client._sender
        for age in (28.0, 22.0, 18.0, 16.0, 8.0):
            sender._n += 1
            future = asyncio.get_running_loop().create_future()
            state = RequestState(PingRequest(), future, sender._n)
            sender._pending_state[sender._n] = state
            cg._seen_at(sender)[sender._n] = time.monotonic() - age
        live_send = sender.put(SendMessageRequest(1))
        pending_before = len(sender._pending_state)
        sender._keepalive_ping(99)
        pending_after_ping = len(sender._pending_state)
        snap = pending_rpc_snapshot(sender)
        live_send.future.cancel()
        sender._pending_state.pop(live_send.msg_id, None)
        return logger, pending_before, pending_after_ping, snap, bot.rpc_governor.snapshot()

    logger, before, after_ping, snap, gov = asyncio.run(scenario())
    waits = _governor_waits(logger)
    max_wait = max(waits) if waits else 0.0
    # Cross-bucket isolation: send must not sit behind delete for seconds.
    assert max_wait < 1500.0, max_wait
    # Unanswered pings must not stack across a new heartbeat.
    assert after_ping <= 2, after_ping
    assert snap["sender_pending"] <= 2
    assert gov["active"] == 0
    assert before >= 6


def test_isolated_governor_under_held_delete():
    # 🔒 محدودیت‌ها از محیط خوانده می‌شوند؛ خودِ تست مقدار محافظه‌کارانه را
    # تعیین می‌کند تا نتیجه به .env همان دستگاه وابسته نباشد (روی دستگاه مالک
    # BOT_RPC_TOTAL_LIMIT=3 است و تست با انتظار ۲ می‌شکست).
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
        held = await governor.acquire(RpcAdmission(P1_DELETE, "delete", "DeleteMessagesRequest", "busy"))
        started = time.perf_counter()
        send = await asyncio.wait_for(
            governor.acquire(RpcAdmission(P2_SEND, "send", "SendMessageRequest", "other")),
            timeout=0.05,
        )
        wait_ms = (time.perf_counter() - started) * 1000.0
        held.release()
        send.release()
        return wait_ms, governor.noncritical_limit, governor.total_limit

    try:
        wait_ms, nc, total = asyncio.run(scenario())
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert total == 2
    assert nc >= 2
    assert wait_ms < 50.0, wait_ms
