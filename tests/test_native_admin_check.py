"""Native admin RPC miss must be cached. No network."""
import asyncio
import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "splusthon" not in sys.modules:
    fake = types.ModuleType("splusthon")
    fake.Button = object
    fake.types = types.ModuleType("splusthon.types")
    tl = types.ModuleType("splusthon.tl")
    tl_types = types.ModuleType("splusthon.tl.types")

    class _Ent:
        def __init__(self, offset=0, length=0, **_kwargs):
            self.offset = offset
            self.length = length

    tl_types.MessageEntityBold = _Ent
    tl_types.MessageEntityBlockquote = _Ent
    tl.types = tl_types
    tl.functions = types.ModuleType("splusthon.tl.functions")
    fake.tl = tl
    sys.modules["splusthon"] = fake
    sys.modules["splusthon.tl"] = tl
    sys.modules["splusthon.tl.types"] = tl_types
    sys.modules["splusthon.tl.functions"] = tl.functions
    sys.modules["splusthon.types"] = fake.types

import handlers.message_handler as handler

PASSED = FAILED = 0


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


class _Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def log_info(self, message):
        self.infos.append(message)

    def log_error(self, message):
        self.errors.append(message)


class _Config:
    def __init__(self, debug=False):
        self.debug = debug

    def get(self, key, default=None):
        if key == "debug_message_pipeline":
            return self.debug
        return default


class _Client:
    def __init__(self, error=None, is_admin=False):
        self.error = error
        self.is_admin = is_admin
        self.calls = []

    async def get_permissions(self, chat_id, user):
        self.calls.append((chat_id, user))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(is_admin=self.is_admin)


def _bot(client, debug=False):
    return SimpleNamespace(
        client=client,
        logger=_Logger(),
        config_manager=_Config(debug=debug),
        native_group_admin_cache={},
    )


def test_negative_native_admin_ttl_is_raised():
    print("\n### TTL نتیجه منفی native admin بالاتر از قبل است")
    check("fail TTL is 180s", handler._NATIVE_ADMIN_FAIL_TTL == 180,
          f"-> {handler._NATIVE_ADMIN_FAIL_TTL}")
    check("non-admin TTL is 90s", handler._NATIVE_ADMIN_NEGATIVE_TTL == 90,
          f"-> {handler._NATIVE_ADMIN_NEGATIVE_TTL}")


def test_native_admin_check_is_only_for_management_commands():
    print("\n### native admin فقط برای دستور مدیریتی")
    check("سلام is not management", handler._is_management_command("سلام") is False)
    check("filter text is not management",
          handler._is_management_command("خرید از shop.com") is False)
    check("راهنما is not management", handler._is_management_command("راهنما") is False)
    check("قفل is management", handler._is_management_command("قفل") is True)
    check("پاک 10 is management", handler._is_management_command("پاک 10") is True)
    check("سکوت is management", handler._is_management_command("سکوت") is True)
    check(".قفل is management", handler._is_management_command(".قفل") is True)
    check("decorative dots are not management",
          handler._is_management_command("........") is False)
    check("unknown dotted text is not management",
          handler._is_management_command(".spammmmm") is False)
    check("regular chat skips native RPC",
          handler._should_check_native_admin(False, False, "سلام") is False)
    check("filter path skips native RPC",
          handler._should_check_native_admin(False, False, "لینک تبلیغاتی") is False)
    check("registered admin skips native RPC",
          handler._should_check_native_admin(False, True, "قفل") is False)
    check("private skips native RPC",
          handler._should_check_native_admin(True, False, "قفل") is False)
    check("management command checks native role",
          handler._should_check_native_admin(False, False, "قفل") is True)
    check("پاک 10 checks native role",
          handler._should_check_native_admin(False, False, "پاک 10") is True)
    check("فعال skips native RPC",
          handler._should_check_native_admin(False, False, "فعال") is False)
    check("ثبت گروه skips native RPC",
          handler._should_check_native_admin(False, False, "ثبت گروه") is False)
    check("ثبت مالک skips native RPC",
          handler._should_check_native_admin(False, False, "ثبت مالک") is False)


def test_regular_message_does_not_call_get_permissions():
    print("\n### پیام عادی get_permissions نمی‌زند")
    client = _Client(error=KeyError(12345))
    bot = _bot(client)

    async def run():
        if handler._should_check_native_admin(False, False, "سلام دوستان"):
            await handler._is_native_group_admin(bot, -1009, 44, None)

    asyncio.run(run())
    check("no RPC on regular chat", client.calls == [], f"-> {client.calls}")
    check("no native fail log", bot.logger.errors == [], f"-> {bot.logger.errors}")


