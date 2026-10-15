"""Mandatory isolation / security / logging / backup tests for B2.

These tests are deliberately self-contained: they never touch the real runtime
data directory, never open a network connection and never need a live session.

Covered requirements
--------------------
1.  settings structure and B2 paths
2.  B1 / B2 / B3 path independence
3.  owner and admin detection
4.  missing and invalid session, without disclosing the value
5.  session/token never written to a log
6.  no duplicated log lines
7.  log rotation and size capping
8.  backup creation, archive integrity, sha256
9.  restore into a temporary directory
10. real data untouched during a trial restore
11. concurrent instances cannot run twice
12. repository does not track secrets
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_INSTANCE", "bot2")

from modules import instance_guard, log_policy, secret_guard  # noqa: E402
from modules import session_resolver  # noqa: E402
from modules import logger_module  # noqa: E402
from modules import runtime_paths  # noqa: E402

FAKE_SESSION = ("1AwASaFAKEfake" * 8) + "XYZ="


def _run_python(code: str, instance: str, extra_env=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["BOT_INSTANCE"] = instance
    env["PYTHONPATH"] = str(ROOT)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )


# ---------------------------------------------------------------------------
class SettingsAndPathsTests(unittest.TestCase):
    """Requirement 1 — settings structure and B2 paths."""

    def test_describe_reports_bot2_and_private_paths(self):
        info = runtime_paths.describe()
        self.assertEqual(info["instance"], os.environ["BOT_INSTANCE"])
        self.assertTrue(info["data_dir"])
        for key in ("config_dir", "log_dir", "db_dir", "project_root"):
            self.assertIn(key, info)

    def test_all_runtime_directories_live_under_the_data_dir(self):
        data_dir = Path(runtime_paths.DATA_DIR)
        for directory in (runtime_paths.CONFIG_DIR, runtime_paths.LOG_DIR,
                          runtime_paths.DB_DIR, runtime_paths.BACKUP_DIR,
                          runtime_paths.ARCHIVE_DIR):
            self.assertTrue(
                str(directory).startswith(str(data_dir)),
                f"{directory} escapes {data_dir}")
        self.assertTrue(runtime_paths.USING_PRIVATE_DATA_DIR,
                        "B2 must never use the in-tree runtime directory")

    def test_env_override_is_honoured(self):
        result = _run_python("""
            from modules import runtime_paths
            print(runtime_paths.DATA_DIR)
        """, "bot2", {"SOROUSH_BOT_DATA_DIR_BOT2": "/tmp/b2-explicit-override"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/tmp/b2-explicit-override")

    def test_marker_file_is_bot2(self):
        self.assertEqual(instance_guard.read_marker(), "bot2")


# ---------------------------------------------------------------------------
class InstanceIndependenceTests(unittest.TestCase):
    """Requirement 2 — B1, B2 and B3 must not share a single path."""

    def test_each_instance_resolves_to_its_own_data_dir(self):
        code = "from modules import runtime_paths; print(runtime_paths.DATA_DIR)"
        dirs = {}
        for instance in ("main", "bot2", "bot3"):
            result = _run_python(code, instance)
            self.assertEqual(result.returncode, 0, result.stderr)
            dirs[instance] = result.stdout.strip()
        self.assertEqual(len(set(dirs.values())), 3, f"paths collide: {dirs}")
        self.assertTrue(dirs["bot2"].endswith("soroush-bot-bot2"), dirs)
        self.assertTrue(dirs["bot3"].endswith("soroush-bot-bot3"), dirs)

    def test_writing_in_one_instance_never_appears_in_another(self):
        code = """
            import os, json
            from pathlib import Path
            from modules.runtime_paths import CONFIG_DIR, ensure_layout
            ensure_layout()
            name = os.environ["BOT_INSTANCE"]
            (CONFIG_DIR / "isolation_probe.json").write_text(
                json.dumps({"instance": name}), encoding="utf-8")
            print(CONFIG_DIR)
        """
        written = {}
        for instance in ("bot2", "bot3"):
            result = _run_python(code, instance)
            self.assertEqual(result.returncode, 0, result.stderr)
            written[instance] = Path(result.stdout.strip())
        self.assertNotEqual(written["bot2"], written["bot3"])
        payload = json.loads(
            (written["bot2"] / "isolation_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["instance"], "bot2")
        payload = json.loads(
            (written["bot3"] / "isolation_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["instance"], "bot3")
        for directory in written.values():
            (directory / "isolation_probe.json").unlink(missing_ok=True)

    def test_generic_data_dir_override_cannot_hijack_bot2(self):
        result = _run_python(
            "from modules import runtime_paths; print(runtime_paths.DATA_DIR)",
            "bot2",
            {"SOROUSH_BOT_DATA_DIR": str(Path.home() / ".local/share/soroush-bot")},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("soroush-bot-bot2"),
                        result.stdout)

    def test_data_dir_of_another_instance_is_rejected(self):
        with self.assertRaises(instance_guard.InstanceConflict):
            instance_guard.assert_data_dir_is_own(
                "bot2", str(Path.home() / ".local/share/soroush-bot"))
        instance_guard.assert_data_dir_is_own(
            "bot2", str(Path.home() / ".local/share/soroush-bot-bot2"))
        # An operator-chosen custom directory is never second-guessed.
        instance_guard.assert_data_dir_is_own("bot2", "/srv/custom-b2-data")


# ---------------------------------------------------------------------------
class InstanceGuardTests(unittest.TestCase):
    """Requirement 11 (part 1) — a wrong clone must not start."""

    def setUp(self):
        self._tmp = Path(self._temp_name())
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._patch = mock.patch.object(instance_guard, "PROJECT_ROOT", self._tmp)
        self._patch.start()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("BOT_INSTANCE", None)
        os.environ.pop("BOT_INSTANCE_BOOTSTRAP", None)

    def _temp_name(self):
        import tempfile
        return tempfile.mkdtemp(prefix="b2-guard-")

    def tearDown(self):
        self._env.stop()
        self._patch.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_marker_blocks_bot2_launcher(self):
        with self.assertRaises(instance_guard.InstanceConflict) as ctx:
            instance_guard.resolve("bot2.py", instance="bot2")
        self.assertIn("marker", str(ctx.exception))
        self.assertFalse(instance_guard.marker_path().exists(),
                         "a refused launch must not stamp the clone")

    def test_marker_of_another_instance_blocks_launch(self):
        instance_guard.write_marker("main")
        with self.assertRaises(instance_guard.InstanceConflict):
            instance_guard.resolve("bot2.py", instance="bot2")

    def test_matching_marker_is_accepted(self):
        instance_guard.write_marker("bot2")
        self.assertEqual(
            instance_guard.resolve("bot2.py", instance="bot2"), "bot2")

    def test_env_contradiction_is_refused(self):
        instance_guard.write_marker("bot2")
        os.environ["BOT_INSTANCE"] = "bot3"
        with self.assertRaises(instance_guard.InstanceConflict):
            instance_guard.resolve("main.py")
        os.environ.pop("BOT_INSTANCE")

    def test_bootstrap_stamps_once_and_never_overwrites(self):
        self.assertTrue(
            instance_guard.write_marker("bot2"))
        with self.assertRaises(instance_guard.InstanceConflict):
            instance_guard.write_marker("bot3")
        self.assertEqual(instance_guard.read_marker(), "bot2")

    def test_plain_main_clone_still_works_without_marker(self):
        self.assertEqual(instance_guard.resolve("main.py"), "main")
        self.assertEqual(instance_guard.read_marker(), None)


# ---------------------------------------------------------------------------
class OwnerAndAdminTests(unittest.TestCase):
    """Requirement 3 — owner and admin detection stays correct."""

    def test_normalize_username_is_case_and_at_insensitive(self):
        from modules import owner_check
        self.assertEqual(owner_check.normalize_username("@OsIne2"), "osine2")
        self.assertEqual(owner_check.normalize_username("  OSINE2 "), "osine2")
        self.assertIsNone(owner_check.normalize_username(None))
        self.assertIsNone(owner_check.normalize_username("  @ "))

    def test_owner_is_read_from_the_deployment_file(self):
        from modules import owner_check
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            owner_file = Path(temp) / "owner.json"
            owner_file.write_text(
                json.dumps({"user_id": 4242, "username": "@TheOwner"}),
                encoding="utf-8")
            with mock.patch.object(owner_check, "DEPLOYMENT_FILE", owner_file), \
                 mock.patch.object(owner_check, "RUNTIME_FILE",
                                   Path(temp) / "runtime_owner.json"), \
                 mock.patch.object(owner_check, "_CACHE_SIGNATURE", None), \
                 mock.patch.object(owner_check, "_CACHE_OWNER", None):
                owner = owner_check.get_owner()
        self.assertIsNotNone(owner)
        self.assertEqual(owner["user_id"], 4242)
        self.assertEqual(owner["username"], "theowner")

    def test_missing_owner_file_fails_closed(self):
        """بدون فایل مالک، هیچ‌کس مالک شناخته نمی‌شود (fail closed)."""
        from modules import owner_check
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(owner_check, "DEPLOYMENT_FILE",
                                   Path(temp) / "missing.json"), \
                 mock.patch.object(owner_check, "RUNTIME_FILE",
                                   Path(temp) / "runtime_owner.json"), \
                 mock.patch.object(owner_check, "_CACHE_SIGNATURE", None), \
                 mock.patch.object(owner_check, "_CACHE_OWNER", None):
                owner = owner_check.get_owner()
                for candidate in (111, 222, 0, None, "111"):
                    self.assertFalse(owner_check.is_global_owner(candidate))
                self.assertFalse(owner_check.owner_configured())
        self.assertIsNone(owner.get("user_id"))
        self.assertIsNone(owner.get("username"))

    def test_stale_runtime_owner_never_becomes_authority(self):
        from modules import owner_check
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            runtime_file = Path(temp) / "runtime_owner.json"
            runtime_file.write_text(
                json.dumps({"user_id": 999, "username": "stale"}),
                encoding="utf-8")
            with mock.patch.object(owner_check, "DEPLOYMENT_FILE",
                                   Path(temp) / "missing.json"), \
                 mock.patch.object(owner_check, "RUNTIME_FILE", runtime_file), \
                 mock.patch.object(owner_check, "_CACHE_SIGNATURE", None), \
                 mock.patch.object(owner_check, "_CACHE_OWNER", None):
                self.assertFalse(owner_check.is_global_owner(999))

    def test_missing_owner_is_announced_once(self):
        from modules import owner_check
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(owner_check, "DEPLOYMENT_FILE",
                                   Path(temp) / "missing.json"), \
                 mock.patch.object(owner_check, "RUNTIME_FILE",
                                   Path(temp) / "runtime_owner.json"), \
                 mock.patch.object(owner_check, "_CACHE_SIGNATURE", None), \
                 mock.patch.object(owner_check, "_CACHE_OWNER", None), \
                 mock.patch.object(owner_check, "_OWNER_MISSING_WARNED", False):
                self.assertTrue(owner_check.warn_if_owner_missing())
                self.assertTrue(owner_check.warn_if_owner_missing())

    def test_admin_recognition_and_rejection(self):
        from modules import admin_storage
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "admins.json"
            with mock.patch.object(admin_storage, "FILE", store), \
                 mock.patch.object(admin_storage, "_cache", None), \
                 mock.patch.object(admin_storage, "_cache_mtime", None):
                admin_storage.add_admin("group-1", 1001, "ali")
                self.assertTrue(admin_storage.is_admin("group-1", 1001))
                self.assertFalse(admin_storage.is_admin("group-1", 2002))
                self.assertFalse(admin_storage.is_admin("group-2", 1001))
                admin_storage.remove_admin("group-1", 1001)
                self.assertFalse(admin_storage.is_admin("group-1", 1001))

    def test_legacy_username_admin_entries_still_work(self):
        from modules import admin_storage
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "admins.json"
            store.write_text(json.dumps({"group-1": ["LegacyAli"]}),
                             encoding="utf-8")
            with mock.patch.object(admin_storage, "FILE", store), \
                 mock.patch.object(admin_storage, "_cache", None), \
                 mock.patch.object(admin_storage, "_cache_mtime", None):
                self.assertTrue(
                    admin_storage.is_admin("group-1", 999, "@legacyali"))
                self.assertFalse(
                    admin_storage.is_admin("group-1", 999, "someone-else"))

    def test_owner_check_never_reads_another_instances_runtime_file(self):
        from modules import owner_check
        self.assertEqual(Path(owner_check.RUNTIME_FILE).parent,
                         Path(runtime_paths.CONFIG_DIR))


# ---------------------------------------------------------------------------
class SessionTests(unittest.TestCase):
    """Requirement 4 — missing/invalid session, with no value disclosure."""

    def test_missing_session_raises_clear_error(self):
        with self.assertRaises(session_resolver.SessionMissing) as ctx:
            session_resolver.resolve("bot2", environ={})
        message = str(ctx.exception)
        self.assertIn("SESSION ERROR", message)
        self.assertIn("SOROUSH_SESSION_STRING_BOT2", message)
        for placeholder in ("None", "null", "Default"):
            self.assertNotIn(placeholder, message)

    def test_placeholder_values_are_rejected_not_used(self):
        for placeholder in ("DISABLED", "none", "changeme"):
            with self.assertRaises(session_resolver.SessionMissing):
                session_resolver.resolve(
                    "bot2", environ={"SOROUSH_SESSION_STRING": placeholder})

    def test_instance_specific_key_wins(self):
        info = session_resolver.resolve("bot2", environ={
            "SOROUSH_SESSION_STRING_BOT2": FAKE_SESSION,
            "SOROUSH_SESSION_STRING": "B" * 120,
        })
        self.assertEqual(info.value, FAKE_SESSION)
        self.assertEqual(info.source, "SOROUSH_SESSION_STRING_BOT2")
        self.assertTrue(info.strict_ok)
        self.assertIsNone(info.announcement())

    def test_generic_key_is_used_but_announced(self):
        info = session_resolver.resolve("bot2",
                                        environ={"SOROUSH_SESSION_STRING": FAKE_SESSION})
        self.assertEqual(info.value, FAKE_SESSION)
        self.assertFalse(info.strict_ok)
        announcement = info.announcement()
        self.assertIsNotNone(announcement)
        self.assertNotIn(FAKE_SESSION, announcement)
        self.assertIn("SOROUSH_SESSION_STRING_BOT2", announcement)

    def test_strict_mode_forbids_the_generic_fallback(self):
        with self.assertRaises(session_resolver.SessionMissing):
            session_resolver.resolve("bot2", environ={
                "SOROUSH_SESSION_STRING": FAKE_SESSION,
                "BOT_SESSION_STRICT": "1",
            })

    def test_error_message_never_contains_the_value(self):
        with self.assertRaises(session_resolver.SessionMissing) as ctx:
            session_resolver.resolve("bot2",
                                     environ={"SOROUSH_SESSION_STRING": "short"})
        self.assertNotIn("short", str(ctx.exception))

    def test_describe_is_masked_but_identifying(self):
        info = session_resolver.resolve(
            "bot2", environ={"SOROUSH_SESSION_STRING_BOT2": FAKE_SESSION})
        text = info.describe()
        self.assertNotIn(FAKE_SESSION, text)
        self.assertIn(secret_guard.fingerprint(FAKE_SESSION), text)


# ---------------------------------------------------------------------------
class SecretRedactionTests(unittest.TestCase):
    """Requirement 5 — secrets never reach a log, an error or a report."""

    def setUp(self):
        secret_guard.register(FAKE_SESSION, "SOROUSH_SESSION_STRING_BOT2")

    def test_registered_value_is_masked(self):
        masked = secret_guard.mask(f"session={FAKE_SESSION} done")
        self.assertNotIn(FAKE_SESSION, masked)
        self.assertIn("<redacted:SOROUSH_SESSION_STRING_BOT2>", masked)

    def test_unknown_long_token_is_still_masked(self):
        unknown = "Z" * 90 + "="
        self.assertNotIn(unknown, secret_guard.mask(f"value {unknown} end"))

    def test_github_and_bot_tokens_are_masked(self):
        text = ("token=ghp_" + "a" * 30 +
                " bot=123456789:" + "b" * 30)
        masked = secret_guard.mask(text)
        # Never embed a token-shaped literal in a test file: the pre-push
        # scanner would (correctly) refuse to let it be committed.
        self.assertNotIn("ghp_" + "a" * 30, masked)
        self.assertNotIn("123456789:", masked)

    def test_env_dotenv_and_env_mapping_registration(self):
        self.assertGreaterEqual(
            secret_guard.register_from_env(
                {"SOROUSH_SESSION_STRING_BOT2": FAKE_SESSION, "PATH": "/bin"}),
            1)
        self.assertNotIn(FAKE_SESSION, secret_guard.mask(FAKE_SESSION))

    def test_redacting_filter_scrubs_record_arguments(self):
        import logging
        record = logging.LogRecord("x", logging.INFO, __file__, 1,
                                   "session %s", (FAKE_SESSION,), None)
        self.assertTrue(secret_guard.RedactingFilter().filter(record))
        self.assertNotIn(FAKE_SESSION, record.getMessage())

    def test_traceback_text_is_scrubbed(self):
        import logging
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom",
                                   (), None)
        record.exc_text = f"ValueError: bad session {FAKE_SESSION}"
        secret_guard.RedactingFilter().filter(record)
        self.assertNotIn(FAKE_SESSION, record.exc_text)

    def test_health_tool_reports_secret_leaks_without_disclosing(self):
        import tempfile
        from tools import log_health
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "bot.log").write_text(
                f"2026-01-01 INFO SESSION SOURCE {FAKE_SESSION}\n",
                encoding="utf-8")
            hits = log_health._scan_for_secrets(directory)
        self.assertTrue(hits)
        self.assertNotIn(FAKE_SESSION, json.dumps(hits))


# ---------------------------------------------------------------------------
class LoggingTests(unittest.TestCase):
    """Requirements 6 and 7 — no duplicates, bounded files, short terminal."""

    def setUp(self):
        import logging
        # 🐛 Several legacy test modules call ``logging.disable(CRITICAL)`` at
        # import time, which switches logging off *globally* for the whole
        # pytest worker process.  That made these assertions fail only in a
        # full-suite run.  Save the level, re-enable logging for this test, and
        # put the previous value back afterwards so no other module is affected.
        self._previous_disable = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self._temp = __import__("tempfile").TemporaryDirectory()
        self.log_dir = Path(self._temp.name) / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._patch = mock.patch.object(runtime_paths, "LOG_DIR", self.log_dir)
        self._patch.start()
        self._runtime = logger_module._RUNTIME
        logger_module._RUNTIME = None
        for name in ("SoroushAntiSpam", "SoroushAntiSpam.deleted",
                     "SoroushAntiSpam.actions"):
            logging.getLogger(name).handlers.clear()

    def tearDown(self):
        import logging
        runtime = logger_module._RUNTIME
        if runtime is not None:
            runtime.stop()
        logger_module._RUNTIME = self._runtime
        self._patch.stop()
        self._temp.cleanup()
        logging.disable(self._previous_disable)

    def _flush(self) -> None:
        """Block until the logging listeners have handled every queued record.

        ``QueueListener`` calls ``task_done()`` after each record, so ``join()``
        is an exact synchronisation point — no sleeping, no flakiness under
        parallel test execution.
        """
        runtime = logger_module._RUNTIME
        if runtime is None:
            return
        for work_queue in (runtime.queue, runtime.deleted_queue):
            try:
                work_queue.join()
            except Exception:
                pass

    def _wait_for(self, path: Path, needle: str, timeout: float = 20.0) -> str:
        self._flush()
        deadline = time.time() + timeout
        text = ""
        while time.time() < deadline:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                if needle in text:
                    return text
            time.sleep(0.05)
        return text

    def test_one_logger_facade_does_not_duplicate_handlers(self):
        import logging
        first = logger_module.BotLogger()
        second = logger_module.BotLogger()
        handler = logging.getLogger("SoroushAntiSpam").handlers
        self.assertEqual(len(handler), 1, f"duplicate handlers: {handler}")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

    def test_a_single_event_is_logged_once(self):
        logger = logger_module.BotLogger()
        logger.log_info("BOT INSTANCE probe-single-line")
        path = self.log_dir / "bot.log"
        text = self._wait_for(path, "probe-single-line")
        self.assertEqual(text.count("probe-single-line"), 1, text)

    def test_hot_path_noise_is_suppressed_in_production(self):
        logger = logger_module.BotLogger()
        logger.log_info("HANDLER CALLED noisy marker")
        logger.log_info("BOT INSTANCE kept marker")
        path = self.log_dir / "bot.log"
        text = self._wait_for(path, "kept marker")
        self.assertNotIn("noisy marker", text)
        self.assertIn("kept marker", text)

    def test_rotation_settings_are_bounded(self):
        logger_module.BotLogger()
        handler = next(
            h for h in logger_module._RUNTIME.listener.handlers
            if hasattr(h, "maxBytes"))
        self.assertLessEqual(handler.maxBytes, 20 * 1024 * 1024)
        self.assertGreaterEqual(handler.backupCount, 1)
        self.assertLessEqual(handler.backupCount, 20)

    def test_rotation_actually_caps_the_file(self):
        from logging.handlers import RotatingFileHandler
        with mock.patch.object(logger_module, "_MAX_LOG_BYTES", 1024), \
             mock.patch.object(logger_module, "_LOG_BACKUPS", 2):
            path = self.log_dir / "rotation-probe.log"
            handler = logger_module._make_handler(
                path, __import__("logging").Formatter("%(message)s"))
            self.assertIsInstance(handler, RotatingFileHandler)
            self.assertEqual(handler.maxBytes, 1024)
            for index in range(200):
                handler.emit(__import__("logging").LogRecord(
                    "x", __import__("logging").INFO, __file__, 1,
                    "filler line %d %s" % (index, "x" * 40), (), None))
            handler.close()
        main = path.stat().st_size if path.exists() else 0
        self.assertLess(main, 1024 * 4, "log grew without rotation")

    def test_retention_sweep_removes_only_old_rotated_files(self):
        old = self.log_dir / "bot.log.2020-01-01_01"
        fresh = self.log_dir / "bot.log.2030-01-01_01"
        active = self.log_dir / "bot.log"
        for path in (old, fresh, active):
            path.write_text("x", encoding="utf-8")
        ancient = time.time() - 40 * 86400
        os.utime(old, (ancient, ancient))
        removed = logger_module.purge_old_logs(self.log_dir, older_than_days=7)
        self.assertIn(str(old), removed)
        self.assertTrue(fresh.exists())
        self.assertTrue(active.exists(), "the active log must never be deleted")

    def test_deleted_messages_audit_is_a_separate_bounded_file(self):
        logger = logger_module.BotLogger()
        logger.log_deleted_message(7, "ali", 99, "g", "text", "spam")
        path = self.log_dir / "deleted_messages.log"
        text = self._wait_for(path, "spam")
        self.assertIn('"reason":"spam"', text)

    def test_disabled_retention_keeps_everything(self):
        old = self.log_dir / "bot.log.2020-01-01_01"
        old.write_text("x", encoding="utf-8")
        ancient = time.time() - 400 * 86400
        os.utime(old, (ancient, ancient))
        self.assertEqual(
            logger_module.purge_old_logs(self.log_dir, older_than_days=0), [])
        self.assertTrue(old.exists())

    def test_health_report_is_read_only_and_structured(self):
        logger_module.BotLogger()
        report = logger_module.health()
        self.assertEqual(report["instance"], os.environ["BOT_INSTANCE"])
        self.assertIn("problems", report)
        self.assertIn("files", report)
        self.assertIn("loggers", report)

    def test_console_level_defaults_to_warning(self):
        self.assertGreaterEqual(logger_module._CONSOLE_LEVEL,
                                __import__("logging").WARNING)

    def test_lifecycle_lines_still_reach_the_console(self):
        import logging
        self.assertTrue(
            logger_module._ConsoleFilter().filter(
                logging.LogRecord("x", logging.INFO, __file__, 1,
                                  "BOT INSTANCE started", (), None)))
        self.assertFalse(
            logger_module._ConsoleFilter().filter(
                logging.LogRecord("x", logging.INFO, __file__, 1,
                                  "HANDLER CALLED something", (), None)))
        self.assertTrue(
            logger_module._ConsoleFilter().filter(
                logging.LogRecord("x", logging.ERROR, __file__, 1,
                                  "anything at all", (), None)))

    def test_log_policy_verbose_switch_restores_noise(self):
        with mock.patch.object(log_policy, "VERBOSE", True):
            self.assertFalse(log_policy.is_noisy("HANDLER CALLED x"))
        with mock.patch.object(log_policy, "VERBOSE", False):
            self.assertTrue(log_policy.is_noisy("HANDLER CALLED x"))


# ---------------------------------------------------------------------------
class BackupRestoreTests(unittest.TestCase):
    """Requirements 8, 9 and 10 — backup, integrity, trial restore."""

    def setUp(self):
        from tools import b2_backup
        self.backup = b2_backup
        self._temp = __import__("tempfile").TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.data = self.root / "data"
        self.out = self.root / "backups"
        for name in ("config", "db", "logs", "archive"):
            (self.data / name).mkdir(parents=True, exist_ok=True)
        (self.data / "config" / "groups.json").write_text(
            json.dumps({"22770700": {"title": "g"}}), encoding="utf-8")
        (self.data / "config" / "admins.json").write_text(
            json.dumps({"22770700": [1001]}), encoding="utf-8")
        import sqlite3
        with sqlite3.connect(self.data / "db" / "bot.sqlite3") as connection:
            connection.execute("CREATE TABLE probe (value TEXT)")
            connection.execute("INSERT INTO probe VALUES ('keep-me')")
        self.patches = [
            mock.patch.object(self.backup, "DATA_DIR", self.data),
            mock.patch.object(self.backup, "CONFIG_DIR", self.data / "config"),
            mock.patch.object(self.backup, "DB_DIR", self.data / "db"),
            mock.patch.object(self.backup, "ARCHIVE_DIR", self.data / "archive"),
            mock.patch.object(self.backup, "BACKUP_DIR", self.out),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self._temp.cleanup()

    def test_backup_creates_verified_named_archive_with_hash(self):
        report = self.backup.create_backup(self.out, keep=3)
        archive = Path(report["archive"])
        self.assertTrue(archive.is_file())
        self.assertIn("B2-backup", archive.name)
        self.assertIn("bot2", archive.name)
        self.assertRegex(archive.name, r"\d{8}-\d{6}")
        self.assertEqual(len(report["sha256"]), 64)
        sidecar = archive.with_suffix(archive.suffix + ".sha256")
        self.assertTrue(sidecar.exists())
        self.assertIn(report["sha256"], sidecar.read_text(encoding="utf-8"))
        self.assertTrue(report["verify"]["ok"], report["verify"])
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_archive_contains_source_data_and_session(self):
        report = self.backup.create_backup(self.out)
        with tarfile.open(report["archive"], "r:gz") as tar:
            names = tar.getnames()
        self.assertTrue(any(n.endswith("MANIFEST.json") for n in names))
        self.assertTrue(any(n.endswith("RESTORE.txt") for n in names))
        self.assertIn(".env", names)
        self.assertTrue(any(n.startswith("data/config/") for n in names))
        self.assertTrue(any(n.endswith("bot.sqlite3") for n in names))
        self.assertTrue(any(n.startswith("source/") for n in names))
        self.assertFalse(any("/.git/" in n for n in names))
        self.assertFalse(any(n.endswith(".log") for n in names),
                         "logs must not bloat a backup")

    def test_sqlite_snapshot_survives_and_is_readable(self):
        import sqlite3
        report = self.backup.create_backup(self.out)
        with __import__("tempfile").TemporaryDirectory() as temp:
            with tarfile.open(report["archive"], "r:gz") as tar:
                member = next(m for m in tar.getmembers()
                              if m.name.endswith("bot.sqlite3"))
                tar.extract(member, path=temp)
            with sqlite3.connect(Path(temp) / member.name) as connection:
                rows = connection.execute("SELECT value FROM probe").fetchall()
        self.assertEqual(rows, [("keep-me",)])

    def test_corrupted_archive_fails_verification(self):
        report = self.backup.create_backup(self.out)
        archive = Path(report["archive"])
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        archive.write_bytes(bytes(data))
        result = self.backup.verify_archive(archive)
        self.assertFalse(result["ok"])
        self.assertTrue(result["problems"])

    def test_hash_mismatch_inside_archive_is_detected(self):
        report = self.backup.create_backup(self.out)
        archive = Path(report["archive"])
        with __import__("tempfile").TemporaryDirectory() as temp:
            tempdir = Path(temp)
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(tempdir)
            target = next(tempdir.rglob("admins.json"))
            target.write_text("{\"tampered\": true}", encoding="utf-8")
            rebuilt = self.out / "tampered.tar.gz"
            with tarfile.open(rebuilt, "w:gz") as tar:
                for item in sorted(tempdir.rglob("*")):
                    if item.is_file():
                        tar.add(item, arcname=str(item.relative_to(tempdir)))
            result = self.backup.verify_archive(rebuilt)
        self.assertFalse(result["ok"])
        self.assertTrue(any("hash mismatch" in p for p in result["problems"]))

    def test_restore_dry_run_lands_in_a_temporary_directory(self):
        report = self.backup.create_backup(self.out)
        before = (self.data / "config" / "groups.json").read_text(encoding="utf-8")
        result = self.backup.restore_archive(Path(report["archive"]), None,
                                             dry_run=True)
        self.assertTrue(result.get("ok"))
        self.assertIn("extracted_to", result)
        self.assertFalse(str(result["extracted_to"]).startswith(str(self.data)))
        self.assertEqual(
            (self.data / "config" / "groups.json").read_text(encoding="utf-8"),
            before, "a trial restore must not change real data")

    def test_restore_refuses_without_confirmation(self):
        report = self.backup.create_backup(self.out)
        result = self.backup.restore_archive(Path(report["archive"]), None)
        self.assertFalse(result.get("applied"))
        self.assertIn("--yes", result.get("error", ""))

    def test_restore_refuses_another_instances_archive(self):
        report = self.backup.create_backup(self.out)
        with mock.patch.object(instance_guard, "normalize",
                               side_effect=lambda value: str(value)):
            result = self.backup.restore_archive(
                Path(report["archive"]), self.root / "elsewhere",
                assume_yes=True, force_instance=False)
        self.assertIn("instance", json.dumps(result, ensure_ascii=False))

    def test_restore_applies_with_yes_and_takes_a_safety_backup(self):
        report = self.backup.create_backup(self.out)
        (self.data / "config" / "groups.json").write_text("{}", encoding="utf-8")
        target = self.root / "restored"
        target.mkdir()
        result = self.backup.restore_archive(
            Path(report["archive"]), target, assume_yes=True)
        self.assertTrue(result.get("applied"), result)
        self.assertGreaterEqual(result.get("restored_count", 0), 1)
        self.assertIn("safety_backup", result)

    def test_prune_keeps_newest_and_only_deletes_verified(self):
        reports = [self.backup.create_backup(self.out) for _ in range(5)]
        # make the unverified case: strip the sidecar of the oldest archive
        archives = [Path(r["archive"]) for r in reports]
        unverified = archives[0]
        unverified.with_suffix(unverified.suffix + ".sha256").unlink()
        removed = self.backup.prune_backups(self.out, keep=2)
        self.assertNotIn(str(unverified), removed)
        self.assertTrue(unverified.exists(),
                        "an archive without a valid hash must never be purged")
        remaining = self.backup.list_backups(self.out)
        self.assertGreaterEqual(len(remaining), 3)

    def test_unsafe_archive_paths_are_refused(self):
        bogus = self.root / "evil.tar.gz"
        payload = self.root / "payload.txt"
        payload.write_text("x", encoding="utf-8")
        with tarfile.open(bogus, "w:gz") as tar:
            tar.add(payload, arcname="../escaped.txt")
            manifest = self.root / "MANIFEST.json"
            manifest.write_text(json.dumps({"instance": "bot2",
                                            "files": []}), encoding="utf-8")
            tar.add(manifest, arcname="MANIFEST.json")
        result = self.backup.restore_archive(bogus, self.root / "out",
                                             assume_yes=True)
        self.assertIn("unsafe path", result.get("error", ""))


# ---------------------------------------------------------------------------
class ConcurrencyTests(unittest.TestCase):
    """Requirement 11 — two instances of B2 must not run at once."""

    def test_pid_lock_is_per_instance(self):
        code = """
            from pathlib import Path
            from modules.runtime_paths import runtime_config_file
            print(runtime_config_file("bot.pid", migrate=False))
        """
        paths = {}
        for instance in ("main", "bot2", "bot3"):
            result = _run_python(code, instance)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths[instance] = result.stdout.strip()
        self.assertEqual(len(set(paths.values())), 3, paths)

    _LOCK_SCRIPT = """
        import os, sys, time
        sys.path.insert(0, %r)
        os.environ["BOT_INSTANCE"] = "bot2"
        from modules import instance_guard
        instance_guard.resolve("main.py")
        import main
        lock = main._acquire_instance_lock()
        print("ACQUIRED", lock, flush=True)
        time.sleep(%d)
        main._release_instance_lock(lock, os.getpid())
    """

    def test_second_run_of_the_same_instance_exits(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(self._LOCK_SCRIPT
                                                   % (str(ROOT), 45))],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)
        try:
            self.assertIn("ACQUIRED", holder.stdout.readline())
            second = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(self._LOCK_SCRIPT
                                                       % (str(ROOT), 0))],
                cwd=str(ROOT), capture_output=True, text=True, timeout=180)
            self.assertNotEqual(second.returncode, 0,
                                "a second live instance must refuse to start")
            self.assertIn("ALREADY RUNNING", second.stdout + second.stderr)
            self.assertIn("bot2", second.stdout + second.stderr)
        finally:
            holder.terminate()
            try:
                holder.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover
                holder.kill()

    def test_lock_file_of_another_instance_is_ignored(self):
        from modules import runtime_paths
        result = _run_python(textwrap.dedent("""
            import os, sys
            sys.path.insert(0, %r)
            from pathlib import Path
            from modules.runtime_paths import runtime_config_file
            bot3_lock = Path(runtime_config_file("bot.pid", migrate=False))
            bot3_lock.parent.mkdir(parents=True, exist_ok=True)
            bot3_lock.write_text("1")   # pid 1 is always alive
            os.environ["BOT_INSTANCE"] = "bot2"
            import importlib, modules.runtime_paths as rp
            importlib.reload(rp)
            print(rp.runtime_config_file("bot.pid", migrate=False))
        """ % str(ROOT)), "bot2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("soroush-bot-bot3", result.stdout)


# ---------------------------------------------------------------------------
class RepositoryHygieneTests(unittest.TestCase):
    """Requirement 12 — the public repository must not contain secrets."""

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120)

    def test_no_env_file_is_tracked(self):
        tracked = self._git("ls-files").stdout.splitlines()
        offenders = [name for name in tracked
                     if name.startswith(".env") and name != ".env.example"]
        self.assertEqual(offenders, [],
                         f"secret files are tracked: {offenders}")

    def test_env_example_is_still_available(self):
        tracked = self._git("ls-files").stdout.splitlines()
        self.assertIn(".env.example", tracked)
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("SOROUSH_SESSION_STRING="):
                self.assertEqual(line.strip(), "SOROUSH_SESSION_STRING=")

    def test_no_tracked_file_contains_a_session_value(self):
        from tools import secret_scan
        findings = secret_scan.scan_repository(ROOT)
        offenders = sorted({item["file"] for item in findings})
        self.assertEqual(
            offenders, [],
            f"secret material found in tracked files: {offenders}")

    def test_scanner_ignores_code_and_placeholders(self):
        from tools import secret_scan
        self.assertIsNone(secret_scan.looks_like_session(
            "رشته_سشن_شما_اینجا"))
        self.assertIsNone(secret_scan.looks_like_session("session_string"))
        self.assertIsNone(secret_scan.looks_like_session(""))
        self.assertIsNotNone(secret_scan.looks_like_session(FAKE_SESSION))

    def test_instance_marker_is_tracked_for_this_repo(self):
        tracked = self._git("ls-files").stdout.splitlines()
        self.assertIn(".bot_instance", tracked)
        self.assertEqual((ROOT / ".bot_instance").read_text(
            encoding="utf-8").strip(), "bot2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
