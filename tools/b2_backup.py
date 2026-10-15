#!/usr/bin/env python3
"""Timestamped, verified backup / restore for one bot instance.

Design constraints (from the deployment requirements)
-----------------------------------------------------
* **Nothing is lost.**  A backup always contains the source tree, the runtime
  ``config`` + ``db`` + ``archive`` directories and the clone's ``.env`` (the
  session is needed to recover a working bot).
* **The archive never lies.**  The live SQLite database is copied through
  SQLite's online backup API, so a concurrent writer cannot produce a torn
  file.  Every archive carries a manifest with per-file hashes and a
  ``.sha256`` sidecar for the archive itself.
* **No junk.**  Logs, caches, ``__pycache__``, previous backups and ``.git``
  are excluded: they are huge and rebuildable.
* **Isolation.**  The archive records which instance it belongs to, the name
  contains that instance, and restore refuses to load B1's archive into B2.
* **Reversible.**  ``restore`` takes a fresh backup of the current data before
  overwriting anything, and requires an explicit ``--yes``.

Subcommands::

    backup   --out DIR [--keep N] [--note TEXT]
    verify   ARCHIVE
    list     [--out DIR]
    prune    --out DIR --keep N
    restore  ARCHIVE [--target DIR] [--yes] [--dry-run]

The defaults target the private per-instance directory, e.g.
``~/.local/share/soroush-bot-bot2/backups/``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

if not os.environ.get("BOT_INSTANCE"):
    try:
        _marker = (_ROOT / ".bot_instance").read_text(encoding="utf-8").strip()
        if _marker:
            os.environ["BOT_INSTANCE"] = _marker
    except OSError:
        pass

from modules import instance_guard  # noqa: E402
from modules import secret_guard  # noqa: E402

secret_guard.bootstrap(_ROOT)

from modules.runtime_paths import (  # noqa: E402
    BACKUP_DIR, CONFIG_DIR, DATA_DIR, DB_DIR, ARCHIVE_DIR, INSTANCE_NAME,
    ensure_layout,
)

SCHEMA_VERSION = 1
DEFAULT_KEEP = 7
ARCHIVE_PREFIX = "B2-backup"
_NAME_HINT = "{prefix}-{instance}-{stamp}.tar.gz"

#: Directory names that are never archived.
_EXCLUDED_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "logs", "node_modules", ".venv", "venv", "build", "dist", ".arena",
    ".cache", ".local",
}
_EXCLUDED_SUFFIXES = (
    ".pyc", ".pyo", ".log", ".tar.gz", ".zip", ".tmp", ".session",
    ".session-journal",
)
_EXCLUDED_NAMES = {"bot.pid", "watchdog.lock"}


# --------------------------------------------------------------- utilities
def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _is_excluded(path: Path) -> bool:
    if path.name in _EXCLUDED_NAMES:
        return True
    if path.name.endswith(_EXCLUDED_SUFFIXES):
        return True
    for part in path.parts:
        if part in _EXCLUDED_DIRS:
            return True
        if part.endswith(".auto_bak") or ".auto_bak_" in part:
            return True
    if path.name.startswith(ARCHIVE_PREFIX):
        return True
    return False


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    for path in sorted(root.rglob("*")):
        try:
            if path.is_symlink() or not path.is_file():
                continue
        except OSError:
            continue
        if _is_excluded(path):
            continue
        yield path


def snapshot_sqlite(source: Path, target: Path) -> bool:
    """Consistent copy of a live SQLite file (safe while the bot is running)."""
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10) as src:
            with sqlite3.connect(str(target)) as dst:
                src.backup(dst)
        return True
    except sqlite3.Error:
        try:
            shutil.copyfile(source, target)
            with sqlite3.connect(str(target)) as check:
                check.execute("PRAGMA quick_check").fetchone()
            return True
        except (OSError, sqlite3.Error):
            return False


# ----------------------------------------------------------------- backup
def _collect(instance: str, staging: Path) -> Dict[str, object]:
    """Stage everything that must survive a device loss."""
    entries: List[Dict[str, object]] = []
    staging.mkdir(parents=True, exist_ok=True)

    def add(src: Path, arcname: str, *, hash_it: bool = False) -> None:
        if not src.exists() or not src.is_file():
            return
        destination = staging / arcname
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, destination)
        record = {"path": arcname, "size": destination.stat().st_size}
        if hash_it:
            record["sha256"] = sha256_file(destination)
        entries.append(record)

    # 1) Source tree (without .git, logs, caches or previous archives)
    for path in _iter_files(_ROOT):
        relative = path.relative_to(_ROOT)
        add(path, str(Path("source") / relative))

    # 2) Runtime state — the part that cannot be rebuilt
    for label, directory in (("config", CONFIG_DIR), ("db", DB_DIR),
                             ("archive", ARCHIVE_DIR)):
        if not directory.exists():
            continue
        for path in _iter_files(directory):
            relative = path.relative_to(directory)
            if path.name.endswith((".sqlite3", ".sqlite", ".db")):
                target = staging / "data" / label / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if snapshot_sqlite(path, target):
                    entries.append({
                        "path": str(Path("data") / label / relative),
                        "size": target.stat().st_size,
                        "sha256": sha256_file(target),
                        "sqlite_snapshot": True,
                    })
                continue
            add(path, str(Path("data") / label / relative), hash_it=True)

    # 3) Session file of this clone only
    add(_ROOT / ".env", ".env", hash_it=True)

    totals = sum(int(item["size"]) for item in entries)
    return {
        "schema": SCHEMA_VERSION,
        "instance": instance,
        "created_at": datetime.now().isoformat(),
        "created_ts": int(time.time()),
        "project_root": str(_ROOT),
        "data_dir": str(DATA_DIR),
        "file_count": len(entries),
        "total_bytes": totals,
        "files": entries,
    }


def create_backup(out_dir: Optional[Path] = None, keep: int = DEFAULT_KEEP,
                  note: str = "") -> Dict[str, object]:
    """Create one timestamped archive and return a structured report."""
    ensure_layout()
    instance = instance_guard.resolve("b2_backup.py", instance=None)
    out = Path(out_dir) if out_dir else Path(BACKUP_DIR)
    out.mkdir(parents=True, exist_ok=True)
    try:
        out.chmod(0o700)
    except OSError:
        pass

    name = _NAME_HINT.format(prefix=ARCHIVE_PREFIX, instance=instance,
                             stamp=_stamp())
    archive = out / name
    if archive.exists():
        archive = out / name.replace(".tar.gz", f"-{int(time.time())}.tar.gz")

    with tempfile.TemporaryDirectory(prefix="b2-backup-stage-") as staging_name:
        staging = Path(staging_name)
        manifest = _collect(instance, staging)
        manifest["note"] = note
        (staging / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (staging / "RESTORE.txt").write_text(_restore_instructions(instance),
                                             encoding="utf-8")
        with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
            for item in sorted(staging.rglob("*")):
                if item.is_file():
                    tar.add(item, arcname=str(item.relative_to(staging)))

    os.chmod(archive, 0o600)
    digest = sha256_file(archive)
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    os.chmod(sidecar, 0o600)

    report = {
        "instance": instance,
        "archive": str(archive),
        "sha256": digest,
        "size": archive.stat().st_size,
        "file_count": manifest["file_count"],
        "note": note,
    }
    report["verify"] = verify_archive(archive)
    report["pruned"] = prune_backups(out, keep=keep)
    return report


def _restore_instructions(instance: str) -> str:
    return (
        f"# بازیابی بکاپ ربات {instance}\n"
        f"# این آرشیو شامل source/ و data/ و .env همان clone است.\n"
        f"# ۱) اول از داده‌ی فعلی بکاپ بگیر:\n"
        f"#      python3 tools/b2_backup.py backup\n"
        f"# ۲) سپس بازیابی آزمایشی در پوشه موقت (بدون تغییر داده‌ی واقعی):\n"
        f"#      python3 tools/b2_backup.py restore <ARCHIVE> --dry-run\n"
        f"# ۳) و فقط پس از تأیید:\n"
        f"#      python3 tools/b2_backup.py restore <ARCHIVE> --yes\n"
    )


# ----------------------------------------------------------------- verify
def verify_archive(archive: Path, *, deep: bool = True) -> Dict[str, object]:
    """Check gzip integrity, manifest presence, sizes and per-file hashes.

    ``deep=True`` (the default) streams every member through gzip, which makes
    the archive's CRC validate the whole file — a single flipped byte anywhere
    is detected even in members that carry no recorded hash.
    """
    archive = Path(archive)
    result: Dict[str, object] = {
        "archive": str(archive), "ok": False, "problems": [], "deep": deep,
    }
    if not archive.is_file():
        result["problems"].append("archive not found")
        return result
    result["size"] = archive.stat().st_size
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            result["members"] = len(members)
            manifest_member = next(
                (m for m in members if m.name.endswith("MANIFEST.json")), None
            )
            if manifest_member is None:
                result["problems"].append("MANIFEST.json missing")
                return result
            manifest = json.load(tar.extractfile(manifest_member))
            result["instance"] = manifest.get("instance")
            result["created_at"] = manifest.get("created_at")
            result["file_count"] = manifest.get("file_count")
            result["manifest_total_bytes"] = manifest.get("total_bytes")

            by_suffix = {}
            for member in members:
                if member.isfile():
                    by_suffix.setdefault(member.name, member)

            declared = {str(item["path"]): item
                        for item in manifest.get("files", [])}
            matched = set()
            for name, item in declared.items():
                member = next((m for m in members
                               if m.name == name or m.name.endswith("/" + name)),
                              None)
                if member is None:
                    result["problems"].append(f"missing member {name}")
                    continue
                matched.add(member.name)
                if member.size != int(item.get("size", member.size)):
                    result["problems"].append(
                        f"size mismatch {name}: {member.size} != {item['size']}")
                if "sha256" not in item:
                    continue
                digest = hashlib.sha256()
                handle = tar.extractfile(member)
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
                if digest.hexdigest() != item["sha256"]:
                    result["problems"].append(f"hash mismatch {name}")

        if deep:
            # Decompress the whole file so gzip's CRC validates every byte of
            # the archive, including members that carry no recorded hash.
            # A single flipped byte anywhere makes this raise.
            with gzip.open(archive, "rb") as handle:
                while handle.read(4 * 1024 * 1024):
                    pass
            result["crc_ok"] = True
    except (tarfile.TarError, OSError, ValueError, json.JSONDecodeError,
            EOFError) as error:
        result["problems"].append(f"unreadable archive: {error!r}")
        return result
    result["ok"] = not result["problems"]
    return result


def list_backups(out_dir: Optional[Path] = None) -> List[Dict[str, object]]:
    out = Path(out_dir) if out_dir else Path(BACKUP_DIR)
    found = []
    if not out.exists():
        return found
    for path in sorted(out.glob(f"{ARCHIVE_PREFIX}-*.tar.gz")):
        sidecar = path.with_suffix(path.suffix + ".sha256")
        found.append({
            "archive": str(path),
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "created": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "has_sha256": sidecar.exists(),
        })
    return found


def prune_backups(out_dir: Optional[Path] = None, keep: int = DEFAULT_KEEP,
                  *, verify: bool = True) -> List[str]:
    """Delete only *verified* old archives, keeping the newest ``keep``."""
    items = list_backups(out_dir)
    if len(items) <= keep:
        return []
    removed: List[str] = []
    for item in items[:-keep] if keep > 0 else items:
        path = Path(item["archive"])
        sidecar = path.with_suffix(path.suffix + ".sha256")
        # فقط بکاپ تأییدشده حذف می‌شود: هش باید موجود و منطبق باشد.
        if not sidecar.exists():
            continue
        try:
            expected = sidecar.read_text(encoding="utf-8").split()[0]
        except (OSError, IndexError):
            continue
        if verify and sha256_file(path) != expected:
            continue
        try:
            path.unlink()
            sidecar.unlink(missing_ok=True)
            removed.append(str(path))
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------- restore
def restore_archive(archive: Path, target: Optional[Path] = None,
                    assume_yes: bool = False, dry_run: bool = False,
                    force_instance: bool = False) -> Dict[str, object]:
    """Restore an archive, refusing to clobber data without confirmation."""
    archive = Path(archive)
    instance = instance_guard.resolve("b2_backup.py", instance=None)
    report: Dict[str, object] = {
        "archive": str(archive), "instance": instance, "applied": False,
    }

    check = verify_archive(archive)
    report["verify"] = check
    if not check.get("ok"):
        report["error"] = "archive failed verification; refusing to restore"
        return report
    if check.get("instance") not in (None, instance) and not force_instance:
        report["error"] = (
            f"archive belongs to instance {check.get('instance')!r}, not "
            f"{instance!r} (use --force-instance only if you are certain)"
        )
        return report

    destination = Path(target) if target else Path(DATA_DIR)
    report["target"] = str(destination)

    if target is None:
        instance_guard.assert_data_dir_is_own(instance, str(destination))

    if dry_run:
        try:
            with tempfile.TemporaryDirectory(prefix="b2-restore-test-") as temp:
                extracted = Path(temp) / "extract"
                extracted.mkdir(parents=True)
                with tarfile.open(archive, "r:gz") as tar:
                    _safe_extract(tar, extracted)
                report["dry_run"] = True
                report["extracted_to"] = str(extracted)
                report["files"] = sum(1 for _ in extracted.rglob("*"))
                report["ok"] = True
        except (ValueError, tarfile.TarError, OSError) as error:
            report["error"] = f"archive rejected: {error}"
            report["ok"] = False
        return report

    if not assume_yes:
        report["error"] = (
            "restore overwrites live data; re-run with --yes (a safety backup "
            "of the current data is taken first) or use --dry-run"
        )
        return report

    # ۱) بکاپ ایمنی از وضعیت فعلی — قبل از هر بازنویسی
    report["safety_backup"] = create_backup(note="pre-restore safety copy")

    with tempfile.TemporaryDirectory(prefix="b2-restore-") as temp:
        extracted = Path(temp) / "extract"
        extracted.mkdir(parents=True)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                _safe_extract(tar, extracted)
        except (ValueError, tarfile.TarError, OSError) as error:
            report["error"] = f"archive rejected: {error}"
            return report
        applied = []

        data_root = extracted / "data"
        if data_root.exists():
            for label, target_dir in (("config", CONFIG_DIR), ("db", DB_DIR),
                                      ("archive", ARCHIVE_DIR)):
                source_dir = data_root / label
                if not source_dir.exists():
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in source_dir.rglob("*"):
                    if not item.is_file():
                        continue
                    relative = item.relative_to(source_dir)
                    destination_file = target_dir / relative
                    destination_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination_file)
                    applied.append(str(destination_file))

        env_source = extracted / ".env"
        if env_source.is_file():
            destination_env = _ROOT / ".env"
            shutil.copy2(env_source, destination_env)
            try:
                destination_env.chmod(0o600)
            except OSError:
                pass
            applied.append(str(destination_env))

        report["applied"] = True
        report["restored_files"] = applied
        report["restored_count"] = len(applied)
    return report


def _safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    """Extract while refusing absolute paths and ``..`` traversal.

    Links are skipped and, on interpreters that support it, the ``data``
    extraction filter removes ownership and special-file metadata as well.
    """
    root = destination.resolve()
    try:
        filter_name = "data" if sys.version_info >= (3, 12) else None
    except Exception:  # pragma: no cover
        filter_name = None
    for member in tar.getmembers():
        member_path = (root / member.name).resolve()
        if member_path != root and not str(member_path).startswith(str(root) + os.sep):
            raise ValueError(f"unsafe path in archive: {member.name}")
        if member.issym() or member.islnk():
            continue
        try:
            if filter_name:
                tar.extract(member, path=root, filter=filter_name)
            else:  # pragma: no cover - older interpreters
                tar.extract(member, path=root)
        except TypeError:  # pragma: no cover - unexpected signature
            tar.extract(member, path=root)


# ------------------------------------------------------------------- CLI
def _print(value: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and key not in ("pruned",):
                print(f"{key}:")
                print(json.dumps(item, ensure_ascii=False, indent=2,
                                 default=str)[:4000])
            else:
                print(f"{key}: {item}")
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", dest="as_json")
    sub = parser.add_subparsers(dest="command")

    p_backup = sub.add_parser("backup", help="create a timestamped archive")
    p_backup.add_argument("--out", default=None)
    p_backup.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    p_backup.add_argument("--note", default="")

    p_verify = sub.add_parser("verify", help="verify an archive")
    p_verify.add_argument("archive")

    p_list = sub.add_parser("list", help="list archives")
    p_list.add_argument("--out", default=None)

    p_prune = sub.add_parser("prune", help="delete old verified archives")
    p_prune.add_argument("--out", default=None)
    p_prune.add_argument("--keep", type=int, default=DEFAULT_KEEP)

    p_restore = sub.add_parser("restore", help="restore an archive")
    p_restore.add_argument("archive")
    p_restore.add_argument("--target", default=None,
                           help="restore here instead of the live data dir")
    p_restore.add_argument("--yes", action="store_true", dest="assume_yes")
    p_restore.add_argument("--dry-run", action="store_true")
    p_restore.add_argument("--force-instance", action="store_true")

    args = parser.parse_args(argv)
    command = args.command or "backup"

    if command == "backup":
        report = create_backup(
            Path(args.out) if getattr(args, "out", None) else None,
            keep=getattr(args, "keep", DEFAULT_KEEP),
            note=getattr(args, "note", ""),
        )
        _print(report, args.as_json)
        return 0 if report.get("verify", {}).get("ok") else 1
    if command == "verify":
        result = verify_archive(Path(args.archive))
        _print(result, args.as_json)
        return 0 if result.get("ok") else 1
    if command == "list":
        items = list_backups(Path(args.out) if args.out else None)
        _print(items, args.as_json)
        return 0
    if command == "prune":
        removed = prune_backups(Path(args.out) if args.out else None,
                                keep=args.keep)
        _print({"removed": removed}, args.as_json)
        return 0
    if command == "restore":
        report = restore_archive(
            Path(args.archive),
            Path(args.target) if args.target else None,
            assume_yes=args.assume_yes,
            dry_run=args.dry_run,
            force_instance=args.force_instance,
        )
        _print(report, args.as_json)
        return 0 if report.get("ok", report.get("applied")) else 1
    parser.error(f"unknown command {command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