def test_management_command_does_call_get_permissions():
    print("\n### دستور مدیریتی native check را با chat حل‌شده اجرا می‌کند")
    client = _Client(is_admin=True)
    bot = _bot(client)
    resolved_chat = SimpleNamespace(id=-1010, access_hash=987)

    async def run():
        called = False
        result = False
        if handler._should_check_native_admin(False, False, "قفل"):
            called = True
            result = await handler._is_native_group_admin(
                bot, -1010, 55, None, resolved_chat
            )
        return called, result

    called, result = asyncio.run(run())
    check("management path entered", called is True)
    check("native admin True", result is True)
    check("one RPC", len(client.calls) == 1, f"-> {client.calls}")
    check(
        "resolved chat passed instead of short id",
        client.calls[0][0] is resolved_chat,
        f"-> {client.calls}",
    )


def test_resolved_channel_uses_supported_admin_list():
    print("\n### peer حل‌شده فهرست ادمین پشتیبانی‌شده را می‌گیرد")

    class InputPeerChannel:
        def __init__(self, channel_id):
            self.channel_id = channel_id

    class InputPeerUser:
        def __init__(self, user_id):
            self.user_id = user_id

    class GetParticipantsRequest:
        def __init__(self, channel, filter, offset, limit, hash):
            self.channel = channel
            self.filter = filter
            self.offset = offset
            self.limit = limit
            self.hash = hash

    class ChannelParticipantsAdmins:
        pass

    class ChannelParticipantAdmin:
        def __init__(self, user_id):
            self.user_id = user_id
    resolved_chat = SimpleNamespace(id=23168821, access_hash=111)
    resolved_sender = SimpleNamespace(id=69221075, access_hash=222)
    input_chat = InputPeerChannel(23168821)
    input_sender = InputPeerUser(69221075)
    other_sender = SimpleNamespace(id=123456, access_hash=333)
    input_other_sender = InputPeerUser(123456)

    class DirectClient:
        def __init__(self):
            self.calls = []
            self.permission_calls = 0

        async def __call__(self, request):
            self.calls.append(request)
            return SimpleNamespace(
                participants=[ChannelParticipantAdmin(69221075)],
                users=[SimpleNamespace(id=69221075)],
            )

        async def get_permissions(self, *_args):
            self.permission_calls += 1
            raise KeyError(23168821)

    fake_root = sys.modules["splusthon"]
    old_utils = getattr(fake_root, "utils", None)
    had_channels = hasattr(handler.functions, "channels")
    old_channels = getattr(handler.functions, "channels", None)
    had_admin_filter = hasattr(handler.types, "ChannelParticipantsAdmins")
    old_admin_filter = getattr(handler.types, "ChannelParticipantsAdmins", None)
    fake_root.utils = SimpleNamespace(
        get_input_peer=lambda value: (
            input_chat if value is resolved_chat
            else input_sender if value is resolved_sender
            else input_other_sender if value is other_sender
            else None
        )
    )
    handler.functions.channels = SimpleNamespace(
        GetParticipantsRequest=GetParticipantsRequest
    )
    handler.types.ChannelParticipantsAdmins = ChannelParticipantsAdmins
    client = DirectClient()
    bot = _bot(client)

    async def run():
        first = await handler._is_native_group_admin(
            bot, 23168821, 69221075, resolved_sender, resolved_chat
        )
        second = await handler._native_admin_from_resolved_peer(
            bot, resolved_chat, other_sender, 123456
        )
        return first, second

    try:
        result, other_result = asyncio.run(run())
    finally:
        if old_utils is None:
            delattr(fake_root, "utils")
        else:
            fake_root.utils = old_utils
        if had_channels:
            handler.functions.channels = old_channels
        else:
            delattr(handler.functions, "channels")
        if had_admin_filter:
            handler.types.ChannelParticipantsAdmins = old_admin_filter
        else:
            delattr(handler.types, "ChannelParticipantsAdmins")

    check("admin-list result says admin", result is True)
    check("other user is not in admin list", other_result is False)
    check("one cached admin-list RPC", len(client.calls) == 1, f"-> {client.calls}")
    check(
        "broken get_permissions was bypassed",
        client.permission_calls == 0,
        f"-> {client.permission_calls}",
    )
    check("no native failure log", bot.logger.errors == [], f"-> {bot.logger.errors}")


