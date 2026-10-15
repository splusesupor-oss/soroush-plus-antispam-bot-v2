"""Test suite and comparative benchmarks for Cache Layer and Circuit Breaker."""
import asyncio
import time
from types import SimpleNamespace

from modules.cache_manager import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    PermissionCircuitBreaker,
    TtlCache,
)
from modules.admin_actions import AdminActions, ChatAdminRequiredError


class FakeClient:
    def __init__(self, rpc_delay=0.01):
        self.rpc_delay = rpc_delay
        self.delete_calls = 0
        self.edit_permission_calls = 0
        self.get_entity_calls = 0
        self.should_fail_admin = False

    async def get_input_entity(self, value):
        self.get_entity_calls += 1
        if self.rpc_delay:
            await asyncio.sleep(self.rpc_delay)
        return SimpleNamespace(id=value, access_hash=123)

    async def get_entity(self, value):
        return await self.get_input_entity(value)

    async def delete_messages(self, chat_id, ids):
        self.delete_calls += 1
        if self.rpc_delay:
            await asyncio.sleep(self.rpc_delay)
        if self.should_fail_admin:
            raise ChatAdminRequiredError("Chat admin required")
        return True

    async def edit_permissions(self, chat, user, **kwargs):
        self.edit_permission_calls += 1
        if self.rpc_delay:
            await asyncio.sleep(self.rpc_delay)
        if self.should_fail_admin:
            raise ChatAdminRequiredError("Chat admin required")
        return True

    async def __call__(self, request):
        if self.rpc_delay:
            await asyncio.sleep(self.rpc_delay)
        if self.should_fail_admin:
            raise ChatAdminRequiredError("Chat admin required")
        return True


class FakeLogger:
    def __init__(self):
        self.logs = []

    def log_info(self, msg):
        self.logs.append(("INFO", msg))

    def log_error(self, msg):
        self.logs.append(("ERROR", msg))

    def log_action(self, action, user_id, chat_id, reason=""):
        self.logs.append(("ACTION", f"{action} user={user_id} chat={chat_id}"))


def test_ttl_cache_basic_and_expiration():
    cache = TtlCache(default_ttl=0.05, max_size=5)
    cache.set("a", 1)
    cache.set("b", 2, ttl=0.1)

    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") is None

    time.sleep(0.06)
    # "a" should be expired, "b" still active
    assert cache.get("a") is None
    assert cache.get("b") == 2

    time.sleep(0.05)
    # "b" should now be expired
    assert cache.get("b") is None

    stats = cache.snapshot()["stats"]
    assert stats["hits"] >= 3
    assert stats["misses"] >= 2
    print("TTL Cache expiration test passed!")


def test_ttl_cache_eviction_on_max_size():
    cache = TtlCache(default_ttl=10.0, max_size=3)
    cache.set("k1", 100)
    cache.set("k2", 200)
    cache.set("k3", 300)
    assert cache.snapshot()["size"] == 3

    # Add 4th item -> should evict k1
    cache.set("k4", 400)
    assert cache.snapshot()["size"] == 3
    assert cache.get("k1") is None
    assert cache.get("k2") == 200
    assert cache.get("k3") == 300
    assert cache.get("k4") == 400
    assert cache.snapshot()["stats"]["evictions"] == 1
    print("TTL Cache eviction test passed!")


# در این نسخهٔ splusthon سازندهٔ ChatAdminRequiredError یک آرگومان (request)
# می‌گیرد. برای این تست فقط *نوع* خطا مهم است، پس یک شیء ساده می‌دهیم.
_ADMIN_REQUIRED = ChatAdminRequiredError(SimpleNamespace())


def test_permission_circuit_breaker_lifecycle():
    cb = PermissionCircuitBreaker(default_cooldown=0.08)
    chat_id = 999

    # 1. Closed state
    assert cb.can_execute(chat_id) is True
    assert not cb.is_open(chat_id)

    # 2. Trip on failure -> OPEN
    cb.record_failure(chat_id, _ADMIN_REQUIRED)
    assert cb.is_open(chat_id) is True
    assert cb.can_execute(chat_id) is False  # Blocked fast!

    # 3. Cooldown elapses -> HALF_OPEN (1 probe allowed)
    time.sleep(0.09)
    assert cb.can_execute(chat_id) is True   # Probe allowed
    assert cb.can_execute(chat_id) is False  # Second call blocked while probe in flight

    # 4. Probe succeeds -> CLOSED
    cb.record_success(chat_id)
    assert cb.is_open(chat_id) is False
    assert cb.can_execute(chat_id) is True

    # 5. Manual reset
    cb.record_failure(chat_id, _ADMIN_REQUIRED)
    assert cb.is_open(chat_id) is True
    cb.reset(chat_id)
    assert cb.is_open(chat_id) is False
    assert cb.can_execute(chat_id) is True
    print("Circuit Breaker lifecycle test passed!")


