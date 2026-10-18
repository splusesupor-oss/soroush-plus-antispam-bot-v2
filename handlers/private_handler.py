"""Independent private-chat path: /start + one test inline button.

This module is isolated from group dispatch, Queue, Governor, and RPC
plumbing. Group messages must never enter these helpers.
"""

START_TEXT = (
    "سلام 👋\n"
    "\n"
    "برای تست دکمه اینلاین، گزینه زیر را بزنید."
)
TEST_BUTTON_TEXT = "🧪 دکمه تست"
TEST_BUTTON_DATA = b"test_button"
TEST_BUTTON_DATA_TEXT = "test_button"
TEST_OK_TEXT = "✅ دکمه کار می‌کند"


def _event_text(event):
    message = getattr(event, "message", None)
    if message is None:
        return ""
    return (
        getattr(message, "message", None)
        or getattr(message, "caption", None)
        or ""
    )


def is_private_event(event):
    """Cheap private-chat check. No RPC and no group-path helpers."""
    if event is None:
        return False
    if bool(getattr(event, "is_private", False)):
        return True
    peer = getattr(event, "_chat_peer", None)
    if peer is not None and type(peer).__name__ == "PeerUser":
        return True
    return False


def is_start_command(text):
    """True only for /start and /start@botname."""
    first = str(text or "").strip().split(None, 1)
    if not first:
        return False
    token = first[0].strip()
    if not token:
        return False
    lowered = token.lower()
    if lowered == "/start":
        return True
    return lowered.startswith("/start@")


def start_keyboard():
    """One full-width inline button on its own row."""
    try:
        from splusthon import Button
    except ImportError:
        return None
    try:
        button = Button.inline(TEST_BUTTON_TEXT, data=TEST_BUTTON_DATA)
    except Exception:
        return None
    return [[button]]


def _callback_data_text(event):
    data = getattr(event, "data", None)
    if data is None:
        data = getattr(event, "data_match", None)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="ignore")
    if data is None:
        return ""
    return str(data)


def is_test_button_callback(event):
    return _callback_data_text(event) == TEST_BUTTON_DATA_TEXT


def _log(bot, message):
    logger = getattr(bot, "logger", None) if bot is not None else None
    if logger is None:
        return
    try:
        logger.log_info(message)
    except Exception:
        pass


async def send_start_reply(bot, event):
    keyboard = start_keyboard()
    kwargs = {}
    if keyboard is not None:
        kwargs["buttons"] = keyboard
    reply = getattr(event, "reply", None)
    if callable(reply):
        await reply(START_TEXT, **kwargs)
        return True
    client = getattr(bot, "client", None) if bot is not None else None
    chat_id = getattr(event, "chat_id", None)
    send_message = getattr(client, "send_message", None) if client is not None else None
    if callable(send_message) and chat_id is not None:
        await send_message(chat_id, START_TEXT, **kwargs)
        return True
    return False


async def try_handle_private_start(bot, event):
    """Handle PV /start only. Return True when the event was consumed."""
    if not is_private_event(event):
        return False
    if not is_start_command(_event_text(event)):
        return False
    await send_start_reply(bot, event)
    _log(
        bot,
        "PRIVATE START SENT "
        f"chat_id={getattr(event, 'chat_id', None)}",
    )
    return True


async def handle_private_callback(bot, event):
    """Guard paid command callbacks, then answer the free test button."""
    from modules import free_tier

    callback_feature = free_tier.feature_for_callback(_callback_data_text(event))
    if callback_feature and not free_tier.is_enabled(callback_feature):
        answer = getattr(event, "answer", None)
        if callable(answer):
            try:
                await answer(free_tier.PAYWALL_MESSAGE)
                return True
            except Exception:
                pass
        reply = getattr(event, "reply", None)
        if callable(reply):
            await reply(free_tier.PAYWALL_MESSAGE)
            return True
        return False

    if not is_private_event(event):
        return False
    if not is_test_button_callback(event):
        return False

    answered = False
    answer = getattr(event, "answer", None)
    if callable(answer):
        try:
            await answer(TEST_OK_TEXT)
            answered = True
        except Exception as error:
            _log(bot, f"PRIVATE CALLBACK ANSWER FAILED error={error!r}")

    if not answered:
        edit = getattr(event, "edit", None)
        if callable(edit):
            kwargs = {}
            keyboard = start_keyboard()
            if keyboard is not None:
                kwargs["buttons"] = keyboard
            await edit(TEST_OK_TEXT, **kwargs)
            answered = True

    if answered:
        _log(
            bot,
            "PRIVATE TEST BUTTON OK "
            f"chat_id={getattr(event, 'chat_id', None)}",
        )
    return answered


def register_private_handlers(bot):
    """Attach the PV callback listener. NewMessage intercept lives in core."""
    client = getattr(bot, "client", None) if bot is not None else None
    if client is None or not hasattr(client, "on"):
        return False
    try:
        from splusthon import events
    except ImportError:
        return False
    callback_query = getattr(events, "CallbackQuery", None)
    if callback_query is None:
        return False

    @client.on(callback_query())
    async def private_test_button(event):
        try:
            await handle_private_callback(bot, event)
        except Exception as error:
            logger = getattr(bot, "logger", None)
            if logger is not None:
                try:
                    logger.log_error(f"PRIVATE CALLBACK FAILED error={error!r}")
                except Exception:
                    pass

    return True