def test_keyerror_is_fail_closed_and_cached():
    print("\n### KeyError سروش → False و بدون RPC دوباره")
    client = _Client(error=KeyError(12345))
    bot = _bot(client)

    async def run():
        first = await handler._is_native_group_admin(bot, -1001, 77, None)
        second = await handler._is_native_group_admin(bot, -1001, 77, None)
        return first, second

    first, second = asyncio.run(run())
    check("first call fail-closed", first is False, f"-> {first}")
    check("second call still False", second is False, f"-> {second}")
    check("get_permissions called once", len(client.calls) == 1, f"-> {client.calls}")
    check("one error log", len(bot.logger.errors) == 1, f"-> {bot.logger.errors}")
    check(
        "error mentions KeyError",
        any("KeyError" in item for item in bot.logger.errors),
        f"-> {bot.logger.errors}",
    )


def test_repeat_keyerror_does_not_relog():
    print("\n### تکرار KeyError در TTL لاگ تازه نمی‌نویسد")
    client = _Client(error=KeyError("missing user"))
    bot = _bot(client)

    async def run():
        await handler._is_native_group_admin(bot, -1002, 88, "sender")
        client.error = KeyError("again")
        await handler._is_native_group_admin(bot, -1002, 88, "sender")
        await handler._is_native_group_admin(bot, -1002, 88, "sender")

    asyncio.run(run())
    check("still one RPC", len(client.calls) == 1, f"-> {len(client.calls)}")
    check("still one error log", len(bot.logger.errors) == 1, f"-> {len(bot.logger.errors)}")


def test_successful_admin_is_cached():
    print("\n### ادمین واقعی کش می‌شود")
    client = _Client(is_admin=True)
    bot = _bot(client)

    async def run():
        first = await handler._is_native_group_admin(bot, -1003, 99, None)
        second = await handler._is_native_group_admin(bot, -1003, 99, None)
        return first, second

    first, second = asyncio.run(run())
    check("first True", first is True)
    check("second True", second is True)
    check("one RPC", len(client.calls) == 1, f"-> {client.calls}")
    check("no error log", bot.logger.errors == [], f"-> {bot.logger.errors}")


def test_successful_member_is_cached():
    print("\n### عضو عادی هم کش می‌شود")
    client = _Client(is_admin=False)
    bot = _bot(client)

    async def run():
        first = await handler._is_native_group_admin(bot, -1004, 11, None)
        second = await handler._is_native_group_admin(bot, -1004, 11, None)
        return first, second

    first, second = asyncio.run(run())
    check("first False", first is False)
    check("second False", second is False)
    check("one RPC", len(client.calls) == 1, f"-> {client.calls}")


def test_expired_failure_retries():
    print("\n### بعد از TTL شکست، RPC دوباره زده می‌شود")
    client = _Client(error=KeyError("gone"))
    bot = _bot(client)

    async def run():
        first = await handler._is_native_group_admin(bot, -1005, 22, None)
        key = next(iter(bot.native_group_admin_cache))
        value, expires = bot.native_group_admin_cache[key]
        bot.native_group_admin_cache[key] = (value, expires - 1000)
        client.error = None
        client.is_admin = True
        second = await handler._is_native_group_admin(bot, -1005, 22, None)
        return first, second

    first, second = asyncio.run(run())
    check("expired miss was False", first is False)
    check("retry saw admin", second is True)
    check("two RPCs after expiry", len(client.calls) == 2, f"-> {len(client.calls)}")


def test_event_input_peer_warms_shared_background_rpc_cache():
    print("\n### peer حل‌شده رویداد برای حذف پس‌زمینه نگه داشته می‌شود")
    peer = object()
    message = SimpleNamespace(_input_chat=peer)
    event = SimpleNamespace(chat_id=23375191, message=message)
    bot = SimpleNamespace(reply_input_peer_cache={})
    result = handler._warm_reply_input_chat(bot, event)
    check("existing event peer retained", result is True)
    check(
        "short group id maps to resolved peer",
        bot.reply_input_peer_cache.get(23375191) is peer,
    )

    normalized_peer = object()
    second_message = SimpleNamespace()
    second_event = SimpleNamespace(chat_id=23375191, message=second_message)
    second_bot = SimpleNamespace(
        reply_input_peer_cache={-1000023375191: normalized_peer}
    )
    normalized_result = handler._warm_reply_input_chat(
        second_bot, second_event
    )
    check("normalized cache form is reused", normalized_result is True)
    check(
        "reused peer attached to message",
        second_message._input_chat is normalized_peer,
    )


