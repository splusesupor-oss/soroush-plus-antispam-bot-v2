#!/usr/bin/env python3
"""Pre-push secret scanner.

Run this before every ``git push`` (and in CI) to make sure no session string,
bot token, API hash or private key is about to become public.

    python3 tools/secret_scan.py              # scan the tracked+staged files
    python3 tools/secret_scan.py --staged     # scan only what is staged
    python3 tools/secret_scan.py --json

Exit code 0 = clean, 1 = findings, 2 = could not inspect the repository.

The scanner never prints a secret value; it prints the file, the line number
and a masked fingerprint so the finding can be located safely.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent

#: A real MTProto / SPlusthon string session: long, URL-safe base64.
_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-+/]{60,}={0,2}$")
_SESSION_KEYS = (
    "SOROUSH_SESSION_STRING",
    "SESSION_STRING",
    "BOT_SESSION",
)
_TOKEN_PATTERNS = (
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "github-token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github-token"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "bot-token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private-key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "api-key"),
)
#: Whole files that must never be tracked.
_FORBIDDEN_NAMES = (
    ".env", ".env.old", ".env.backup_old_session", ".env.session_backup",
    ".env.before_fix", ".env.before_fi", ".env.before_restore",
)
_FORBIDDEN_SUFFIXES = (".session", ".session-journal", ".pem", ".key")

#: Values that only *look* like secrets: documentation placeholders and code.
_PLACEHOLDER_RE = re.compile(
    r"^[<{\[]|^رشته|^session|^your|^توکن|^کلید|^xxx|^\.\.\.|"
    r"^\$|^os\.|^session_string$|^None$|^null$",
    re.IGNORECASE,
)
_MAX_BYTES = 4 * 1024 * 1024


def looks_like_session(value: str) -> Optional[str]:
    """Return a short fingerprint when ``value`` is a plausible session."""
    text = (value or "").strip().strip('"').strip("'")
    if not text or _PLACEHOLDER_RE.search(text):
        return None
    if text.startswith(("f\"", "f'", "{", "<")):
        return None
    if not _SESSION_RE.match(text):
        return None
    import hashlib
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(ROOT),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git failed")
    return result.stdout


def _candidate_files(staged_only: bool) -> List[str]:
    if staged_only:
        output = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        output = _git("ls-files")
    return [line for line in output.splitlines() if line.strip()]


def _scan_archive(path: Path) -> List[dict]:
    """Look inside tracked zip/tar archives for embedded ``.env`` files.

    A stray ``bot_project.zip`` used to ship five ``.env`` files with a live
    session inside.  Text scanning alone would never have seen them.
    """
    import io
    import zipfile

    findings: List[dict] = []

    def _inspect(member_name: str, reader) -> None:
        if not member_name.endswith(".env") and ".env." not in member_name:
            return
        try:
            text = reader().decode("utf-8", "replace")
        except Exception:
            return
        for key in _SESSION_KEYS:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"{key}="):
                    fingerprint = looks_like_session(
                        stripped.split("=", 1)[1])
                    if fingerprint:
                        findings.append({
                            "file": str(path.name), "line": 0,
                            "kind": "session-inside-archive",
                            "member": member_name,
                            "fingerprint": fingerprint,
                        })

    try:
        if path.suffix == ".zip" and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    _inspect(name, lambda n=name: archive.read(n))
        elif path.name.endswith((".tar.gz", ".tgz", ".tar")):
            import tarfile
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    _inspect(member.name,
                             lambda m=member: archive.extractfile(m).read())
    except Exception:
        return findings
    return findings


def scan_file(path: Path) -> List[dict]:
    findings: List[dict] = []
    name = path.name
    if name in _FORBIDDEN_NAMES or any(name.endswith(s)
                                       for s in _FORBIDDEN_SUFFIXES):
        return [{"file": str(path.name), "line": 0, "kind": "forbidden-file"}]
    if name.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        findings.extend(_scan_archive(path))
        return findings
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return findings
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        for key in _SESSION_KEYS:
            if stripped.startswith(f"{key}="):
                value = stripped.split("=", 1)[1]
                fingerprint = looks_like_session(value)
                if fingerprint:
                    findings.append({
                        "file": str(path.name), "line": number,
                        "kind": "session-value", "fingerprint": fingerprint,
                    })
        for pattern, kind in _TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "file": str(path.name), "line": number, "kind": kind,
                })
    return findings


def scan_repository(root: Optional[Path] = None,
                    staged_only: bool = False) -> List[dict]:
    findings: List[dict] = []
    base = Path(root) if root else ROOT
    for name in _candidate_files(staged_only):
        path = base / name
        findings.extend(scan_file(path))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true",
                        help="scan only files staged for the next commit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        findings = scan_repository(staged_only=args.staged)
    except RuntimeError as error:
        print(f"secret_scan: cannot inspect repository: {error}",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"findings": findings}, ensure_ascii=False, indent=2))
    elif findings:
        print("SECRETS FOUND — do not push:")
        for item in findings:
            suffix = f" fp={item['fingerprint']}" if item.get("fingerprint") else ""
            print(f"  - {item['file']}:{item['line']} [{item['kind']}]{suffix}")
    else:
        print("secret_scan: clean — no session, token or key in the scanned files")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