def test_admin_actions_circuit_breaker_and_entity_cache():
    async def scenario():
        client = FakeClient(rpc_delay=0.005)
        logger = FakeLogger()
        config = {"send_warning": False}
        cb = PermissionCircuitBreaker(default_cooldown=0.1, logger=logger)
        admin = AdminActions(client, logger, config, circuit_breaker=cb)

        # First delete succeeds
        ok1 = await admin.delete_message(101, 1)
        assert ok1 is True
        assert client.delete_calls == 1

        # Now simulate bot losing admin rights
        client.should_fail_admin = True
        ok2 = await admin.delete_message(101, 2)
        assert ok2 is False
        assert client.delete_calls == 2
        assert cb.is_open(101) is True

        # Next 50 delete calls should be blocked locally without calling client.delete_messages!
        t_start = time.perf_counter()
        for msg_id in range(3, 53):
            blocked = await admin.delete_message(101, msg_id)
            assert blocked is False
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        # Delete calls on client remain exactly 2 (50 calls avoided!)
        assert client.delete_calls == 2
        # Elapsed time for 50 blocked calls is sub-millisecond (not 50 * 5ms = 250ms)
        assert elapsed_ms < 20.0

        # Entity resolution caching
        client.should_fail_admin = False
        ent1 = await admin._input_entity(555)
        ent2 = await admin._input_entity(555)
        assert ent1 is ent2
        assert client.get_entity_calls == 1  # 2nd call was served from cache!

        print(f"AdminActions integration test passed! 50 doomed RPCs skipped in {elapsed_ms:.2f}ms")

    asyncio.run(scenario())


def run_comparative_benchmark():
    """Comparative run: 100 spam messages in an unprivileged group with vs without Circuit Breaker."""
    async def run_scenario(use_circuit_breaker: bool):
        client = FakeClient(rpc_delay=0.002)  # 2ms per network call (simulated fast MTProto)
        logger = FakeLogger()
        config = {"send_warning": False}
        client.should_fail_admin = True

        if use_circuit_breaker:
            cb = PermissionCircuitBreaker(default_cooldown=60.0)
            admin = AdminActions(client, logger, config, circuit_breaker=cb)
        else:
            # Dummy breaker that never trips
            class NoopBreaker:
                def can_execute(self, *a, **k): return True
                def record_success(self, *a): pass
                def record_failure(self, *a, **k): pass
            admin = AdminActions(client, logger, config, circuit_breaker=NoopBreaker())

        t0 = time.perf_counter()
        for i in range(100):
            await admin.delete_message(500, i + 1)
        duration_ms = (time.perf_counter() - t0) * 1000
        return duration_ms, client.delete_calls

    async def main():
        time_no_cb, rpc_no_cb = await run_scenario(use_circuit_breaker=False)
        time_with_cb, rpc_with_cb = await run_scenario(use_circuit_breaker=True)

        reduction_pct = ((rpc_no_cb - rpc_with_cb) / rpc_no_cb) * 100
        speedup = time_no_cb / max(0.001, time_with_cb)

        print("\n================ COMPARATIVE BENCHMARK (100 Spam Messages in Non-Admin Group) ================")
        print(f"Without Circuit Breaker : Time = {time_no_cb:.2f} ms | Network RPC Calls = {rpc_no_cb}")
        print(f"With Circuit Breaker    : Time = {time_with_cb:.2f} ms | Network RPC Calls = {rpc_with_cb}")
        print(f"RPC Reduction           : {reduction_pct:.1f}% fewer requests to Soroush server")
        print(f"Speedup Factor          : {speedup:.1f}x faster execution")
        print("===============================================================================================\n")

    asyncio.run(main())


if __name__ == "__main__":
    test_ttl_cache_basic_and_expiration()
    test_ttl_cache_eviction_on_max_size()
    test_permission_circuit_breaker_lifecycle()
    test_admin_actions_circuit_breaker_and_entity_cache()
    run_comparative_benchmark()