def test_mute_target_check_never_fetches_all_group_members():
    print("\n### سکوت برای حفاظت ادمین همه اعضای گروه را نمی‌گیرد")
    source = inspect.getsource(handler.handle_new_message)
    check(
        "unfiltered participant fetch removed",
        "get_participants(chat_id)" not in source,
    )
    check(
        "mute target uses bounded native-admin helper",
        "_is_native_group_admin(\n                    bot, chat_id, target_user.id, target_user,\n                    resolved_permission_chat,\n                )" in source,
    )


def test_ban_execution_and_admin_check_logs_are_debug_only():
    print("\n### لاگ BAN/ADMIN CHECK فقط در debug")
    quiet = SimpleNamespace(
        logger=_Logger(),
        config_manager=_Config(debug=False),
        punished_users=set(),
    )
    noisy = SimpleNamespace(
        logger=_Logger(),
        config_manager=_Config(debug=True),
        punished_users=set(),
    )
    handler._log_ban_execution(quiet, -1, 2, "اسپم")
    handler._log_ban_execution(noisy, -1, 2, "اسپم")
    check("quiet ban log off", quiet.logger.infos == [])
    check("debug ban log on", any("BAN EXECUTION DEBUG" in item for item in noisy.logger.infos))

    orig_owner = handler.is_global_owner
    orig_admin = handler.is_admin
    orig_group_owner = handler.get_group_owner
    handler.ADMIN_PERMISSION_CACHE.clear()

    async def run_checks():
        handler.is_global_owner = lambda _uid: True
        handler.is_admin = lambda *_a, **_k: False
        handler.get_group_owner = lambda _chat: None
        handler._has_group_management_permission(quiet, -9, 5, "x")
        handler.ADMIN_PERMISSION_CACHE.clear()
        handler._has_group_management_permission(noisy, -8, 6, "y")

    try:
        asyncio.run(run_checks())
    finally:
        handler.is_global_owner = orig_owner
        handler.is_admin = orig_admin
        handler.get_group_owner = orig_group_owner
        handler.ADMIN_PERMISSION_CACHE.clear()
    check("quiet admin check off", quiet.logger.infos == [])
    check(
        "debug admin check on",
        any("ADMIN CHECK DEBUG" in item for item in noisy.logger.infos),
        f"-> {noisy.logger.infos}",
    )

    handler._debug_log(quiet, "✅ ADMIN BYPASS FILTER: osine1")
    handler._debug_log(noisy, "✅ ADMIN BYPASS FILTER: osine1")
    check(
        "quiet ADMIN BYPASS FILTER off",
        not any("ADMIN BYPASS FILTER" in item for item in quiet.logger.infos),
    )
    check(
        "debug ADMIN BYPASS FILTER on",
        any("ADMIN BYPASS FILTER" in item for item in noisy.logger.infos),
        f"-> {noisy.logger.infos}",
    )


class HashableTask(SimpleNamespace):
    """جایگزین asyncio.Task در تست.

    ``SimpleNamespace`` قابل درج در ``set`` نیست (unhashable است) ولی خودِ
    هندلر تسک‌های زنده را داخل ``set`` می‌ریزد؛ پس این کلاس فقط ``__hash__``
    واقعی می‌گیرد تا مثل تسک واقعی رفتار کند.
    """

    __hash__ = object.__hash__

    def cancel(self):
        return None


