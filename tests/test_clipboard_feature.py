"""Offline tests for the Fox clipboard feature.

Run with:
    python tests/test_clipboard_feature.py
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import clipboard_storage as storage
from handlers import clipboard_handler as handler


class MessageEntityBold:
    def __init__(self, offset=0, length=0, **kwargs):
        self.offset = offset
        self.length = length
        self.__dict__.update(kwargs)


class MessageEntityTextUrl(MessageEntityBold):
    pass


class FakeTypes:
    MessageEntityBold = MessageEntityBold
    MessageEntityBlockquote = MessageEntityBold
    MessageEntityTextUrl = MessageEntityTextUrl


class FakeLogger:
    def __init__(self):
        self.errors = []

    def log_error(self, message):
        self.errors.append(message)

    def log_info(self, message):
        pass


class FakeBot:
    def __init__(self):
        self.logger = FakeLogger()
        self.client = SimpleNamespace()


class FakeSent:
    def __init__(self, message_id, text, entities):
        self.id = message_id
        self.message = text
        self.entities = list(entities or [])


class FakeEvent:
    def __init__(self, text="", *, message_id=1, reply_to_id=None, entities=None):
        self.is_private = False
        self.chat_id = 100
        self.sender_id = 10
        self.message = SimpleNamespace(
            message=text,
            caption=text,
            id=message_id,
            entities=list(entities or []),
            reply_to=(
                SimpleNamespace(reply_to_msg_id=reply_to_id)
                if reply_to_id is not None else None
            ),
        )
        self.replies = []
        self.responses = []
        self._next_id = 1000

    async def reply(self, text, formatting_entities=None, **kwargs):
        self._next_id += 1
        sent = FakeSent(self._next_id, text, formatting_entities)
        self.replies.append(sent)
        return sent

    async def respond(self, text, formatting_entities=None, **kwargs):
        self._next_id += 1
        sent = FakeSent(self._next_id, text, formatting_entities)
        self.responses.append(sent)
        return sent


class TempStorage:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_file = storage.FILE
        storage.FILE = Path(self.tmp.name) / "clipboard.json"
        storage.reset_cache()

    def close(self):
        storage.FILE = self.old_file
        storage.reset_cache()
        self.tmp.cleanup()


PASSED = FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  PASS", label)
    else:
        FAILED += 1
        print("  FAIL", label, detail)


def test_storage_and_formatting():
    env = TempStorage()
    try:
        bold = MessageEntityBold(offset=0, length=5)
        link = MessageEntityTextUrl(offset=6, length=4, url="https://example.com")
        ok, reason = storage.save(100, "سلام\nلینک", [bold, link])
        check("plain/multiline clipboard saves", ok and reason is None)
        raw = storage.get_raw(100)
        check("entity type persisted", raw["entities"][0]["type"] == "MessageEntityBold")
        check("link attribute persisted", raw["entities"][1]["attrs"]["url"] == "https://example.com")
        restored = storage.deserialize_entities(raw["entities"], FakeTypes)
        check("formatting entity round-trip", len(restored) == 2)
        check("link formatting round-trip", getattr(restored[1], "url", None) == "https://example.com")

        storage.reset_cache()
        check("clipboard survives cache reset", storage.get_raw(100)["text"] == "سلام\nلینک")

        ok, _ = storage.save(100, "متن جدید", [])
        check("new text replaces old text", ok and storage.get_raw(100)["text"] == "متن جدید")
        check("group isolation", storage.get_raw(200) is None)
    finally:
        env.close()


def test_pending_guide_and_handler():
    env = TempStorage()
    original_permission = handler.admin_tools.has_admin_permission
    handler.admin_tools.has_admin_permission = lambda *args: True
    try:
        bot = FakeBot()
        guide_event = FakeEvent("کپی بورد")
        consumed = asyncio.run(handler.handle_command(bot, guide_event, 100, 10, SimpleNamespace(username="admin"), "کپی بورد"))
        check("copyboard command consumed", consumed)
        check("exactly one guide sent", len(guide_event.replies) == 1)
        guide = guide_event.replies[0]
        check("guide has bold and quote entities", len(guide.entities) == 3)
        check("guide stores its exact message id", storage.get_pending_guide(100) == guide.id)

        saved_event = FakeEvent("سلام دوستان 👋", message_id=2, reply_to_id=guide.id, entities=[MessageEntityBold(0, 5)])
        consumed = asyncio.run(handler.handle_reply_save(bot, saved_event, 100, 10, SimpleNamespace(username="admin"), saved_event.message.message))
        check("correct reply saves", consumed and storage.get_raw(100)["text"] == "سلام دوستان 👋")
        check("pending guide clears after save", storage.get_pending_guide(100) is None)
        check("success acknowledgement sent", saved_event.replies[-1].message == "✅ متن کپی بورد با موفقیت ذخیره شد.")

        copy_event = FakeEvent("کپی")
        consumed = asyncio.run(handler.handle_command(bot, copy_event, 100, 10, SimpleNamespace(username="admin"), "کپی"))
        check("copy command consumed", consumed)
        check("stored text is sent", copy_event.responses[-1].message == "سلام دوستان 👋")

        guide_event2 = FakeEvent("کپی بورد")
        asyncio.run(handler.handle_command(bot, guide_event2, 100, 10, SimpleNamespace(username="admin"), "کپی بورد"))
        wrong = FakeEvent("نباید ذخیره شود", reply_to_id=999)
        consumed = asyncio.run(handler.handle_reply_save(bot, wrong, 100, 10, SimpleNamespace(username="admin"), "نباید ذخیره شود"))
        check("wrong reply is ignored", not consumed and storage.get_raw(100)["text"] == "سلام دوستان 👋")

        forbidden = FakeEvent("ک ی ر", reply_to_id=guide_event2.replies[0].id)
        consumed = asyncio.run(handler.handle_reply_save(bot, forbidden, 100, 10, SimpleNamespace(username="admin"), "ک ی ر"))
        check("forbidden content is rejected", consumed and storage.get_raw(100)["text"] == "سلام دوستان 👋")
        check("forbidden acknowledgement shown", "غیرمجاز" in forbidden.replies[-1].message)
    finally:
        handler.admin_tools.has_admin_permission = original_permission
        env.close()


def test_permissions_and_missing_clipboard():
    env = TempStorage()
    original_permission = handler.admin_tools.has_admin_permission
    try:
        handler.admin_tools.has_admin_permission = lambda *args: False
        bot = FakeBot()
        denied = FakeEvent("کپی بورد")
        asyncio.run(handler.handle_command(bot, denied, 100, 10, SimpleNamespace(username="user"), "کپی بورد"))
        check("ordinary user cannot create guide", not denied.replies[0].message.startswith("🔖"))
        check("ordinary user cannot create pending guide", storage.get_pending_guide(100) is None)

        handler.admin_tools.has_admin_permission = lambda *args: True
        missing = FakeEvent("کپی")
        asyncio.run(handler.handle_command(bot, missing, 300, 10, SimpleNamespace(username="admin"), "کپی"))
        check("missing clipboard has clear response", "هنوز متنی" in missing.replies[-1].message)
    finally:
        handler.admin_tools.has_admin_permission = original_permission
        env.close()


def main():
    test_storage_and_formatting()
    test_pending_guide_and_handler()
    test_permissions_and_missing_clipboard()
    print(f"\nclipboard tests: passed={PASSED} failed={FAILED}")
    raise SystemExit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