def test_cleanup_expired_handler_state_sweeps_ttl_maps():
    print("\\n### جاروی TTL هندلر نقشه‌های منقضی را بدون سقف پاک می‌کند")
    handler.ADMIN_PERMISSION_CACHE.clear()
    bot = SimpleNamespace(
        native_group_admin_cache={
            ("g1", "u1"): (True, 10.0),
            ("g1", "u2"): (False, 100.0),
        },
        native_group_admin_ids_cache={
            "g1": (frozenset({"u1"}), 10.0),
            "g2": (frozenset({"u9"}), 80.0),
        },
        _native_admin_fail_logged={
            ("g1", "u1"): 5.0,
            ("g1", "u3"): 90.0,
        },
        _forward_albums={
            ("g1", 1): {"ids": {1}, "is_forward": True, "expires": 5.0},
            ("g1", 2): {"ids": {2}, "is_forward": False, "expires": 70.0},
        },
        group_timer_tasks={
            11: {HashableTask(done=lambda: True)},
            12: {HashableTask(done=lambda: False)},
        },
        _spam_cleanup_incidents={
            ("g", "orphan"): {
                "id": 1, "deleted": 0, "ban_confirmed": False,
                "_touched_at": 1.0,
            },
            ("g", "fresh"): {
                "id": 2, "deleted": 0, "ban_confirmed": False,
                "_touched_at": 50.0,
            },
            ("g", "live"): {
                "id": 3, "deleted": 0, "ban_confirmed": False,
                "_touched_at": 1.0,
                "notice_task": SimpleNamespace(done=lambda: False),
            },
        },
        _auto_spam_cleanup_tasks={
            ("g", "done"): SimpleNamespace(done=lambda: True),
        },
        _auto_spam_cleanup_pending={("g", "orphan"): {1}},
        _big_spam_incidents={
            ("g", "stale"): {
                "id": 9, "ban_state": "failed", "_touched_at": 0.0,
                "cleanup_task": SimpleNamespace(done=lambda: True),
            },
            ("g", "pending"): {
                "id": 10, "ban_state": "pending",
                "ban_absolute_deadline": 999.0, "_touched_at": 1.0,
                "cleanup_task": None,
            },
        },
    )
    handler.ADMIN_PERMISSION_CACHE[(-1, 1, "a")] = (10.0, True)
    handler.ADMIN_PERMISSION_CACHE[(-1, 2, "b")] = (90.0, False)
    removed = handler.cleanup_expired_handler_state(bot, now=60.0)
    check("native admin منقضی رفت", ("g1", "u1") not in bot.native_group_admin_cache)
    check("native admin زنده ماند", ("g1", "u2") in bot.native_group_admin_cache)
    check("admin-ids منقضی رفت", "g1" not in bot.native_group_admin_ids_cache)
    check("admin-ids زنده ماند", "g2" in bot.native_group_admin_ids_cache)
    check("fail-log منقضی رفت", ("g1", "u1") not in bot._native_admin_fail_logged)
    check("fail-log زنده ماند", ("g1", "u3") in bot._native_admin_fail_logged)
    check("permission منقضی رفت", (-1, 1, "a") not in handler.ADMIN_PERMISSION_CACHE)
    check("permission زنده ماند", (-1, 2, "b") in handler.ADMIN_PERMISSION_CACHE)
    check("آلبوم منقضی رفت", ("g1", 1) not in bot._forward_albums)
    check("آلبوم زنده ماند", ("g1", 2) in bot._forward_albums)
    check("تایمر تمام‌شده رفت", 11 not in bot.group_timer_tasks)
    check("تایمر زنده ماند", 12 in bot.group_timer_tasks)
    check("incident یتیم رفت", ("g", "orphan") not in bot._spam_cleanup_incidents)
    check("pending یتیم رفت", ("g", "orphan") not in bot._auto_spam_cleanup_pending)
    check("incident تازه ماند", ("g", "fresh") in bot._spam_cleanup_incidents)
    check("incident با تسک زنده ماند", ("g", "live") in bot._spam_cleanup_incidents)
    check("تسک cleanup تمام‌شده رفت",
          ("g", "done") not in bot._auto_spam_cleanup_tasks)
    check("big-spam کهنه رفت", ("g", "stale") not in bot._big_spam_incidents)
    check("big-spam pending تا مهلت ماند",
          ("g", "pending") in bot._big_spam_incidents)
    check("حداقل چند کلید واقعاً حذف شد", removed >= 8, f"-> {removed}")
    handler.ADMIN_PERMISSION_CACHE.clear()


def test_owner_cleanup_wires_ttl_sweeps():
    print("\\n### cleanup_temporary_state جاروی GIF و هندلر را صدا می‌زند")
    source = (ROOT / "core" / "bot_working_split_ok.py").read_text(
        encoding="utf-8"
    )
    start = source.find("def cleanup_temporary_state")
    end = source.find("\n    def _make_client", start)
    body = source[start:end if end != -1 else start + 4000]
    check("هندلر TTL در owner loop است",
          "cleanup_expired_handler_state" in body)
    check("GIF TTL در owner loop است",
          "gif_spam_detector" in body and "cleanup_expired" in body)


if __name__ == "__main__":
    test_negative_native_admin_ttl_is_raised()
    test_native_admin_check_is_only_for_management_commands()
    test_regular_message_does_not_call_get_permissions()
    test_management_command_does_call_get_permissions()
    test_resolved_channel_uses_supported_admin_list()
    test_keyerror_is_fail_closed_and_cached()
    test_repeat_keyerror_does_not_relog()
    test_successful_admin_is_cached()
    test_successful_member_is_cached()
    test_expired_failure_retries()
    test_event_input_peer_warms_shared_background_rpc_cache()
    test_mute_target_check_never_fetches_all_group_members()
    test_ban_execution_and_admin_check_logs_are_debug_only()
    print(f"\n{PASSED} passed, {FAILED} failed")
    raise SystemExit(1 if FAILED else 0)
